from app.rag.client import get_study_materials_collection
from app.rag.client import _genai_client

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Splits text into overlapping chunks so retrieval can return
    precise, relevant sections rather than whole documents.
    """
    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap

    return chunks


def ingest_study_material(
    material_id: str,
    subject: str,
    title: str,
    extracted_text: str | None,
) -> dict:
    """
    Embeds a study material's extracted text into the study_materials
    ChromaDB collection, chunked for retrieval. 
    """
    if not extracted_text or not extracted_text.strip():
        return {"ingested": False, "reason": "no extracted text available"}

    chunks = chunk_text(extracted_text)
    if not chunks:
        return {"ingested": False, "reason": "no chunks produced"}

    collection = get_study_materials_collection()

    ids = [f"{material_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "material_id": str(material_id),
            "subject": subject,
            "title": title,
            "chunk_index": i,
        }
        for i in range(len(chunks))
    ]

    collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)

    return {"ingested": True, "chunk_count": len(chunks)}

def debug_query_study_materials(query: str, collection_name: str = "study_materials", n_results: int = 3) -> list[dict]:
    """
    TEMPORARY debug helper — runs a raw similarity search against
    the given collection and returns matches with their distance scores.
    
    """
    from app.rag.client import get_collection_by_name

    collection = get_collection_by_name(collection_name)
    results = collection.query(query_texts=[query], n_results=n_results)

    matches = []
    documents = results["documents"][0]
    distances = results["distances"][0]
    metadatas = results["metadatas"][0]

    for doc, dist, meta in zip(documents, distances, metadatas):
        matches.append({
            "chunk_text": doc,
            "distance": dist,
            "metadata": meta,
        })

    return matches
    

# from google.genai import types

def retrieve_and_generate(query: str, collection_name: str = "study_materials", n_results: int = 3) -> dict:
    """
    Core reusable RAG function: retrieves relevant chunks from the given
    collection, then asks Gemini to answer the query grounded in that context.

    Generic by design — collection_name lets any future agent (Contextual
    Portal Assistant, Admin AI Assistant) point this at a different corpus
    without duplicating retrieval or generation logic.
    """
    from app.rag.client import get_collection_by_name  # avoid circular import at module load

    collection = get_collection_by_name(collection_name)
    results = collection.query(query_texts=[query], n_results=n_results)

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]

    if not documents:
        return {
            "answer": "I couldn't find any relevant material to answer that question.",
            "sources": [],
        }

    context_blocks = []
    sources = []
    for doc, meta in zip(documents, metadatas):
        context_blocks.append(f"[Source: {meta.get('title', 'Unknown')}]\n{doc}")
        sources.append({
            "chunk_text": doc,
            "title": meta.get("title", "Unknown"),
            "subject": meta.get("subject", "Unknown"),
        })

    context_text = "\n\n---\n\n".join(context_blocks)

    prompt = f"""You are a study assistant answering a student's or teacher's question using ONLY the reference material provided below.

Reference material:
{context_text}

Question: {query}

Instructions:
- Answer using only the information in the reference material above.
- If the reference material does not contain enough information to answer, say so clearly instead of guessing.
- Keep your answer concise and directly relevant to the question."""

    response = _genai_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )

    return {
        "answer": response.text,
        "sources": sources,
    }