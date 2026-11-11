import asyncio
import inspect
import io
import logging
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Timetable
from app.core.config import settings
from app.core.database import get_db
from app.core.llm_provider import (
    LLMCallUsage,
    ProviderQuotaExhaustedError,
    ProviderTransientError,
)
from app.core.tenant import (
    TenantContext,
    get_tenant_db,
    get_trusted_tenant_id,
    require_tenant_role,
    tenant_session_scope,
)
from app.ml.diagnosis import diagnose_student
from app.ml.explain import get_at_risk_explanation
from app.ml.recommendations import get_recommendations_for_weak_topics
from app.ml.schemas import AtRiskPrediction, WeakTopicResponse
from app.ml.service import (
    MLServiceError,
    get_at_risk_prediction,
    get_weak_topic_predictions,
)
from app.ml.worksheet_generator import (
    WorksheetGenerationError,
    WorksheetGuardrailError,
    WorksheetParsingError,
    generate_worksheet_pdf,
)
from app.observability.quota import (
    MeteredRequestContext,
    get_current_metered_context,
    metered_execution_context,
)
from app.observability.service import log_llm_usage
from app.users.dependencies import require_role
from app.users.models import StudentProfile, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ml", tags=["ml"])

# Concurrency & Timeout Bounds
WORKSHEET_GENERATION_SEMAPHORE = asyncio.Semaphore(10)
WORKSHEET_SEMAPHORE_TIMEOUT = 5.0
TOTAL_WORKSHEET_DEADLINE_SECONDS = 45.0

ML_INFERENCE_SEMAPHORE = asyncio.Semaphore(16)
ML_INFERENCE_ACQUIRE_TIMEOUT = 5.0

# Task registries: Retain strong references to running worker tasks
_ACTIVE_WORKSHEET_TASKS: set[asyncio.Task] = set()
_ACTIVE_ML_INFERENCE_TASKS: set[asyncio.Task] = set()
_ACTIVE_DETACHED_TELEMETRY_TASKS: set[asyncio.Task] = set()

# Process-wide shutdown gate: Set True when server initiates lifespan shutdown
_ML_SHUTDOWN_IN_PROGRESS: bool = False


def _reset_ml_shutdown_state_for_testing() -> None:
    """Resets ML shutdown state flag for test suite isolation."""
    global _ML_SHUTDOWN_IN_PROGRESS
    _ML_SHUTDOWN_IN_PROGRESS = False


async def run_with_inference_capacity(coro_or_func, *args, **kwargs):
    """
    Acquires an ML inference semaphore slot before scheduling worker.
    Guarantees that cancellation or timeout of the awaiting request does NOT
    release the semaphore while the underlying physical worker is still running.
    Releases the semaphore permit exactly once when physical execution completes.
    Rejects admission with HTTP 503 if server shutdown has commenced.
    """
    if _ML_SHUTDOWN_IN_PROGRESS:
        logger.warning("[ML Router] ML inference admission rejected: service is shutting down.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML inference service is currently shutting down. Please retry shortly.",
            headers={"Retry-After": "5"},
        )

    try:
        await asyncio.wait_for(
            ML_INFERENCE_SEMAPHORE.acquire(),
            timeout=ML_INFERENCE_ACQUIRE_TIMEOUT,
        )
    except TimeoutError as te:
        logger.warning("[ML Router] ML inference capacity exhausted (16 concurrent). HTTP 503 returned.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML inference service is currently at maximum capacity. Please retry shortly.",
            headers={"Retry-After": "5"},
        ) from te

    if _ML_SHUTDOWN_IN_PROGRESS:
        ML_INFERENCE_SEMAPHORE.release()
        logger.warning("[ML Router] ML inference admission rejected after acquire: service is shutting down.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML inference service is currently shutting down. Please retry shortly.",
            headers={"Retry-After": "5"},
        )

    semaphore_released = False

    async def _execute_work():
        if inspect.iscoroutinefunction(coro_or_func):
            return await coro_or_func(*args, **kwargs)
        elif callable(coro_or_func):
            res = coro_or_func(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res
        elif inspect.isawaitable(coro_or_func):
            return await coro_or_func
        else:
            return coro_or_func

    worker_task: asyncio.Task = asyncio.create_task(_execute_work())
    _ACTIVE_ML_INFERENCE_TASKS.add(worker_task)

    def _on_inference_done(t: asyncio.Task) -> None:
        nonlocal semaphore_released
        _ACTIVE_ML_INFERENCE_TASKS.discard(t)
        if not t.cancelled():
            _ = t.exception()
        if not semaphore_released:
            semaphore_released = True
            ML_INFERENCE_SEMAPHORE.release()

    worker_task.add_done_callback(_on_inference_done)

    # Shield worker_task so caller cancellation does NOT abort worker
    # and does NOT release semaphore prematurely while physical thread continues
    return await asyncio.shield(worker_task)


@asynccontextmanager
async def ml_inference_capacity_scope():
    """
    DEPRECATED & RETIRED in Phase 5 Step 3.6 Stage 4.

    Context-manager scoping cannot safely retain physical worker capacity under
    caller cancellation when operations execute in background OS threads.
    Use `await run_with_inference_capacity(coro_or_func, *args, **kwargs)` instead.
    """
    raise RuntimeError(
        "ml_inference_capacity_scope() has been retired because context-manager scoping "
        "cannot guarantee physical worker capacity retention under asyncio cancellation. "
        "Use run_with_inference_capacity() instead."
    )
    yield  # pragma: no cover


async def wait_for_ml_quiescence(timeout: float = 5.0) -> int:
    """
    Waits iteratively up to `timeout` seconds for active ML inference, worksheet generation,
    and detached telemetry tasks to reach physical completion during shutdown.
    Activates `_ML_SHUTDOWN_IN_PROGRESS = True` before the first drain snapshot to reject
    new incoming admissions.
    Re-inspects task registries across iterations to ensure tasks scheduled by completion
    callbacks (such as detached telemetry) are completely drained.
    Returns the count of tasks that did not complete before the timeout (0 if clean).
    Does NOT cancel pending tasks or claim that physical threads have terminated if the deadline expired.
    """
    global _ML_SHUTDOWN_IN_PROGRESS
    _ML_SHUTDOWN_IN_PROGRESS = True

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    iteration = 0

    while True:
        active = set(_ACTIVE_ML_INFERENCE_TASKS | _ACTIVE_WORKSHEET_TASKS | _ACTIVE_DETACHED_TELEMETRY_TASKS)
        if not active:
            logger.info(
                "[ML Router] Shutdown quiescence achieved: all task registries empty (iterations=%d).",
                iteration,
            )
            return 0

        remaining_time = deadline - loop.time()
        if remaining_time <= 0:
            logger.warning(
                "[ML Router] Shutdown quiescence deadline (%.1fs) reached with %d task(s) still executing in thread pool "
                "(inference=%d, worksheet=%d, telemetry=%d). "
                "Underlying OS worker threads remain running and are not forcibly terminated.",
                timeout,
                len(active),
                len(_ACTIVE_ML_INFERENCE_TASKS),
                len(_ACTIVE_WORKSHEET_TASKS),
                len(_ACTIVE_DETACHED_TELEMETRY_TASKS),
            )
            return len(active)

        iteration += 1
        logger.info(
            "[ML Router] Shutdown quiescence iteration %d: awaiting %d active task(s) (remaining=%.2fs)...",
            iteration,
            len(active),
            remaining_time,
        )

        done, pending = await asyncio.wait(active, timeout=remaining_time)
        for t in done:
            if not t.cancelled():
                _ = t.exception()


async def authorize_student_ml_access(
    student_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> tuple[User, StudentProfile]:
    """
    Validates access to student ML diagnostics:
    1. Verifies the target student exists, has role 'student', and has a StudentProfile (404 otherwise).
    2. Administrators have universal platform access to student ML diagnostics.
    3. Teachers require:
       a) Student must have a valid grade and section (403 if unassigned).
       b) Teacher must have an assigned Timetable entry for that class_section (403 if unassigned).
    4. Any other role is forbidden (403).
    """
    result = await db.execute(
        select(User, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .where(User.id == student_id, User.role == "student")
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    student_user, profile = row

    if current_user.role == "admin":
        return student_user, profile

    if current_user.role == "teacher":
        if not profile.grade or not profile.section:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Student is not assigned to any grade/section",
            )

        student_section = f"{profile.grade}-{profile.section}"
        tt_res = await db.execute(
            select(Timetable.id)
            .where(
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
        return student_user, profile

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden",
    )


@router.get("/predict/at-risk/{student_id}", response_model=AtRiskPrediction)
async def predict_at_risk(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        return await run_with_inference_capacity(get_at_risk_prediction, db=db, student_id=student_id)
    except HTTPException:
        raise
    except (MLServiceError, Exception) as exc:
        logger.exception("Inference error in predict_at_risk for student_id=%s: %s", student_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/predict/at-risk-admin/{student_id}", response_model=AtRiskPrediction)
async def predict_at_risk_admin(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        return await run_with_inference_capacity(get_at_risk_prediction, db=db, student_id=student_id)
    except HTTPException:
        raise
    except (MLServiceError, Exception) as exc:
        logger.exception("Inference error in predict_at_risk_admin for student_id=%s: %s", student_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/explain/at-risk/{student_id}")
async def explain_at_risk(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        return await run_with_inference_capacity(get_at_risk_explanation, db=db, student_id=student_id)
    except HTTPException:
        raise
    except (MLServiceError, Exception) as exc:
        logger.exception("Inference error in explain_at_risk for student_id=%s: %s", student_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/predict/weak-topics/{student_id}", response_model=WeakTopicResponse)
async def predict_weak_topics(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        async def _work():
            predictions = await get_weak_topic_predictions(db=db, student_id=student_id)
            return {"student_id": student_id, "predictions": predictions}

        return await run_with_inference_capacity(_work)
    except HTTPException:
        raise
    except (MLServiceError, Exception) as exc:
        logger.exception("Inference error in predict_weak_topics for student_id=%s: %s", student_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/diagnose/{student_id}")
async def diagnose_student_endpoint(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        async def _work():
            at_risk_result = await get_at_risk_prediction(db=db, student_id=student_id)
            weak_topics = await get_weak_topic_predictions(db=db, student_id=student_id)
            diagnosis = diagnose_student(at_risk_result, weak_topics)
            return {"student_id": student_id, **diagnosis}

        return await run_with_inference_capacity(_work)
    except HTTPException:
        raise
    except (MLServiceError, Exception) as exc:
        logger.exception("Inference error in diagnose_student for student_id=%s: %s", student_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/diagnose-with-recommendations/{student_id}")
async def diagnose_with_recommendations(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        async def _work():
            at_risk_result = await get_at_risk_prediction(db=db, student_id=student_id)
            weak_topics = await get_weak_topic_predictions(db=db, student_id=student_id)
            diagnosis = diagnose_student(at_risk_result, weak_topics)

            trusted_tenant = get_trusted_tenant_id(current_user)
            recommendations = get_recommendations_for_weak_topics(
                diagnosis["top_weak_topics"],
                tenant_id=trusted_tenant,
            )
            diagnosis["recommendations"] = recommendations

            return {"student_id": student_id, **diagnosis}

        return await run_with_inference_capacity(_work)
    except HTTPException:
        raise
    except (MLServiceError, Exception) as exc:
        logger.exception(
            "Inference error in diagnose_with_recommendations for student_id=%s: %s", student_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/recommend-topic")
async def recommend_for_topic(
    subject: str,
    topic: str,
    current_user: User = Depends(require_role("teacher")),
):
    trusted_tenant = get_trusted_tenant_id(current_user)
    try:
        recommendations = get_recommendations_for_weak_topics(
            [{"subject": subject, "topic": topic}],
            tenant_id=trusted_tenant,
            n_results_per_topic=3,
        )
        return (
            recommendations[0]
            if recommendations
            else {"subject": subject, "topic": topic, "recommendation": None, "sources": []}
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error in recommend_for_topic for subject=%s, topic=%s: %s", subject, topic, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/generate-worksheet")
async def generate_worksheet(
    subject: str,
    topic: str,
    student_name: str | None = None,
    student_context: str | None = None,
    tenant: TenantContext = Depends(require_tenant_role("teacher", "admin")),
    db: AsyncSession = Depends(get_tenant_db),
):
    captured_usage: LLMCallUsage | None = None
    pdf_bytes: bytes | None = None
    request_timed_out_or_cancelled = False

    # 1. Async request orchestration acquires semaphore BEFORE scheduling worker with timeout
    if _ML_SHUTDOWN_IN_PROGRESS:
        logger.warning("[ML Router] Worksheet generation admission rejected: service is shutting down.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worksheet generation service is currently shutting down. Please retry shortly.",
            headers={"Retry-After": "5"},
        )

    try:
        await asyncio.wait_for(
            WORKSHEET_GENERATION_SEMAPHORE.acquire(),
            timeout=WORKSHEET_SEMAPHORE_TIMEOUT,
        )
    except TimeoutError as te:
        logger.warning("[ML Router] Worksheet generation capacity exhausted (10 concurrent). HTTP 503 returned.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worksheet generation service is currently at maximum capacity. Please retry shortly.",
            headers={"Retry-After": "5"},
        ) from te

    if _ML_SHUTDOWN_IN_PROGRESS:
        WORKSHEET_GENERATION_SEMAPHORE.release()
        logger.warning("[ML Router] Worksheet generation admission rejected after acquire: service is shutting down.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worksheet generation service is currently shutting down. Please retry shortly.",
            headers={"Retry-After": "5"},
        )
    semaphore_released = False

    metered_ctx = None
    if settings.ENABLE_TENANT_AI_QUOTAS or get_current_metered_context() is not None:
        metered_ctx = MeteredRequestContext(
            institution_id=tenant.institution_id,
            user_id=tenant.user_id,
            endpoint="ml/generate-worksheet",
            usage_category="interactive_ai",
            idempotency_key=f"worksheet:{tenant.institution_id}:{uuid.uuid4()}",
        )
    elif settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant AI quotas are disabled or unconfigured in production.",
        )

    def _run_worksheet_gen():
        if metered_ctx is not None:
            with metered_execution_context(metered_ctx):
                return generate_worksheet_pdf(
                    subject=subject,
                    topic=topic,
                    student_name=student_name,
                    student_context=student_context,
                )
        return generate_worksheet_pdf(
            subject=subject,
            topic=topic,
            student_name=student_name,
            student_context=student_context,
        )

    # 2. Schedule worker task on event loop; worker thread never touches semaphore
    worker_task: asyncio.Task = asyncio.create_task(
        asyncio.to_thread(_run_worksheet_gen)
    )
    _ACTIVE_WORKSHEET_TASKS.add(worker_task)

    def _on_worker_task_done(t: asyncio.Task) -> None:
        nonlocal semaphore_released
        _ACTIVE_WORKSHEET_TASKS.discard(t)

        # Retrieve exception to prevent unretrieved exception warnings
        exc = None if t.cancelled() else t.exception()
        worker_usage = None
        if exc:
            worker_usage = getattr(exc, "usage", None)
        elif not t.cancelled():
            result = t.result()
            if isinstance(result, tuple) and len(result) == 2:
                _, worker_usage = result

        # If request was disconnected or timed out, persist usage in detached scope
        if worker_usage and (request_timed_out_or_cancelled or not db.is_active):
            bg_task = asyncio.create_task(
                _persist_background_detached_usage(worker_usage, tenant.institution_id)
            )
            _ACTIVE_DETACHED_TELEMETRY_TASKS.add(bg_task)
            bg_task.add_done_callback(_ACTIVE_DETACHED_TELEMETRY_TASKS.discard)

        # Release semaphore slot EXACTLY ONCE when underlying thread physically finishes
        if not semaphore_released:
            semaphore_released = True
            WORKSHEET_GENERATION_SEMAPHORE.release()

    worker_task.add_done_callback(_on_worker_task_done)

    try:
        # 3. Shield worker_task so request cancellation or wait_for timeout
        # DOES NOT propagate cancellation into the worker!
        pdf_bytes, captured_usage = await asyncio.wait_for(
            asyncio.shield(worker_task),
            timeout=TOTAL_WORKSHEET_DEADLINE_SECONDS,
        )

    except TimeoutError as te:
        request_timed_out_or_cancelled = True
        logger.error(
            "[ML Router] Request deadline (45s) exceeded. HTTP 504 returned; worker thread remains running."
        )
        # DO NOT release semaphore here! The done-callback releases it when the thread physically completes.
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Worksheet generation timed out. Please try again with a narrower topic.",
        ) from te

    except asyncio.CancelledError:
        request_timed_out_or_cancelled = True
        logger.warning("[ML Router] Client disconnected; worker thread remains running.")
        # DO NOT release semaphore here! The done-callback releases it when the thread physically completes.
        raise

    except WorksheetGuardrailError as ge:
        captured_usage = ge.usage or captured_usage
        logger.warning("[ML Router] Worksheet guardrail triggered: %s", ge)
        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if ge.is_output_violation
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=ge.refusal_message) from ge

    except WorksheetParsingError as pe:
        captured_usage = pe.usage or captured_usage
        logger.warning("[ML Router] Upstream model output parsing failed: %s", pe)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream AI model returned invalid worksheet format: {pe.message}",
        ) from pe

    except (ProviderQuotaExhaustedError, ProviderTransientError) as pe:
        logger.error("[ML Router] All AI providers exhausted for worksheet generation: %s", pe)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI worksheet generation service is temporarily unavailable. Please try again later.",
        ) from pe

    except WorksheetGenerationError as wge:
        captured_usage = wge.usage or captured_usage
        logger.error("[ML Router] Worksheet generation error: %s", wge)
        status_code = (
            status.HTTP_400_BAD_REQUEST
            if "cannot be empty" in wge.message
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        detail = (
            wge.message
            if "cannot be empty" in wge.message
            else f"Failed to generate practice worksheet: {wge.message}"
        )
        raise HTTPException(
            status_code=status_code,
            detail=detail,
        ) from wge

    except Exception as exc:
        logger.exception("[ML Router] Unexpected error during worksheet generation: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while generating the practice worksheet.",
        ) from exc

    finally:
        # Telemetry Persistence: Exception-safe, isolated transaction, executed on event loop
        if captured_usage is not None and db is not None and db.is_active:
            await _safe_persist_telemetry(db, captured_usage, tenant.institution_id)

    safe_topic = re.sub(r"[^A-Za-z0-9_\-]", "_", topic).strip("_")
    filename = f"{safe_topic or 'practice'}_worksheet.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _safe_persist_telemetry(
    db: AsyncSession,
    usage: LLMCallUsage,
    institution_id: uuid.UUID,
) -> None:
    """
    Guarantees isolated telemetry persistence even if session is in a failed transaction.
    Never raises exceptions; never masks original errors or invalidates successful PDFs.
    """
    try:
        in_tx = db.in_transaction() if hasattr(db, "in_transaction") else False
        if inspect.isawaitable(in_tx):
            in_tx = await in_tx
        sync_active = getattr(getattr(db, "sync_session", None), "is_active", True)
        if not db.is_active or (in_tx and not sync_active):
            logger.info("[ML Router] Recovering aborted database transaction for telemetry logging.")
            await db.rollback()
            await db.execute(
                text("SELECT set_config('app.current_institution_id', :inst_id, true)"),
                {"inst_id": str(institution_id)},
            )

        await log_llm_usage(
            db=db,
            endpoint="ml/generate-worksheet",
            usage=usage,
            institution_id=institution_id,
        )
        await db.commit()
    except Exception as log_err:
        logger.warning("[ML Router] Non-fatal telemetry persistence failure: %s", log_err)


async def _persist_background_detached_usage(
    usage: LLMCallUsage,
    institution_id: uuid.UUID,
) -> None:
    """
    Persists telemetry for completed detached worker tasks using tenant_session_scope.
    """
    try:
        async with tenant_session_scope(institution_id) as db:
            await log_llm_usage(
                db=db,
                endpoint="ml/generate-worksheet",
                usage=usage,
                institution_id=institution_id,
            )
    except Exception as bg_err:
        logger.warning("[ML Router] Detached background telemetry persistence failed: %s", bg_err)
