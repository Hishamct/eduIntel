from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.users.models import User, StudentProfile, TeacherProfile, AdminProfile
from app.auth.schemas import SignupRequest, LoginRequest
from app.auth.security import hash_password, verify_password, create_access_token


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


import secrets
from datetime import datetime, timedelta, timezone
from app.auth.models import PasswordResetToken


async def request_password_reset(db: AsyncSession, email: str) -> str | None:
    user = await get_user_by_email(db, email)
    if not user:
        # Don't reveal whether the email exists — return None, router treats it the same either way
        return None

    token_value = secrets.token_urlsafe(32)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token_value,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db.add(reset_token)
    await db.commit()
    return token_value


async def confirm_password_reset(db: AsyncSession, token: str, new_password: str) -> None:
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == token)
    )
    reset_token = result.scalar_one_or_none()

    if not reset_token:
        raise ValueError("Invalid reset token")
    if reset_token.used:
        raise ValueError("This reset token has already been used")
    if reset_token.expires_at < datetime.now(timezone.utc):
        raise ValueError("This reset token has expired")

    result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    user.hashed_password = hash_password(new_password)
    reset_token.used = True
    await db.commit()