# EduIntel AI — Testing Strategy & Quality Assurance Architecture

This document establishes the testing strategy, test inventory, fixtures harness, and quality assurance gates for EduIntel AI on branch `develop/production-readiness`.

---

## 1. Testing Philosophy & Test Pyramid

EduIntel follows an automated testing pyramid designed to ensure high confidence in security, authentication, AI safety guardrails, and deterministic agent behavior without requiring external cloud connectivity.

```mermaid
flowchart TD
    E2E["End-to-End & Portal Tests (Phase 4)<br><i>Simulated Browser & HTTP client flows</i>"]
    Integration["Integration Tests (Current Baseline)<br><i>Async FastAPI test client, SQLite/PostgreSQL, LangGraph graph execution</i>"]
    Unit["Unit & Security Tests (Current Baseline)<br><i>Regex PII redaction, prompt injection heuristics, password hashing, token validation</i>"]

    Unit --> Integration --> E2E
```

### Core Testing Principles:
1. **Zero External Cloud Dependencies**: Tests must execute in CI/CD and offline development environments without invoking live Google Gemini or Groq cloud endpoints. All external LLM and embedding calls are mocked via pytest fixtures.
2. **Security & Containment Regression**: Security tests (such as verifying that the Admin Assistant rejects arbitrary SQL strings) are non-negotiable regression gates.
3. **Asynchronous Test Support**: All async route handlers and database queries are tested using `pytest-asyncio` with `asyncio_mode = auto`.

---

## 2. Test Configuration & Harness

- **Test Runner**: Pytest 9.1+ with `pytest-asyncio 1.4+`.
- **Configuration File**: [`backend/pytest.ini`](file:///home/dell/projects/eduIntel/backend/pytest.ini).
- **Core Fixture Harness**: [`backend/tests/conftest.py`](file:///home/dell/projects/eduIntel/backend/tests/conftest.py):
  - `async_client`: FastAPI `AsyncClient` bound to the application for testing HTTP requests.
  - `mock_db_session`: Async database session rollback fixture to prevent test pollution.
  - `admin_token`, `teacher_token`, `student_token`: Pre-generated valid JWT tokens with test claims.
  - `mock_gemini_client`: Mocked LLM responses for deterministic agent and RAG evaluations.

---

## 3. Current Test Inventory (328 Automated Tests)

The test suite in [`backend/tests/`](file:///home/dell/projects/eduIntel/backend/tests/) contains **328 collected tests across 20 test modules**, with a **100% pass rate**:

### 3.1. Phase 2B Security & Containment Suites (11 Modules — 249 Tests)
1. **`test_admin_assistant_security.py`** (17 tests): Parameter validation, regex SQL containment, extra field forbidden.
2. **`test_guardrails.py`** (44 tests): PII redaction (Aadhaar, phone, email, IPv4/v6, credit card), prompt injection heuristic filters, Socratic redirects.
3. **`test_password_reset_lifecycle.py`** (22 tests, SEC-01): 32-byte cryptographically secure random token, SHA-256 token hashing at rest, sanitized response payloads, user enumeration timing mitigation, 5 req/min rate limit.
4. **`test_registration_privilege_escalation.py`** (26 tests, SEC-02): Public signup disabled (403 Forbidden), admin user provisioning (`/admin/teachers`, `/admin/students`, `/admin/administrators`), offline CLI bootstrap tool.
5. **`test_parent_report_authorization.py`** (30 tests, SEC-03): Multi-factor relational authorization, timetable section matching, strict dispatch to verified `parent_email`.
6. **`test_ocr_security.py`** (19 tests, SEC-05): Authenticated extraction, 5 MB streaming file cutoff, image magic byte verification, `asyncio.Semaphore` bounded worker concurrency (max 2), 10s timeout.
7. **`test_file_download_idor.py`** (25 tests, SEC-06 & SEC-S3-03): Student homework ownership, teacher timetable assignment verification, student grade/section enrollment check for study materials, institutional `tenant.role` evaluation.
8. **`test_ml_diagnostics_idor.py`** (34 tests, SEC-07): Student profile join verification, teacher section matching, sanitized `502 Bad Gateway` error envelopes.
9. **`test_rag_tenant_isolation.py`** (33 tests, SEC-08): Server-side trusted tenant resolution, mandatory `where={"institution_id": ...}` ChromaDB metadata filter, authenticated `/rag/collections`.
10. **`test_admin_ai_tenant_isolation.py`** (23 tests, SEC-09): Pre-SQL `verify_tenant_reporting_authorized()` guard, namespaced LRU conversation memory.
11. **`test_auth_cookie_security.py`** (12 tests, SEC-10): Backend `HttpOnly`, `SameSite=Strict`, `Secure` cookie issuance with dual-mode Bearer header fallback.

### 3.2. Phase 2 Stage 3 Multi-Tenancy & Scoping Suites (7 Modules — 79 Tests)
12. **`test_tenant_isolation_rls.py`**: Validates schema definitions, migration models, and PostgreSQL RLS policy structures.
13. **`test_tenant_student_scoping.py`**: Scoped homework submissions, doubt threads, attendance history, SEC-S3-02 filename sanitization (`os.path.basename`), and SEC-S3-03 `tenant.role` material download.
14. **`test_tenant_teacher_scoping.py`**: Scoped class creation, study material management, assignment grading, and student roster access.
15. **`test_tenant_admin_scoping.py`**: Scoped administrative dashboards, timetable scheduling, fee collections, and teacher salary disbursements.
16. **`test_tenant_announcements_scoping.py`**: Scoped institution broadcast filtering and target audience delivery.
17. **`test_tenant_observability_scoping.py`**: Scoped telemetry tracking, LLM token logging, INR cost calculations, and trace log filtering by `institution_id`.
18. **`test_tenant_agents_scoping.py`**: Portal assistant session isolation, LRU memory bounds, session TTL cleanup, and MCP server tenant scoping with `tenant_session_scope`.

---

## 4. Empirical Pytest Execution & Quality Gate Results

```bash
cd backend && pytest tests/ -v
```

### Verified Results:
- **Total Tests Collected**: 328
- **Passed**: 328 (100% PASS)
- **Failed**: 0
- **Errors**: 0
- **Duration**: ~73 seconds
- **Code Quality**: `ruff check` and `ruff format --check` report 0 errors across all 23 Stage 3 scoped files.
- **Frontend Security Suite**: 8/8 tests passed (`node --test`).

---

## 4. Test Execution Instructions & Test Database Isolation

### 4.1. Test Database Requirement
Tests that require database transactions (`test_auth_rbac.py`, `test_observability.py`) instantiate an async test engine using `TEST_DATABASE_URL`:
```bash
TEST_DATABASE_URL="postgresql+asyncpg://eduintel:eduintel_dev@localhost:5432/eduintel_test"
```
> [!IMPORTANT]
> The test fixture [`test_engine`](file:///home/dell/projects/eduIntel/backend/tests/conftest.py) executes `Base.metadata.create_all` and `Base.metadata.drop_all` around each test execution. Therefore, `TEST_DATABASE_URL` must point to an isolated database (e.g. `eduintel_test`), never to the primary development or production database `eduintel`.
> To initialize the test database locally:
> ```bash
> docker exec -it eduintel-postgres psql -U eduintel -d eduintel -c "CREATE DATABASE eduintel_test;"
> ```

### 4.2. Running the Test Suite
```bash
cd backend
source venv/bin/activate

# Run offline unit and guardrail tests (61 tests, zero DB required)
pytest tests/test_guardrails.py tests/test_admin_assistant_security.py -v

# Run full suite including database integration tests
TEST_DATABASE_URL="postgresql+asyncpg://eduintel:eduintel_dev@localhost:5432/eduintel_test" pytest tests/ -v
```

---

## 5. Coverage Gaps & Phase 4 Roadmap

While current tests cover security, guardrails, and authentication thoroughly, Phase 4 (Testing Infrastructure & CI/CD) is scheduled to address the following gaps:

1. **Portal End-to-End Route Tests**: Add pytest suites covering complete CRUD workflows for timetable creation, assignment grading, and fee payments.
2. **ChromaDB Vector Mocking**: Add dedicated unit tests for the chunking and embedding retrieval logic with a mocked ChromaDB in-memory client.
3. **ML Inference Pipeline Tests**: Add regression tests verifying that `at_risk_model.json` and `weak_topics_model.json` produce valid predictions when given edge-case feature inputs (e.g. 0% attendance, NaN features).
4. **Automated CI Pipeline**: Configure GitHub Actions to execute `ruff check` and `pytest --cov=app` on every pull request.
