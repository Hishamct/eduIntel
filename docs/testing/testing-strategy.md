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

- **Test Runner**: Pytest 9.1+ with `pytest-asyncio 1.4+` and `pytest-randomly 3.16+`.
- **Configuration File**: [`backend/pytest.ini`](file:///home/dell/projects/eduIntel/backend/pytest.ini).
- **Core Fixture Harness**: [`backend/tests/conftest.py`](file:///home/dell/projects/eduIntel/backend/tests/conftest.py):
  - **Fail-Closed Safety Guard (`assert_safe_test_database`)**: Multi-factor URL verification enforcing test-mode flags (`ENVIRONMENT='testing'`, `EDUINTEL_TEST_MODE='true'`), loopback host (`localhost`/`127.0.0.1`), standard port 5432, zero rogue query parameters, prohibited protected database names, and strict regex allowlisting (`^eduintel_test(_[a-zA-Z0-9_-]+)?$`).
  - **Dynamic Alembic Migration & Schema Assertion (`verify_and_prepare_test_database`)**: Runs `alembic upgrade head` dynamically and asserts schema integrity (22 tables, 17 `FORCE ROW LEVEL SECURITY` tables, 68 split policies, and unprivileged application role).
  - **Savepoint Transaction Isolation (`db_connection`)**: Executes tests inside nested savepoints (`join_transaction_mode="create_savepoint"`). Route and service commits release savepoints rather than committing the outer transaction. Teardown unconditionally rolls back the outer transaction.
  - **Resilient Session Teardown Reset**: Cleanses connection state after every test: `RESET ROLE; RESET ALL; PERFORM set_config('app.current_institution_id', '', false); PERFORM set_config('app.is_platform_admin', '', false);`.
  - **Unprivileged Role Execution**: Connects under `eduintel_app` (`NOSUPERUSER, NOBYPASSRLS`) so PostgreSQL RLS policies cannot be bypassed.
  - `client`: FastAPI `AsyncClient` via `ASGITransport` wired to the savepoint transaction session.
  - `admin_token`, `teacher_token`, `student_token`: Pre-provisioned user tokens scoped to transaction savepoints.
  - `prevent_live_smtp_during_tests`: Autouse global mock intercepting SMTP dispatch.
  - `reset_app_engine_pool`: Autouse teardown disposing pooled connections across event loop lifecycles.

---

## 3. Current Backend Test Inventory (540 Automated Tests)

The test suite in [`backend/tests/`](file:///home/dell/projects/eduIntel/backend/tests/) contains **540 collected tests across 23 test modules**, with a **100% pass rate**:

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

### 3.3. Phase 2 Stages 4 & 5 Platform Admin & Remediation Suite (1 Module — 20 Tests)
19. **`test_platform_admin.py`** (20 tests):
    - **Authorization & Dependency Checks**: `require_platform_admin` verifies database `is_platform_admin` column; rejects forged JWT claims, unauthenticated users, and institutional admins with 403.
    - **Atomic Institution Onboarding**: 100% rollback on duplicate slug or email; verifies initial admin account is inactive (`is_active=False`) with random password lockout; verifies 48-hour single-use SHA-256 hashed activation token.
    - **Email Format Validation (SEC-01)**: Verifies Pydantic `EmailStr` rejects malformed `admin_email` and `contact_email` with HTTP 422.
    - **Accurate Invitation Status (SEC-04)**: Verifies `invitation_sent` accurately distinguishes configured SMTP delivery vs unconfigured fallback.
    - **Operational Suspension**: Verifies `PATCH /institutions/{id}/status` suspends institutions, blocking single-tenant members while preserving multi-tenant users' access to other active institutes.
    - **Database RLS Read-Write Isolation (SEC-03)**: Verifies Platform Admin cross-tenant `SELECT` queries succeed with `app.is_platform_admin = 'true'`, while cross-tenant `INSERT`, `UPDATE`, and `DELETE` queries are denied by PostgreSQL with SQLSTATE `42501` (`insufficient_privilege`).

### 3.4. Database Integrity, Core Authentication & Isolation Suites (4 Modules — 192 Tests)
20. **`test_database_pooling.py`** (6 tests): Pool settings validation (`pool_size=10, max_overflow=5, timeout=30, recycle=1800, pre_ping=True, echo=False`), queue pool starvation handling, and connection reset verification.
21. **`test_auth_rbac.py`**: End-to-end authentication, password hashing, role transitions, and profile resolution.
22. **`test_observability.py`**: Metrics endpoints, cost aggregation, and trace instrumentation.
23. **`test_database_isolation_between_tests.py`** (10 tests, Phase 4): Fail-closed safety guard enforcement, unprivileged role RLS blocking (SQLSTATE 42501), clean session GUC verification, and savepoint rollback isolation tested under forward, reverse, and randomized orders via `pytest-randomly`.

---

## 4. Empirical Pytest Execution & Quality Gate Results

```bash
set -a && source backend/.env && set +a
cd backend && pytest tests/ -v
```

### Verified Results:
- **Total Tests Collected**: 540
- **Passed**: 540 (100% PASS)
- **Failed**: 0
- **Errors**: 0
- **Duration**: ~109 seconds
- **Code Quality**: `ruff check` reports 0 errors across all backend source and test files.

---

## 5. Frontend Testing Architecture & Suites (Vitest & RTL)

Following the security audit remediation (SEC-05), a dedicated frontend test framework was established:
- **Test Runner**: Vitest v4.1.12 with `jsdom` environment ([`frontend/vitest.config.js`](file:///home/dell/projects/eduIntel/frontend/vitest.config.js)).
- **Testing Utilities**: React Testing Library (`@testing-library/react`), `@testing-library/jest-dom`.
- **Command**: `cd frontend && npm test`

### 5.1. Vitest Test Suites (3 Modules — 12 Tests)
1. **`tests/protected_route.test.jsx`** (4 tests):
   - Redirects unauthenticated users to `/login`.
   - Allows authenticated users with matching roles to access protected components.
   - Redirects users with mismatched roles to their designated home routes.
   - Restricts Platform Admin routes (`/platform-admin/*`) exclusively to sessions where `sessionStorage.is_platform_admin === "true"`, redirecting ordinary institutional admins to `/admin/dashboard`.
2. **`tests/login_flow.test.jsx`** (4 tests):
   - Verifies atomic session storage cleanup on submission start.
   - Validates that `sessionStorage.is_authenticated`, `user_role`, and `is_platform_admin` are set atomically only after both `/auth/login` and `/users/me` succeed.
   - Clears all session keys on `/users/me` failure, 401 error, or inactive account status.
   - Enforces correct post-login routing: Platform Admins $\rightarrow$ `/platform-admin/dashboard`; institutional users $\rightarrow$ role home route.
3. **`tests/institution_management.test.jsx`** (4 tests):
   - Verifies input validation on the institution onboarding modal (name, slug, email format).
   - Verifies single-use activation token presentation dialog and copy-to-clipboard behavior without storing raw tokens in `localStorage` or `sessionStorage`.
   - Verifies confirmation modals for institution suspension and reactivation.

### 5.2. Node.js Security Test Suite (1 Module — 8 Tests)
- **`frontend/tests/test_sec11_demo_mode_remediation.js`**: Native Node.js test runner (`node --test`).
- Verifies complete removal of `demo_mode` flags, demo bypass buttons, and hardcoded credentials from frontend source bundles.

---

## 6. Test Execution Instructions & Test Database Isolation

### 6.1. Test Database Safety & Unprivileged Execution
Integration and RLS tests execute against a dedicated, isolated test database (`eduintel_test`) under the unprivileged PostgreSQL role `eduintel_app` (`NOSUPERUSER, NOBYPASSRLS`):
```bash
TEST_DATABASE_URL="postgresql+asyncpg://eduintel_app:eduintel_dev@localhost:5432/eduintel_test"
```
> [!IMPORTANT]
> **Production Safety Invariants (`assert_safe_test_database`):**
> 1. Requires `ENVIRONMENT='testing'` and `EDUINTEL_TEST_MODE='true'`.
> 2. Prohibits non-loopback hosts and non-standard ports.
> 3. Forbids protected database names (`eduintel`, `postgres`, `production`, `staging`).
> 4. Test schema is constructed dynamically via **`alembic upgrade head`** rather than `Base.metadata.create_all`, ensuring tests exercise real PostgreSQL RLS policies, composite indexes, and triggers.
> 5. Tests use **savepoint transaction isolation** (`join_transaction_mode="create_savepoint"`). Mutations are rolled back at the connection level, and connection state is cleansed via `RESET ROLE; RESET ALL; PERFORM set_config(...)` between tests, avoiding destructive table recreation.

To provision the test database and unprivileged application role locally:
```bash
docker exec -it eduintel-postgres psql -U eduintel -d eduintel -c "
  CREATE DATABASE eduintel_test;
  DO \$\$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel_app') THEN
      CREATE ROLE eduintel_app WITH LOGIN PASSWORD 'eduintel_dev' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
  END \$\$;
  GRANT USAGE ON SCHEMA public TO eduintel_app;
"
```

### 6.2. Running the Test Suites

#### Backend Test Suite (Pytest)
```bash
cd backend
source venv/bin/activate
set -a && source .env && set +a

# Run full suite with realistic Alembic harness and savepoint isolation (540 tests)
pytest tests/ -v

# Run with randomized test ordering to verify order-independence
pytest tests/ -v --randomly-seed=12345
```

#### Frontend Test Suites (Vitest & Node)
```bash
cd frontend

# Run Vitest component & route protection suites (12 tests)
npm test

# Run Node.js security text scan (8 tests)
node --test tests/test_sec11_demo_mode_remediation.js
```

---

## 7. Automated CI Pipeline & Phase 4 Roadmap Status

### 7.1. Automated GitHub Actions CI Pipeline (Implemented in Step 2)
The CI pipeline in [`.github/workflows/ci.yml`](file:///home/dell/projects/eduIntel/.github/workflows/ci.yml) enforces quality gates on all pushes and PRs:
1. **Code Quality & Linting (`lint`)**: Runs `ruff check .` on backend and `npm run lint` (ESLint) on frontend.
2. **Backend Test Suite (`backend`)**: Launches a dedicated `postgres:16` service container, provisions `eduintel_app`, runs `alembic upgrade head`, and executes `pytest` across all 23 suites.
3. **Frontend Test Suite & Build (`frontend`)**: Executes Vitest component suites, Node.js demo mode security audit, and verifies `vite build` production compilation.

### 7.2. Remaining Phase 4 Workstream Steps
1. **Step 4: Deterministic Mocks & Network Guard**: Centralize Gemini/Groq mocks and enforce fail-closed loopback guard intercepting unauthorized outbound calls.
2. **Step 5: Coverage Baseline & Ratchet**: Establish empirical coverage floor on `backend/app/` using `pytest-cov` and block regressions.
3. **Step 6: DevSecOps Gates & Grounded Auth Matrix**: Integrate Bandit (`-ll -ii`), pip-audit, and Gitleaks with a security exceptions register; build grounded authorization matrix.
4. **Step 7: Frontend Portal Coverage**: Author Vitest/RTL tests for student and teacher portal views and enforce required branch protection status checks.
