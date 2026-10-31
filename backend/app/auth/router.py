from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.schemas import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    TokenResponse,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limiter import password_reset_limiter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=status.HTTP_403_FORBIDDEN)
async def signup():
    """
    Public self-registration is disabled.
    All user accounts (students, teachers, administrators) must be provisioned
    by an authorized institution administrator.
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Public registration is disabled. Please contact your "
            "institution administrator to obtain access credentials."
        ),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    try:
        token = await service.authenticate_user(db, data)
        secure_flag = (
            settings.AUTH_COOKIE_SECURE
            if settings.AUTH_COOKIE_SECURE is not None
            else settings.ENVIRONMENT == "production"
        )
        response.set_cookie(
            key=settings.AUTH_COOKIE_NAME,
            value=token,
            httponly=True,
            secure=secure_flag,
            samesite=settings.AUTH_COOKIE_SAMESITE.lower(),
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            path=settings.AUTH_COOKIE_PATH,
        )
        return TokenResponse(access_token=token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(response: Response):
    """
    Clears the HttpOnly authentication cookie with matching security flags.
    """
    secure_flag = (
        settings.AUTH_COOKIE_SECURE
        if settings.AUTH_COOKIE_SECURE is not None
        else settings.ENVIRONMENT == "production"
    )
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path=settings.AUTH_COOKIE_PATH,
        httponly=True,
        secure=secure_flag,
        samesite=settings.AUTH_COOKIE_SAMESITE.lower(),
    )
    return {"message": "Successfully logged out"}


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(password_reset_limiter)],
)
async def password_reset_request(
    data: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    raw_token, recipient_email = await service.request_password_reset(db, data.email)
    if raw_token and recipient_email:
        background_tasks.add_task(
            service.send_password_reset_email_background, raw_token, recipient_email
        )
    return {
        "message": "If that email is registered, a password reset link has been sent to your email."
    }


@router.post("/password-reset/confirm")
async def password_reset_confirm(
    data: PasswordResetConfirm, db: AsyncSession = Depends(get_db)
):
    try:
        await service.confirm_password_reset(db, data.token, data.new_password)
        return {"message": "Password has been reset successfully."}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
