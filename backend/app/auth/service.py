import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

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
    if not user or not verify_password(data.password, user.hashed_password):
        raise ValueError("Incorrect email or password")
    if not user.is_active:
        raise ValueError("This account has been deactivated")

    token = create_access_token(data={"sub": str(user.id), "role": user.role})
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
    reset_token.used = True
    await db.commit()
