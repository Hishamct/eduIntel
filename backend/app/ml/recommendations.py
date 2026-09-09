"""
Given a student's diagnosed weak topics, retrieves and synthesizes targeted
study recommendations from the study_materials RAG collection. Reuses the
existing generic retrieve_and_generate function from app.rag.service rather
than duplicating retrieval logic — consistent with how the Portal/Admin
Assistants already consume RAG.

Handles subject naming inconsistency in real teacher-uploaded materials
(e.g. "Maths", "physics") via normalization, since exact-match subject
filtering isn't used here (retrieve_and_generate does pure semantic search
across the whole collection, not a subject-filtered query) — but normalization
is still applied to the query text itself, so search terms match canonical
subject naming as closely as possible.
"""
from app.rag.service import retrieve_and_generate

SUBJECT_ALIASES = {
    "maths": "Mathematics",
    "math": "Mathematics",
    "mathematics": "Mathematics",
    "physics": "Physics",
    "chemistry": "Chemistry",
    "computer science": "Computer Science",
    "cs": "Computer Science",
}


def normalize_subject_for_query(raw_subject: str) -> str:
    key = raw_subject.strip().lower()
    return SUBJECT_ALIASES.get(key, raw_subject.strip().title())


def get_recommendations_for_weak_topics(top_weak_topics: list[dict], n_results_per_topic: int = 3) -> list[dict]:
    recommendations = []

    for weak_topic in top_weak_topics:
        subject = weak_topic["subject"]
        topic = weak_topic["topic"]
        readable_subject = normalize_subject_for_query(subject)

        query = f"Explain the key concepts and common problem areas in {topic} for {readable_subject}, and what a student struggling with this topic should focus on."

        result = retrieve_and_generate(
            query=query,
            collection_name="study_materials",
            n_results=n_results_per_topic,
        )

        recommendations.append({
            "subject": subject,
            "topic": topic,
            "recommendation": result["answer"],
            "sources": [
                {"title": s["title"], "subject": s["subject"]}
                for s in result["sources"]
            ],
        })

    return recommendations