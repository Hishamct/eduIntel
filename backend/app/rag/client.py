import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from google import genai
from app.core.config import settings

CHROMA_PERSIST_DIR = "chroma_data"

_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
_genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)


class GeminiEmbeddingFunction(EmbeddingFunction):
    """
    Custom embedding function using Gemini's free-tier embedding model.
    ChromaDB calls this automatically whenever documents are added or queried.
    """

    def __call__(self, input: Documents) -> Embeddings:
        response = _genai_client.models.embed_content(
            model="gemini-embedding-001",
            contents=input,
        )
        return [e.values for e in response.embeddings]


_embedding_fn = GeminiEmbeddingFunction()


def get_portal_help_collection():
    return _client.get_or_create_collection(
        name="portal_help_docs",
        embedding_function=_embedding_fn,
    )


def get_study_materials_collection():
    return _client.get_or_create_collection(
        name="study_materials",
        embedding_function=_embedding_fn,
    )

def get_collection_by_name(name: str):
    if name == "portal_help_docs":
        return get_portal_help_collection()
    elif name == "study_materials":
        return get_study_materials_collection()
    else:
        raise ValueError(f"Unknown collection: {name}")