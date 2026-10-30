# ADR 0003: ChromaDB as Embedded Persistent Vector Store

- **Status**: Accepted
- **Deciders**: EduIntel Engineering Team
- **Date**: 2026-10-18

---

## Context and Problem Statement

EduIntel requires vector storage and semantic search capabilities for two distinct workloads:
1. **Portal Help Documents**: Enabling the Portal Assistant to retrieve user guides, workflow instructions, and FAQs.
2. **Academic Study Materials**: Enabling students and teachers to retrieve context-specific textbook chapters, lecture notes, and formula sheets for Socratic doubt resolution.

We evaluated potential vector persistence solutions:
- Cloud-hosted managed vector services (Pinecone, Weaviate Cloud, Qdrant Cloud).
- In-database relational vector extensions (`pgvector` in PostgreSQL).
- Self-hosted / embedded vector engines (ChromaDB, FAISS).

Constraints included zero external cloud cost for local development, ease of setup in containerized/local environments, persistence across restarts, and Python native integration.

---

## Decision Outcome

We selected **ChromaDB** using its local persistent DuckDB/SQLite + HNSW storage engine (`PersistentClient`).

### Implementation Strategy:
- ChromaDB is initialized locally in `backend/chroma_data/` via [`backend/app/rag/service.py`](file:///home/dell/projects/eduIntel/backend/app/rag/service.py).
- Two segregated collections are maintained:
  - `portal_help_docs`: System navigation and help documentation.
  - `study_materials`: Educational notes, syllabus breakdowns, and lecture PDFs.
- Vector embeddings (768 dimensions) are computed via Google Gemini's `gemini-embedding-001` model.

---

## Consequences

### Positive Consequences
- **Zero Cloud Infrastructure Cost**: Runs entirely on the host filesystem without incurring vector DB SaaS subscription fees.
- **Local Dev Autonomy**: Developers and automated tests run against ChromaDB locally without requiring network access or external mock servers.
- **Python-Native API**: ChromaDB's Python client integrates directly into the FastAPI application process without network latency between app and vector index.

### Negative Consequences
- **Single-Node Filesystem Bound**: In multi-instance distributed deployments, a local filesystem-backed ChromaDB cannot be shared across multiple backend worker replicas without transitioning to ChromaDB's client/server mode or a network-attached store.
- **Backup Complexity**: Backups require copying the persistent directory (`backend/chroma_data/`) in sync with PostgreSQL snapshots.

---

## Alternatives Considered

- **PostgreSQL `pgvector`**: Strong candidate for unified relational and vector queries. Deferred for initial implementation because ChromaDB provided an out-of-the-box Python abstraction with pre-built collection indexing, but pgvector remains an attractive future target during the cloud DB migration (Phase 3).
- **Pinecone**: Rejected due to subscription costs, external network latency, and vendor lock-in during early local development.
- **FAISS (In-Memory)**: Rejected because raw FAISS requires custom persistence wrappers and metadata management, whereas ChromaDB handles metadata filtering natively.

