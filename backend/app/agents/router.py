"""
backend/app/agents/router.py

Phase 5 Step 3.3: Router Refactoring, 3-Phase Checkout Protocol & LangGraph Decoupling.
Provides decoupled, connection-pool-hygienic endpoints for Portal and Admin AI Assistants:
- Phase 1 (Lease Checkout): Short-lived session reservation, idempotency check, latest-10 history.
- Phase 2 (Decoupled Generation): Zero database connections held during external LLM inference;
  database-backed admin tools acquire short-lived scoped sessions per tool execution.
- Phase 3 (Fenced Commit): Conditional atomic commit verifying wall-clock expiry via clock_timestamp().
- Cancellation and disconnect safety using explicitly managed shielded cleanup tasks.
- Canonical session UUID normalization (preserving valid UUIDs, deterministic UUIDv5 for legacy keys).
- Client turn ID conflict detection and fresh UUID fallback.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.agents.admin_assistant import chat_with_admin_assistant
from app.agents.dependencies import get_session_store, get_shared_in_memory_store
from app.agents.portal_assistant import (
    chat_with_portal_assistant,
    current_generation_fence,
    current_generation_owner_token,
)
from app.agents.schemas import (
    AdminAssistantRequest,
    AdminAssistantResponse,
    PortalAssistantRequest,
    PortalAssistantResponse,
)
from app.agents.session_store import (
    AbstractSessionStore,
    FencedCommitPreemptedError,
    SessionAccessDeniedError,
    SessionConcurrencyError,
    SessionDeletedError,
    SessionExpiredError,
    SessionStoreUnavailableError,
)
from app.agents.task_registry import (
    SessionTaskTrackingRegistry,
)
from app.agents.task_registry import (
    is_session_quiescent as is_session_quiescent_unified,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.tenant import TenantContext, require_tenant_role, tenant_session_scope
from app.core.worker_pool import (
    WorkerCapacityExhaustedError,
    WorkerTrackingRegistry,
)
from app.observability.quota import (
    MeteredRequestContext,
    get_current_metered_context,
    metered_execution_context,
)
from app.observability.service import log_agent_trace, log_ai_query, log_llm_usage
from app.users.dependencies import require_role
from app.users.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-\.:]{1,64}$")
EDUINTEL_SESSION_NAMESPACE = uuid.UUID("e7d01f80-0a2b-4d4b-9b7e-8c3e0b2d6a1f")


def normalize_session_id(raw_id: str | uuid.UUID) -> uuid.UUID:
    """
    Canonical session UUID normalization contract:
    - Preserves existing valid UUID objects and valid hex UUID strings unchanged.
    - Deterministically hashes valid legacy alphanumeric strings via UUIDv5 with EDUINTEL_SESSION_NAMESPACE.
    - Trims whitespace. Rejects empty, whitespace-only, malformed, or overlong identifiers with HTTP 422.
    """
    if isinstance(raw_id, uuid.UUID):
        return raw_id
    if not isinstance(raw_id, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Session identifier must be a valid string or UUID.",
        )
    clean_id = raw_id.strip()
    if not clean_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Session identifier cannot be empty or whitespace.",
        )
    try:
        return uuid.UUID(clean_id)
    except ValueError:
        pass

    if not SESSION_ID_PATTERN.match(clean_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Malformed session identifier format.",
        )
    return uuid.uuid5(EDUINTEL_SESSION_NAMESPACE, clean_id)


def resolve_client_turn_id(
    body_turn_id: str | None,
    header_turn_id: str | None,
) -> str:
    """
    Resolves client turn ID with strict conflict detection:
    - Priority: Body client_turn_id -> Header X-Client-Turn-Id -> Fresh random UUID.
    - Rejects conflicting body and header values with HTTP 422.
    - Non-deterministic fresh UUID fallback prevents replay collisions on identical queries.
    """
    clean_body = body_turn_id.strip() if body_turn_id else None
    clean_header = header_turn_id.strip() if header_turn_id else None

    if clean_body and clean_header and clean_body != clean_header:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Conflicting client_turn_id provided: request body and X-Client-Turn-Id header do not match.",
        )
    return clean_body or clean_header or str(uuid.uuid4())


def _resolve_effective_store(request: Request, store: AbstractSessionStore) -> AbstractSessionStore:
    """Supports mock-db unit test fixtures when running in non-production environments."""
    if (
        settings.ENVIRONMENT != "production"
        and get_session_store not in request.app.dependency_overrides
        and get_db in request.app.dependency_overrides
    ):
        return get_shared_in_memory_store()
    return store


def _safe_parse_uuid(val: Any) -> uuid.UUID | None:
    if not val:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError, AttributeError):
        return None


async def _release_lease_when_quiescent(
    store_ref: AbstractSessionStore,
    session_id: uuid.UUID,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    fence: int,
    owner_token: uuid.UUID | str,
    gen_task_ref: asyncio.Task | None = None,
    max_wait_seconds: float = 60.0,
) -> None:
    """
    Background lease release coordinator.
    Ensures that the PostgreSQL generation lease is released ONLY AFTER:
    1. The LangGraph generation task has fully completed/terminated, AND
    2. All physical worker threads (WorkerTrackingRegistry) for this session are quiescent.
    """
    try:
        if gen_task_ref is not None and not gen_task_ref.done():
            try:
                await gen_task_ref
            except (asyncio.CancelledError, Exception):
                pass

        loop = asyncio.get_running_loop()
        start_time = loop.time()
        while not WorkerTrackingRegistry.is_session_quiescent(institution_id, session_id):
            if loop.time() - start_time > max_wait_seconds:
                logger.warning(
                    f"[Router] Timed out waiting {max_wait_seconds}s for physical worker quiescence "
                    f"for session ({institution_id}, {session_id}). Releasing lease now."
                )
                break
            await asyncio.sleep(0.05)

        await store_ref.release_generation_lease(
            session_id=session_id,
            institution_id=institution_id,
            user_id=user_id,
            fence=fence,
            owner_token=owner_token,
        )
        logger.debug(
            f"[Router] Safely released lease in background for session {session_id} "
            f"(fence={fence}, owner_token={owner_token}) after quiescence."
        )
    except Exception as exc:
        logger.error(
            f"[Router] Failed to release lease in background for session {session_id}: {exc}",
            exc_info=True,
        )


@router.post("/portal-assistant/chat", response_model=PortalAssistantResponse)
async def portal_assistant_chat(
    payload: PortalAssistantRequest,
    request: Request,
    current_user: User = Depends(require_role("student")),
    tenant: TenantContext = Depends(require_tenant_role("student")),
    store: AbstractSessionStore = Depends(get_session_store),
    x_client_turn_id: Annotated[str | None, Header(alias="X-Client-Turn-Id")] = None,
):
    session_uuid = normalize_session_id(payload.session_id)
    client_turn_id = resolve_client_turn_id(payload.client_turn_id, x_client_turn_id)
    effective_store = _resolve_effective_store(request, store)

    # -------------------------------------------------------------------------
    # MANDATORY DIRECTIVES 1 & 2: Unified Session Quiescence Barrier Before DB Lease
    # -------------------------------------------------------------------------
    if not is_session_quiescent_unified(tenant.institution_id, session_uuid):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Previous generation workers are still active for this session. Please retry shortly.",
            headers={"Retry-After": "1"},
        )

    # -------------------------------------------------------------------------
    # PHASE 1: Short-Lived Lease Reservation (< 15ms)
    # -------------------------------------------------------------------------
    try:
        await effective_store.get_or_create_session(
            session_id=session_uuid,
            institution_id=tenant.institution_id,
            user_id=current_user.id,
            agent_name="portal_assistant",
            title="Portal Assistant Conversation",
        )
        lease_result = await effective_store.reserve_generation_lease(
            session_id=session_uuid,
            institution_id=tenant.institution_id,
            user_id=current_user.id,
            client_turn_id=client_turn_id,
            history_limit=10,
        )
    except SessionConcurrencyError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
            headers={"Retry-After": str(e.retry_after)},
        ) from e
    except SessionExpiredError as e:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This conversation session has expired due to 24 hours of inactivity.",
        ) from e
    except SessionDeletedError as e:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This conversation session has been deleted.",
        ) from e
    except SessionAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this session is denied.",
        ) from e
    except SessionStoreUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    # Completed turn idempotency hit (Migration 0028)
    if lease_result.is_cached and lease_result.cached_response:
        cached = lease_result.cached_response
        return PortalAssistantResponse(
            answer=cached["answer"],
            grounded=cached.get("metadata", {}).get("grounded", True),
        )

    # ZERO DATABASE CONNECTIONS HELD BEYOND THIS POINT!

    # -------------------------------------------------------------------------
    # PHASE 2: Decoupled LLM Inference Window (0 DB Connections Held)
    # -------------------------------------------------------------------------
    token_fence = current_generation_fence.set(lease_result.fence)
    token_owner = current_generation_owner_token.set(lease_result.owner_token)

    try:
        portal_kwargs = {
            "session_id": payload.session_id,
            "query": payload.query,
            "tenant_id": str(tenant.institution_id),
            "user_id": current_user.id,
        }
        if lease_result.history:
            portal_kwargs["history"] = lease_result.history

        gen_task = None
        metered_ctx = None
        if settings.ENABLE_TENANT_AI_QUOTAS or get_current_metered_context() is not None:
            metered_ctx = MeteredRequestContext(
                institution_id=tenant.institution_id,
                user_id=current_user.id,
                endpoint="portal-assistant/chat",
                usage_category="interactive_ai",
                idempotency_key=f"{client_turn_id}:portal_assistant",
            )
        elif settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Tenant AI quotas are disabled or unconfigured in production.",
            )

        async def _run_portal_generation():
            if metered_ctx is not None:
                with metered_execution_context(metered_ctx):
                    res = chat_with_portal_assistant(**portal_kwargs)
                    if inspect.iscoroutine(res):
                        return await res
                    return res
            res = chat_with_portal_assistant(**portal_kwargs)
            if inspect.iscoroutine(res):
                return await res
            return res

        try:
            gen_task = asyncio.create_task(_run_portal_generation())
            SessionTaskTrackingRegistry.register_task(
                institution_id=tenant.institution_id,
                session_id=session_uuid,
                task=gen_task,
                fence=lease_result.fence,
                owner_token=lease_result.owner_token,
            )
            # Enforce router 35.0s shielded deadline
            result = await asyncio.wait_for(asyncio.shield(gen_task), timeout=35.0)
        except TimeoutError as timeout_err:
            logger.warning(f"Router 35.0s timeout tripped during portal generation for session {session_uuid}.")
            # CRIT-3.6-S2-01: Do NOT release the lease prematurely while gen_task is still running.
            # Instead, delegate release to background watcher which waits for gen_task and all
            # session worker threads to achieve full quiescence.
            asyncio.create_task(
                _release_lease_when_quiescent(
                    store_ref=effective_store,
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                    gen_task_ref=gen_task,
                )
            )
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Generation timed out at router deadline.",
            ) from timeout_err
        except WorkerCapacityExhaustedError as pool_err:
            logger.warning(f"Worker capacity exhausted for session {session_uuid}: {pool_err}")
            cleanup_task = asyncio.create_task(
                effective_store.release_generation_lease(
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                )
            )
            try:
                await asyncio.shield(cleanup_task)
            except Exception as cleanup_err:
                logger.error(
                    f"Failed to release lease on worker pool exhaustion: {cleanup_err}",
                    exc_info=True,
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(pool_err),
                headers={"Retry-After": str(pool_err.retry_after)},
            ) from pool_err
        except asyncio.CancelledError:
            logger.info(f"Client disconnected / cancelled during portal generation for session {session_uuid}.")
            if gen_task and not gen_task.done():
                gen_task.cancel()
                try:
                    await gen_task
                except (asyncio.CancelledError, Exception):
                    pass

            cleanup_task = asyncio.create_task(
                _release_lease_when_quiescent(
                    store_ref=effective_store,
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                    gen_task_ref=None,
                )
            )
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
            except Exception as cleanup_err:
                logger.error(f"Failed to release lease on cancellation: {cleanup_err}", exc_info=True)
            raise
        except Exception as gen_err:
            logger.error(f"Generation error in portal session {session_uuid}: {gen_err}", exc_info=True)
            cleanup_task = asyncio.create_task(
                _release_lease_when_quiescent(
                    store_ref=effective_store,
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                    gen_task_ref=gen_task,
                )
            )
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
            except Exception as cleanup_err:
                logger.error(f"Failed to release lease on generation error: {cleanup_err}", exc_info=True)
            raise

        # -------------------------------------------------------------------------
        # PHASE 3: Short-Lived Fenced Commit & Telemetry (< 15ms)
        # -------------------------------------------------------------------------
        is_blocked = result.get("blocked", False)
        is_failed = result.get("status") == "FAILED"

        if is_blocked:
            try:
                await effective_store.commit_turn_atomic(
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    client_turn_id=client_turn_id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                    user_message=payload.query,
                    assistant_message=result["answer"],
                    llm_usage=result.get("llm_usage"),
                    trace_id=_safe_parse_uuid(result.get("trace_id")),
                    status="BLOCKED",
                    metadata={"grounded": False, "block_reason": result.get("block_reason")},
                )
            except FencedCommitPreemptedError as e:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Generation lease was preempted or expired during guardrail processing.",
                ) from e
        elif is_failed:
            await _release_lease_when_quiescent(
                store_ref=effective_store,
                session_id=session_uuid,
                institution_id=tenant.institution_id,
                user_id=current_user.id,
                fence=lease_result.fence,
                owner_token=lease_result.owner_token,
                gen_task_ref=gen_task,
            )
        else:
            try:
                await effective_store.commit_turn_atomic(
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    client_turn_id=client_turn_id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                    user_message=payload.query,
                    assistant_message=result["answer"],
                    llm_usage=result.get("llm_usage"),
                    trace_id=_safe_parse_uuid(result.get("trace_id")),
                    status="COMPLETED",
                    metadata={"grounded": result.get("grounded", False)},
                )
            except FencedCommitPreemptedError as e:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Generation lease was preempted or expired before turn completion.",
                ) from e

        # Telemetry logging inside short-lived scope (<5ms)
        try:
            if settings.ENVIRONMENT != "production" and get_db in request.app.dependency_overrides:
                mock_db = request.app.dependency_overrides[get_db]()
                await log_ai_query(
                    db=mock_db,
                    user_id=current_user.id,
                    endpoint="portal-assistant/chat",
                    query_text=payload.query,
                    was_blocked=is_blocked,
                    block_reason=result.get("block_reason"),
                    institution_id=tenant.institution_id,
                )
                await log_llm_usage(
                    db=mock_db,
                    endpoint="portal-assistant/generate",
                    usage=result.get("llm_usage"),
                    institution_id=tenant.institution_id,
                )
                await log_agent_trace(
                    db=mock_db,
                    trace_id=result["trace_id"],
                    agent_name="portal-assistant",
                    session_id=payload.session_id,
                    trace_steps=result.get("trace_steps", []),
                    institution_id=tenant.institution_id,
                )
            else:
                async with tenant_session_scope(tenant.institution_id) as db:
                    await log_ai_query(
                        db=db,
                        user_id=current_user.id,
                        endpoint="portal-assistant/chat",
                        query_text=payload.query,
                        was_blocked=is_blocked,
                        block_reason=result.get("block_reason"),
                        institution_id=tenant.institution_id,
                    )
                    await log_llm_usage(
                        db=db,
                        endpoint="portal-assistant/generate",
                        usage=result.get("llm_usage"),
                        institution_id=tenant.institution_id,
                    )
                    await log_agent_trace(
                        db=db,
                        trace_id=result["trace_id"],
                        agent_name="portal-assistant",
                        session_id=payload.session_id,
                        trace_steps=result.get("trace_steps", []),
                        institution_id=tenant.institution_id,
                    )
        except Exception as tel_err:
            logger.error(f"Telemetry logging failed for session {session_uuid}: {tel_err}", exc_info=True)

        return PortalAssistantResponse(
            answer=result["answer"],
            grounded=result.get("grounded", False),
        )
    finally:
        current_generation_fence.reset(token_fence)
        current_generation_owner_token.reset(token_owner)


@router.post("/admin-assistant/chat", response_model=AdminAssistantResponse)
async def admin_assistant_chat(
    payload: AdminAssistantRequest,
    request: Request,
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    store: AbstractSessionStore = Depends(get_session_store),
    x_client_turn_id: Annotated[str | None, Header(alias="X-Client-Turn-Id")] = None,
):
    session_uuid = normalize_session_id(payload.session_id)
    client_turn_id = resolve_client_turn_id(payload.client_turn_id, x_client_turn_id)
    effective_store = _resolve_effective_store(request, store)

    # -------------------------------------------------------------------------
    # MANDATORY DIRECTIVES 1 & 2: Unified Session Quiescence Barrier Before DB Lease
    # -------------------------------------------------------------------------
    if not is_session_quiescent_unified(tenant.institution_id, session_uuid):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Previous generation workers are still active for this session. Please retry shortly.",
            headers={"Retry-After": "1"},
        )

    # -------------------------------------------------------------------------
    # PHASE 1: Short-Lived Lease Reservation (< 15ms)
    # -------------------------------------------------------------------------
    try:
        await effective_store.get_or_create_session(
            session_id=session_uuid,
            institution_id=tenant.institution_id,
            user_id=current_user.id,
            agent_name="admin_assistant",
            title="Admin Assistant Conversation",
        )
        lease_result = await effective_store.reserve_generation_lease(
            session_id=session_uuid,
            institution_id=tenant.institution_id,
            user_id=current_user.id,
            client_turn_id=client_turn_id,
            history_limit=10,
        )
    except SessionConcurrencyError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
            headers={"Retry-After": str(e.retry_after)},
        ) from e
    except SessionExpiredError as e:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This conversation session has expired due to 24 hours of inactivity.",
        ) from e
    except SessionDeletedError as e:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This conversation session has been deleted.",
        ) from e
    except SessionAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this session is denied.",
        ) from e
    except SessionStoreUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    # Completed turn idempotency hit
    if lease_result.is_cached and lease_result.cached_response:
        cached = lease_result.cached_response
        return AdminAssistantResponse(
            answer=cached["answer"],
            tools_used=cached.get("metadata", {}).get("tools_used", []),
        )

    # -------------------------------------------------------------------------
    # PHASE 2: Decoupled LLM Inference Window (0 DB Connections Held)
    # -------------------------------------------------------------------------
    token_fence = current_generation_fence.set(lease_result.fence)
    token_owner = current_generation_owner_token.set(lease_result.owner_token)

    try:
        admin_kwargs = {
            "session_id": payload.session_id,
            "query": payload.query,
            "tenant_id": str(tenant.institution_id),
            "user_id": current_user.id,
            "fence": lease_result.fence,
            "owner_token": lease_result.owner_token,
        }
        if lease_result.history:
            admin_kwargs["history"] = lease_result.history

        gen_task = None
        metered_ctx = None
        if settings.ENABLE_TENANT_AI_QUOTAS or get_current_metered_context() is not None:
            metered_ctx = MeteredRequestContext(
                institution_id=tenant.institution_id,
                user_id=current_user.id,
                endpoint="admin-assistant/chat",
                usage_category="interactive_ai",
                idempotency_key=f"{client_turn_id}:admin_assistant",
            )
        elif settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Tenant AI quotas are disabled or unconfigured in production.",
            )

        async def _run_admin_generation():
            if metered_ctx is not None:
                with metered_execution_context(metered_ctx):
                    res = chat_with_admin_assistant(**admin_kwargs)
                    if inspect.iscoroutine(res):
                        return await res
                    return res
            res = chat_with_admin_assistant(**admin_kwargs)
            if inspect.iscoroutine(res):
                return await res
            return res

        try:
            gen_task = asyncio.create_task(_run_admin_generation())
            SessionTaskTrackingRegistry.register_task(
                institution_id=tenant.institution_id,
                session_id=session_uuid,
                task=gen_task,
                fence=lease_result.fence,
                owner_token=lease_result.owner_token,
            )
            # Enforce router 35.0s shielded deadline
            result = await asyncio.wait_for(asyncio.shield(gen_task), timeout=35.0)
        except TimeoutError as timeout_err:
            logger.warning(f"Router 35.0s timeout tripped during admin generation for session {session_uuid}.")
            # CRIT: Do NOT release lease prematurely while gen_task is still running.
            # Instead, delegate release to background watcher which waits for gen_task and all
            # session worker threads to achieve full quiescence.
            asyncio.create_task(
                _release_lease_when_quiescent(
                    store_ref=effective_store,
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                    gen_task_ref=gen_task,
                )
            )
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Generation timed out at router deadline.",
            ) from timeout_err
        except WorkerCapacityExhaustedError as pool_err:
            logger.warning(f"Worker capacity exhausted for admin session {session_uuid}: {pool_err}")
            cleanup_task = asyncio.create_task(
                effective_store.release_generation_lease(
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                )
            )
            try:
                await asyncio.shield(cleanup_task)
            except Exception as cleanup_err:
                logger.error(
                    f"Failed to release lease on worker pool exhaustion: {cleanup_err}",
                    exc_info=True,
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(pool_err),
                headers={"Retry-After": str(pool_err.retry_after)},
            ) from pool_err
        except asyncio.CancelledError:
            logger.info(f"Client disconnected / cancelled during admin generation for session {session_uuid}.")
            if gen_task and not gen_task.done():
                gen_task.cancel()
                try:
                    await gen_task
                except (asyncio.CancelledError, Exception):
                    pass

            cleanup_task = asyncio.create_task(
                _release_lease_when_quiescent(
                    store_ref=effective_store,
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                    gen_task_ref=None,
                )
            )
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
            except Exception as cleanup_err:
                logger.error(f"Failed to release lease on cancellation: {cleanup_err}", exc_info=True)
            raise
        except Exception as gen_err:
            logger.error(f"Generation error in admin session {session_uuid}: {gen_err}", exc_info=True)
            cleanup_task = asyncio.create_task(
                _release_lease_when_quiescent(
                    store_ref=effective_store,
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                    gen_task_ref=gen_task,
                )
            )
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
            except Exception as cleanup_err:
                logger.error(f"Failed to release lease on admin error: {cleanup_err}", exc_info=True)
            raise

        # -------------------------------------------------------------------------
        # PHASE 3: Short-Lived Fenced Commit & Telemetry (< 15ms)
        # -------------------------------------------------------------------------
        is_blocked = result.get("blocked", False)
        is_failed = result.get("status") == "FAILED"

        if is_blocked:
            try:
                await effective_store.commit_turn_atomic(
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    client_turn_id=client_turn_id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                    user_message=payload.query,
                    assistant_message=result["answer"],
                    llm_usage=result.get("llm_usage"),
                    trace_id=_safe_parse_uuid(result.get("trace_id")),
                    status="BLOCKED",
                    metadata={"tools_used": [], "block_reason": result.get("block_reason")},
                )
            except FencedCommitPreemptedError as e:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Generation lease was preempted or expired during admin guardrail evaluation.",
                ) from e
        elif is_failed:
            await _release_lease_when_quiescent(
                store_ref=effective_store,
                session_id=session_uuid,
                institution_id=tenant.institution_id,
                user_id=current_user.id,
                fence=lease_result.fence,
                owner_token=lease_result.owner_token,
                gen_task_ref=gen_task,
            )
        else:
            try:
                await effective_store.commit_turn_atomic(
                    session_id=session_uuid,
                    institution_id=tenant.institution_id,
                    user_id=current_user.id,
                    client_turn_id=client_turn_id,
                    fence=lease_result.fence,
                    owner_token=lease_result.owner_token,
                    user_message=payload.query,
                    assistant_message=result["answer"],
                    llm_usage=result.get("llm_usage"),
                    trace_id=_safe_parse_uuid(result.get("trace_id")),
                    status="COMPLETED",
                    metadata={"tools_used": result.get("tools_used", [])},
                )
            except FencedCommitPreemptedError as e:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Generation lease was preempted or expired before admin turn completion.",
                ) from e

        # Telemetry logging
        try:
            if settings.ENVIRONMENT != "production" and get_db in request.app.dependency_overrides:
                mock_db = request.app.dependency_overrides[get_db]()
                await log_ai_query(
                    db=mock_db,
                    user_id=current_user.id,
                    endpoint="admin-assistant/chat",
                    query_text=payload.query,
                    was_blocked=is_blocked,
                    block_reason=result.get("block_reason"),
                    institution_id=tenant.institution_id,
                )
                for endpoint_tag, usage in result.get("llm_usage", {}).items():
                    await log_llm_usage(
                        db=mock_db,
                        endpoint=endpoint_tag,
                        usage=usage,
                        institution_id=tenant.institution_id,
                    )
                await log_agent_trace(
                    db=mock_db,
                    trace_id=result["trace_id"],
                    agent_name="admin-assistant",
                    session_id=payload.session_id,
                    trace_steps=result.get("trace_steps", []),
                    institution_id=tenant.institution_id,
                )
            else:
                async with tenant_session_scope(tenant.institution_id) as db:
                    await log_ai_query(
                        db=db,
                        user_id=current_user.id,
                        endpoint="admin-assistant/chat",
                        query_text=payload.query,
                        was_blocked=is_blocked,
                        block_reason=result.get("block_reason"),
                        institution_id=tenant.institution_id,
                    )
                    for endpoint_tag, usage in result.get("llm_usage", {}).items():
                        await log_llm_usage(
                            db=db,
                            endpoint=endpoint_tag,
                            usage=usage,
                            institution_id=tenant.institution_id,
                        )
                    await log_agent_trace(
                        db=db,
                        trace_id=result["trace_id"],
                        agent_name="admin-assistant",
                        session_id=payload.session_id,
                        trace_steps=result.get("trace_steps", []),
                        institution_id=tenant.institution_id,
                    )
        except Exception as tel_err:
            logger.error(f"Telemetry logging failed for admin session {session_uuid}: {tel_err}", exc_info=True)

        return AdminAssistantResponse(
            answer=result["answer"],
            tools_used=result.get("tools_used", []),
        )
    finally:
        current_generation_fence.reset(token_fence)
        current_generation_owner_token.reset(token_owner)
