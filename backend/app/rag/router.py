from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.observability.service import log_llm_usage, log_socratic_redirect
from app.rag.client import get_portal_help_collection, get_study_materials_collection
from app.rag.schemas import (
    CollectionStatus,
    DebugQueryResult,
    RagQueryRequest,
    RagQueryResponse,
)
from app.rag.service import debug_query_study_materials, retrieve_and_generate
from app.users.dependencies import get_current_user
from app.users.models import User

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
    result = retrieve_and_generate(
        query=payload.query,
        collection_name=payload.collection,
        n_results=payload.n_results,
    )

    # Guardrail: log the anti-cheating outcome to the audit trail.
    # result only carries socratic_mode/cheating_pattern for the
    # study_materials collection (see retrieve_and_generate) — for
    # portal_help_docs these keys are absent, so default them to the
    # "guard didn't apply here" values rather than skipping the log
    # entirely, so every query still gets one audit row.
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
    current_user: User = Depends(get_current_user),
):
    return debug_query_study_materials(
        query=q, collection_name=collection, n_results=n_results
    )
