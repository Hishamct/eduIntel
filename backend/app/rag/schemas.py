from pydantic import BaseModel


class CollectionStatus(BaseModel):
    name: str
    document_count: int

class DebugQueryResult(BaseModel):
    chunk_text: str
    distance: float
    metadata: dict

class RagQueryRequest(BaseModel):
    query: str
    collection: str = "study_materials"  # or "portal_help_docs"
    n_results: int = 3


class RagSource(BaseModel):
    chunk_text: str
    title: str
    subject: str


class RagQueryResponse(BaseModel):
    answer: str
    sources: list[RagSource]