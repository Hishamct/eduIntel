# EduIntel Phase 2B — Milestone 1: Security Hotfix Implementation Plan (Final Pre-Implementation)

**Project:** EduIntel AI — Educational Decision Intelligence Platform  
**Branch:** `develop/production-readiness`  
**Author:** Senior Application Security Engineer, Backend Security Auditor & Python/FastAPI Specialist  
**Document Status:** 🟡 **FINAL PRE-IMPLEMENTATION PLAN — AWAITING EXPLICIT USER AUTHORIZATION**  
**Target Milestone:** Phase 2B Milestone 1 (Critical Security Risk Containment)

---

## 1. Executive Summary & Pre-Implementation Clarifications

Following the independent security verification ([`04-critical-security-verification-report.md`](file:///home/dell/projects/eduIntel/docs/production-readiness/04-critical-security-verification-report.md)) and the final pre-implementation review, this revised document establishes the approved implementation plan for remediating the four critical vulnerabilities: **SEC-01**, **SEC-02**, **SEC-03**, and **SEC-05**.

### Final Directives Incorporated:
1. **SEC-03 — Student-Specific Academic Relationship Required (Class-Level Assignment Removed):**
   - Class-level [`Assignment`](file:///home/dell/projects/eduIntel/backend/app/teacher/models.py#L16) creation does **not** establish a student-specific academic relationship. Creating an assignment for a class must never grant a teacher permission to generate reports for every student in that class.
   - Authorization strictly requires a concrete, student-specific academic record:
     - [`ExamResult`](file:///home/dell/projects/eduIntel/backend/app/teacher/models.py#L48) linked to the target student and entered by the teacher.
     - [`Attendance`](file:///home/dell/projects/eduIntel/backend/app/admin/models.py#L82) linked to the target student and marked by the teacher.
     - [`HomeworkSubmission`](file:///home/dell/projects/eduIntel/backend/app/student/models.py#L14) linked to the target student and graded by the teacher.
   - Class-level assignment records are explicitly removed from the authorization criteria.
2. **SEC-01 — Timing Defense & Realistic Security Claims:**
   - Background tasks and rate limiting do **not** guarantee constant-time behavior. The plan avoids claiming constant-time execution without empirical measurement and statistical benchmarking.
   - Defense is established via:
     - Identical status codes (`200 OK`) and uniform response payloads for both existing and nonexistent accounts.
     - Decoupling SMTP network latency by dispatching emails outside the request lifecycle via FastAPI `BackgroundTasks`.
     - Application-level rate limiting to restrict automated high-frequency sampling.
     - Executing comparable processing paths (synthetic token generation and hashing) when accounts do not exist to narrow delta latencies.
3. **Administrative Provisioning Safeguards & Role Protection:**
   - Only authorized institutional administrators ([`require_role("admin")`](file:///home/dell/projects/eduIntel/backend/app/users/dependencies.py)) can provision student and staff accounts.
   - Institutional administrators cannot create platform-level superadmins; all API-created administrators share standard institutional scope (`role = "admin"`).
   - Ordinary profile-update endpoints ([`PUT /users/me`](file:///home/dell/projects/eduIntel/backend/app/users/router.py#L25)) cannot escalate user roles. `User.role` is immutable on profile endpoints and schemas reject extra fields (`extra = "forbid"`).
   - Administrative provisioning actions are auditable (actor ID, target user ID, target email, assigned role, client IP, timestamp).
   - Sensitive credentials (passwords, hashes, reset tokens, secret keys) are strictly prohibited from audit logs and application logs.
4. **Platform Administrator Database Design (No Migration in Milestone 1):**
   - The `is_platform_admin` Alembic migration is deferred to the Phase 2C multi-tenant architecture.
   - Zero database migrations will be executed in Milestone 1. Initial administrator access is provisioned out-of-band via CLI (`backend/app/core/bootstrap_admin.py`).
5. **Student Enrollment Controlled by Institution:**
   - Public self-registration ([`POST /auth/signup`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py#L18)) is disabled (`HTTP 403 Forbidden`).
   - Student creation is handled strictly by authenticated institutional administrators via `POST /admin/students`. No shared institutional enrollment secret is implemented.
6. **Local Development Email:**
   - **Mailpit** (`localhost:1025` SMTP, `localhost:8025` Web UI) is used for manual email testing in local dev.
   - An **in-memory email capture fixture** (`captured_emails = []`) is used for automated tests.
7. **SEC-05 Process Concurrency & Deployment Safeguards:**
   - The `asyncio.Semaphore` is documented as **process-local** (single worker).
   - Deployment-level resource safeguards (worker count limits, container CPU/RAM quotas, reverse-proxy rate limiting) are documented.

---

## 2. Component Traceability Matrix

| Vulnerability | Backend Router | Service Layer | Pydantic Schemas | Database Models & Migrations | Configuration | Frontend Component | Test Fixture Impact |
|---|---|---|---|---|---|---|---|
| **SEC-01** | [`app/auth/router.py`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py#L38) | [`app/auth/service.py`](file:///home/dell/projects/eduIntel/backend/app/auth/service.py#L56) | [`app/auth/schemas.py`](file:///home/dell/projects/eduIntel/backend/app/auth/schemas.py#L33) | [`app/auth/models.py`](file:///home/dell/projects/eduIntel/backend/app/auth/models.py#L11) (`PasswordResetToken`) — **No migration** | `FRONTEND_BASE_URL`, `ENVIRONMENT`, `SMTP_*` | [`PasswordReset.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/PasswordReset.jsx) | `test_password_reset_lifecycle` |
| **SEC-02** | [`app/auth/router.py`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py#L18), [`app/admin/router.py`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py), [`app/users/router.py`](file:///home/dell/projects/eduIntel/backend/app/users/router.py#L25) | [`app/auth/service.py`](file:///home/dell/projects/eduIntel/backend/app/auth/service.py#L14), [`app/admin/service.py`](file:///home/dell/projects/eduIntel/backend/app/admin/service.py), [`app/users/service.py`](file:///home/dell/projects/eduIntel/backend/app/users/service.py#L21) | [`app/auth/schemas.py`](file:///home/dell/projects/eduIntel/backend/app/auth/schemas.py#L7), [`app/admin/schemas.py`](file:///home/dell/projects/eduIntel/backend/app/admin/schemas.py), [`app/users/schemas.py`](file:///home/dell/projects/eduIntel/backend/app/users/schemas.py) | [`app/users/models.py`](file:///home/dell/projects/eduIntel/backend/app/users/models.py#L10) (`User`, `AdminProfile`, `TeacherProfile`, `StudentProfile`) — **No migration** | None | [`Signup.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/Signup.jsx) | [`tests/conftest.py`](file:///home/dell/projects/eduIntel/backend/tests/conftest.py#L133) (`admin_token`, `teacher_token`, `student_token`) |
| **SEC-03** | [`app/reports/router.py`](file:///home/dell/projects/eduIntel/backend/app/reports/router.py#L18) | [`app/reports/parent_report_agent.py`](file:///home/dell/projects/eduIntel/backend/app/reports/parent_report_agent.py#L49) | [`app/reports/router.py`](file:///home/dell/projects/eduIntel/backend/app/reports/router.py#L13) | [`app/users/models.py`](file:///home/dell/projects/eduIntel/backend/app/users/models.py#L33), [`app/admin/models.py`](file:///home/dell/projects/eduIntel/backend/app/admin/models.py#L14) (`Timetable`), [`app/teacher/models.py`](file:///home/dell/projects/eduIntel/backend/app/teacher/models.py#L48) (`ExamResult`), [`app/student/models.py`](file:///home/dell/projects/eduIntel/backend/app/student/models.py#L14) (`HomeworkSubmission`), [`app/admin/models.py`](file:///home/dell/projects/eduIntel/backend/app/admin/models.py#L82) (`Attendance`) | `EMAIL_FROM`, `SMTP_*` | [`ProgressMonitoring.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/teacher/ProgressMonitoring.jsx) | None |
| **SEC-05** | [`app/ocr/router.py`](file:///home/dell/projects/eduIntel/backend/app/ocr/router.py#L11) | [`app/ocr/service.py`](file:///home/dell/projects/eduIntel/backend/app/ocr/service.py#L9) | [`app/ocr/schemas.py`](file:///home/dell/projects/eduIntel/backend/app/ocr/schemas.py) | None — **No migration** | `MAX_CONCURRENT_OCR_WORKERS` | [`HomeworkUpload.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/student/HomeworkUpload.jsx) | None |

---

## 3. SEC-01: Password Reset Remediation Plan

### 3.1. Architectural Requirements & Policies
1. **Zero Token Disclosure:** Under no circumstances shall `dev_reset_token` or any raw credential token appear in HTTP JSON response bodies.
2. **Token Hashing at Rest (SHA-256):**
   - The token generated for the user is 32 cryptographically random bytes via `secrets.token_urlsafe(32)`.
   - The server immediately hashes this value via `hashlib.sha256(raw_token.encode("utf-8")).hexdigest()` and stores strictly the 64-character hexadecimal digest in `PasswordResetToken.token`.
   - The database never stores raw tokens. If the database is compromised, dumped, or leaked, the stored digests cannot be reversed or used to authenticate reset requests.
   - *Database Schema Compatibility:* The existing column `PasswordResetToken.token` is declared as `VARCHAR` / `String` in [`backend/app/auth/models.py:16`](file:///home/dell/projects/eduIntel/backend/app/auth/models.py#L16). A 64-character hex string natively fits without requiring schema migrations.
3. **User Enumeration & Timing Attack Mitigations:**
   - Both existing and nonexistent email requests return the identical HTTP 200 payload:
     `{"message": "If that email is registered, a password reset link has been sent to your email."}`
   - *Timing Defense Realism:* BackgroundTasks and rate limiting do **not** guarantee constant-time behavior. Without empirical timing measurement and statistical benchmarking across various server loads, pure constant-time execution cannot be claimed. Instead, timing attack resistance is achieved through:
     - **Identical Status & Payload:** The response structure leaks zero boolean state.
     - **Asynchronous SMTP Delivery:** Outgoing reset emails are dispatched outside the HTTP request lifecycle via FastAPI `BackgroundTasks`, isolating network latency from the response time.
     - **Comparable Processing Paths:** When an account is not found, the service executes a synthetic token generation and SHA-256 hash operation (`_dummy_hash_computation()`) to ensure both branches execute comparable cryptographic work, minimizing execution latency differentials.
     - **Rate Limiting:** Applying a strict rate limit (e.g. 5 requests per minute per IP) prevents high-frequency statistical timing analysis.
4. **Configurable Base URL & Production HTTPS Enforcement:**
   - Base URL is driven by `settings.FRONTEND_BASE_URL` in [`backend/app/core/config.py`](file:///home/dell/projects/eduIntel/backend/app/core/config.py).
   - In production environments (`ENVIRONMENT == "production"`), the backend validates that `FRONTEND_BASE_URL` uses the `https://` protocol scheme.
5. **Strict Logging Privacy:**
   - Raw reset tokens, reset URLs, and user password hashes must **never** be printed to ordinary backend logs, debug logs, or console stdout.
   - Only non-sensitive audit milestones (e.g. `logger.info("Password reset requested for email_hash=%s", masked_email)`) may be emitted.
6. **Local Development Email Testing:**
   - **Manual Testing in Local Development:** Integrated with **Mailpit** running on `localhost:1025` (SMTP) and `localhost:8025` (Web UI). Developers can inspect rendered HTML emails in the Mailpit inbox without external SMTP credentials.
   - **Automated Testing:** Integration tests use an in-memory email capture fixture (`captured_emails = []`) to intercept outgoing emails without invoking external network sockets.
7. **Lifecycle, Expiration & Single-Use:**
   - Tokens expire strictly after 30 minutes (`expires_at < datetime.now(UTC)`).
   - Single-use is strictly enforced: `reset_token.used` is checked and immediately updated to `True` within the confirmation transaction.

### 3.2. Detailed Code Implementation

#### Configuration: [`backend/app/core/config.py`](file:///home/dell/projects/eduIntel/backend/app/core/config.py)
```python
class Settings(BaseSettings):
    # ... existing settings ...
    ENVIRONMENT: str = "development"
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    MAX_CONCURRENT_OCR_WORKERS: int = 2

    @field_validator("FRONTEND_BASE_URL")
    @classmethod
    def validate_frontend_url(cls, v: str, info) -> str:
        env = info.data.get("ENVIRONMENT", "development")
        if env == "production" and not v.startswith("https://"):
            raise ValueError(f"In production, FRONTEND_BASE_URL must use HTTPS: {v}")
        return v.rstrip("/")
```

#### Service Layer: [`backend/app/auth/service.py`](file:///home/dell/projects/eduIntel/backend/app/auth/service.py)
```python
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.models import PasswordResetToken
from app.auth.security import hash_password
from app.core.config import settings
from app.reports.parent_report_agent import send_email_direct
from app.users.models import User

def _hash_token(raw_token: str) -> str:
    """Hash raw reset token using SHA-256 for secure storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

def _dummy_hash_computation():
    """Execute synthetic token generation and hashing to provide comparable execution paths."""
    dummy_token = secrets.token_urlsafe(32)
    _hash_token(dummy_token)

async def request_password_reset(db: AsyncSession, email: str) -> tuple[str | None, str | None]:
    """
    Process password reset request securely.
    Returns (raw_token, recipient_email) if user exists, else (None, None).
    Executes comparable cryptographic work regardless of whether the user exists.
    """
    result = await db.execute(select(User).where(User.email == email.lower(), User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        _dummy_hash_computation()
        return None, None

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    reset_record = PasswordResetToken(
        user_id=user.id,
        token=token_hash,  # Store SHA-256 hash
        expires_at=expires_at,
        used=False,
    )
    db.add(reset_record)
    await db.commit()
    return raw_token, user.email

def send_password_reset_email_background(raw_token: str, recipient_email: str):
    """Dispatches password reset email via SMTP (Mailpit in dev, TLS SMTP in prod)."""
    reset_url = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}"
    body = (
        f"You requested a password reset for your EduIntel account.\n\n"
        f"Click the link below to set a new password:\n{reset_url}\n\n"
        f"This link expires in 30 minutes. If you did not make this request, you can safely ignore this email."
    )
    send_email_direct(
        to_email=recipient_email,
        subject="EduIntel — Password Reset Request",
        body_text=body,
    )

async def confirm_password_reset(db: AsyncSession, raw_token: str, new_password: str) -> bool:
    """Validate raw token against stored SHA-256 hash and update password."""
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == token_hash,
            PasswordResetToken.used == False,
            PasswordResetToken.expires_at > now,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        return False

    user_result = await db.execute(select(User).where(User.id == record.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return False

    user.hashed_password = hash_password(new_password)
    record.used = True
    await db.commit()
    return True
```

#### Router: [`backend/app/auth/router.py`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py)
```python
from fastapi import BackgroundTasks

@router.post("/password-reset/request", status_code=status.HTTP_200_OK)
async def request_password_reset(
    data: PasswordResetRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    raw_token, email = await service.request_password_reset(db, data.email)
    if raw_token and email:
        # Decouple SMTP transmission from HTTP response timing
        background_tasks.add_task(service.send_password_reset_email_background, raw_token, email)

    # Identical HTTP 200 payload for registered and unregistered emails
    return {
        "message": "If that email is registered, a password reset link has been sent to your email."
    }
```

#### Frontend Handling: [`frontend/src/pages/auth/PasswordReset.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/PasswordReset.jsx)
```jsx
// Read token directly from URL query parameters (e.g. /reset-password?token=<raw_token>)
const [searchParams] = useSearchParams();
const tokenFromUrl = searchParams.get("token");

useEffect(() => {
  if (tokenFromUrl) {
    setToken(tokenFromUrl);
    setStep("confirm");
  }
}, [tokenFromUrl]);
```

---

## 4. SEC-02: Registration & Privileged Accounts Remediation Plan

### 4.1. Identity Architecture for Milestone 1
- Zero schema migrations in Milestone 1. The separation of platform superadmins and institutional administrators is deferred to the Phase 2C multi-tenant architecture.
- Public self-registration is closed.
- All user accounts are provisioned by authenticated administrators.

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Institution Administrator (Admin)                                   │
│    - Role: "admin" in users table                                      │
│    - Manages school operations, teachers, and students                 │
│    - Initial root account created via server-side bootstrap CLI        │
├────────────────────────────────────────────────────────────────────────┤
│ 2. Teacher (Educator)                                                  │
│    - Role: "teacher" in users table                                    │
│    - Provisioned strictly by authenticated Admin: POST /admin/teachers│
│    - Public signup completely blocked                                  │
├────────────────────────────────────────────────────────────────────────┤
│ 3. Student (Learner)                                                   │
│    - Role: "student" in users table                                    │
│    - Provisioned strictly by authenticated Admin: POST /admin/students│
│    - Public self-registration completely disabled (403 Forbidden)      │
└────────────────────────────────────────────────────────────────────────┘
```

### 4.2. Database Model & Migration Evaluation
- **Evaluation:** Does Milestone 1 require adding an `is_platform_admin` column to the `users` table?
  - **Verdict:** **No schema migration is necessary or approved.**
  - **Justification:** In [`backend/app/users/models.py:17`](file:///home/dell/projects/eduIntel/backend/app/users/models.py#L17), `role` is defined as `Enum("student", "teacher", "admin", name="user_role")`.
  - Restricting privileged creation to `require_role("admin")` and closing public signup completely resolves the security vulnerabilities (SEC-02 privilege escalation and unauthorized self-registration).
- **Documented Bootstrap Limitation:** In Milestone 1, all users with `role == "admin"` possess equal administrative authority in the single-tenant database. Initial administrative access must be established via direct server console execution using `backend/app/core/bootstrap_admin.py`.

### 4.3. Administrative Provisioning Safeguards & Role Protection
To prevent unauthorized privilege escalation, mass-assignment vulnerabilities, and unauthorized account creation:

1. **Authorization Gate:**
   - Only authorized administrators ([`require_role("admin")`](file:///home/dell/projects/eduIntel/backend/app/users/dependencies.py)) can create staff or student accounts.
   - Calling `POST /admin/teachers`, `POST /admin/administrators`, or `POST /admin/students` as an unauthenticated or non-admin user immediately returns `HTTP 401 Unauthorized` or `HTTP 403 Forbidden`.
2. **Platform Administrator Isolation:**
   - Institutional administrators cannot create platform superadmins.
   - The endpoint `POST /admin/administrators` only provisions an administrator with standard institutional privileges (`role = "admin"`). No API parameters allow privilege elevation to platform superadmin; any future superadmin role is strictly restricted to server console execution (`bootstrap_admin.py`).
3. **Role Escalation Protection on Profile Updates:**
   - In [`backend/app/users/router.py:update_my_profile`](file:///home/dell/projects/eduIntel/backend/app/users/router.py#L25) (`PUT /users/me`), users update their profile details.
   - Pydantic update schemas ([`StudentProfileUpdate`](file:///home/dell/projects/eduIntel/backend/app/users/schemas.py#L52), [`TeacherProfileUpdate`](file:///home/dell/projects/eduIntel/backend/app/users/schemas.py#L59), [`AdminProfileUpdate`](file:///home/dell/projects/eduIntel/backend/app/users/schemas.py#L64)) contain only non-privileged profile attributes (grade, section, department, etc.).
   - The service layer [`update_profile`](file:///home/dell/projects/eduIntel/backend/app/users/service.py#L21) strictly modifies `profile` attributes on the related profile table, never on `User`.
   - Security rule: `User.role` and `User.is_active` are immutable via `PUT /users/me`. Incoming schemas enforce `extra = "forbid"` to reject any payload attempting mass-assignment privilege escalation (e.g. attempting to pass `{"role": "admin"}`).
4. **Audit Logging for Administrative Actions:**
   - When an administrator provisions a user, a structured audit log entry is emitted:
     ```python
     logger.info(
         "AUDIT: User provisioned | actor_id=%s | target_id=%s | target_email=%s | role=%s | ip=%s",
         current_user.id,
         new_user.id,
         new_user.email,
         new_user.role,
         request.client.host if request.client else "unknown",
     )
     ```
5. **Strict Credential Suppression in Logs:**
   - Passwords (raw or hashed), password reset tokens, JWTs, and secret keys must **never** be logged in the audit record or ordinary application logs. Only non-sensitive identity metadata (user IDs, emails, roles, timestamps, client IPs) is recorded.

### 4.4. Detailed Code Implementation

#### Public Signup Lockdown: [`backend/app/auth/router.py`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py)
```python
@router.post("/signup", status_code=status.HTTP_403_FORBIDDEN)
async def signup():
    """
    Public self-registration is disabled.
    All user accounts (students, teachers, administrators) must be provisioned
    by an authorized institution administrator.
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Public registration is disabled. Please contact your institution administrator to obtain access credentials."
    )
```

#### Authenticated User Provisioning: [`backend/app/admin/router.py`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py)
```python
import logging
from fastapi import Request

logger = logging.getLogger(__name__)

class StudentProvisionRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str
    grade: str | None = None
    section: str | None = None
    roll_number: str | None = None
    parent_name: str | None = None
    parent_email: EmailStr | None = None
    parent_phone: str | None = None

    model_config = ConfigDict(extra="forbid")

class StaffProvisionRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str
    department: str | None = None
    designation: str | None = None
    subjects: str | None = None

    model_config = ConfigDict(extra="forbid")

@router.post("/students", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    data: StudentProvisionRequest,
    request: Request,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Authenticated institutional administrator provisions a student account."""
    new_user = await service.create_student_user(db, data)
    logger.info(
        "AUDIT: User provisioned | actor_id=%s | target_id=%s | target_email=%s | role=%s | ip=%s",
        current_user.id,
        new_user.id,
        new_user.email,
        new_user.role,
        request.client.host if request.client else "unknown",
    )
    return new_user

@router.post("/teachers", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_teacher(
    data: StaffProvisionRequest,
    request: Request,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Authenticated institutional administrator provisions a teacher account."""
    new_user = await service.create_staff_user(db, data, role="teacher")
    logger.info(
        "AUDIT: User provisioned | actor_id=%s | target_id=%s | target_email=%s | role=%s | ip=%s",
        current_user.id,
        new_user.id,
        new_user.email,
        new_user.role,
        request.client.host if request.client else "unknown",
    )
    return new_user

@router.post("/administrators", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_administrator(
    data: StaffProvisionRequest,
    request: Request,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Authenticated institutional administrator provisions an additional administrator account."""
    new_user = await service.create_staff_user(db, data, role="admin")
    logger.info(
        "AUDIT: User provisioned | actor_id=%s | target_id=%s | target_email=%s | role=%s | ip=%s",
        current_user.id,
        new_user.id,
        new_user.email,
        new_user.role,
        request.client.host if request.client else "unknown",
    )
    return new_user
```

#### Service Helper: [`backend/app/admin/service.py`](file:///home/dell/projects/eduIntel/backend/app/admin/service.py)
```python
async def create_student_user(db: AsyncSession, data: StudentProvisionRequest) -> User:
    existing = (await db.execute(select(User).where(User.email == data.email.lower()))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    user = User(
        email=data.email.lower(),
        name=data.name,
        hashed_password=hash_password(data.password),
        role="student",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    profile = StudentProfile(
        user_id=user.id,
        grade=data.grade,
        section=data.section,
        roll_number=data.roll_number,
        parent_name=data.parent_name,
        parent_email=data.parent_email,
        parent_phone=data.parent_phone,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(user)
    return user

async def create_staff_user(db: AsyncSession, data: StaffProvisionRequest, role: str) -> User:
    if role not in ("teacher", "admin"):
        raise HTTPException(status_code=400, detail="Invalid staff role")

    existing = (await db.execute(select(User).where(User.email == data.email.lower()))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    user = User(
        email=data.email.lower(),
        name=data.name,
        hashed_password=hash_password(data.password),
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    if role == "teacher":
        db.add(TeacherProfile(user_id=user.id, department=data.department, subjects=data.subjects))
    elif role == "admin":
        db.add(AdminProfile(user_id=user.id, designation=data.designation, department=data.department))

    await db.commit()
    await db.refresh(user)
    return user
```

#### Root Administrator Bootstrap CLI: `backend/app/core/bootstrap_admin.py`
```python
"""
CLI bootstrap command to provision the initial institutional administrator out-of-band.
Usage:
    python -m app.core.bootstrap_admin --email admin@eduintel.ai --name "System Administrator" --password "SecurePass123!"
"""
import argparse
import asyncio
from sqlalchemy import select
from app.auth.security import hash_password
from app.core.database import AsyncSessionLocal
from app.users.models import AdminProfile, User

async def bootstrap(email: str, name: str, password: str):
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
        if existing:
            print(f"Error: User with email {email} already exists.")
            return

        admin_user = User(
            email=email.lower(),
            name=name,
            hashed_password=hash_password(password),
            role="admin",
            is_active=True,
        )
        db.add(admin_user)
        await db.flush()

        admin_profile = AdminProfile(
            user_id=admin_user.id,
            designation="System Administrator",
            department="Executive Management",
        )
        db.add(admin_profile)
        await db.commit()
        print(f"Successfully bootstrapped Administrator: {email} (ID: {admin_user.id})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EduIntel Administrator Bootstrap")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    asyncio.run(bootstrap(args.email, args.name, args.password))
```

#### Test Fixtures Refactoring: [`backend/tests/conftest.py`](file:///home/dell/projects/eduIntel/backend/tests/conftest.py)
```python
@pytest_asyncio.fixture
async def admin_token(test_db_session: AsyncSession) -> str:
    """Fixture creating an admin user directly in the test database session."""
    user = User(
        email=f"admin_{uuid.uuid4().hex[:8]}@eduintel.test",
        name="Test Administrator",
        hashed_password=hash_password("AdminPass123!"),
        role="admin",
        is_active=True,
    )
    test_db_session.add(user)
    await test_db_session.flush()
    test_db_session.add(AdminProfile(user_id=user.id, designation="Test Administrator"))
    await test_db_session.commit()
    return create_access_token({"sub": str(user.id), "role": "admin"})

@pytest_asyncio.fixture
async def teacher_token(test_db_session: AsyncSession) -> str:
    """Fixture creating a teacher user directly in the test database session."""
    user = User(
        email=f"teacher_{uuid.uuid4().hex[:8]}@eduintel.test",
        name="Test Teacher",
        hashed_password=hash_password("TeacherPass123!"),
        role="teacher",
        is_active=True,
    )
    test_db_session.add(user)
    await test_db_session.flush()
    test_db_session.add(TeacherProfile(user_id=user.id, department="Science"))
    await test_db_session.commit()
    return create_access_token({"sub": str(user.id), "role": "teacher"})

@pytest_asyncio.fixture
async def student_token(test_db_session: AsyncSession) -> tuple[str, User, StudentProfile]:
    """Fixture creating a student user directly in the test database session."""
    user = User(
        email=f"student_{uuid.uuid4().hex[:8]}@eduintel.test",
        name="Test Student",
        hashed_password=hash_password("StudentPass123!"),
        role="student",
        is_active=True,
    )
    test_db_session.add(user)
    await test_db_session.flush()
    profile = StudentProfile(
        user_id=user.id,
        grade="10",
        section="A",
        parent_name="Parent Test",
        parent_email="parent@eduintel.test",
    )
    test_db_session.add(profile)
    await test_db_session.commit()
    token = create_access_token({"sub": str(user.id), "role": "student"})
    return token, user, profile
```

#### Frontend Notice: [`frontend/src/pages/auth/Signup.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/Signup.jsx)
The signup page is updated to replace the self-registration form with an institutional access banner:
> "Public account registration is disabled. All student and faculty accounts are provisioned directly by the institution administrator. If you need an account, please contact your coaching institute office."

---

## 5. SEC-03: Parent Reports Remediation Plan

### 5.1. Authorization & Delivery Architecture
1. **Mandatory Authentication & Role Check:**
   `current_user: User = Depends(require_role("teacher", "admin"))`. Anonymous callers receive `HTTP 401 Unauthorized`; student callers receive `HTTP 403 Forbidden`.
2. **Multi-Factor Teacher Authorization (Class Assignment + Student-Specific Academic Relationship):**
   A teacher is permitted to trigger parent reports for a student if and only if **both** of the following conditions are verified:
   - **Condition A (Timetable Class Assignment):**
     The teacher is explicitly assigned on the timetable to the student's class section in [`backend/app/admin/models.py:Timetable`](file:///home/dell/projects/eduIntel/backend/app/admin/models.py#L14):
     `Timetable.teacher_id == current_user.id AND Timetable.class_section == student_section`.
   - **Condition B (Concrete Student-Specific Academic Relationship):**
     The teacher must have entered or graded a concrete academic artifact linked specifically to **this target student**:
     1. **Exam Results:** `ExamResult.student_id == student.id AND ExamResult.entered_by == current_user.id AND ExamResult.class_section == student_section` ([`backend/app/teacher/models.py:48`](file:///home/dell/projects/eduIntel/backend/app/teacher/models.py#L48)).
     2. **Attendance Records:** `Attendance.student_id == student.id AND Attendance.marked_by == current_user.id AND Attendance.class_section == student_section` ([`backend/app/admin/models.py:82`](file:///home/dell/projects/eduIntel/backend/app/admin/models.py#L82)).
     3. **Homework Submissions:** `HomeworkSubmission.student_id == student.id AND HomeworkSubmission.graded_by == current_user.id` ([`backend/app/student/models.py:14`](file:///home/dell/projects/eduIntel/backend/app/student/models.py#L14)).
   - **Strict Removal of Class-Level Assignments:**
     Class-level [`Assignment`](file:///home/dell/projects/eduIntel/backend/app/teacher/models.py#L16) creation does **not** count as student-specific authorization. A teacher who created an assignment for a class has not necessarily graded or assessed this specific student and must not gain permission to generate reports for every student in that class.
   - **Strict Rejection:** If the calling teacher created exam results or marked attendance for a *different* student, or only created an assignment for the class, authorization evaluates to `False` and returns `HTTP 403 Forbidden`.
   - Institutional administrators (`role == "admin"`) are authorized across all students within the institution.
3. **Recipient Override Removal:**
   - Client-supplied `parent_email` fields in [`ParentReportPayload`](file:///home/dell/projects/eduIntel/backend/app/reports/router.py#L22) are completely removed.
   - The recipient address is loaded strictly from `StudentProfile.parent_email` in the database.
   - If `StudentProfile.parent_email` is missing or null, the request aborts with `HTTP 400 Bad Request: "Student has no registered parent email on file"`.
4. **Verified Delivery Path:**
   - Dispatched through `send_email_direct` via SMTP (Mailpit in development, TLS SMTP in production).

### 5.2. Detailed Code Implementation

#### Router: [`backend/app/reports/router.py`](file:///home/dell/projects/eduIntel/backend/app/reports/router.py)
```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.admin.models import Attendance, Timetable
from app.core.database import get_db
from app.reports.parent_report_agent import generate_and_send_report
from app.student.models import HomeworkSubmission
from app.teacher.models import ExamResult
from app.users.dependencies import require_role
from app.users.models import StudentProfile, User

router = APIRouter(prefix="/reports", tags=["reports"])

class ParentReportRequest(BaseModel):
    custom_message_note: str | None = None  # ZERO client recipient overrides allowed
    model_config = ConfigDict(extra="forbid")

@router.post("/parent-report/{student_id}")
async def trigger_parent_report(
    student_id: str,
    payload: ParentReportRequest | None = None,
    current_user: User = Depends(require_role("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid student UUID format")

    result = await db.execute(
        select(User, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .where(User.id == uid, User.role == "student")
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")

    student_user, profile = row
    student_section = f"{profile.grade}-{profile.section}" if profile.grade and profile.section else None

    # Multi-Factor Teacher Authorization Verification
    if current_user.role == "teacher":
        if not student_section:
            raise HTTPException(status_code=403, detail="Student is not assigned to any grade/section")

        # 1. Condition A: Timetable Class Assignment
        tt_res = await db.execute(
            select(Timetable.id).where(
                Timetable.teacher_id == current_user.id,
                Timetable.class_section == student_section
            ).limit(1)
        )
        if not tt_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authorization denied: You are not assigned to teach this student's class section."
            )

        # 2. Condition B: Concrete Student-Specific Academic Relationship
        # Must match at least one student-specific record entered or graded by this teacher
        exam_link = await db.execute(
            select(ExamResult.id).where(
                ExamResult.student_id == uid,
                ExamResult.entered_by == current_user.id,
                ExamResult.class_section == student_section
            ).limit(1)
        )
        att_link = await db.execute(
            select(Attendance.id).where(
                Attendance.student_id == uid,
                Attendance.marked_by == current_user.id,
                Attendance.class_section == student_section
            ).limit(1)
        )
        hw_link = await db.execute(
            select(HomeworkSubmission.id).where(
                HomeworkSubmission.student_id == uid,
                HomeworkSubmission.graded_by == current_user.id
            ).limit(1)
        )

        has_student_specific_link = (
            exam_link.scalar_one_or_none() is not None or
            att_link.scalar_one_or_none() is not None or
            hw_link.scalar_one_or_none() is not None
        )
        if not has_student_specific_link:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authorization denied: No student-specific academic records (entered exam scores, marked attendance, or graded homework) link you to this student."
            )

    # Strictly enforce verified parent email from database
    if not profile.parent_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has no registered parent email on file. Update student profile before generating report."
        )

    # Dispatch strictly to verified database email
    report_result = await generate_and_send_report(
        student_id=str(uid),
        student_name=student_user.name or "Student",
        parent_email=profile.parent_email,
        db=db,
        generated_by_user_id=current_user.id,
    )
    return report_result
```

---

## 6. SEC-05: OCR Remediation Plan

### 6.1. Security, Concurrency & Deployment Safeguards Architecture
1. **Mandatory Authentication:** `current_user: User = Depends(get_current_user)`.
2. **Streaming 5 MB Size Limit:** Read in 64 KB chunks, tracking total byte count. If bytes exceed `5 * 1024 * 1024`, immediately abort and raise `HTTP 413 Payload Too Large` without buffering the remainder into memory.
3. **Magic Byte & Content Validation:**
   - Validate magic byte signatures before passing data to Pillow:
     - JPEG: `b"\xff\xd8\xff"`
     - PNG: `b"\x89PNG\r\n\x1a\n"`
     - WebP: `b"RIFF....WEBP"`
   - Open image with Pillow and call `image.verify()` to validate structural image integrity.
4. **Decompression Bomb & Dimension Caps:**
   - Configure `Image.MAX_IMAGE_PIXELS = 16_000_000` (prevents decompression bomb memory exhaustion).
   - Reject images where `image.width > 4096 or image.height > 4096` with `HTTP 400 Bad Request`.
5. **Process-Local Semaphore Limitation & Deployment Safeguards:**
   - **Limitation Analysis:** `ocr_semaphore = asyncio.Semaphore(2)` is strictly **process-local** (bound to a single Python process/event loop). It does **not** establish a cluster-wide or multi-worker concurrency ceiling. If Uvicorn runs with `--workers 4`, four separate workers could each process 2 tasks concurrently (effective instance concurrency = 8).
   - **Deployment-Level Resource Safeguards:**
     - *Worker Process Bounds:* In resource-constrained environments, Uvicorn should be run with `--workers 1` or `--workers 2`.
     - *Container Resource Limits:* Enforce container-level CPU and memory quotas via Docker Compose or Kubernetes (e.g. `cpus: "1.0"`, `memory: "1G"`) to prevent an OCR spike from exhausting host resources.
     - *Reverse Proxy Rate Limiting:* Configure Nginx or API Gateway rate limits (e.g. `limit_req_zone $binary_remote_addr zone=ocr_zone:10m rate=5r/m`).
     - *Future Architectural Transition:* Offload OCR tasks to a distributed background worker queue (e.g. Celery / Redis Queue with a globally bounded concurrency pool) during multi-tenancy implementation.
6. **Threadpool Execution & Timeouts:**
   - Offload synchronous Pillow / Tesseract processing via `await run_in_threadpool(service.extract_text, file_bytes)` so the AsyncIO event loop remains unblocked.
   - Configure Tesseract processing timeout: `timeout=10` seconds.
   - Explicit cleanup in `try ... finally:` ensuring `image.close()` and buffer memory release.

### 6.2. Detailed Code Implementation

#### Router: [`backend/app/ocr/router.py`](file:///home/dell/projects/eduIntel/backend/app/ocr/router.py)
```python
import asyncio
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool
from app.ocr import service
from app.ocr.schemas import OcrExtractResponse
from app.users.dependencies import get_current_user
from app.users.models import User

router = APIRouter(prefix="/ocr", tags=["ocr"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
# Process-local semaphore: bounds simultaneous OCR tasks within this worker process
ocr_semaphore = asyncio.Semaphore(2)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAGIC_NUMBERS = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/webp": [b"RIFF"],
}

@router.post("/extract", response_model=OcrExtractResponse)
async def extract_text_from_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),  # Authentication enforced
):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported image type: {file.content_type}. Allowed: {ALLOWED_CONTENT_TYPES}"
        )

    # Enforce streaming byte count limit
    file_bytes = bytearray()
    chunk_size = 64 * 1024
    while chunk := await file.read(chunk_size):
        file_bytes.extend(chunk)
        if len(file_bytes) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File size exceeds maximum permitted 5 MB limit."
            )

    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file submitted.")

    # Validate file magic bytes
    expected_magics = MAGIC_NUMBERS.get(file.content_type, [])
    if not any(file_bytes.startswith(magic) for magic in expected_magics):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content does not match reported image format."
        )

    # Process-local bounded concurrency semaphore + threadpool execution
    async with ocr_semaphore:
        result = await run_in_threadpool(service.extract_text, bytes(file_bytes))

    return OcrExtractResponse(
        extracted_text=result["extracted_text"],
        confidence=result["confidence"],
    )
```

#### Service: [`backend/app/ocr/service.py`](file:///home/dell/projects/eduIntel/backend/app/ocr/service.py)
```python
import io
from fastapi import HTTPException, status
from PIL import Image
import pytesseract

MAX_PIXELS = 16_000_000
MAX_DIM = 4096

def extract_text(file_bytes: bytes) -> dict:
    image = None
    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        image = Image.open(io.BytesIO(file_bytes))
        
        # Verify image integrity
        image.verify()
        # Re-open after verify() (Pillow requirement)
        image = Image.open(io.BytesIO(file_bytes))

        if image.width > MAX_DIM or image.height > MAX_DIM:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Image dimensions ({image.width}x{image.height}) exceed maximum allowed {MAX_DIM}x{MAX_DIM} px"
            )

        text = pytesseract.image_to_string(image, timeout=10)
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, timeout=10)
        confidences = [int(c) for c in data["conf"] if c != "-1"]
        avg_confidence = (sum(confidences) / len(confidences) / 100) if confidences else None
    except HTTPException:
        raise
    except RuntimeError as te:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="OCR processing timed out (exceeded 10 seconds)."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OCR engine failure: {e!s}"
        )
    finally:
        if image:
            image.close()

    return {
        "extracted_text": text.strip(),
        "confidence": avg_confidence,
    }
```

---

## 7. Revised Testing Strategy & Isolated Test DB Plan

### 7.1. Isolated Test Database Execution Plan
All integration and security tests run strictly against an isolated PostgreSQL test database (`eduintel_test`):
- **Port:** Configured on port 5434 (Docker test container) or dedicated `eduintel_test` on port 5432.
- **Fixture Lifecycle:** `tests/conftest.py` executes `Base.metadata.create_all()` before each session and `drop_all()` on completion.
- **Data Safety Guarantee:** The active development database (`eduintel`) is never targeted by test runners.
- **In-Memory Email Capture Fixture:** Outgoing reset emails are captured in an in-memory list fixture (`captured_emails = []`) to assert email transmission and content without network calls.

### 7.2. Expanded Test Cases Matrix (34 Test Cases)

```
       AUTHENTICATION (6)           PASSWORD RESET (8)             REGISTRATION (8)
   ┌─────────────────────────┐   ┌─────────────────────────┐   ┌─────────────────────────┐
   │ • Login success/fail    │   │ • No token in JSON      │   │ • Public signup 403     │
   │ • Inactive user 401     │   │ • Uniform payload/status│   │ • Admin creates student │
   │ • Expired JWT 401       │   │ • SHA-256 hash at rest  │   │ • Admin creates teacher │
   │ • Invalid token 401     │   │ • Confirm password ok   │   │ • Admin creates admin   │
   │ • Role check gate       │   │ • Single-use rejected   │   │ • Non-admin blocked 403 │
   │ • Me endpoint user data │   │ • Expiry rejected (30m) │   │ • Role update reject 422│
   │                         │   │ • URL token query param │   │ • Provision audit log   │
   │                         │   │ • HTTPS scheme in prod  │   │ • Password min-len 422  │
   └─────────────────────────┘   └─────────────────────────┘   └─────────────────────────┘

        PARENT REPORTS (6)                 OCR (6)
   ┌─────────────────────────┐   ┌─────────────────────────┐
   │ • Unauthenticated 401   │   │ • Unauthenticated 401   │
   │ • Student caller 403    │   │ • Upload > 5 MB 413     │
   │ • Unassigned teacher 403│   │ • Fake magic bytes 400  │
   │ • Class asgn only 403   │   │ • Dimension bomb 400    │
   │ • Matching student 200  │   │ • Threadpool non-block  │
   │ • Missing parent mail 400│  │ • Process semaphore bnd │
   └─────────────────────────┘   └─────────────────────────┘
```

#### Complete Test Catalog:
1. `test_login_success`: Valid credentials return access token.
2. `test_login_invalid_password`: Wrong password returns 401.
3. `test_login_inactive_account`: Deactivated user returns 401.
4. `test_jwt_expired_token`: Expired JWT returns 401 with `WWW-Authenticate`.
5. `test_jwt_tampered_signature`: Tampered JWT returns 401.
6. `test_users_me_profile`: Authenticated user retrieves own profile.
7. `test_reset_no_token_in_response`: `POST /auth/password-reset/request` does NOT contain `dev_reset_token`.
8. `test_reset_user_enumeration_uniformity`: Identical response payload and 200 status for registered and unregistered emails.
9. `test_reset_token_hashed_in_database`: Database stores 64-char SHA-256 digest, never raw token.
10. `test_reset_confirm_success`: Valid raw token confirms and updates password hash.
11. `test_reset_single_use_enforcement`: Re-using confirmed token returns 400.
12. `test_reset_expiration_enforcement`: Expired token (> 30 min) returns 400.
13. `test_reset_url_token_query_parameter`: Frontend correctly reads token from search parameters.
14. `test_reset_https_production_validation`: `FRONTEND_BASE_URL` raises validation error if HTTP in production.
15. `test_public_signup_disabled_rejected`: `POST /auth/signup` returns `403 Forbidden`.
16. `test_admin_creates_student_success`: Authenticated admin provisions student account via `POST /admin/students`.
17. `test_admin_creates_teacher_success`: Authenticated admin provisions teacher account via `POST /admin/teachers`.
18. `test_admin_creates_admin_success`: Authenticated admin provisions institutional admin via `POST /admin/administrators`.
19. `test_non_admin_cannot_create_staff_or_student`: Non-admin calling staff or student provisioning gets 403.
20. `test_profile_update_cannot_escalate_role`: `PUT /users/me` with `{"role": "admin"}` rejects extra field or does not escalate user role.
21. `test_admin_provisioning_audit_logging`: Administrative creation emits structured audit log containing actor ID, target user ID, email, and role, without logging plaintext passwords.
22. `test_provision_password_min_length_enforced`: Password shorter than 8 characters returns 422.
23. `test_parent_report_unauthenticated_rejected`: `POST /reports/parent-report/{id}` returns 401.
24. `test_parent_report_student_rejected`: Student caller returns 403.
25. `test_parent_report_unassigned_teacher_rejected`: Teacher with no timetable assignment to student's class gets 403.
26. `test_parent_report_class_level_assignment_only_rejected`: Teacher assigned on timetable who only created a class-level Assignment (no student-specific ExamResult, Attendance, or graded Homework) is rejected with 403.
27. `test_parent_report_matching_student_and_class_success`: Teacher assigned on timetable with student-specific ExamResult, Attendance, or graded Homework for this student is authorized (200 OK).
28. `test_parent_report_missing_parent_email_rejected`: Student with null parent email returns 400.
29. `test_ocr_unauthenticated_rejected`: `POST /ocr/extract` returns 401.
30. `test_ocr_file_too_large_rejected`: Upload > 5 MB returns 413.
31. `test_ocr_fake_extension_magic_bytes_rejected`: Text file with `.png` extension returns 400.
32. `test_ocr_dimension_bomb_rejected`: Image with dimensions > 4096 px returns 400.
33. `test_ocr_threadpool_execution_unblocked`: Async event loop handles concurrent health checks during OCR execution.
34. `test_ocr_process_semaphore_bounded`: Concurrent requests within worker respect bounded semaphore.

---

## 8. Potential Side Effects, Risks & Rollback Strategy

| Risk Scenario | Impact | Mitigation Strategy | Rollback Procedure |
|---|---|---|---|
| **Test Fixture Breakage** | `tests/conftest.py` fails if signup is locked | Update fixtures in `conftest.py` atomically with signup changes. | Revert `conftest.py` with `git restore tests/conftest.py`. |
| **Email Delivery in Local Dev** | Reset emails fail if SMTP unreachable | Integrate Mailpit (`localhost:1025`) and in-memory test fixture. | Set `SMTP_HOST=localhost`, `SMTP_PORT=1025`. |
| **Pillow Decompression Bomb False Positives** | Legitimate large architectural scans rejected | Allow up to 4096x4096px (16 MP); clearly document limit in UI. | Increase `MAX_DIM` to 6000px if required. |
| **Zero Migration Schema Risk** | Zero risk of migration lock or data corruption | No schema migrations executed in Milestone 1. | N/A (no database schema changes). |

---

## 9. Final Decision Summary & Authorization Gateway

All technical decisions and pre-implementation directives are fully incorporated:

1. **SEC-03 Authorization:** Class-level `Assignment` records are explicitly excluded. Multi-factor verification strictly requires student-specific records (`ExamResult`, `Attendance`, `HomeworkSubmission`).
2. **SEC-01 Timing:** Avoids unsupported constant-time claims; implements identical status/payloads, asynchronous background email delivery, comparable execution paths (`_dummy_hash_computation`), and rate limiting.
3. **Administrative Provisioning Safeguards:** Authenticated admin gate (`require_role("admin")`), platform superadmin creation prohibited from API, profile-update role escalation protection (`extra = "forbid"`), and credential-free audit logging.
4. **Database Policy:** Zero migrations. Single-tenant admin parity documented; bootstrap via server CLI.
5. **Student Enrollment:** Controlled exclusively by institutional administrators (`POST /admin/students`). Public signup disabled (`HTTP 403`).
6. **Local Development Email:** Mailpit manual inspection + in-memory automated test capture fixture.
7. **OCR Safeguards:** Process-local semaphore limitation acknowledged; container quotas and worker bounds specified.

**Execution Boundary:** The planning phase is complete. Application code, database schemas, records, and configurations remain untouched. Implementation will begin immediately upon your explicit authorization.
