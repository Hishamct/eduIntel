"""
tests/test_auth_rbac.py

Integration smoke tests for role-based access control: confirms each
role-gated endpoint actually rejects the wrong role and accepts the right
one. Uses the app/conftest.py fixtures (throwaway signed-up users per
role, in-process AsyncClient against a test database — nothing here hits
your real dev database).

Deliberately does NOT test the 200-success path for the two chat
endpoints (admin-assistant/chat, portal-assistant/chat) — those call a
real Gemini/Groq API on success, which would be slow, non-deterministic,
and burn your very limited free-tier quota (Gemini RPD=20) every test
run. This suite only verifies the guard rejects wrong roles/no token
correctly — the actual chat behavior is better covered by your manual/
browser testing pass.
"""
import pytest


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# (path, method, json_body) for every role-gated endpoint worth checking.
# ADJUST the request bodies here if your Pydantic schemas require more
# fields than session_id/query — a 422 (validation error) instead of a
# 401/403 in these tests is your signal that a required field is missing,
# not that RBAC is broken.
ADMIN_ONLY_ENDPOINTS = [
    ("/agents/admin-assistant/chat", "post", {"session_id": "test-session", "query": "hello"}),
    ("/observability/llm-usage-summary", "get", None),
    ("/observability/agent-traces/summary", "get", None),
]

STUDENT_ONLY_ENDPOINTS = [
    ("/agents/portal-assistant/chat", "post", {"session_id": "test-session", "query": "hello"}),
]


class TestNoTokenRejected:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,method,body", ADMIN_ONLY_ENDPOINTS + STUDENT_ONLY_ENDPOINTS)
    async def test_returns_401_without_a_token(self, client, path, method, body):
        if method == "get":
            resp = await client.get(path)
        else:
            resp = await client.post(path, json=body)
        assert resp.status_code == 401, (
            f"{method.upper()} {path} without a token returned {resp.status_code}, "
            f"expected 401. A missing-auth request should never reach the handler."
        )


class TestWrongRoleRejected:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,method,body", ADMIN_ONLY_ENDPOINTS)
    async def test_student_cannot_access_admin_only_endpoints(self, client, student_token, path, method, body):
        headers = auth_headers(student_token)
        resp = await client.get(path, headers=headers) if method == "get" else await client.post(path, json=body, headers=headers)
        assert resp.status_code == 403, f"Student got {resp.status_code} on admin-only {path}, expected 403"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,method,body", ADMIN_ONLY_ENDPOINTS)
    async def test_teacher_cannot_access_admin_only_endpoints(self, client, teacher_token, path, method, body):
        headers = auth_headers(teacher_token)
        resp = await client.get(path, headers=headers) if method == "get" else await client.post(path, json=body, headers=headers)
        assert resp.status_code == 403, f"Teacher got {resp.status_code} on admin-only {path}, expected 403"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,method,body", STUDENT_ONLY_ENDPOINTS)
    async def test_admin_cannot_access_student_only_endpoints(self, client, admin_token, path, method, body):
        headers = auth_headers(admin_token)
        resp = await client.get(path, headers=headers) if method == "get" else await client.post(path, json=body, headers=headers)
        assert resp.status_code == 403, f"Admin got {resp.status_code} on student-only {path}, expected 403"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path,method,body", STUDENT_ONLY_ENDPOINTS)
    async def test_teacher_cannot_access_student_only_endpoints(self, client, teacher_token, path, method, body):
        headers = auth_headers(teacher_token)
        resp = await client.get(path, headers=headers) if method == "get" else await client.post(path, json=body, headers=headers)
        assert resp.status_code == 403, f"Teacher got {resp.status_code} on student-only {path}, expected 403"


class TestCorrectRoleAccepted:
    @pytest.mark.asyncio
    async def test_admin_can_reach_llm_usage_summary(self, client, admin_token):
        # Safe to test the 200 path here — this endpoint only does a DB
        # query, no LLM call, no quota cost.
        resp = await client.get("/observability/llm-usage-summary", headers=auth_headers(admin_token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_can_reach_agent_traces_summary(self, client, admin_token):
        resp = await client.get("/observability/agent-traces/summary", headers=auth_headers(admin_token))
        assert resp.status_code == 200
