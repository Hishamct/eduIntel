from fastapi import APIRouter, Depends
from app.users.dependencies import require_role
from app.users.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard")
async def admin_dashboard(current_user: User = Depends(require_role("admin"))):
    return {
        "message": f"Welcome, {current_user.email}",
        "role": current_user.role,
        "total_students": 0,
        "total_teachers": 0,
        "revenue_this_month": 0,
    }