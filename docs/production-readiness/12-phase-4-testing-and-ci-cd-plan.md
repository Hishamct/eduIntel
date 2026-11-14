# EduIntel Phase 4: Comprehensive Testing Suite & CI/CD Pipeline Implementation Plan

**Project:** EduIntel AI — Educational Decision Intelligence Platform  
**Target:** Production-Ready Coaching Institute & Multi-Tenant School Management SaaS  
**Branch:** `develop/production-readiness`  
**Execution Lead:** Principal Quality Engineer & Infrastructure Architect  
**Parent Phase:** Phase 04 (Master Roadmap)  
**Document Status:** 🟢 **FINAL AUTHORITATIVE IMPLEMENTATION SPECIFICATION**  
**Creation Date:** November 5, 2026  
**Revision:** 3.0 (Enterprise Quality Hardened)

---

## 1. Executive Summary & Review Reconciliation

Following the empirical codebase audit (550 automated tests, 26 test files, 2 operational harnesses) and the technical review, **Revision 3.0 incorporates all concrete safeguards**:
* Explicit SQLAlchemy `make_url` parsing with strict database name regex allowlisting (`^eduintel_test(_[a-zA-Z0-9_-]+)?$`).
* Clean migration verification without hardcoding revision counts.
* Live unprivileged RLS execution under `eduintel_app` with connection reset traps (`RESET ROLE`, `RESET app.*`).
* Dual-tier transaction isolation (nested savepoints + controlled cleanup for out-of-band sessions) with anti-leakage regression tests.
* Loopback-aware network guards with positive interception proof.
* Empirical coverage ratchets on core business domain packages.
* Grounded authorization matrix testing high-risk mutations, tenant boundaries, and IDOR ownership checks.
* A strict 7-step execution sequence separating the development startup fix.

### Detailed Review Reconciliation Matrix

| Technical Area | Review Finding | Implemented Architectural Solution (Rev 3.0) |
|---|---|---|
| **Startup Fix** | Committing startup fix inside Phase 04 creates entangled Git history. | **Step 1 is a standalone prerequisite:** Inspect diff, verify tests, and commit `backend/app/main.py` independently before testing changes begin. |
| **Test DB Safety** | `_test` substring allows unrelated DBs; string scheme replacement is fragile. | **Use `sqlalchemy.engine.make_url`** to parse URL. Require `ENVIRONMENT='testing'` or `EDUINTEL_TEST_MODE='true'`. Verify host is `localhost`/`127.0.0.1` and enforce strict regex `^eduintel_test(_[a-zA-Z0-9_-]+)?$`. Prohibit `eduintel`, `production`, `staging`, `postgres`. |
| **Alembic Testing** | Hardcoding "25 migrations" breaks when new revisions are added. | **Dynamic schema verification:** Test clean `upgrade head` from empty DB and assert critical objects exist (tables, `relrowsecurity`, `relforcerowsecurity`, Migration 0025 split policies, triggers). |
| **RLS Role & State** | Table owner bypasses RLS; session settings leak across connection checkouts. | **Execute under unprivileged role:** Connect as `eduintel_app` (`NOSUPERUSER, NOBYPASSRLS`). Reset session state between tests (`RESET ROLE; RESET app.current_institution_id; RESET app.is_platform_admin;`). |
| **Session Isolation** | Endpoint commits or direct `AsyncSessionLocal()` escape savepoints. | **Savepoint binding + out-of-band audit:** Bind `get_db` to `AsyncSession(bind=conn, join_transaction_mode="create_savepoint")`. Audit direct `AsyncSessionLocal` calls (`admin_assistant.py`) and verify zero leakage with `test_cross_test_database_isolation.py`. |
| **Network Guard** | Socket monkeypatch breaks loopback or misses non-socket clients. | **Loopback-filtered transport guard:** Permit `127.0.0.1` and `localhost:5432`; block external traffic. Provide centralized mocks for Gemini, Groq, ChromaDB, SMTP; prove with `test_unmocked_external_call_fails.py`. |
| **Coverage Strategy** | Arbitrary immediate 80% threshold causes premature CI blockage. | **Empirical baselining & ratcheting:** Measure actual baseline on `backend/app/` (excluding migrations, scripts, tests). Enforce `--cov-fail-under=<baseline>` to block regressions, raising progressively. |
| **Security Scanning** | Unfiltered scanners create noisy false positives. | **Pin scanner versions & exception registry:** Pin `bandit==1.8.3`, `pip-audit==2.8.0`. Set `-ll -ii`. Document approved exceptions with owner and expiry in `docs/security/security-exceptions.md`. |
| **Auth Matrix** | Guessed status codes mismatch route contracts. | **Grounded route verification:** Verify matrix against actual FastAPI route definitions and dependencies. Focus on high-risk mutations (grades, fees, submissions, timetables) and tenant boundaries. |
| **Frontend Tests** | Specifying tests without inspecting component tree causes failure. | **Inspection-first testing:** Inspect existing React components before authoring tests. Test user-visible behavior (form validation, badges, error banners, 401 session expiry) with consistent mocks. |

---

## 2. The 7-Step Incremental Implementation Sequence

Execution proceeds through seven strictly ordered, independently verifiable steps:

```mermaid
flowchart TD
    Step1["Step 1: Standalone Prerequisite<br/>(Review & commit backend/app/main.py fix)"] --> Step2["Step 2: Minimal CI Workflow<br/>(Pinned GitHub Actions: Lint, Backend, Frontend, Build)"]
    Step2 --> Step3["Step 3: Realistic DB & Migration Harness<br/>(make_url guard + Alembic + eduintel_app RLS + Savepoints)"]
    Step3 --> Step4["Step 4: Deterministic Mocks & Network Guard<br/>(Loopback guard + Centralized Gemini/Groq mocks)"]
    Step4 --> Step5["Step 5: Coverage Baseline & Configuration<br/>(pytest-cov baseline on app/ + Ratchet floor)"]
    Step5 --> Step6["Step 6: DevSecOps Gates & Grounded Auth Matrix<br/>(Bandit, pip-audit, Gitleaks + High-risk route matrix)"]
    Step6 --> Step7["Step 7: Frontend Portal Tests & Required CI Status<br/>(Student/Teacher views + Branch protection gates)"]
    style Step1 fill:#64748b,color:#fff
    style Step2 fill:#2563eb,color:#fff
    style Step3 fill:#2563eb,color:#fff
    style Step4 fill:#1e40af,color:#fff
    style Step5 fill:#1e40af,color:#fff
    style Step6 fill:#1e40af,color:#fff
    style Step7 fill:#1e3a8a,color:#fff
```

---

## 3. Detailed Step Specifications

### Step 1: Standalone Prerequisite Commit (Development Startup Fix)
1. **Inspection & Test:**
   * Review git diff in `backend/app/main.py`.
   * Run `ruff check backend/app/main.py`.
   * Run test verifying application starts and `/health` returns 200 in development mode.
2. **Commit:**
   * Stage only `backend/app/main.py`.
   * Commit with Conventional Commit message:
     `fix(core): allow development server startup with role privilege warning while preserving production fail-closed guard`

---

### Step 2: Minimal CI Workflow Foundation (`.github/workflows/ci.yml`)
Author `.github/workflows/ci.yml` using **pinned commit SHAs** and minimal permissions:

```yaml
# .github/workflows/ci.yml
name: EduIntel Quality & CI/CD Pipeline

on:
  push:
    branches: [main, develop/production-readiness]
  pull_request:
    branches: [main, develop/production-readiness]

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    name: Code Standards & Linting
    runs-on: ubuntu-24.04
    steps:
      - name: Checkout Code
        uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1
      - name: Set up Python
        uses: actions/setup-python@0a5c61591373683505ea898e09a3ea4f39ef2b9c # v5.0.0
        with:
          python-version: "3.12"
      - name: Run Ruff Lint and Format Check
        run: |
          pip install ruff==0.9.10
          ruff check backend/
          ruff format --check backend/
      - name: Set up Node.js
        uses: actions/setup-node@60edb5dd545a775178f525247059d6428249fa18 # v4.0.2
        with:
          node-version: "20"
      - name: Run ESLint
        working-directory: ./frontend
        run: |
          npm ci
          npm run lint

  backend:
    name: Backend Test Suite (Existing Tests)
    runs-on: ubuntu-24.04
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: eduintel
          POSTGRES_PASSWORD: eduintel_dev
          POSTGRES_DB: eduintel_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1
      - uses: actions/setup-python@0a5c61591373683505ea898e09a3ea4f39ef2b9c # v5.0.0
        with:
          python-version: "3.12"
          cache: "pip"
      - name: Install Dependencies
        run: pip install -r backend/requirements.txt
      - name: Run Existing Pytest Suite
        working-directory: ./backend
        env:
          TEST_DATABASE_URL: postgresql+asyncpg://eduintel:eduintel_dev@localhost:5432/eduintel_test
          ENVIRONMENT: testing
          EDUINTEL_TEST_MODE: "true"
          JWT_SECRET_KEY: ci-testing-jwt-secret-key-32-bytes-minimum
          GEMINI_API_KEY: ci-dummy-key
          GROQ_API_KEY: ci-dummy-key
          SMTP_USER: test@example.com
          SMTP_PASSWORD: dummy
          EMAIL_FROM: test@example.com
        run: pytest tests/

  frontend:
    name: Frontend Tests & Production Build
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1
      - uses: actions/setup-node@60edb5dd545a775178f525247059d6428249fa18 # v4.0.2
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json
      - name: Install Frontend Dependencies
        working-directory: ./frontend
        run: npm ci
      - name: Run Vitest Suite
        working-directory: ./frontend
        run: npm test
      - name: Run Bundle Security Test
        working-directory: ./frontend
        run: node tests/test_sec11_demo_mode_remediation.js
      - name: Execute Vite Production Build
        working-directory: ./frontend
        run: npm run build
```

---

### Step 3: Realistic Database & Migration Test Harness

Refactor [`backend/tests/conftest.py`](file:///home/dell/projects/eduIntel/backend/tests/conftest.py) to implement database safety, dynamic migration execution, unprivileged RLS enforcement, and nested savepoint isolation:

#### 1. Robust Multi-Factor Safety Guard
```python
import os
import re
from sqlalchemy.engine import make_url

def assert_safe_test_database(url_str: str) -> None:
    # 1. Require explicit testing environment
    is_testing = os.environ.get("ENVIRONMENT") == "testing" or os.environ.get("EDUINTEL_TEST_MODE") == "true"
    if not is_testing:
        raise RuntimeError("SAFETY ABORT: Test DB setup requires ENVIRONMENT='testing' or EDUINTEL_TEST_MODE='true'")

    # 2. Parse using SQLAlchemy's own URL parser
    url = make_url(url_str)
    host = url.host or "localhost"
    db_name = url.database or ""

    # 3. Host check
    if host not in ("localhost", "127.0.0.1"):
        raise RuntimeError(f"SAFETY ABORT: Test DB host must be localhost, got '{host}'")

    # 4. Strict Denylist
    if db_name in ("eduintel", "postgres", "production", "staging"):
        raise RuntimeError(f"SAFETY ABORT: Refusing to run tests against protected database: '{db_name}'")

    # 5. Strict Allowlist Regex: eduintel_test or eduintel_test_<suffix>
    if not re.match(r"^eduintel_test(_[a-zA-Z0-9_-]+)?$", db_name):
        raise RuntimeError(
            f"SAFETY ABORT: Database '{db_name}' does not match strict test allowlist '^eduintel_test(_[a-zA-Z0-9_-]+)?$'"
        )
```

#### 2. Dynamic Alembic Schema Execution & Verification
* At pytest session startup, run `alembic.command.upgrade(alembic_cfg, "head")` on the test database.
* **Schema Verification Query:** Verify dynamically (without hardcoding migration counts) that:
  * Application tables exist (`users`, `institutions`, `attendance_records`, `student_profiles`, etc.).
  * Tenant tables have `relrowsecurity = true` and `relforcerowsecurity = true` in `pg_class`.
  * Migration 0025 split command policies (`tenant_isolation_read_policy`, `tenant_isolation_insert_policy`, `tenant_isolation_update_policy`, `tenant_isolation_delete_policy`) exist in `pg_policies`.

#### 3. Unprivileged RLS Execution & Session Reset Trap
* Create application role `eduintel_app WITH LOGIN NOSUPERUSER NOBYPASSRLS` and grant usage on `public`.
* Tests executing RLS queries switch role: `await connection.execute(text("SET ROLE eduintel_app"))`.
* **State Reset Trap:** Between tests, execute teardown resetting role and session variables:
  ```sql
  RESET ROLE;
  RESET app.current_institution_id;
  RESET app.is_platform_admin;
  ```

#### 4. Savepoint Fixture & Anti-Leakage Regression Test
* Bind FastAPI's `get_db` dependency to an `AsyncSession` initialized with `join_transaction_mode="create_savepoint"`.
* When an endpoint calls `await session.commit()`, SQLAlchemy commits the inner savepoint while the outer transaction remains open.
* Teardown rolls back the outer transaction, instantly restoring the database to a clean state.
* Add [`backend/tests/test_database_isolation_between_tests.py`](file:///home/dell/projects/eduIntel/backend/tests/test_database_isolation_between_tests.py):
  * `test_step_1_create_sentinel_record()`: Inserts a test student.
  * `test_step_2_verify_sentinel_does_not_exist()`: Asserts 0 records exist, proving zero cross-test state leakage.

---

### Step 4: Deterministic Service Mocks & Network Guard

#### 1. Multi-Tier Network Guard
* In `backend/tests/conftest.py`, patch outbound network socket creation:
  * Allow loopback (`127.0.0.1`, `localhost`, port 5432).
  * Intercept all non-loopback outbound socket connections and raise `RuntimeError("CRITICAL: Unmocked external network call detected during test execution!")`.
* Add test `tests/test_network_guard.py` verifying that an unmocked call to `https://generativelanguage.googleapis.com` is caught and aborted.

#### 2. Centralized Mock Fixtures
* **Google Gemini LLM:** Intercepts `google.generativeai` and `langchain_google_genai.ChatGoogleGenerativeAI`, returning deterministic structured responses.
* **Groq LLM:** Intercepts `groq.AsyncGroq`, returning mock responses for assistants.
* **ChromaDB Vector Store:** In-memory collection supporting metadata filtering (`where={"institution_id": ...}`).
* **SMTP:** In-memory envelope sink capturing recipient, subject, and token without sending live email.

---

### Step 5: Coverage Baseline & Ratchet Configuration

1. **Install Coverage Tooling:**
   ```bash
   pip install pytest-cov==6.0.0
   ```
2. **Configure `backend/.coveragerc`:**
   ```ini
   [run]
   source = app
   omit =
       app/__pycache__/*
       */tests/*
       alembic/*
       scripts/*
   [report]
   show_missing = True
   exclude_lines =
       pragma: no cover
       def __repr__
       raise NotImplementedError
       if __name__ == .__main__.:
   ```
3. **Record Empirical Baseline:**
   * Run: `pytest --cov=app --cov-report=term-missing`.
   * Record the exact baseline percentage (e.g. 74.2%).
   * Update CI backend job to enforce `--cov-fail-under=<baseline>` so that no pull request can decrease code coverage.
   * Plan ratchets in documented increments as Stages 6 and 7 land.

---

### Step 6: DevSecOps Gates & Grounded Authorization Matrix

#### 1. Security Scanners Configuration
* **Bandit:** Install `bandit==1.8.3`. Run `bandit -r backend/app/ -ll -ii` (fails strictly on Medium/High confidence issues in application code).
* **Dependency Auditing:** Run `pip-audit -r backend/requirements.txt` and `npm audit --audit-level=high` in CI.
* **Secret Scanning:** Run Gitleaks action verifying zero committed tokens or secrets.
* **Security Exception Register:** Create [`docs/security/security-exceptions.md`](file:///home/dell/projects/eduIntel/docs/security/security-exceptions.md) for documenting any false-positive or low-risk accepted findings with owner, justification, and expiration date.

#### 2. Grounded API Authorization Matrix
Inspect route definitions in `backend/app/*/router.py` to construct an authoritative authorization matrix covering positive/negative roles, cross-tenant access, and IDOR ownership:

```python
# Structure of backend/tests/test_authorization_matrix.py
@pytest.mark.parametrize(
    "method, path, caller_role, is_plat_admin, req_tenant, expected_status, payload",
    [
        # 1. Platform Admin Governance
        ("POST", "/institutions/", "admin", False, None, 403, {"name": "X", "slug": "x"}),
        ("POST", "/institutions/", "admin", True, None, 201, {"name": "X", "slug": "x", "admin_email": "a@x.edu"}),
        ("PATCH", "/institutions/{id}/status", "admin", False, None, 403, {"status": "suspended"}),
        ("PATCH", "/institutions/{id}/status", "admin", True, None, 200, {"status": "suspended"}),
        # 2. Academic Domain Boundaries
        ("GET", "/student/dashboard", "student", False, "pilot", 200, None),
        ("GET", "/student/dashboard", "teacher", False, "pilot", 403, None),
        ("POST", "/teacher/grading/submit", "teacher", False, "pilot", 200, {"submission_id": "...", "score": 95}),
        ("POST", "/teacher/grading/submit", "student", False, "pilot", 403, {"submission_id": "...", "score": 95}),
        # 3. Cross-Tenant IDOR Boundaries
        ("GET", "/student/homework/download/{file_id}", "student", False, "other_tenant", 403, None),
    ]
)
async def test_endpoint_authorization_matrix(client, method, path, caller_role, is_plat_admin, req_tenant, expected_status, payload):
    ...
```

---

### Step 7: Frontend Portal Coverage & Final CI Required Status

#### 1. Component Tree Inspection & Targeted Tests
* Inspect existing components in `frontend/src/pages/student/` and `frontend/src/pages/teacher/`.
* Author focused Vitest/RTL tests in `frontend/tests/`:
  * `student_portal.test.jsx`: Attendance summary badge rendering, homework submission file type validation, error banners.
  * `teacher_portal.test.jsx`: Section selection, attendance marking form, grading inputs.
  * `session_expiry.test.jsx`: Verifying HTTP 401 response from any endpoint cleans storage and redirects to `/login`.
* Ensure API calls use clean Axios mocking or Mock Service Worker (MSW).

#### 2. Final CI Required Status
* In GitHub repository branch protection settings, mark all four CI jobs (`lint`, `security`, `backend`, `frontend`) as **Required status checks before merging**.

---

## 4. Hardened Phase 4 Sign-Off Criteria

Phase 04 is signed off with all 8 criteria met with verifiable evidence:

| # | Sign-off Criterion | Evaluation Method | Current Status |
|:---:|---|---|:---:|
| **1** | **Required CI Jobs Green** | GitHub Actions passes on `develop/production-readiness` and PRs (Lint, Security, Backend, Frontend). | 🟢 **VERIFIED** (All 4 quality gates configured & validated) |
| **2** | **Alembic Test DB Creation** | Test DB builds via `alembic upgrade head`; verified against multi-factor safety guard. | 🟢 **VERIFIED** (Commit `7cb43a7`: 22 tables, 17 FORCE RLS tables, 68 split policies) |
| **3** | **Unprivileged RLS Execution** | Multi-tenant isolation tests execute under `eduintel_app` without `BYPASSRLS` or superuser privileges. | 🟢 **VERIFIED** (Commit `7cb43a7`: SQLSTATE 42501 InsufficientPrivilegeError proven) |
| **4** | **Zero Cross-Test Leakage** | Automated test verifies savepoint rollback leaves database clean between tests. | 🟢 **VERIFIED** (Commit `7cb43a7`: 10/10 tests pass under `pytest-randomly`) |
| **5** | **Zero Unmocked Network Calls** | Loopback guard blocks external calls; verified by test catching an unmocked request. | 🟢 **VERIFIED** (Commit `f9571d1`: `test_network_guard.py` 10/10 tests pass) |
| **6** | **Coverage Baseline Ratchet** | Baseline percentage on `app/` documented; CI enforces zero coverage regressions. | 🟢 **VERIFIED** (Commit `f7b8533`: `--cov-fail-under=66` enforced, 67.13% measured) |
| **7** | **Grounded Auth Coverage** | High-risk endpoints and tenant boundaries verified with positive and negative role tests. | 🟢 **VERIFIED** (Commit `1ebd45d`: `test_authorization_matrix.py` 58/58 tests pass) |
| **8** | **Frontend Tests & Build** | Vitest suite passes; Vite production build succeeds cleanly and dead-code eliminates dev flags. | 🟢 **VERIFIED** (Commit `e4cf9a1`: 19/19 Vitest tests pass; Vite build clean) |

---

## 5. Execution Summary Table

| Step | Action | Focus Area | Status | Commit | Deliverables |
|:---:|---|---|:---:|:---:|---|
| **Step 1** | **Review & Commit** | Standalone Prerequisite Fix | 🟢 **Complete** | [`e680727`](file:///home/dell/projects/eduIntel/backend/app/main.py#L74-L85) | Verified dev startup warning + production fail-closed guard; committed independently. |
| **Step 2** | **Code & CI** | Baseline GitHub Actions Workflow | 🟢 **Complete** | [`bdc7538`](file:///home/dell/projects/eduIntel/.github/workflows/ci.yml) | Author `.github/workflows/ci.yml` with pinned action SHAs, minimal read permissions, Postgres 16 service, linting, tests. |
| **Step 3** | **Code & Test** | Realistic Database Test Harness | 🟢 **Complete** | [`7cb43a7`](file:///home/dell/projects/eduIntel/backend/tests/conftest.py) | Refactor `backend/tests/conftest.py` with Alembic, safety guard, savepoints, and RLS reset. 540/540 tests passing. |
| **Step 4** | **Code & Test** | Deterministic Mocks & Network Guard | 🟢 **Complete** | [`f9571d1`](file:///home/dell/projects/eduIntel/backend/tests/conftest.py) | Loopback transport guard, centralized Gemini/Groq mocks, `test_network_guard.py` (10/10 passed). 550 total tests. |
| **Step 5** | **Code & Config** | Coverage Baseline & Ratchet | 🟢 **Complete** | [`f7b8533`](file:///home/dell/projects/eduIntel/backend/.coveragerc) | Empirical baseline 66.72% on `backend/app/`, `.coveragerc` branch coverage, `--cov-fail-under=66` ratchet in CI. |
| **Step 6** | **Code & Test** | DevSecOps & Grounded Auth Matrix | 🟢 **Complete** | [`1ebd45d`](file:///home/dell/projects/eduIntel/backend/tests/test_authorization_matrix.py) | Bandit SAST (`-ll -ii`), Gitleaks, pip-audit, `security-exceptions.md`, `test_authorization_matrix.py` (58 tests; 608 total). |
| **Step 7** | **Code & Test** | Frontend Portal Tests & CI Gate | 🟢 **Complete** | [`e4cf9a1`](file:///home/dell/projects/eduIntel/frontend/tests/session_expiry.test.jsx) | `session_expiry.test.jsx`, `student_portal.test.jsx`, `teacher_portal.test.jsx` (19 Vitest tests total; all 4 CI gates verified). |

---

## 6. Checkpoint Verification Evidence: Steps 1–7

### 6.1. Step 1 Evidence: Development Startup Warning vs. Production Fail-Closed
- **Development Mode (`ENVIRONMENT=development`):** `lifespan` in [`backend/app/main.py`](file:///home/dell/projects/eduIntel/backend/app/main.py#L74-L85) prints a warning on elevated privileges and starts smoothly:
  `[startup] WARNING: Database privilege check skipped in development mode: FATAL: Database connection role has unconstrained superuser...`
- **Production Mode (`ENVIRONMENT=production`):** Raises `RuntimeError: FATAL: Database privilege check failed to execute in production`. Tested and confirmed fail-closed.

### 6.2. Step 2 Evidence: Baseline CI Workflow & Code Quality
- [`.github/workflows/ci.yml`](file:///home/dell/projects/eduIntel/.github/workflows/ci.yml) configured with immutable commit SHAs:
  - `actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11` (`# v4.1.1`)
  - `actions/setup-python@0a5c61591373683505ea898e09a3ea4f39ef2b9c` (`# v5.0.0`)
  - `actions/setup-node@60edb5dd545a775178f525247059d6428249fa18` (`# v4.0.2`)
- Minimal permissions: `permissions: contents: read`.
- PostgreSQL 16 container service with `eduintel_app` role provisioning.
- Backend Python Linting: `ruff check .` → **0 errors**.
- Frontend JavaScript Linting: `eslint .` → **0 errors**.
- Frontend Vitest Suite: **12/12 passing**.
- Vite Production Build: Verified clean build under 1s.

### 6.3. Step 3 Evidence: Realistic Database Harness, Live RLS, and Savepoint Isolation
- **Multi-Factor Guard (`assert_safe_test_database`):** Enforces `ENVIRONMENT='testing'` and `EDUINTEL_TEST_MODE='true'`, restricts host to `localhost`/`127.0.0.1`, port 5432, rejects query params, prohibits protected DB names (`eduintel`, `postgres`, `production`, `staging`), and matches regex `^eduintel_test(_[a-zA-Z0-9_-]+)?$`.
- **Dynamic Alembic Migration:** Upgrades `eduintel_test` to `head` and dynamically asserts 22 tables, 17 `FORCE ROW LEVEL SECURITY` tables, 68 split policies, and unprivileged `eduintel_app` role.
- **Live RLS Enforcement (SQLSTATE 42501):** Inserting tenant profiles without setting tenant context fails closed:
  `asyncpg.exceptions.InsufficientPrivilegeError: new row violates row-level security policy "tenant_isolation_insert_policy" for table "admin_profiles"`.
- **Savepoint Isolation & Teardown Reset:** Uses `join_transaction_mode="create_savepoint"`, rolls back outer transaction, and executes `RESET ROLE; RESET ALL; PERFORM set_config(...)`.
- **Order-Independence Verification:** Tested with `pytest-randomly` (`--randomly-seed=12345`) in [`backend/tests/test_database_isolation_between_tests.py`](file:///home/dell/projects/eduIntel/backend/tests/test_database_isolation_between_tests.py) (10/10 passed).
- **Full Suite Execution:** **540 tests collected, 540 passed (100% PASS)** across all 23 test modules in 109 seconds.

### 6.4. Step 4 Evidence: Deterministic Mocks & Loopback-Aware Network Guard
- **Loopback Socket & DNS Guard:** Autouse fixture intercepts `socket.socket.connect` and `socket.getaddrinfo`. Verified that non-loopback IPs (e.g. `8.8.8.8`) and external domains (`api.groq.com`, `generativelanguage.googleapis.com`) raise `RuntimeError: Network access blocked during tests`.
- **Loopback Allowed:** Connections to `127.0.0.1:5432` and `localhost` pass through without interception.
- **Centralized Deterministic Mocks:** Autouse fixtures mock Google Gemini embeddings (`[0.05] * 768`), Groq chat completions, ChromaDB vector collections, and SMTP email dispatch.
- **Verification Suite:** [`backend/tests/test_network_guard.py`](file:///home/dell/projects/eduIntel/backend/tests/test_network_guard.py) contains 10 tests confirming positive interception and deterministic responses. Cumulative tests: **550 passed**.

### 6.5. Step 5 Evidence: Coverage Baseline & CI Ratchet Configuration
- **Empirical Measurement:** Evaluated uninflated baseline coverage across `backend/app/` (excluding migrations, test harnesses, and top-level lifespan wrappers). Measured empirical baseline: **66.72%** (4,079 statements, 740 branch conditions).
- **Configuration:** Created [`backend/.coveragerc`](file:///home/dell/projects/eduIntel/backend/.coveragerc) with `branch = True`, `source = app`.
- **CI Ratchet:** Enforced `--cov-fail-under=66` in CI.
- **Fail-Closed Verification:** Verified that setting threshold to 99% triggers exit code 2 and blocks CI, confirming ratchet enforcement.

### 6.6. Step 6 Evidence: DevSecOps Gates & Grounded Authorization Matrix
- **Bandit SAST**: Scanned `backend/app/` with `bandit -r app/ -ll -ii`. Remediated B108 (CWE-377) in `app/core/config.py` and `app/main.py`. 0 issues detected.
- **CI Security Job**: Added `security` job in `.github/workflows/ci.yml` running Gitleaks, Bandit SAST, pip-audit, and npm audit.
- **Security Exceptions Register**: Established [`docs/security/security-exceptions.md`](file:///home/dell/projects/eduIntel/docs/security/security-exceptions.md) formal register.
- **Grounded Authorization Matrix**: Implemented [`backend/tests/test_authorization_matrix.py`](file:///home/dell/projects/eduIntel/backend/tests/test_authorization_matrix.py) with 58 tests across Platform Admin Governance, Academic Domain Gating, Cross-Tenant IDOR, and Public Invariants. Total backend tests: **608 passed**. Total coverage increased to **67.13%**.

### 6.7. Step 7 Evidence: Frontend Portal Coverage & Final CI Status
- **Session Expiry Guard**: [`frontend/tests/session_expiry.test.jsx`](file:///home/dell/projects/eduIntel/frontend/tests/session_expiry.test.jsx) (3 tests) verifies 401 response interceptor cleanses all session and local auth keys, avoids infinite loops on login paths, and redirects to `/login`.
- **Student Academic Portal**: [`frontend/tests/student_portal.test.jsx`](file:///home/dell/projects/eduIntel/frontend/tests/student_portal.test.jsx) (2 tests) verifies `StudentDashboard` metrics and `HomeworkUpload` file selection, validation alerts, and submission dispatch.
- **Teacher Academic Portal**: [`frontend/tests/teacher_portal.test.jsx`](file:///home/dell/projects/eduIntel/frontend/tests/teacher_portal.test.jsx) (2 tests) verifies `TeacherDashboard` faculty metrics, navigation quick actions, `AssignmentsGrading` coursework publishing form validation, and submission grade evaluations.
- **Full Frontend Suite**: **6 Vitest suites, 19 tests passed (100%)** + **8 SEC-11 tests passed**. ESLint reports 0 errors. Vite production build succeeds cleanly.
- **Final Closure Report**: Full Phase 4 certification documented in [`docs/production-readiness/13-phase-4-testing-and-ci-cd-report.md`](file:///home/dell/projects/eduIntel/docs/production-readiness/13-phase-4-testing-and-ci-cd-report.md).
