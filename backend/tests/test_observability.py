"""
tests/test_observability.py

Smoke tests for the observability endpoints built this session (LLM usage
summary, agent traces summary/detail) — these are the newest, least
battle-tested pieces of the backend (verified so far only via manual
dashboard screenshots), so an automated contract check is worth having.

Runs against an empty test database (see conftest.py) — these endpoints
must handle "zero rows logged yet" gracefully (which they do: the service
functions default every aggregate to 0/None rather than erroring on an
empty table), so this also doubles as a regression check for that.
"""
import uuid
import pytest


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestLlmUsageSummary:
    @pytest.mark.asyncio
    async def test_response_shape_on_empty_data(self, client, admin_token):
        resp = await client.get(
            "/observability/llm-usage-summary",
            params={"since_days": 30},
            headers=auth_headers(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["since_days"] == 30
        assert "overall" in data and "by_endpoint" in data
        assert data["overall"]["call_count"] == 0
        assert data["overall"]["total_estimated_cost_inr"] == 0.0
        assert data["by_endpoint"] == []

        # Quota sections must always be present, even with zero calls logged.
        assert "gemini_quota" in data
        assert data["gemini_quota"]["requests_used_today"] == 0
        assert "groq_quota" in data
        assert data["groq_quota"]["requests_used_today"] == 0

    @pytest.mark.asyncio
    async def test_all_time_when_since_days_is_zero_or_omitted(self, client, admin_token):
        # Router treats since_days=0 (or omitted) as "no filter, all-time" —
        # confirms that contract holds, since it's easy to accidentally
        # break by passing 0 straight through as a real day-count filter.
        resp = await client.get(
            "/observability/llm-usage-summary",
            params={"since_days": 0},
            headers=auth_headers(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["since_days"] is None


class TestAgentTracesSummary:
    @pytest.mark.asyncio
    async def test_response_shape_on_empty_data(self, client, admin_token):
        resp = await client.get(
            "/observability/agent-traces/summary",
            params={"since_days": 30},
            headers=auth_headers(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["since_days"] == 30
        assert data["run_counts"] == {}
        assert data["node_breakdown"] == []
        assert data["recent_traces"] == []

    @pytest.mark.asyncio
    async def test_detail_for_unknown_trace_id_returns_empty_steps(self, client, admin_token):
        # Not a 404 by design (see app/observability/router.py) — an
        # unknown/never-logged trace_id is a valid, just-empty result.
        fake_trace_id = str(uuid.uuid4())
        resp = await client.get(
            f"/observability/agent-traces/{fake_trace_id}",
            headers=auth_headers(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == fake_trace_id
        assert data["steps"] == []