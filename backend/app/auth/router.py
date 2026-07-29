from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.auth.schemas import (
    SignupRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
    PasswordResetRequest,
    PasswordResetConfirm,
)
from app.auth import service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(data: SignupRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await service.signup_user(db, data)
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        token = await service.authenticate_user(db, data)
        return TokenResponse(access_token=token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post("/password-reset/request")
async def password_reset_request(data: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    token = await service.request_password_reset(db, data.email)
    # Always return the same generic message, whether or not the email exists
    response = {"message": "If that email is registered, a reset link has been generated."}
    if token:
        # DEV ONLY: return the raw token directly since email-sending (mcp module) isn't built until Week 4
        response["dev_reset_token"] = token
    return response


@router.post("/password-reset/confirm")
async def password_reset_confirm(data: PasswordResetConfirm, db: AsyncSession = Depends(get_db)):
    try:
        await service.confirm_password_reset(db, data.token, data.new_password)
        return {"message": "Password has been reset successfully."}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))