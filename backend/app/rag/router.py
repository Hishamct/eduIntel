import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_trusted_tenant_id
from app.observability.service import log_llm_usage, log_socratic_redirect
from app.rag.client import get_portal_help_collection, get_study_materials_collection
from app.rag.schemas import (
    CollectionStatus,
    DebugQueryResult,
    RagQueryRequest,
    RagQueryResponse,
)
from app.rag.service import debug_query_study_materials, retrieve_and_generate
from app.users.dependencies import get_current_user, require_role
from app.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


@router.get("/collections", response_model=list[CollectionStatus])
async def list_collection_status():
    portal_help = get_portal_help_collection()
    study_materials = get_study_materials_collection()

    return [
        CollectionStatus(name="portal_help_docs", document_count=portal_help.count()),
        CollectionStatus(
            name="study_materials", document_count=study_materials.count()
        ),
    ]


@router.post("/query", response_model=RagQueryResponse)
async def query_rag(
    payload: RagQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    trusted_tenant_id = get_trusted_tenant_id(current_user)

    if payload.collection == "study_materials" and not trusted_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context required for study materials access",
        )

    try:
        result = retrieve_and_generate(
            query=payload.query,
            collection_name=payload.collection,
            n_results=payload.n_results,
            institution_id=trusted_tenant_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error during RAG retrieve_and_generate")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="RAG retrieval service temporarily unavailable. Please try again later.",
        ) from None

    # Guardrail: log the anti-cheating outcome to the audit trail.
    await log_socratic_redirect(
        db=db,
        user_id=current_user.id,
        endpoint="rag/query",
        query_text=payload.query,
        was_socratic_redirected=result.get("socratic_mode", False),
        socratic_trigger_pattern=result.get("cheating_pattern"),
    )
    await log_llm_usage(db=db, endpoint="rag/query", usage=result.get("llm_usage"))

    return result


@router.get("/debug-query", response_model=list[DebugQueryResult])
async def debug_query(
    q: str,
    collection: str = "study_materials",
    n_results: int = 3,
    current_user: User = Depends(require_role("admin")),
):
    trusted_tenant_id = get_trusted_tenant_id(current_user)

    if collection == "study_materials" and not trusted_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context required for study materials access",
        )

    try:
        return debug_query_study_materials(
            query=q,
            collection_name=collection,
            n_results=n_results,
            institution_id=trusted_tenant_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error during debug_query_study_materials")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="RAG retrieval service temporarily unavailable. Please try again later.",
        ) from None
