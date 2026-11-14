import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Attendance, Timetable
from app.core.config import settings
from app.core.json_encoder import ParentReportPayloadTooLargeError
from app.core.tenant import (
    TenantContext,
    get_tenant_db,
    require_tenant_role,
    tenant_session_scope,
)
from app.observability.quota import (
    MeteredRequestContext,
    get_current_metered_context,
    metered_execution_context,
)
from app.observability.service import log_llm_usage
from app.reports.parent_report_agent import (
    ParentReportGuardrailError,
    generate_and_send_report,
)
from app.student.models import HomeworkSubmission
from app.teacher.models import ExamResult
from app.users.dependencies import require_role
from app.users.models import StudentProfile, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

PARENT_REPORT_SEMAPHORE = asyncio.Semaphore(10)
TOTAL_PARENT_REPORT_DEADLINE_SECONDS = 45.0
_ACTIVE_PARENT_REPORT_TASKS: set[asyncio.Task] = set()


class ParentReportRequest(BaseModel):
    custom_message_note: str | None = None  # ZERO client recipient overrides allowed
    model_config = ConfigDict(extra="forbid")


async def _persist_background_report_usage(usage, institution_id: uuid.UUID) -> None:
    """
    Persists telemetry for completed detached parent report tasks using tenant_session_scope.
    """
    try:
        async with tenant_session_scope(institution_id) as db:
            await log_llm_usage(
                db=db,
                endpoint="reports/parent-report",
                usage=usage,
                institution_id=institution_id,
            )
    except Exception as bg_err:
        logger.warning("[Reports Router] Detached background telemetry persistence failed: %s", bg_err)


@router.post("/parent-report/{student_id}")
async def trigger_parent_report(
    student_id: str,
    payload: ParentReportRequest | None = None,
    current_user: User = Depends(require_role("teacher", "admin")),
    tenant: TenantContext = Depends(require_tenant_role("teacher", "admin")),
    db: AsyncSession = Depends(get_tenant_db),
):
    try:
        uid = uuid.UUID(student_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid student UUID format",
        ) from e

    result = await db.execute(
        select(User, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .where(
            User.id == uid,
            User.role == "student",
            StudentProfile.institution_id == tenant.institution_id,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    student_user, profile = row
    student_section = f"{profile.grade}-{profile.section}" if profile.grade and profile.section else None

    # Multi-Factor Teacher Authorization Verification
    if tenant.role == "teacher":
        if not student_section:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Student is not assigned to any grade/section",
            )

        # 1. Condition A: Timetable Class Assignment
        tt_res = await db.execute(
            select(Timetable.id)
            .where(
                Timetable.institution_id == tenant.institution_id,
                Timetable.teacher_id == current_user.id,
                Timetable.class_section == student_section,
            )
            .limit(1)
        )
        if not tt_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authorization denied: You are not assigned to teach this student's class section.",
            )

        # 2. Condition B: Concrete Student-Specific Academic Relationship
        exam_link = await db.execute(
            select(ExamResult.id)
            .where(
                ExamResult.institution_id == tenant.institution_id,
                ExamResult.student_id == uid,
                ExamResult.entered_by == current_user.id,
                ExamResult.class_section == student_section,
            )
            .limit(1)
        )
        att_link = await db.execute(
            select(Attendance.id)
            .where(
                Attendance.institution_id == tenant.institution_id,
                Attendance.student_id == uid,
                Attendance.marked_by == current_user.id,
                Attendance.class_section == student_section,
            )
            .limit(1)
        )
        hw_link = await db.execute(
            select(HomeworkSubmission.id)
            .where(
                HomeworkSubmission.institution_id == tenant.institution_id,
                HomeworkSubmission.student_id == uid,
                HomeworkSubmission.graded_by == current_user.id,
                HomeworkSubmission.status == "graded",
            )
            .limit(1)
        )

        has_student_specific_link = (
            exam_link.scalar_one_or_none() is not None
            or att_link.scalar_one_or_none() is not None
            or hw_link.scalar_one_or_none() is not None
        )
        if not has_student_specific_link:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Authorization denied: No student-specific academic records "
                    "(entered exam scores, marked attendance, or graded homework) link you to this student."
                ),
            )

    # Strictly enforce verified parent email from database
    if not profile.parent_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has no registered parent email on file. Update student profile before generating report.",
        )

    # Concurrency control & cancellation decoupling
    await PARENT_REPORT_SEMAPHORE.acquire()
    semaphore_released = False
    request_timed_out_or_cancelled = False

    custom_note = payload.custom_message_note if payload else None

    worker_kwargs = {
        "student_id": str(uid),
        "student_name": student_user.name or "Student",
        "parent_email": profile.parent_email,
        "db": None,
        "generated_by_user_id": current_user.id,
        "institution_id": tenant.institution_id,
    }
    if custom_note is not None:
        worker_kwargs["custom_message_note"] = custom_note

    metered_ctx = None
    if settings.ENABLE_TENANT_AI_QUOTAS or get_current_metered_context() is not None:
        metered_ctx = MeteredRequestContext(
            institution_id=tenant.institution_id,
            user_id=current_user.id,
            endpoint="reports/parent-report",
            usage_category="interactive_ai",
            idempotency_key=f"parent_report:{uid}:{uuid.uuid4()}",
        )
    elif settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant AI quotas are disabled or unconfigured in production.",
        )

    async def _run_report_gen():
        if metered_ctx is not None:
            with metered_execution_context(metered_ctx):
                return await generate_and_send_report(**worker_kwargs)
        return await generate_and_send_report(**worker_kwargs)

    # Dispatch to worker under shield
    worker_task = asyncio.create_task(_run_report_gen())
    _ACTIVE_PARENT_REPORT_TASKS.add(worker_task)

    def _on_worker_task_done(t: asyncio.Task) -> None:
        nonlocal semaphore_released
        _ACTIVE_PARENT_REPORT_TASKS.discard(t)
        try:
            exc = t.exception() if not t.cancelled() else None
        except Exception:
            exc = None

        if request_timed_out_or_cancelled:
            worker_usage = getattr(exc, "usage", None) if exc else None
            if worker_usage:
                asyncio.create_task(_persist_background_report_usage(worker_usage, tenant.institution_id))

        if not semaphore_released:
            semaphore_released = True
            PARENT_REPORT_SEMAPHORE.release()

    worker_task.add_done_callback(_on_worker_task_done)

    try:
        report_result = await asyncio.wait_for(
            asyncio.shield(worker_task),
            timeout=TOTAL_PARENT_REPORT_DEADLINE_SECONDS,
        )
        return report_result

    except TimeoutError as te:
        request_timed_out_or_cancelled = True
        logger.error("[Reports Router] Report generation deadline (45s) exceeded for student_id=%s", uid)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Parent progress report generation timed out. Please try again later.",
        ) from te

    except asyncio.CancelledError:
        request_timed_out_or_cancelled = True
        logger.warning("[Reports Router] Client disconnected for student_id=%s; worker remains running.", uid)
        raise

    except HTTPException:
        raise

    except ParentReportPayloadTooLargeError as pte:
        logger.warning("[Reports Router] Payload size exceeded for student_id=%s: %s", uid, pte)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(pte),
        ) from pte

    except ParentReportGuardrailError as ge:
        logger.warning("[Reports Router] Guardrail error for student_id=%s: %s", uid, ge)
        status_code = status.HTTP_502_BAD_GATEWAY if ge.is_output_violation else status.HTTP_400_BAD_REQUEST
        raise HTTPException(
            status_code=status_code,
            detail=ge.message,
        ) from ge

    except ValueError as ve:
        logger.warning("[Reports Router] Validation error for student_id=%s: %s", uid, ve)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve),
        ) from ve

    except Exception as e:
        logger.error(
            "Parent report generation/delivery failed | actor_id=%s | student_id=%s | error_type=%s",
            current_user.id,
            uid,
            type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Failed to generate or deliver progress report. Please contact system support if this issue persists."
            ),
        ) from e
