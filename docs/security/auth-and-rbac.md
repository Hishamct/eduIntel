# EduIntel AI — Authentication, RBAC & Security Architecture

This document details EduIntel AI's identity management, token lifecycle, role-based access control (RBAC), multi-factor relational authorization, and security mitigations on branch `develop/production-readiness`.

---

## 1. Authentication Flow & Token Lifecycle

EduIntel implements JSON Web Token (JWT) authentication using the `HS256` symmetric signing algorithm and the `passlib` bcrypt hashing library. Following Phase 2B (SEC-10), web browser clients store tokens exclusively in `HttpOnly` cookies, preventing XSS credential theft.

```mermaid
sequenceDiagram
    autonumber
    actor Client as User / Browser
    participant API as FastAPI /auth/login
    participant DB as PostgreSQL 16 (users table)
    participant Protected as Protected Endpoint

    Client->>API: POST /auth/login (email, password)
    API->>DB: SELECT * FROM users WHERE email = :email
    DB-->>API: Return user record (with hashed_password)
    API->>API: Verify password using passlib bcrypt.verify()
    alt Invalid Password / User Inactive / Missing User
        API-->>Client: 401 Unauthorized ("Invalid credentials")
    end
    API->>API: Generate HS256 JWT: {sub: user_id, role: role, exp: timestamp}
    API-->>Client: 200 OK + Set-Cookie: access_token=eyJ... (HttpOnly, Secure, SameSite=Strict, Path=/)

    Note over Client,Protected: Subsequent Authenticated Requests
    Client->>Protected: GET /users/me (Browser automatically attaches Cookie: access_token)
    Protected->>Protected: get_current_user extracts cookie (or Authorization: Bearer fallback)
    Protected->>Protected: Decodes JWT, validates signature & expiration
    Protected->>DB: SELECT * FROM users WHERE id = :user_id
    alt Inactive / Missing / Expired
        Protected-->>Client: 401 Unauthorized ("Could not validate credentials")
    end
    Protected->>Protected: require_role(roles) checks current_user.role
    alt Insufficient Role
        Protected-->>Client: 403 Forbidden ("This action requires one of these roles...")
    end
    Protected-->>Client: 200 OK (Protected Data)
```

### 1.1. Password & Token Hashing Specification
- **User Passwords**: `bcrypt` via `passlib.context.CryptContext(schemes=["bcrypt"], deprecated="auto")`.
  - 12 salt rounds automatically generated per password.
  - Plaintext passwords are never logged, stored, or cached.
- **Password Reset Tokens (SEC-01)**:
  - Cryptographically generated 32-byte raw token via `secrets.token_urlsafe(32)`.
  - Server immediately hashes the token via `hashlib.sha256(raw_token.encode("utf-8")).hexdigest()`.
  - Database stores strictly the 64-character hexadecimal digest at rest (`PasswordResetToken.token`).
  - Zero raw tokens are stored in the database or disclosed in API JSON responses.

### 1.2. JWT Token Payload & Claims
Access tokens are signed using `JWT_SECRET_KEY` with a 30-minute expiration (`settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30`).
```json
{
  "sub": "b8f9e0a1-4321-4def-89ab-123456789abc",
  "role": "admin",
  "exp": 1732982400
}
```

### 1.3. Cookie Security Attributes (SEC-10)
Web authentication uses `Response.set_cookie()` with strict security attributes:
- **`HttpOnly=True`**: Token cannot be accessed by client-side JavaScript (`document.cookie`), neutralizing token exfiltration via Cross-Site Scripting (XSS).
- **`SameSite=Strict`**: Browser refuses to attach the cookie on cross-site requests, mitigating Cross-Site Request Forgery (CSRF).
- **`Secure`**: Enforced in production (`settings.ENVIRONMENT == "production"` or explicit `AUTH_COOKIE_SECURE=True`). Allowed over HTTP in local development (`localhost`).
- **`Path=/`**: Cookie scope covers all API routes.
- **`Max-Age`**: Synchronized with JWT expiration (`ACCESS_TOKEN_EXPIRE_MINUTES * 60`).
- **Logout Endpoint (`POST /auth/logout`)**: Deletes the cookie with matching `Path`, `HttpOnly`, `Secure`, and `SameSite` flags.

### 1.4. Dual-Mode Authentication (SEC-10)
[`backend/app/users/dependencies.py`](file:///home/dell/projects/eduIntel/backend/app/users/dependencies.py) supports dual authentication:
1. **Primary (Browsers)**: Extracts the token from `request.cookies.get(settings.AUTH_COOKIE_NAME)`.
2. **Fallback (CLI / Automated Tests)**: Extracts the token from `Authorization: Bearer <token>` via `HTTPBearer(auto_error=False)`.
3. If neither credential source contains a valid token, the request fails closed with `401 Unauthorized`.

---

## 2. Role-Based & Relationship-Based Access Control

Access control in EduIntel combines single-dimension RBAC with multi-factor relationship-based access control (ABAC).

### 2.1. Authentication & Role Dependencies

```python
async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    # 1. Primary: Extract from HttpOnly cookie
    if settings.AUTH_COOKIE_NAME in request.cookies:
        token = request.cookies[settings.AUTH_COOKIE_NAME]
    # 2. Fallback: Extract from Authorization Bearer header
    elif credentials is not None:
        token = credentials.credentials
    else:
        raise HTTPException(401, detail="Could not validate credentials")

    # 3. Decode JWT payload, extract 'sub', validate UUID
    # 4. Fetch active user from database
    # 5. Fail closed (401) on missing, expired, invalid, or inactive user
    return user

def require_role(*allowed_roles: str):
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(403, detail=f"This action requires one of these roles: {', '.join(allowed_roles)}")
        return current_user
    return role_checker
```

### 2.1.1. Multi-Tenant Authorization & Session Scoping (Phase 2 Stage 3)

In Stage 3, institutional multi-tenancy was decoupled from global user identity:

```python
async def get_tenant_context(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    # 1. Resolve institution_id from X-Institution-ID header, query param, or user default membership
    # 2. Query institution_memberships table for (institution_id, current_user.id)
    # 3. Fail closed (403) if user is not an active member of this institution
    # 4. Return TenantContext(institution_id, role, membership_id)
    ...

def require_tenant_role(*allowed_roles: str):
    async def tenant_role_checker(
        tenant: TenantContext = Depends(get_tenant_context),
    ) -> TenantContext:
        if tenant.role not in allowed_roles:
            raise HTTPException(403, detail="Insufficient institutional role permissions")
        return tenant
    return tenant_role_checker

async def get_tenant_db(
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> AsyncGenerator[AsyncSession, None]:
    # Configures PostgreSQL RLS session variable for this transaction
    await session.execute(
        text("SELECT set_config('app.current_institution_id', :id, true)"),
        {"id": str(tenant.institution_id)},
    )
    yield session
```

- **SEC-S3-03 (Tenant-Specific Role Enforcement):** Study material downloads evaluate institutional `tenant.role` rather than `current_user.role`, preventing cross-tenant privilege confusion for users holding differing roles across institutes.
- **Fail-Closed Default:** With `ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE: bool = False`, unauthenticated or unmigrated requests fail closed (`403 Forbidden`).

### 2.2. Multi-Factor Relationship-Based Authorization (SEC-03, SEC-06, SEC-07)

Simple role checks (`require_role("teacher")`) are insufficient for multi-tenant and multi-class environments. EduIntel enforces student-specific academic relationships:

1. **Parent Reports (`POST /reports/parent-report/{student_id}`, SEC-03)**:
   - For teachers, requires an active timetable entry linking the teacher to the student's assigned grade and section, OR a concrete academic submission (graded homework, exam result, or attendance entry).
   - Recipient email override is forbidden; report is strictly dispatched to the verified `parent_email` stored in `student_profiles`.
2. **File Downloads (`/teacher/homework/{id}/file`, `/student/study-materials/{id}/file`, SEC-06)**:
   - Homework download requires either ownership by the submitting student OR timetable/grader assignment for the teacher.
   - Study material download requires enrollment in the grade/section where the material was assigned.
3. **ML Diagnostics (`/ml/predict/*`, `/ml/diagnose/*`, `/ml/explain/*`, SEC-07)**:
   - Verifies target user is an active student with a valid profile (returns 404 if missing or non-student).
   - Verifies requesting teacher has an active timetable assignment for that student's section (returns 403 otherwise). Administrators have supervisory read access.

### 2.3. Platform Administrator Role & Privileged Scope

In Phase 2 Stages 4 & 5, global multi-institution management was introduced for the `platform_admin` role. Unlike institutional roles (`admin`, `teacher`, `student`) that operate strictly inside a single institution tenant context, Platform Administrators govern the entire platform.

#### 2.3.1. Database Identity & Indexing (Migration 0024)
- **Column**: `users.is_platform_admin` (`BOOLEAN NOT NULL DEFAULT false`).
- **Index**: `ix_users_is_platform_admin` (B-Tree on `users(is_platform_admin)`).
- **Decoupling**: A platform admin may have `user.role == "admin"`, but their platform-wide privileges stem strictly from `is_platform_admin = true`.

#### 2.3.2. Authoritative Database Enforcement (`require_platform_admin`)
[`backend/app/users/dependencies.py`](file:///home/dell/projects/eduIntel/backend/app/users/dependencies.py):
- `require_platform_admin` depends on `get_current_user`.
- Checks the authenticated user's live database record (`current_user.is_platform_admin`).
- Rejects requests with `403 Forbidden ("Platform Administrator privileges required")` if false or inactive.
- **Security Rule**: Role checks **never** trust JWT claims, request headers, or frontend role state. The database is queried authoritatively on every request.

#### 2.3.3. Transaction-Local Cross-Tenant Session (`get_platform_admin_db`)
[`backend/app/core/tenant.py`](file:///home/dell/projects/eduIntel/backend/app/core/tenant.py):
- Privileged endpoints consume `get_platform_admin_db` instead of `get_db` or `get_tenant_db`.
- Executes `SELECT set_config('app.is_platform_admin', 'true', true)`.
- The third argument (`is_local = true`) guarantees the setting automatically reverts to empty when the transaction commits or rolls back.
- When the connection is returned to the pool, `RESET app.is_platform_admin` is executed, preventing privilege leakage across pooled connections.

#### 2.3.4. Secure Institution Onboarding & Activation Flow
[`backend/app/institutions/router.py`](file:///home/dell/projects/eduIntel/backend/app/institutions/router.py):
- **Atomic Provisioning**: Institution, initial administrator user, admin profile, and membership are created inside a single atomic database transaction. Any failure (e.g. duplicate slug or email) rolls back all records, leaving zero orphaned accounts.
- **Pre-Activation Inactivity & Random Password Lockout**: Initial administrator accounts are provisioned with `is_active=False` and a 32-byte cryptographically random password (`secrets.token_urlsafe(32)`). They cannot authenticate via `/auth/login` (which fails closed on inactive accounts) until activation completes.
- **Activation Token Cryptography**:
  - Raw token: 32-byte URL-safe string (`secrets.token_urlsafe(32)`).
  - Storage: Only the SHA-256 hex digest is stored in `password_reset_tokens`.
  - Expiry: Strictly 48 hours (`timedelta(hours=48)`).
  - Single-Use: Upon activation (`POST /auth/password-reset/confirm`), the token is marked `is_used=True`, the user's password is set, and `is_active` is updated to `True`.
- **Email Validation & Delivery Verification (SEC-01 & SEC-04)**:
  - Both `admin_email` and optional `contact_email` are validated via Pydantic `EmailStr`, returning HTTP 422 for malformed syntax.
  - `invitation_sent` accurately reflects actual delivery evidence: `True` only when SMTP is configured and transmission succeeds; `False` if unconfigured or failed, accompanied by a sanitized `invitation_error` message.
  - One-time fallback: When unconfigured/failed, `activation_token` is returned once in the response body to the authorized Platform Admin, never logged or stored in browser storage.

#### 2.3.5. Out-of-Band CLI Provisioner
[`scripts/create_platform_admin.py`](file:///home/dell/projects/eduIntel/scripts/create_platform_admin.py):
- Secure command-line tool for provisioning the initial Platform Administrator.
- Enforces strict password complexity ($\ge 12$ characters, upper, lower, digits, symbols).
- Bypasses public signup (which remains disabled, SEC-02) and ensures no plaintext tokens or passwords appear in shell logs.

---

### 2.4. Endpoint Authorization Matrix

| Endpoint Path | Method | Minimum Role | Relational / Ownership Requirement |
|---|:---:|:---:|---|
| `/auth/login` | `POST` | Public | Valid credentials; sets `HttpOnly` cookie |
| `/auth/logout` | `POST` | Public | Clears `HttpOnly` cookie |
| `/auth/signup` | `POST` | Disabled | **403 Forbidden** — Public self-registration disabled (SEC-02) |
| `/auth/password-reset/request` | `POST` | Public | Rate limited (5 req/min); background SMTP dispatch; zero disclosure |
| `/auth/password-reset/confirm` | `POST` | Public | Valid SHA-256 token digest required |
| `/users/me` | `GET`, `PUT` | Authenticated | Scoped strictly to `current_user.id` |
| `/admin/teachers` | `POST` | `admin` | Admin provisions teacher account (SEC-02) |
| `/admin/students` | `POST` | `admin` | Admin provisions student account with profile (SEC-02) |
| `/admin/administrators` | `POST` | `admin` | Admin provisions additional administrator (SEC-02) |
| `/admin/dashboard` | `GET` | `admin` | Protected dashboard overview |
| `/student/dashboard` | `GET` | `student` | Scoped to `current_user.id` |
| `/student/homework/upload` | `POST` | `student` | Scoped to student's enrolled section |
| `/student/study-materials/{id}/file`| `GET` | `student` | Section-enrolled students only (SEC-06) |
| `/teacher/dashboard` | `GET` | `teacher` | Scoped to teacher's classes |
| `/teacher/homework/{id}/file` | `GET` | `teacher` | Assigned teacher or student owner only (SEC-06) |
| `/teacher/study-materials/upload` | `POST` | `teacher` | Timetable assigned teacher |
| `/ocr/extract` | `POST` | Authenticated | `get_current_user` required; 5 MB limit; magic bytes (SEC-05) |
| `/rag/query` | `POST` | Authenticated | Mandatory tenant filter `where={"institution_id": ...}` (SEC-08) |
| `/rag/debug-query` | `GET` | `admin` | Administrator only; mandatory tenant filter (SEC-08) |
| `/ml/diagnose/{student_id}` | `GET` | `teacher`, `admin` | Timetable section assignment required for teachers (SEC-07) |
| `/ml/predict/at-risk/{student_id}` | `GET` | `teacher`, `admin` | Timetable section assignment required for teachers (SEC-07) |
| `/ml/explain/at-risk/{student_id}` | `GET` | `teacher`, `admin` | Timetable section assignment required for teachers (SEC-07) |
| `/reports/parent-report/{student_id}`| `POST`| `teacher`, `admin` | Timetable section assignment + academic records (SEC-03) |
| `/agents/admin-assistant/chat` | `POST` | `admin` | Tenant reporting authorization required (SEC-09) |
| `/institutions` | `GET` | `platform_admin` | Platform Admin only; live metrics and aggregated institution roster |
| `/institutions` | `POST` | `platform_admin` | Platform Admin only; atomic institution + admin user + membership onboarding |
| `/institutions/me` | `GET` | Authenticated | Scoped to `current_user.id` active institution memberships |
| `/institutions/current` | `GET` | Authenticated | Resolves caller's current tenant context |
| `/institutions/{id}` | `GET` | `platform_admin` | Platform Admin only; institution detail and user breakdown |
| `/institutions/{id}/status` | `PATCH` | `platform_admin` | Platform Admin only; suspend/reactivate institution |

---

## 3. Frontend Route Protection & Storage Hygiene (SEC-10, SEC-11, SEC-02)

### 3.1. Route Guard ([`frontend/src/components/ProtectedRoute.jsx`](file:///home/dell/projects/eduIntel/frontend/src/components/ProtectedRoute.jsx))
- Evaluates `sessionStorage.getItem("is_authenticated") === "true"`.
- If unauthenticated, navigates immediately to `/login`.
- Evaluates `requirePlatformAdmin` flag:
  - If a route requires platform admin privileges (e.g. `/platform-admin/dashboard`, `/platform-admin/institutions`) and `sessionStorage.getItem("is_platform_admin") !== "true"`, the user is redirected to `/admin/dashboard`.
- Evaluates `allowedRoles`:
  - If the user's role is not in `allowedRoles`, redirects to the user's designated home route based on `user_role`.
- `localStorage.getItem("demo_mode")` bypass is completely removed.

### 3.2. Atomic Login Session State (SEC-02 Remediation) ([`frontend/src/pages/auth/Login.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/Login.jsx))
- Clears stale session state (`is_authenticated`, `user_role`, `is_platform_admin`, `user_email`) at the start of submission.
- Calls `POST /auth/login` to obtain authentication credentials.
- Calls `GET /users/me` to authoritatively determine user identity, active status, role, and `is_platform_admin`.
- Sets `is_authenticated`, `user_role`, and `is_platform_admin` in `sessionStorage` **atomically only after both API calls succeed**.
- If either call fails, or if an account is inactive, all session keys are purged immediately, preventing partial or stale session privilege escalation.
- Intended routing: Platform Admins are redirected to `/platform-admin/dashboard`; institutional users to their respective dashboards (`/admin/dashboard`, `/teacher/dashboard`, `/student/dashboard`).

### 3.3. Response Interceptor & Storage Purging ([`frontend/src/api/client.js`](file:///home/dell/projects/eduIntel/frontend/src/api/client.js))
- Configured with `withCredentials: true` so modern browsers automatically send `HttpOnly` cookies.
- On HTTP `401 Unauthorized`:
  - Purges `sessionStorage.is_authenticated`, `sessionStorage.user_role`, `sessionStorage.is_platform_admin`, and `sessionStorage.user_email`.
  - Clears legacy tokens (`localStorage.access_token`).
  - Redirects to `/login` without infinite loops.

### 3.4. Development Credentials Protection ([`frontend/src/pages/auth/Login.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/Login.jsx))
- Demo bypass buttons are permanently deleted from the codebase.
- Helper Fill buttons are wrapped in `{import.meta.env.DEV && (...)}`, ensuring development test credentials are completely stripped from production bundles by Vite tree-shaking.

---

## 4. Phase 0A: Critical SQL Execution Risk Containment

### 3.1. Vulnerability Root Cause (Baseline Audit)
During the Phase 0 baseline audit, an unrestricted SQL execution vulnerability was identified in the LangGraph Admin Assistant ([`backend/app/agents/admin_assistant.py`](file:///home/dell/projects/eduIntel/backend/app/agents/admin_assistant.py)):
- The agent was configured with a tool named `execute_sql` that accepted an arbitrary string parameter `query: str`.
- The tool executed `await db.execute(text(query))` directly against the PostgreSQL connection.
- Because the database user possessed table creation and modification privileges, prompt injection or LLM hallucination could execute destructive DDL (`DROP TABLE`), arbitrary data modification (`UPDATE salary_records SET net_salary = 999999`), or multi-statement injections.

### 3.2. Implemented Containment (Phase 0A)
In Phase 0A, the arbitrary SQL tool was completely eliminated and replaced with **6 safe, strictly parameterized reporting tools**:

```mermaid
graph TD
    UserQuery["Admin Natural Language Query"] --> Agent["LangGraph Admin Assistant State Machine"]
    Agent --> ToolRouter{"LangGraph Tool Router"}
    
    ToolRouter --> Tool1["query_fee_summary(status, due_before)"]
    ToolRouter --> Tool2["query_teacher_salaries(month, year)"]
    ToolRouter --> Tool3["query_timetable_coverage(day_of_week)"]
    ToolRouter --> Tool4["query_student_attendance(date, min_rate)"]
    ToolRouter --> Tool5["query_exam_performance(subject, exam_name)"]
    ToolRouter --> Tool6["query_at_risk_students(risk_threshold)"]

    Tool1 --> ORM["SQLAlchemy 2.0 Parameterized ORM Selects"]
    Tool2 --> ORM
    Tool3 --> ORM
    Tool4 --> ORM
    Tool5 --> ORM
    Tool6 --> ORM

    ORM --> SafePG[("PostgreSQL 16 (Read-Only Param Execution)")]
```

### Safety Guarantees:
1. **Zero Dynamic SQL Strings**: All queries use SQLAlchemy `select(...)` constructs with strict column bindings.
2. **Strict Parameter Validation**: Tool inputs are validated using Pydantic models (e.g. date formats, enums for days of week).
3. **No Write / DDL Operations**: The reporting tools contain only read-only `select()` statements, making data modification architecturally impossible through the agent.

