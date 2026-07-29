from fastapi import APIRouter, Depends
from app.users.dependencies import require_role
from app.users.models import User

router = APIRouter(prefix="/teacher", tags=["teacher"])


@router.get("/dashboard")
async def teacher_dashboard(current_user: User = Depends(require_role("teacher"))):
    return {
        "message": f"Welcome, {current_user.email}",
        "role": current_user.role,
        # Placeholder — real data (progress monitoring, flagged students) arrives in Week 2/4
        "students_assigned": 0,
        "pending_grading": 0,
        "flagged_students": 0,
    }