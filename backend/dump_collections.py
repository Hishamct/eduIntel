from app.rag.client import get_portal_help_collection, get_study_materials_collection

def dump(collection, label):
    data = collection.get(include=["documents", "metadatas"])
    print(f"\n=== {label}: {len(data['ids'])} chunks ===")
    for doc, meta in zip(data["documents"], data["metadatas"]):
        title = meta.get("title", "—")
        print(f"\n[{title}] {meta}")
        print(doc[:300], "..." if len(doc) > 300 else "")

dump(get_portal_help_collection(), "portal_help_docs")
dump(get_study_materials_collection(), "study_materials")