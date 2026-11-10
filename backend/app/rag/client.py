import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from google import genai

from app.core.config import settings

CHROMA_PERSIST_DIR = "chroma_data"

_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
_genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)


class GeminiEmbeddingFunction(EmbeddingFunction):
    """
    Custom embedding function using Gemini's embedding model.
    Governed by Stage 7.3 MeteredAIService.
    """

    def __call__(self, input: Documents) -> Embeddings:
        from app.core.llm_client import (
            QuotaSystemDisabledError,
            UnmeteredAIInvocationError,
        )
        from app.observability.quota.adapter import (
            get_current_metered_context,
            get_metered_ai_service,
            run_metered_coro_sync,
        )

        ctx = get_current_metered_context()
        if ctx is not None:
            service = get_metered_ai_service()
            result = run_metered_coro_sync(service.execute_embedding_generation(ctx, list(input)))
            return result.embeddings

        is_production = getattr(settings, "is_production", False) or settings.ENVIRONMENT == "production"
        is_test_bypass = not is_production and getattr(settings, "ALLOW_UNMETERED_AI_TEST_BYPASS", False)

        if not is_test_bypass:
            if not settings.ENABLE_TENANT_AI_QUOTAS:
                raise QuotaSystemDisabledError(
                    "Embedding generation rejected: ENABLE_TENANT_AI_QUOTAS is disabled and unmetered bypass is forbidden."
                )
            raise UnmeteredAIInvocationError(
                "Embedding generation rejected: No verified MeteredRequestContext is active in the execution context."
            )

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
