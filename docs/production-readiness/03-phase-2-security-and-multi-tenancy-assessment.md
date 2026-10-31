# Phase 2A: Comprehensive Security, Authorization, Privacy & Multi-Tenancy Assessment

**Project:** EduIntel AI — Educational Decision Intelligence Platform  
**Branch:** `develop/production-readiness`  
**Assessment Date:** October 30, 2026  
**Auditor Roles:** Principal Software Architect, Application Security Engineer, Database Architect, Multi-Tenant SaaS Specialist  
**Status:** 🟡 **ASSESSMENT COMPLETE — AWAITING USER APPROVAL FOR PHASE 2B IMPLEMENTATION**

---

## 1. Executive Summary

This assessment provides the foundational security evaluation and architectural design required to evolve EduIntel from a single-institute system into an enterprise-grade, Multi-Tenant Software-as-a-Service (SaaS) educational platform.

### Scope and Boundary Adherence
- **Assessment Only:** Zero application source code was modified, zero database schemas were altered, no Alembic migrations were executed, no secrets were altered, and no Git commits or pushes were performed.
- **Empirical Grounding:** Every vulnerability, architectural limitation, and data leakage vector reported herein is supported by exact source code file paths, line numbers, and verified execution flows.

### Headline Findings:
1. **Critical Vulnerabilities:**
   - **SEC-01 (CVSS 9.8):** Password reset tokens are returned directly in HTTP JSON response bodies (`/auth/password-reset/request`), allowing immediate account takeover for any known email address.
   - **SEC-02 (CVSS 9.8):** Public signup accepts `role: "admin"`, allowing arbitrary self-registration of administrative users without invitation or approval.
   - **SEC-03 (CVSS 9.6):** The Parent Report endpoint (`POST /reports/parent-report/{student_id}`) is completely unauthenticated, leaks minor student academic dossiers, and acts as an open SMTP email relay to arbitrary external addresses.
   - **SEC-04 (CVSS 9.4):** Total absence of multi-tenancy. Every relational query throughout the platform executes globally across the entire database without tenant qualifiers.
2. **Architecture Recommendation:** Adopt **Shared Database, Shared Schema with PostgreSQL Row-Level Security (RLS)** paired with a decoupled **Multi-Institution Membership Model** (`institutions`, `users`, `institution_memberships`), transaction-scoped tenant context propagation (`SET LOCAL`), ChromaDB metadata vector partitioning, and tenant-prefixed file storage.

---

## 2. Existing Architecture Overview

EduIntel is built as an async Python modular monolith with 16 domain packages:
- **Backend Framework:** FastAPI 0.111.0 on Python 3.12, running AsyncIO with SQLAlchemy 2.0 and `asyncpg`.
- **Relational Persistence:** PostgreSQL 16 comprising 20 tables managed via 20 Alembic migrations.
- **Vector Store:** ChromaDB 0.5.3 running in local persistent directory mode (`backend/chroma_data/`), using dual global collections (`portal_help_docs`, `study_materials`) with Gemini embeddings.
- **AI & Agents:** LangGraph 0.1.0 state machines (`AdminAssistant`, `PortalAssistant`) utilizing Gemini 2.5 Flash with Groq fallback (`openai/gpt-oss-120b`), and a FastMCP server over stdio.
- **Machine Learning:** Pre-trained XGBoost classifiers (`at_risk_model.joblib`, `weak_topic_model.joblib`) with SHAP TreeExplainer feature importance and local SQLite MLflow tracking (`mlflow.db`).
- **Frontend Client:** React 18 SPA built with Vite, Tailwind CSS, custom design tokens, and Axios HTTP client.

---

## 3. Authentication Architecture Audit (Workstream A)

### Detailed Findings & Technical Answers:

1. **How does authentication currently work?**
   Authentication is handled via OAuth2 Bearer password flow. Clients `POST /auth/login` with `email` and `password`. [`app/auth/service.py:39`](file:///home/dell/projects/eduIntel/backend/app/auth/service.py#L39) looks up the user, verifies the password hash, checks `is_active`, and returns a signed JWT.
2. **Where are passwords stored?**
   Passwords are stored in the PostgreSQL `users` table ([`app/users/models.py:16`](file:///home/dell/projects/eduIntel/backend/app/users/models.py#L16)) in the `hashed_password` column (`VARCHAR(255)`). Plaintext passwords are never stored.
3. **Which password hashing algorithm is used?**
   Passlib's `CryptContext(schemes=["bcrypt"], deprecated="auto")` with standard 12 salt rounds ([`app/auth/security.py:8`](file:///home/dell/projects/eduIntel/backend/app/auth/security.py#L8)).
4. **How are JWTs generated and validated?**
   Generated and decoded via `python-jose` using symmetric HMAC-SHA256 (`HS256`) and `settings.JWT_SECRET_KEY` loaded from `.env` ([`app/auth/security.py:25`](file:///home/dell/projects/eduIntel/backend/app/auth/security.py#L25)).
5. **Which claims are included in the JWT?**
   The payload contains only `sub` (User UUID string), `role` (`student`, `teacher`, or `admin`), and `exp` (expiration timestamp). It lacks tenant identifier (`institution_id`), token ID (`jti`), issuer (`iss`), and audience (`aud`).
6. **How is a user's identity retrieved?**
   FastAPI dependency `get_current_user` in [`app/users/dependencies.py:15`](file:///home/dell/projects/eduIntel/backend/app/users/dependencies.py#L15) decodes the Bearer token, extracts `sub`, and queries `select(User).where(User.id == uuid.UUID(user_id))` where `is_active = True`.
7. **How are expired or invalid tokens handled?**
   `decode_access_token` catches `JWTError` and raises `ValueError`. `get_current_user` catches this and returns `HTTP 401 Unauthorized` with `headers={"WWW-Authenticate": "Bearer"}`.
8. **Is token revocation possible?**
   **No.** Tokens are completely stateless. There is no blocklist, token versioning, or Redis store. A compromised token remains valid until its 30-minute expiration elapses.
9. **Are refresh tokens implemented?**
   **No.** Users must re-enter their full credentials upon token expiration.
10. **Are there authentication bypass risks?**
    **Yes.** 
    - *Bypass 1:* Password reset token disclosure in `POST /auth/password-reset/request` allows immediate password override.
    - *Bypass 2:* Public registration in `POST /auth/signup` permits self-provisioning `role: "admin"`.
    - *Bypass 3:* Frontend `localStorage.getItem("demo_mode")` bypasses React route guards.
11. **Are sensitive tokens stored securely on the frontend?**
    **No.** Tokens are stored in browser `localStorage` under `access_token` ([`frontend/src/pages/auth/Login.jsx:22`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/Login.jsx#L22)), exposing them to Cross-Site Scripting (XSS).
12. **Are authentication endpoints protected against brute-force attempts?**
    **No.** There is zero rate limiting (no `slowapi`, no Redis bucket, no IP lockout) on `/auth/login` or `/auth/signup`.

---

## 4. RBAC & Authorization Audit (Workstream B)

### 4.1. Existing Role Model & Verification
EduIntel enforces roles through a single string column on `users` (`role = Enum('student', 'teacher', 'admin')`).
- **Platform Administrator:** **Non-existent.** There is no platform super-admin role. Any user with role `admin` is treated as a full system administrator.
- **Institute Administrator:** Combined with system admin; accesses all institutional and system-wide data.
- **Teacher:** Enforced via `require_role("teacher")`.
- **Student:** Enforced via `require_role("student")`.

### 4.2. High-Level Authorization Findings
- **Inconsistent Checks:** 3 endpoints (`/ocr/extract`, `/reports/parent-report/{student_id}`, `/rag/collections`) lack all authorization.
- **IDOR Vulnerabilities:** Any teacher can download any student's homework (`/teacher/homework/{submission_id}/file`) or inspect any student's ML diagnostics (`/ml/predict/at-risk/{student_id}`).
- **Cross-Tenant Bleed:** `get_all_submissions`, `get_students`, `get_teachers`, and `list_assignments` return all records across the entire database.

*(For the complete 60-endpoint matrix, see [`docs/security/authorization-matrix.md`](file:///home/dell/projects/eduIntel/docs/security/authorization-matrix.md)).*

---

## 5. Tenant Ownership Inventory (Workstream C)

Every entity was evaluated for tenant ownership, direct/indirect relationships, and required tenant strategy:

| Entity | Current Table | Classification | Current Foreign Keys | Required Multi-Tenant Strategy |
|---|---|:---:|---|---|
| **Institutions** | *New Table* | **Platform-Owned** | None (Root entity) | Root tenant entity with `id`, `name`, `slug`, `domain`, `settings`. |
| **Memberships** | *New Table* | **Institution-Owned** | FK -> `institutions.id`, FK -> `users.id` | Links users to institutions; stores tenant-specific role. |
| **Users** | `users` | **Globally Shared** | None | Global user identity account; globally unique email. |
| **Student Profiles** | `student_profiles` | **Institution-Owned** | FK -> `users.id` | Add `institution_id`; unique `(institution_id, roll_number)`. |
| **Teacher Profiles** | `teacher_profiles` | **Institution-Owned** | FK -> `users.id` | Add `institution_id`; departmental classification. |
| **Admin Profiles** | `admin_profiles` | **Institution-Owned** | FK -> `users.id` | Add `institution_id`; designation. |
| **Assignments** | `assignments` | **Institution-Owned** | FK -> `users.id` (teacher) | Add `institution_id`; composite unique `(institution_id, id)`. |
| **Homework Submissions** | `homework_submissions` | **Institution-Owned** | FK -> `assignments.id`, FK -> `users.id` | Add `institution_id`; composite FK referencing `assignments(institution_id, id)`. |
| **Doubt Threads** | `doubt_threads` | **Institution-Owned** | FK -> `users.id` (student) | Add `institution_id`; RLS enabled. |
| **Doubt Messages** | `doubt_messages` | **Institution-Owned** | FK -> `doubt_threads.id`, FK -> `users.id` | Add `institution_id`; RLS enabled. |
| **Study Materials** | `study_materials` | **Institution-Owned** | FK -> `users.id` (teacher) | Add `institution_id`; file path prefix & ChromaDB metadata tag. |
| **Exam Results** | `exam_results` | **Institution-Owned** | FK -> `users.id` (student) | Add `institution_id`; RLS enabled. |
| **Timetable Entries** | `timetable_entries` | **Institution-Owned** | FK -> `users.id` (teacher) | Add `institution_id`; unique `(institution_id, class_section, day, period)`. |
| **Salary Records** | `salary_records` | **Institution-Owned** | FK -> `users.id` (teacher) | Add `institution_id`; strict RLS policy. |
| **Fee Records** | `fee_records` | **Institution-Owned** | FK -> `users.id` (student) | Add `institution_id`; strict RLS policy. |
| **Attendance Records** | `attendance_records` | **Institution-Owned** | FK -> `users.id` (student) | Add `institution_id`; composite index `(institution_id, attendance_date)`. |
| **Announcements** | `announcements` | **Institution-Owned** | FK -> `users.id` (creator) | Add `institution_id`; RLS enabled. |
| **Audit Logs** | `audit_logs` | **Institution-Owned** | FK -> `users.id` | Add `institution_id`; PII-redacted prompt storage. |
| **Agent Trace Logs** | `agent_trace_logs` | **Institution-Owned** | `session_id` | Add `institution_id`; AI latency & token tracking. |
| **LLM Usage Logs** | `llm_usage_logs` | **Platform / Tenant Shared** | `endpoint` | Add `institution_id` (nullable for system benchmarks); aggregate token accounting. |

---

## 6. Tenant Isolation Architecture Comparison (Workstream D)

Three architectures were evaluated:
1. **Option 1: Shared Database, Shared Schema (Application-Level Filter Only):**
   - High developer-error risk; single omitted `where()` leaks cross-tenant data. Rejected.
2. **Option 2: Shared Database, Shared Schema with PostgreSQL Row-Level Security (RLS) [RECOMMENDED]:**
   - Combines single-instance cost efficiency with engine-level isolation. Database engine intercepts all SQL queries and transparently applies `WHERE institution_id = current_setting('app.current_institution_id')`.
   - Overhead is negligible (< 2%) with composite indexes.
3. **Option 3: Separate Database or Schema per Institution:**
   - Prohibitive infrastructure cost on AWS RDS ($15–$50/mo per small institute). Alembic migrations across hundreds of tenant schemas suffer catastrophic failure and schema drift. Rejected.

### Connection Pooling & Transaction-Scoped Context Protocol:
Session-level `SET app.current_institution_id` pollutes connection pools. EduIntel must use **`SET LOCAL app.current_institution_id = :id`** inside explicit transaction blocks (`async with session.begin():`). When the transaction completes, the setting automatically reverts to empty, leaving the connection pristine.

*(For complete technical specifications, see [`docs/security/tenant-isolation-design.md`](file:///home/dell/projects/eduIntel/docs/security/tenant-isolation-design.md)).*

---

## 7. Recommended Multi-Institution Data Model (Workstream G)

We recommend decoupling platform user identity from institutional affiliation via an explicit membership model:
- **`institutions` Table:** Represents the educational entity (`id`, `name`, `slug`, `domain`, `is_active`, `tier`, `settings`).
- **`users` Table:** Represents a human identity (`id`, `email`, `hashed_password`, `name`, `phone`, `is_platform_admin`, `is_active`).
- **`institution_memberships` Table:** Links user to institute (`id`, `institution_id`, `user_id`, `role`, `status`, `joined_at`). Constraint: `UNIQUE (institution_id, user_id)`.

### Benefits:
- Expert teachers can teach at multiple independent coaching institutes using a single login.
- Parents can monitor children enrolled across multiple institutes.
- Platform administrators can oversee tenant health without dummy accounts in every school.
- Membership suspension cuts access to one institute without deleting the user's account.

---

## 8. AI, RAG & ML Isolation Assessment (Workstream E)

1. **ChromaDB Vector Store:**
   - *Current State:* Two global collections (`portal_help_docs`, `study_materials`). Chunks have no tenant metadata. Queries search across all institutes' documents.
   - *Target Architecture:* Keep `portal_help_docs` global. Partition `study_materials` by upserting chunks with `metadata={"institution_id": str(tenant_id), ...}` and mandating `where={"institution_id": str(current_tenant_id)}` on all queries.
2. **LangGraph AI Assistants:**
   - *Admin AI Assistant:* Inject `institution_id` into `AdminAssistantState`. Pass `institution_id` to all 6 reporting tools so financial and attendance summaries are strictly tenant-bound.
   - *Session Namespacing:* Enforce session prefixes: `session_id = f"{tenant_id}:{user_id}:{client_uuid}"`.
3. **FastMCP Server:**
   - `get_student_data` must validate that the student belongs to the caller's `institution_id`.
   - `send_email` must enforce recipient domain validation and tenant rate limits.
4. **Machine Learning Pipelines:**
   - XGBoost models (`at_risk_model.joblib`, `weak_topic_model.joblib`) are pre-trained on generalized patterns (weights contain no tenant PII).
   - Inference feature computation in `app/ml/service.py` executes under PostgreSQL RLS, automatically preventing cross-tenant feature leakage.

---

## 9. File & Storage Isolation Assessment (Workstream E)

- **Current State:** Flat local directories (`backend/uploads/homework/` and `backend/uploads/study_materials/`) storing all files from all institutes together.
- **Target Architecture:**
  - Prefix directory paths by tenant UUID:
    `uploads/{institution_id}/homework/{file_uuid}_{filename}`
    `uploads/{institution_id}/study_materials/{file_uuid}_{filename}`
  - Route download endpoints verify that requested files reside strictly within `uploads/{current_tenant_id}/*`.
  - In Phase 8, mirror this structure to Amazon S3: `s3://eduintel-production-uploads/{institution_id}/*` with IAM/pre-signed URL constraints.

---

## 10. API Security & Privacy Findings (Workstream F)

1. **Unredacted PII in Audit Logs (SEC-13):** `log_ai_query` records raw `query_text` into `audit_logs`. Prompts containing phone numbers or emails persist indefinitely in plaintext.
   - *Remediation:* Pass `query_text` through `redact_pii()` before saving to `audit_logs`.
2. **Frontend Token Storage (SEC-10):** Storing JWTs in `localStorage` creates XSS vulnerability.
   - *Remediation:* Migrate to `HttpOnly`, `Secure`, `SameSite=Strict` cookies.
3. **Missing HTTP Security Headers (SEC-15):** Responses lack HSTS, CSP, and X-Frame-Options.
   - *Remediation:* Add a security headers middleware in FastAPI.
4. **Stale CORS Origin (SEC-16):** Hardcoded decommissioned AWS IP `http://13.205.55.115` must be removed from `allow_origins`.

*(For complete privacy assessment, see [`docs/security/privacy-and-pii-assessment.md`](file:///home/dell/projects/eduIntel/docs/security/privacy-and-pii-assessment.md)).*

---

## 11. Existing Data Migration Strategy (Workstream H)

The current development database contains 500+ synthetic students and 209,796 historical records representing an existing coaching institute.

### Zero-Data-Loss Migration Protocol:
1. **Full Logical Snapshot:** Execute `pg_dump -Fc -d eduintel > backup_pre_phase2.dump`.
2. **Create New Tables:** Execute DDL creating `institutions` and `institution_memberships`.
3. **Seed Default Institution:** Insert seed institution record (e.g. UUID `a0000000-0000-0000-0000-000000000001`, name "EduIntel Pilot Academy", slug "eduintel-pilot").
4. **Backfill Memberships:** Query `users` and insert matching rows into `institution_memberships` associating existing users with the seed institution.
5. **Add Tenant Column:** Add `institution_id UUID REFERENCES institutions(id)` as nullable to all 17 tenant tables.
6. **Backfill Records:** Execute `UPDATE <table> SET institution_id = 'a0000000-0000-0000-0000-000000000001' WHERE institution_id IS NULL;` across all 17 tables.
7. **Enforce Non-Null & Composite Constraints:** Set `ALTER TABLE <table> ALTER COLUMN institution_id SET NOT NULL;` and create composite foreign keys.
8. **Enable RLS:** Enable Row-Level Security on all 17 tables and apply isolation policies.
9. **Verification Drill:** Verify record counts (209,796 rows) match exactly before and after migration.

---

## 12. Tenant Isolation Testing Strategy (Workstream I)

An automated verification suite in `tests/test_tenant_isolation.py` using two synthetic institutions:
- **Institute A:** `Admin A`, `Teacher A`, `Student A`.
- **Institute B:** `Admin B`, `Teacher B`, `Student B`.
- **Platform Admin:** Global auditor.

### Core Test Cases:
1. **Cross-Tenant Student Isolation:** `Student A` attempts `GET /student/homework` with `Student B` submission ID -> Returns HTTP 404.
2. **Cross-Tenant Teacher Grading:** `Teacher A` attempts `PATCH /teacher/homework/{submission_b_id}/grade` -> Returns HTTP 404/403.
3. **Cross-Tenant Admin Metrics:** `Admin A` queries `/admin/debug/salary-summary` -> Returns only Institute A payroll amounts.
4. **ChromaDB Vector Isolation:** Semantic query by `Student A` returns 0 chunks from Institute B study materials.
5. **Physical File Access:** `Teacher A` requests `/teacher/homework/{submission_b_id}/file` -> Returns HTTP 404.
6. **Platform Admin Audit Mode:** Platform admin token bypasses RLS and inspects aggregated metrics.

---

## 13. Supabase vs. AWS RDS Evaluation (Workstream J)

| Architecture Question | Supabase PostgreSQL Evaluation | AWS RDS PostgreSQL Evaluation |
|---|---|---|
| **Can EduIntel use it as managed PostgreSQL?** | ✅ Yes. Connect via standard PostgreSQL connection string (`postgresql+asyncpg://...`). | ✅ Yes. Standard PostgreSQL RDS instance. |
| **Can FastAPI handle auth & business logic?** | ✅ Yes. FastAPI JWT authentication operates identically; Supabase Auth is completely bypassed. | ✅ Yes. Full control in FastAPI. |
| **Can SQLAlchemy & Alembic continue working?** | ✅ Yes. Standard asyncpg dialect; Alembic runs standard migrations. | ✅ Yes. Fully native. |
| **Implications of PostgreSQL RLS?** | ✅ Native support. Supabase runs standard PostgreSQL RLS policies; `SET LOCAL app.current_institution_id` works identically. | ✅ Native support. Standard PostgreSQL RLS. |
| **Connection Pooling & PgBouncer?** | 🟡 Supabase uses Supavisor/PgBouncer. In transaction pooling mode, `statement_cache_size=0` must be configured for asyncpg. | 🟡 Requires AWS RDS Proxy or application-side pooling. |
| **Estimated Monthly Cost (Startup Phase)** | 🟢 **$25/month flat (Pro tier):** Includes 8GB compute, 100GB storage, automated backups, and vector extension. | 🔴 **$50–$70/month:** `db.t4g.medium` instance + multi-AZ + allocated GP3 storage + backup retention. |
| **Operational Simplicity** | 🟢 Built-in dashboard, instant table viewer, automated SSL, zero VPC configuration needed. | 🟡 Requires VPC peering, security groups, subnet groups, and manual monitoring setup. |

### Recommendation:
Both providers support the target RLS architecture cleanly without code divergence. **Supabase Pro ($25/mo)** offers superior developer agility and lower fixed cost for the initial multi-tenant rollout, while **AWS RDS** is preferable if strict VPC isolation and AWS enterprise compliance are mandatory. The final decision remains open.

---

## 14. Security Risks Classified by Severity

| Risk ID | Title | Severity | CVSS | Affected Source | Impact Summary | User Approval Needed? |
|---|---|:---:|:---:|---|---|:---:|
| **SEC-01** | Public Password Reset Token Disclosure | 🔴 Critical | 9.8 | [`app/auth/router.py:48`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py#L48) | Complete account takeover of any user | Yes (Authorize removal of dev token) |
| **SEC-02** | Admin Self-Registration Privilege Escalation | 🔴 Critical | 9.8 | [`app/auth/router.py:19`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py#L19) | Arbitrary administrator account creation | Yes (Authorize signup restriction) |
| **SEC-03** | Unauthenticated Parent Report & Open SMTP Relay | 🔴 Critical | 9.6 | [`app/reports/router.py:18`](file:///home/dell/projects/eduIntel/backend/app/reports/router.py#L18) | Minor PII exposure & arbitrary email spam | Yes (Authorize auth enforcement) |
| **SEC-04** | Total Absence of Multi-Tenant Isolation | 🔴 Critical | 9.4 | Global / All services | Cross-tenant commercial data breach | Yes (Authorize Phase 2B schema migration) |
| **SEC-05** | Unauthenticated Tesseract OCR Execution | 🟠 High | 7.5 | [`app/ocr/router.py:11`](file:///home/dell/projects/eduIntel/backend/app/ocr/router.py#L11) | CPU thread exhaustion / DoS | Yes |
| **SEC-06** | IDOR in Homework & Study Material Downloads | 🟠 High | 8.6 | [`app/teacher/router.py:137`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py#L137) | Cross-tenant private file theft | Yes |
| **SEC-07** | IDOR in ML Diagnostics & Predictions | 🟠 High | 7.7 | [`app/ml/router.py:16`](file:///home/dell/projects/eduIntel/backend/app/ml/router.py#L16) | Unauthorized student diagnostic access | Yes |
| **SEC-08** | RAG Cross-Tenant Vector Leakage | 🟠 High | 7.7 | [`app/rag/service.py:167`](file:///home/dell/projects/eduIntel/backend/app/rag/service.py#L167) | Proprietary study notes leaked in AI chat | Yes |
| **SEC-09** | LangGraph Admin AI Aggregation Bleed | 🟠 High | 8.5 | [`app/agents/admin_assistant.py`](file:///home/dell/projects/eduIntel/backend/app/agents/admin_assistant.py) | Institutional financial data leakage | Yes |
| **SEC-10** | Token Storage in LocalStorage | 🟠 High | 7.2 | [`frontend/Login.jsx:22`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/Login.jsx#L22) | XSS token theft | Yes |
| **SEC-11** | Frontend Demo Mode Route Bypass | 🟠 High | 7.1 | [`frontend/ProtectedRoute.jsx:4`](file:///home/dell/projects/eduIntel/frontend/src/components/ProtectedRoute.jsx#L4) | Client-side authorization bypass | Yes |
| **SEC-12** | Absence of Rate Limiting | 🟡 Medium | 5.3 | Auth & AI endpoints | Credential stuffing & LLM bill shock | Yes |
| **SEC-13** | Unredacted PII in Observability Logs | 🟡 Medium | 5.5 | [`app/observability/service.py`](file:///home/dell/projects/eduIntel/backend/app/observability/service.py) | PII persistence in audit table | Yes |
| **SEC-14** | Inability to Revoke Stateless JWTs | 🟡 Medium | 5.3 | [`app/auth/security.py`](file:///home/dell/projects/eduIntel/backend/app/auth/security.py) | Token validity after logout/password reset | Yes |
| **SEC-15** | Missing HTTP Security Headers | 🟡 Medium | 4.8 | [`app/main.py`](file:///home/dell/projects/eduIntel/backend/app/main.py) | Clickjacking / MIME sniffing risks | Yes |
| **SEC-16** | Stale Decommissioned AWS IP in CORS | 🟡 Medium | 4.3 | [`app/main.py:21`](file:///home/dell/projects/eduIntel/backend/app/main.py#L21) | Potential third-party origin trust | Yes |
| **SEC-17** | Weak Password Complexity Policy | 🟡 Medium | 4.2 | [`app/auth/schemas.py:9`](file:///home/dell/projects/eduIntel/backend/app/auth/schemas.py#L9) | Brute-force / dictionary vulnerability | Yes |
| **SEC-18** | Public Vector Store Status Disclosure | ⚪ Low | 3.7 | [`app/rag/router.py:20`](file:///home/dell/projects/eduIntel/backend/app/rag/router.py#L20) | Internal metadata disclosure | Yes |
| **SEC-19** | Duplicate User Model Declaration | ⚪ Info | N/A | `auth.models` vs `users.models` | Code maintainability gap | Yes |

---

## 15. Decisions Requiring User Approval

Before Phase 2B implementation begins, your explicit approval is required on the following architectural and business decisions:

1. **Initial Institution Identity:**
   - What name and slug should be assigned to the initial institution created during backfill?
   - *Recommendation:* Name: `"EduIntel Demonstration Institute"`, Slug: `"eduintel-demo"`.
2. **User Identity Uniqueness:**
   - Should user email addresses be globally unique across all institutions (like Slack, GitHub, Linear), or should the same email be allowed to register independently per institution?
   - *Recommendation:* **Globally Unique.** Allows one unified identity with memberships across multiple institutions.
3. **Public Registration Policy:**
   - Should public self-registration (`/auth/signup`) be restricted to students only, or completely disabled in favor of an invitation-only model for all roles?
   - *Recommendation:* **Invitation-Only** for Administrators and Teachers; self-registration for students only if an institute enrollment code is supplied.
4. **Critical Security Hotfixes Scope:**
   - Confirm approval to immediately remediate SEC-01 (remove dev reset token), SEC-02 (lock admin signup), and SEC-03 (authenticate parent reports) as Milestone 1 of Phase 2B.
5. **Database Provider Direction:**
   - Retain local Docker PostgreSQL for development and prepare for Supabase Pro or AWS RDS for production.

---

## 16. Phase 2 Implementation Roadmap Summary

- **Milestone 1:** Critical Security Hotfixes (SEC-01, SEC-02, SEC-03, SEC-05, SEC-16).
- **Milestone 2:** Multi-Institution Schema (`institutions`, `institution_memberships`) & Historical Data Backfill.
- **Milestone 3:** Tenant Context Middleware & Connection Pool Safety (`SET LOCAL`).
- **Milestone 4:** PostgreSQL Row-Level Security (RLS) Policies on all 17 tables & Composite Indexes.
- **Milestone 5:** Vector (ChromaDB), File Storage (`uploads/{institution_id}/...`), and AI Agent Scoping.
- **Milestone 6:** API RBAC/ABAC Hardening & IDOR Remediation across all 60 endpoints.
- **Milestone 7:** Automated Cross-Tenant Isolation Verification Test Suite.

*(For full execution details, see [`Hisham-workspace/implementation-plans/PHASE-2-IMPLEMENTATION-ROADMAP.md`](file:///home/dell/projects/eduIntel/Hisham-workspace/implementation-plans/PHASE-2-IMPLEMENTATION-ROADMAP.md)).*

---

## 17. Dependencies & Blockers

1. **Test Database Environment Blocker:**
   - The test suite requires an isolated PostgreSQL instance for integration tests (`tests/test_auth_rbac.py` and upcoming `test_tenant_isolation.py`). Test container provisioning must be maintained.
2. **Awaiting User Approval:**
   - Milestone 1 and Milestone 2 require user sign-off on the decisions in Section 15 before applying any changes to the codebase or database.

---

## 18. Final Recommendation

**Do not deploy the current codebase to production or multi-institution environments in its current state.**

The platform currently operates with zero tenant isolation, exposes password reset tokens, permits self-registration as an administrator, and leaves sensitive minor student dossiers and SMTP relays unauthenticated. 

Adopting the proposed **Shared Database with PostgreSQL RLS and Decoupled Membership Model** will establish enterprise-grade security, prevent cross-tenant leakage, and provide a solid architectural foundation for EduIntel's commercial SaaS growth.

Proceed with **Phase 2B (Milestones 1 through 7)** upon your explicit authorization.

