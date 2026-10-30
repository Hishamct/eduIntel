# ADR 0001: Modular Monolith Architecture Pattern

- **Status**: Accepted
- **Deciders**: EduIntel Engineering Team
- **Date**: 2026-10-15

---

## Context and Problem Statement

EduIntel is designed to unify three operational and academic portals (Student, Teacher, Admin) with AI workflows including OCR, RAG-based doubt resolution, machine learning diagnostics, and autonomous agents. 

We needed to decide whether to architect the backend as:
1. A **Microservices Architecture** (independent services for auth, portals, ml, rag, admin), or
2. A **Traditional Monolith** (single repository with tangled shared dependencies), or
3. A **Modular Monolith** (single deployable codebase with strict internal domain package boundaries).

Premature decomposition into microservices introduces massive operational complexity: distributed transactions, network latency between internal services, API versioning overhead, distributed tracing requirements, and multi-container deployment burdens on a small engineering team. Conversely, an unstructured monolith tends toward spaghetti dependencies, making future service extraction nearly impossible.

---

## Decision Outcome

We chose to build EduIntel as a **Modular Monolith**.

The application is structured into 16 discrete, self-contained domain packages under `backend/app/` across four tiers (Shared, Portal, Intelligence, Cross-Cutting). 

### Rules Enforced:
- Each module encapsulates its own routers, schemas, models, and domain logic.
- Cross-module communication is permitted only through designated service interfaces or public utility functions.
- Direct database schema tampering across domains is prohibited.
- Shared infrastructure (DB connection, config, base models) is centralized in `backend/app/core/`.

---

## Consequences

### Positive Consequences
- **Single Deployment Artifact**: The entire backend compiles and deploys as a single Uvicorn/FastAPI process, simplifying CI/CD, local development, and single-node hosting.
- **In-Memory Performance**: Inter-module calls execute as in-memory Python function invocations without network serialization overhead or RPC latency.
- **Straightforward Refactoring**: Moving code between modules does not require breaking network API contracts.
- **Future Extraction Path**: Because each module maintains clean boundaries, heavy AI services (such as OCR or ML training) can be extracted into dedicated workers or microservices in future phases without rewriting the core business domain.

### Negative Consequences
- **Process Fate Sharing**: A crash or CPU-intensive thread in one module (e.g., synchronous Tesseract OCR or PDF parsing) can impact the responsiveness of unrelated endpoints if not carefully isolated.
- **Shared Database Connection Pool**: All modules compete for connections in the same PostgreSQL connection pool.

---

## Alternatives Considered

- **Microservices**: Rejected due to high operational complexity, distributed state overhead, and unnecessary infrastructure costs for single-institution deployment.
- **Unstructured Monolith**: Rejected because mixing AI logic directly into portal routes prevents code reusability and impedes team scalability.

