from fastapi import APIRouter, Depends
from app.users.dependencies import require_role
from app.users.models import User

router = APIRouter(prefix="/student", tags=["student"])


@router.get("/dashboard")
async def student_dashboard(current_user: User = Depends(require_role("student"))):
    return {
        "message": f"Welcome, {current_user.email}",
        "role": current_user.role,
        "homework_count": 0,
        "unresolved_doubts": 0,
        "study_plan_ready": False,
    }