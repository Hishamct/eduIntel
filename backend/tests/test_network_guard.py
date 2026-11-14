"""
backend/tests/test_network_guard.py

Phase 04 Step 4 Verification:
1. Verifies that the loopback-aware network guard intercepts outbound socket connections to non-loopback hosts.
2. Verifies that the network guard intercepts outbound DNS lookups to external hostnames.
3. Verifies that local loopback connections (PostgreSQL on 127.0.0.1:5432 and localhost) succeed without interruption.
4. Verifies that unmocked external HTTP requests via httpx and urllib fail closed with a descriptive RuntimeError.
5. Verifies that centralized deterministic Gemini LLM mock returns predictable outputs with zero network calls.
6. Verifies that centralized deterministic Groq fallback mock executes on rate-limit triggers.
7. Verifies that centralized ChromaDB embedding mock returns 768-dimensional vectors with zero external calls.
8. Verifies that centralized SMTP sink records dispatched emails in-memory without external dispatch.
"""

import socket
import urllib.request
from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import text

from app.core import llm_client
from app.rag.client import GeminiEmbeddingFunction
from tests.conftest import is_loopback_host


class TestLoopbackAwareNetworkGuard:
    """Verifies that non-loopback network traffic is intercepted and blocked fail-closed."""

    def test_loopback_helper_classifies_correctly(self):
        """Proves loopback allowlist accurately identifies local vs remote addresses."""
        assert is_loopback_host("localhost") is True
        assert is_loopback_host("127.0.0.1") is True
        assert is_loopback_host("127.0.1.1") is True
        assert is_loopback_host("::1") is True
        assert is_loopback_host("0.0.0.0") is True
        assert is_loopback_host("") is True
        assert is_loopback_host(None) is True

        assert is_loopback_host("generativelanguage.googleapis.com") is False
        assert is_loopback_host("api.groq.com") is False
        assert is_loopback_host("142.250.190.46") is False
        assert is_loopback_host("10.0.0.1") is False
        assert is_loopback_host("192.168.1.1") is False

    def test_network_guard_blocks_external_socket_connect(self):
        """Proves direct TCP socket.connect to external IP raises fail-closed RuntimeError."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(RuntimeError) as exc_info:
                s.connect(("142.250.190.46", 443))
            err_msg = str(exc_info.value)
            assert "CRITICAL: Unmocked external network call detected" in err_msg
            assert "142.250.190.46" in err_msg
        finally:
            s.close()

    def test_network_guard_blocks_external_dns_lookup(self):
        """Proves socket.getaddrinfo to external hostname raises fail-closed RuntimeError."""
        with pytest.raises(RuntimeError) as exc_info:
            socket.getaddrinfo("generativelanguage.googleapis.com", 443)
        err_msg = str(exc_info.value)
        assert "CRITICAL: Unmocked external network call detected" in err_msg
        assert "generativelanguage.googleapis.com" in err_msg

    def test_network_guard_blocks_unmocked_urllib_external_call(self):
        """Proves standard library urllib outbound HTTP calls are intercepted."""
        with pytest.raises(RuntimeError) as exc_info:
            urllib.request.urlopen("https://api.groq.com/openai/v1/models", timeout=2)
        err_msg = str(exc_info.value)
        assert "CRITICAL: Unmocked external network call detected" in err_msg
        assert "api.groq.com" in err_msg

    @pytest.mark.asyncio
    async def test_network_guard_blocks_unmocked_httpx_async_call(self):
        """Proves async HTTP clients (httpx) attempting external calls fail closed."""
        with pytest.raises((RuntimeError, ExceptionGroup)) as exc_info:
            async with httpx.AsyncClient() as client:
                await client.get("https://generativelanguage.googleapis.com", timeout=2)

        err_str = str(exc_info.value)
        assert "CRITICAL: Unmocked external network call detected" in err_str

    @pytest.mark.asyncio
    async def test_network_guard_allows_loopback_postgres(self, db_connection):
        """Proves authorized local loopback PostgreSQL queries execute without interference."""
        result = await db_connection.execute(text("SELECT 1 AS alive"))
        assert result.scalar() == 1


class TestCentralizedDeterministicServiceMocks:
    """Verifies that centralized AI and SMTP fixtures deliver deterministic results with zero network calls."""

    def test_centralized_gemini_mock_returns_deterministic_output(self):
        """Proves Gemini text generation uses centralized mock and returns predictable text/usage."""
        text_out, usage = llm_client.generate_text_with_usage("Explain Newton's third law of motion")
        assert text_out == "Mocked AI response for testing."
        assert usage.provider == "gemini"
        assert usage.model == "gemini-3.6-flash"
        assert usage.input_tokens == 15
        assert usage.output_tokens == 25
        assert usage.used_fallback is False

    def test_centralized_groq_fallback_mock_on_gemini_rate_limit(self, monkeypatch):
        """Proves rate-limit trigger activates Groq fallback mock seamlessly."""
        # Force Gemini to simulate 429 RESOURCE_EXHAUSTED
        rate_limit_error = Exception("429 RESOURCE_EXHAUSTED: quota exceeded")
        monkeypatch.setattr(
            llm_client._gemini_client.models,
            "generate_content",
            MagicMock(side_effect=rate_limit_error),
        )

        text_out, usage = llm_client.generate_text_with_usage("Generate practice exam questions")
        assert text_out == "Mocked Groq fallback response."
        assert usage.provider == "groq"
        assert usage.model == "openai/gpt-oss-120b"
        assert usage.input_tokens == 15
        assert usage.output_tokens == 25
        assert usage.used_fallback is True

    def test_centralized_chromadb_embedding_mock(self):
        """Proves GeminiEmbeddingFunction returns 768-dimensional float vectors offline in 0ms."""
        embed_fn = GeminiEmbeddingFunction()
        input_chunks = [
            "Photosynthesis is the process by which green plants use sunlight to synthesize nutrients.",
            "Cellular respiration is a set of metabolic reactions taking place in cells to convert energy.",
        ]
        vectors = embed_fn(input_chunks)
        assert len(vectors) == 2
        assert len(vectors[0]) == 768
        assert len(vectors[1]) == 768
        assert all(isinstance(val, float) for val in vectors[0])
        assert vectors[0][0] == 0.05

    def test_centralized_smtp_sink_records_dispatched_emails(self, prevent_live_smtp_during_tests):
        """Proves emails sent during tests are captured in mock sink without opening live SMTP sockets."""
        from app.reports.parent_report_agent import send_email_direct

        recipient = "parent.student@example.com"
        subject = "Monthly Attendance & Academic Report"
        body = "Student achieved 96% attendance this month."

        res = send_email_direct(to_email=recipient, subject=subject, body=body)
        assert res["status"] == "sent"

        # Inspect captured outbox in fixture
        outbox = prevent_live_smtp_during_tests.outbox
        assert len(outbox) >= 1
        last_email = outbox[-1]
        assert last_email["to_email"] == recipient
        assert last_email["subject"] == subject
        assert last_email["body"] == body
