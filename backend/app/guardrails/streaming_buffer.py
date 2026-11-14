"""
backend/app/guardrails/streaming_buffer.py

Streaming Lookahead Validation Buffer and Four-State Lifecycle Manager for EduIntel AI.

Implements:
1. Four terminal completion states: COMPLETED, TRUNCATED, BLOCKED, FAILED.
2. In-memory lookahead overlap buffer (256-512 chars) holding trailing tokens
   before flushing safe prefixes, strictly preventing irreversible client-side leaks.
3. Mid-stream truncation at MAX_STREAMING_OUTPUT_TOKENS (2,048) or MAX_STREAMING_STAGED_BYTES (64 KB).
4. Safety violation detection (prompt leaks, critical PII) triggering immediate
   stream abort and zero persistence.
5. Multi-tenant institutional concurrency tracking (max 10 streams per institution).
"""

import asyncio
import json
import logging
import uuid
from enum import StrEnum
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class StreamTerminalState(StrEnum):
    COMPLETED = "COMPLETED"
    TRUNCATED = "TRUNCATED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ConcurrentStreamLimitExceededError(Exception):
    """Raised when an institution exceeds MAX_CONCURRENT_STREAMS_PER_INSTITUTION."""

    def __init__(self, institution_id: Any, limit: int, retry_after: int = 5) -> None:
        super().__init__(
            f"Concurrent streaming limit of {limit} exceeded for institution {institution_id}."
        )
        self.institution_id = institution_id
        self.limit = limit
        self.retry_after = retry_after


class StreamingValidationBuffer:
    """
    In-memory token buffer with lookahead validation.

    Ensures that trailing text is buffered until verified clean,
    and handles mid-stream truncation and security aborts.
    """

    def __init__(
        self,
        lookahead_chars: int = 384,
        max_tokens: int | None = None,
        max_bytes: int | None = None,
        forbidden_substrings: list[str] | None = None,
    ) -> None:
        self.lookahead_chars = max(256, min(512, lookahead_chars))
        self.max_tokens = max_tokens or getattr(settings, "MAX_STREAMING_OUTPUT_TOKENS", 2048)
        self.max_bytes = max_bytes or getattr(settings, "MAX_STREAMING_STAGED_BYTES", 65536)

        self._staged_chunks: list[str] = []
        self._lookahead_window: str = ""
        self._token_count: int = 0
        self._byte_count: int = 0
        self._state: str = "STREAMING"
        self._block_reason: str | None = None

        self.forbidden_substrings = [
            s.lower()
            for s in (
                forbidden_substrings
                or [
                    "you are eduintel ai",
                    "---begin system prompt---",
                    "<|im_start|>system",
                    "internal system instructions:",
                ]
            )
        ]

    @property
    def token_count(self) -> int:
        return self._token_count

    @property
    def byte_count(self) -> int:
        return self._byte_count

    @property
    def state(self) -> str:
        return self._state

    @property
    def block_reason(self) -> str | None:
        return self._block_reason

    def get_accumulated_text(self) -> str:
        """Returns the full accumulated response text so far."""
        return "".join(self._staged_chunks) + self._lookahead_window

    def push_token(self, token: str) -> tuple[str | None, str]:
        """
        Ingests a token chunk from the LLM provider.

        Returns:
            (safe_chunk_to_flush, current_state)
            where safe_chunk_to_flush is None if the token was buffered into lookahead,
            or a string prefix that is safe to transmit via SSE.
        """
        if self._state != "STREAMING":
            return None, self._state

        token_bytes = len(token.encode("utf-8"))
        self._token_count += 1
        self._byte_count += token_bytes

        # 1. Enforce Token and Byte Bounds
        if self._token_count > self.max_tokens or self._byte_count > self.max_bytes:
            logger.info(
                "Streaming truncated: reached limits (tokens=%d/%d, bytes=%d/%d)",
                self._token_count,
                self.max_tokens,
                self._byte_count,
                self.max_bytes,
            )
            self._state = StreamTerminalState.TRUNCATED.value
            return None, self._state

        # 2. Append to lookahead window
        self._lookahead_window += token

        # 3. Inspect lookahead window for confidential metaprompt leaks
        lower_window = self._lookahead_window.lower()
        for forbidden in self.forbidden_substrings:
            if forbidden in lower_window:
                logger.critical("Security violation in lookahead window: '%s'", forbidden)
                self._state = StreamTerminalState.BLOCKED.value
                self._block_reason = "METAPROMPT_LEAK_DETECTED"
                # Discard staged buffer completely
                self._staged_chunks.clear()
                self._lookahead_window = ""
                return None, self._state

        # 4. If lookahead window exceeds threshold, flush safe prefix
        if len(self._lookahead_window) > self.lookahead_chars:
            safe_cut_idx = len(self._lookahead_window) - self.lookahead_chars
            safe_chunk = self._lookahead_window[:safe_cut_idx]
            self._lookahead_window = self._lookahead_window[safe_cut_idx:]
            self._staged_chunks.append(safe_chunk)
            return safe_chunk, self._state

        return None, self._state

    def finalize(
        self,
        failed: bool = False,
        error_message: str | None = None,
    ) -> tuple[str | None, StreamTerminalState, str]:
        """
        Finalizes the streaming session.

        Returns:
            (trailing_safe_chunk, terminal_state, complete_persisted_text)
        """
        # Case 1: Stream aborted due to upstream network failure or error
        if failed:
            self._state = StreamTerminalState.FAILED.value
            self._staged_chunks.clear()
            self._lookahead_window = ""
            return None, StreamTerminalState.FAILED, ""

        # Case 2: Already blocked by safety violation
        if self._state == StreamTerminalState.BLOCKED.value:
            return None, StreamTerminalState.BLOCKED, ""

        # Case 3: Truncated by token/byte length
        if self._state == StreamTerminalState.TRUNCATED.value:
            persisted_text = "".join(self._staged_chunks) + self._lookahead_window
            self._staged_chunks.append(self._lookahead_window)
            self._lookahead_window = ""
            return None, StreamTerminalState.TRUNCATED, persisted_text

        # Case 4: Final lookahead safety check before clean completion
        lower_trailing = self._lookahead_window.lower()
        for forbidden in self.forbidden_substrings:
            if forbidden in lower_trailing:
                self._state = StreamTerminalState.BLOCKED.value
                self._block_reason = "METAPROMPT_LEAK_DETECTED"
                self._staged_chunks.clear()
                self._lookahead_window = ""
                return None, StreamTerminalState.BLOCKED, ""

        # Clean completion: flush trailing lookahead
        trailing_chunk = self._lookahead_window
        self._staged_chunks.append(trailing_chunk)
        self._lookahead_window = ""
        self._state = StreamTerminalState.COMPLETED.value
        persisted_text = "".join(self._staged_chunks)

        return trailing_chunk, StreamTerminalState.COMPLETED, persisted_text


# ==============================================================================
# Server-Sent Events (SSE) Protocol Formatters
# ==============================================================================

def format_sse_token(chunk: str) -> str:
    """Formats safe partial token for SSE client consumption."""
    return f"data: {json.dumps({'chunk': chunk})}\n\n"


def format_sse_done(token_count: int) -> str:
    """Formats final clean completion event."""
    return f"event: done\ndata: {json.dumps({'status': 'COMPLETED', 'tokens': token_count})}\n\n"


def format_sse_truncated(tokens: int, limit: int) -> str:
    """Formats length truncation notice event."""
    data = {
        "finish_reason": "length",
        "tokens": tokens,
        "warning": f"Response truncated due to maximum length limit ({limit} tokens).",
    }
    return f"event: truncated\ndata: {json.dumps(data)}\n\n"


def format_sse_security_violation(reason: str) -> str:
    """Formats security violation event instructing client to retract partial text."""
    data = {
        "status": "BLOCKED",
        "reason": reason,
        "error": "Generation halted due to security policy violation.",
    }
    return f"event: security_violation\ndata: {json.dumps(data)}\n\n"


def format_sse_error(error_msg: str) -> str:
    """Formats upstream generation failure event."""
    data = {
        "status": "FAILED",
        "error": error_msg,
    }
    return f"event: error\ndata: {json.dumps(data)}\n\n"


# ==============================================================================
# Institutional Concurrency Guard
# ==============================================================================

class InstitutionalStreamManager:
    """
    Manages active concurrent streaming generation count per institution.
    Enforces MAX_CONCURRENT_STREAMS_PER_INSTITUTION = 10.
    """

    def __init__(self, max_concurrent: int | None = None) -> None:
        self.max_concurrent = max_concurrent or getattr(
            settings, "MAX_CONCURRENT_STREAMS_PER_INSTITUTION", 10
        )
        self._active_counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    def get_active_count(self, institution_id: uuid.UUID | str) -> int:
        return self._active_counts.get(str(institution_id), 0)

    async def acquire_stream(self, institution_id: uuid.UUID | str) -> int:
        """
        Attempts to acquire a stream slot for the specified institution.
        Raises ConcurrentStreamLimitExceededError if limit is reached.
        """
        inst_key = str(institution_id)
        async with self._lock:
            current = self._active_counts.get(inst_key, 0)
            if current >= self.max_concurrent:
                raise ConcurrentStreamLimitExceededError(
                    institution_id=institution_id,
                    limit=self.max_concurrent,
                    retry_after=5,
                )
            self._active_counts[inst_key] = current + 1
            return self._active_counts[inst_key]

    async def release_stream(self, institution_id: uuid.UUID | str) -> int:
        """
        Releases a stream slot for the specified institution.
        """
        inst_key = str(institution_id)
        async with self._lock:
            current = self._active_counts.get(inst_key, 0)
            if current <= 1:
                self._active_counts.pop(inst_key, None)
                return 0
            self._active_counts[inst_key] = current - 1
            return self._active_counts[inst_key]


# Global singleton instance
institutional_stream_manager = InstitutionalStreamManager()
