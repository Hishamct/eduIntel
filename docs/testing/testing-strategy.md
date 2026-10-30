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

## 3. Current Test Inventory (79 Automated Tests)

The test suite in [`backend/tests/`](file:///home/dell/projects/eduIntel/backend/tests/) contains exactly **79 collected tests** across four test modules:

### 3.1. `test_admin_assistant_security.py` (17 Tests — Status: 🟢 17 Passed)
Validates the Phase 0A security containment of the LangGraph Admin Assistant:
- Verifies that raw SQL injection attempts (`DROP TABLE`, `SELECT * FROM users`, `UNION SELECT`) are intercepted and rejected.
- Tests that each of the 6 parameterized reporting tools (`query_fee_summary`, `query_teacher_salaries`, `query_timetable_coverage`, `query_student_attendance`, `query_exam_performance`, `query_at_risk_students`) accepts only strictly typed inputs.
- Validates that non-admin callers receive HTTP 403 Forbidden when attempting to query the assistant.

### 3.2. `test_guardrails.py` (44 Tests — Status: 🟢 44 Passed)
Validates AI security and privacy layers:
- PII redaction accuracy across Indian Aadhaar numbers, 10-digit mobile phones, email addresses, IPv4/v6 addresses, and credit cards.
- Edge case redaction: multiple PII entities in a single sentence, formatted phone numbers (`+91-9876543210`), and punctuation boundary cases.
- Prompt injection filter detection: flags known jailbreak signatures (`"ignore previous instructions"`, `"DAN mode"`, `"developer mode"`).
- Socratic guardrail: verifies that direct answer requests set `is_socratic_redirect = True`.

### 3.3. `test_auth_rbac.py` (14 Tests — Status: 🟡 14 Blocked / Setup Errors)
Validates identity management and privilege enforcement:
- Password hashing and verification via bcrypt (handles correct password, incorrect password, empty input).
- JWT generation, decoding, signature verification, and expiration handling.
- Role-based route guard enforcement (`require_role`): ensures students cannot access teacher routes, teachers cannot access admin routes, and unauthenticated requests return 401.

### 3.4. `test_observability.py` (4 Tests — Status: 🟡 4 Blocked / Setup Errors)
Validates telemetry tracking:
- Input and output token counting calculations.
- Cost computation converting LLM tokens to Indian Rupees (₹) based on active rates.
- Serialization and retrieval of `agent_trace_logs`.

---

## 4. Empirical Pytest Execution Audit & Verification Results

During the Phase 1 quality review, the test suite was executed against the local repository:
```bash
cd backend && ./venv/bin/pytest tests/
```

### Exact Execution Results:
- **Total Tests Collected**: 79
- **Passed**: 61 (100% of offline unit, security, and guardrail tests)
- **Failed**: 0 (Zero assertion failures in any test logic)
- **Skipped**: 0
- **Blocked / Setup Errors**: 18 (14 in `test_auth_rbac.py` + 4 in `test_observability.py`)
- **Pytest Exit Code**: `1` (Non-zero exit code due to setup errors)

### Root Cause of Setup Errors:
All 18 blocked tests rely on the function-scoped async fixture `test_engine` in [`backend/tests/conftest.py`](file:///home/dell/projects/eduIntel/backend/tests/conftest.py). This fixture executes `Base.metadata.create_all` and `Base.metadata.drop_all` against `TEST_DATABASE_URL` (default: `postgresql+asyncpg://eduintel:eduintel@localhost:5432/eduintel_test`).
Because the local PostgreSQL container on port 5432 was either stopped or not exposing the `eduintel_test` database with matching credentials during execution, `asyncpg` raised:
```
ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 5432)
```
The test bodies were never reached. The failure is entirely environmental (lack of reachable test database), not a defect in application source code.

> [!WARNING]
> **Production-Readiness Rule:** The complete test suite cannot be reported as "100% passing" until an isolated `eduintel_test` database instance is running and all 79 tests exit with code `0`. Hardening this test infrastructure is scheduled for Phase 4.

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
