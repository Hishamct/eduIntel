import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PasswordResetToken
from app.auth.schemas import LoginRequest, SignupRequest
from app.auth.security import create_access_token, hash_password, verify_password
from app.core.config import settings
from app.reports.parent_report_agent import send_email_direct
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User

logger = logging.getLogger(__name__)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def signup_user(db: AsyncSession, data: SignupRequest) -> User:
    existing = await get_user_by_email(db, data.email)
    if existing:
        raise ValueError("A user with this email already exists")

    new_user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        role=data.role,
    )
    db.add(new_user)
    await db.flush()

    if data.role == "student":
        db.add(StudentProfile(user_id=new_user.id))
    elif data.role == "teacher":
        db.add(TeacherProfile(user_id=new_user.id))
    elif data.role == "admin":
        db.add(AdminProfile(user_id=new_user.id))

    await db.commit()
    await db.refresh(new_user)
    return new_user


async def authenticate_user(db: AsyncSession, data: LoginRequest) -> str:
    user = await get_user_by_email(db, data.email)
    if not user:
        raise ValueError("Incorrect email or password")
    if not user.is_active:
        raise ValueError("This account is inactive or has not been activated")
    if not verify_password(data.password, user.hashed_password):
        raise ValueError("Incorrect email or password")

    # If user is not platform admin, enforce per-institution suspension semantics
    if not getattr(user, "is_platform_admin", False):
        from app.institutions.models import Institution, InstitutionMembership

        mem_stmt = (
            select(InstitutionMembership, Institution)
            .join(Institution, Institution.id == InstitutionMembership.institution_id)
            .where(InstitutionMembership.user_id == user.id)
        )
        mem_results = (await db.execute(mem_stmt)).all()
        if mem_results:
            has_any_active_access = any(
                m.status == "active" and inst.is_active for m, inst in mem_results
            )
            if not has_any_active_access:
                raise ValueError("INSTITUTION_SUSPENDED: All associated institutions are currently suspended.")

    token = create_access_token(
        data={
            "sub": str(user.id),
            "role": user.role,
            "is_platform_admin": getattr(user, "is_platform_admin", False),
        }
    )
    return token


def _hash_token(raw_token: str) -> str:
    """Hash raw reset token using SHA-256 for secure storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _dummy_hash_computation() -> None:
    """Execute synthetic token generation and hashing to provide comparable execution paths."""
    dummy_token = secrets.token_urlsafe(32)
    _hash_token(dummy_token)


async def request_password_reset(
    db: AsyncSession, email: str
) -> tuple[str | None, str | None]:
    """
    Process password reset request securely.
    Returns (raw_token, recipient_email) if user exists and is active, else (None, None).
    Executes comparable cryptographic work regardless of whether the user exists.
    Stores strictly the SHA-256 hash in the database, never the raw token.
    """
    user = await get_user_by_email(db, email.lower())
    if not user or not user.is_active:
        _dummy_hash_computation()
        return None, None

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(minutes=30)

    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token_hash,  # Store SHA-256 hash
        expires_at=expires_at,
        used=False,
    )
    db.add(reset_token)
    await db.commit()
    return raw_token, user.email


def send_password_reset_email_background(raw_token: str, recipient_email: str) -> None:
    """
    Dispatches password reset email via SMTP (Mailpit in dev, TLS SMTP in prod).
    Raw token and reset URLs are excluded from standard logging.
    """
    reset_url = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}"
    body = (
        f"You requested a password reset for your EduIntel account.\n\n"
        f"Click the link below to set a new password:\n{reset_url}\n\n"
        f"This link expires in 30 minutes. If you did not make this request, you can safely ignore this email."
    )
    send_email_direct(
        to_email=recipient_email,
        subject="EduIntel — Password Reset Request",
        body=body,
    )


def send_institution_admin_invitation_email(
    raw_token: str, recipient_email: str, recipient_name: str, institution_name: str
) -> dict[str, Any]:
    """
    Dispatches onboarding activation email to the initial institution administrator.
    Raw token and activation URLs are excluded from standard logging.
    Returns delivery status:
    - {'status': 'sent'}: Successfully dispatched via SMTP
    - {'status': 'unconfigured'}: SMTP host is unconfigured or disabled
    - {'status': 'failed', 'detail': ...}: SMTP transmission failed
    """
    if not settings.SMTP_HOST or settings.SMTP_HOST.strip().lower() in ("none", "disabled", ""):
        return {"status": "unconfigured", "detail": "SMTP host is not configured."}

    activation_url = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}"
    body = (
        f"Hello {recipient_name},\n\n"
        f"You have been designated as the initial administrator for {institution_name} on EduIntel AI.\n\n"
        f"Please click the link below to activate your account and choose your password:\n"
        f"{activation_url}\n\n"
        f"This invitation link expires in 48 hours and can only be used once.\n"
        f"If you were not expecting this invitation, please contact your platform administrator."
    )
    result = send_email_direct(
        to_email=recipient_email,
        subject=f"EduIntel — Invitation to Administer {institution_name}",
        body=body,
    )
    if result.get("status") == "error":
        return {"status": "failed", "detail": result.get("detail", "SMTP error")}
    return {"status": "sent"}


async def confirm_password_reset(
    db: AsyncSession, token: str, new_password: str
) -> None:
    token_hash = _hash_token(token)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == token_hash)
    )
    reset_token = result.scalar_one_or_none()

    if not reset_token:
        raise ValueError("Invalid reset token")
    if reset_token.used:
        raise ValueError("This reset token has already been used")
    if reset_token.expires_at < datetime.now(UTC):
        raise ValueError("This reset token has expired")

    result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    user.hashed_password = hash_password(new_password)
    user.is_active = True
    reset_token.used = True
    await db.commit()
