from fastapi import APIRouter, Depends
from app.rag.client import get_portal_help_collection, get_study_materials_collection
from app.rag.schemas import CollectionStatus, RagQueryRequest, RagQueryResponse, DebugQueryResult
from app.rag.service import retrieve_and_generate, debug_query_study_materials
from app.users.dependencies import get_current_user
from app.users.models import User

router = APIRouter(prefix="/rag", tags=["rag"])


@router.get("/collections", response_model=list[CollectionStatus])
async def list_collection_status():
    portal_help = get_portal_help_collection()
    study_materials = get_study_materials_collection()

    return [
        CollectionStatus(name="portal_help_docs", document_count=portal_help.count()),
        CollectionStatus(name="study_materials", document_count=study_materials.count()),
    ]


@router.post("/query", response_model=RagQueryResponse)
async def query_rag(
    payload: RagQueryRequest,
    current_user: User = Depends(get_current_user),
):
    result = retrieve_and_generate(
        query=payload.query,
        collection_name=payload.collection,
        n_results=payload.n_results,
    )
    return result


@router.get("/debug-query", response_model=list[DebugQueryResult])
async def debug_query(
    q: str,
    collection: str = "study_materials",
    n_results: int = 3,
    current_user: User = Depends(get_current_user),
):
    return debug_query_study_materials(query=q, collection_name=collection, n_results=n_results)