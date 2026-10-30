# EduIntel AI

**Agentic AI-Powered Educational Decision Intelligence Platform**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg?logo=python)](https://python.org)
[![React](https://img.shields.io/badge/React-18.3.1-61DAFB.svg?logo=react)](https://reactjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1.svg?logo=postgresql)](https://postgresql.org)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-0.5.0-FC4C02.svg)](https://trychroma.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.1.0-FF6F00.svg)](https://langchain.com)

---

## 1. Executive Summary

**EduIntel AI** is a modular monolith, decision intelligence platform engineered for coaching institutes, competitive exam academies, and schools. It bridges the operational and academic divide by unifying three role-specific web portals (**Student**, **Teacher**, **Admin**) with an enterprise AI pipeline:

- **Automated Homework Ingestion & OCR**: Optical Character Recognition (`pytesseract` and `pypdf`) transforms handwritten homework submissions and PDF notes into indexed, searchable text.
- **Socratic RAG Assistance**: Retrieval-Augmented Generation backed by ChromaDB and Google Gemini embeddings (`gemini-embedding-001`) powers a doubt resolution tutor that uses Socratic questioning instead of providing direct homework solutions.
- **Machine Learning Academic Diagnostics**: XGBoost classification models predict student at-risk status and weak subject topics, supplemented with SHAP tree explainability to provide teachers with actionable intervention recommendations.
- **Agentic LangGraph Assistants**: Stateful AI assistants automate administrative reporting, fee reconciliations, and academic data queries through controlled, parameterized tools.
- **Security & Privacy Guardrails**: In-flight PII redaction (masking Aadhaar numbers, phone numbers, emails, IPs, and credit cards), regex-based prompt injection filtering, and append-only audit logging.

---

## 2. High-Level Architecture

The platform follows a **Modular Monolith** architecture where the frontend Single Page Application (SPA) communicates via JSON REST APIs with a FastAPI backend. Data persistence is decoupled across relational, vector, artifact, and ML experiment storage.

```mermaid
flowchart TD
    subgraph ClientLayer ["Client Layer (React 18 SPA)"]
        StudentUI["Student Portal (Doubts, Homework, Materials)"]
        TeacherUI["Teacher Portal (Grading, Progress, Exams)"]
        AdminUI["Admin Portal (Timetables, Salaries, Fees, Risk)"]
    end

    subgraph Gateway ["Reverse Proxy & Web Server"]
        Proxy["Caddy / Vite Dev Server (:80 / :5173)"]
    end

    subgraph AppLayer ["Application Tier (FastAPI Modular Monolith)"]
        CoreAuth["Shared Tier: core, auth, users"]
        Portals["Portal Tier: student, teacher, admin, announcements"]
        Intel["Intelligence Tier: ocr, rag, ml, agents, mcp, reports"]
        CrossCut["Cross-Cutting Tier: guardrails, observability"]
    end

    subgraph DataLayer ["Data & Persistence Tier"]
        PG[("PostgreSQL 16 (Relational Engine)")]
        Chroma[("ChromaDB (Vector Store)")]
        MLflowDB[("MLflow SQLite (Model Tracking)")]
        Storage[("Local File Storage (Uploads & Artifacts)")]
    end

    subgraph ExternalAI ["External AI Services"]
        Gemini["Google Gemini API (LLM & Embeddings)"]
        Groq["Groq API (Fallback LLM)"]
    end

    StudentUI --> Proxy
    TeacherUI --> Proxy
    AdminUI --> Proxy

    Proxy --> AppLayer

    CoreAuth --> PG
    Portals --> PG
    Intel --> PG
    Intel --> Chroma
    Intel --> MLflowDB
    Intel --> Storage
    Intel --> ExternalAI
    CrossCut --> PG
```

---

## 3. Technology Stack

| Layer | Technologies | Purpose |
|---|---|---|
| **Frontend** | React 18, Vite, React Router v6, Axios, Lucide Icons | Responsive role-based portals (custom CSS design system) |
| **Backend API** | Python 3.12, FastAPI (AsyncIO), Pydantic v2 | High-throughput, async REST API layer (57 endpoints) |
| **Relational DB** | PostgreSQL 16, SQLAlchemy 2.0 (Async), Alembic | 19 relational tables, transactions, migrations, and audit trails |
| **Vector DB** | ChromaDB (HNSW persistent storage) | Dual vector collections for help docs and study materials |
| **AI / LLM** | Google Gemini (`gemini-3.6-flash`, `gemini-embedding-001`), Groq API fallback (`openai/gpt-oss-120b`) | Primary LLM inference, embeddings, rate-limit fallback |
| **Agent Orchestration**| LangGraph 0.1.0, LangChain | Stateful graph agents for admin queries and portal documentation |
| **Machine Learning**| XGBoost, Scikit-Learn, SHAP, MLflow | At-risk student classification, weak topic prediction, explainability |
| **Document Processing**| PyTesseract, PyPDF, Pillow | OCR for handwritten homework, PDF text parsing |
| **Infrastructure** | Docker, Docker Compose, Caddy | Containerized PostgreSQL, production reverse proxy, HTTPS |

---

## 4. Quick Start & Local Setup

### Prerequisites
- **Python**: 3.12+
- **Node.js**: 20+ (with npm)
- **Docker & Docker Compose**: For local PostgreSQL 16
- **Tesseract OCR**: (Optional) `sudo apt install tesseract-ocr`

### 1. Clone & Configure Environment
```bash
git clone https://github.com/your-org/eduintel.git
cd eduintel

# Create backend .env file
cat <<EOF > backend/.env
DATABASE_URL=postgresql+asyncpg://eduintel:eduintel_dev@localhost:5432/eduintel
JWT_SECRET_KEY=your_development_secret_key_at_least_32_chars
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=43200
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
EOF
```

### 2. Launch Local Database & Run Migrations
```bash
cd backend
docker compose up -d

# Verify PostgreSQL is accepting connections on 5432
docker compose ps
```

### 3. Initialize Python Environment & Run Backend
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Apply Alembic schema migrations
alembic upgrade head

# Launch FastAPI development server
uvicorn app.main:app --reload --port 8000
```
- API Base: `http://localhost:8000`
- Interactive Swagger UI: `http://localhost:8000/docs`
- ReDoc Documentation: `http://localhost:8000/redoc`

### 4. Launch React Frontend
In a new terminal window:
```bash
cd frontend
npm install
npm run dev
```
- Web Application: `http://localhost:5173`

---

## 5. Comprehensive Documentation Index

All technical, architectural, operational, and development documentation is maintained under the [`docs/`](docs/README.md) directory:

- 📖 **[Master Documentation Index](docs/README.md)**: Entry point for the full documentation corpus.
- 🎯 **[Project Scope & Purpose](docs/project/purpose-and-scope.md)**: Problem statement, user personas, and acceptance criteria.
- 📊 **[Feature Matrix](docs/project/feature-matrix.md)**: Exhaustive implementation status of all 16 modules and 21 UI pages.
- 🏛️ **[System Architecture](docs/architecture/system-overview.md)**: In-depth C4 models, data topology, and architectural patterns.
- 🧩 **[Backend Modules](docs/architecture/backend-modules.md)**: Detailed breakdown of the 16 modules across 4 functional tiers.
- 📜 **[Architecture Decision Records (ADRs)](docs/architecture/adr/)**: Architectural decisions (Modular monolith, Async SQLAlchemy, ChromaDB, LangGraph, Multi-tenancy, RDS).
- 🔌 **[API Route Inventory & Conventions](docs/api/route-inventory.md)**: Complete catalog of 57 API endpoints with authentication scopes.
- 🗄️ **[Database Schema & ERD](docs/database/schema-and-erd.md)**: Detailed schema for 19 PostgreSQL tables and Alembic migration history.
- 🛡️ **[Security, RBAC & Guardrails](docs/security/auth-and-rbac.md)**: JWT lifecycle, role enforcement, PII redaction, and prompt injection defense.
- 🤖 **[AI, RAG & Machine Learning](docs/ai/rag-architecture.md)**: Vector retrieval, LangGraph agents, XGBoost models, and SHAP explainability.
- 🧪 **[Testing Strategy](docs/testing/testing-strategy.md)**: Pytest harness, test inventory, and quality assurance gates.
- 🚀 **[Deployment & Operations](docs/deployment/deployment-topology.md)**: Docker configurations, deployment topology (historical & proposed), backups, and observability.

---

## 6. Production-Readiness Roadmap

The project is tracking through the established 9-phase production-readiness roadmap on branch `develop/production-readiness`:

| Phase | Title | Status |
|:---:|---|:---:|
| **0** | Repository Audit and Baseline | ✅ **Completed** |
| **1** | Documentation and Architecture | 🔄 **In Progress (Final Review)** |
| **2** | Security, Authorization, and Privacy | ⏳ Planned |
| **3** | Database Integrity and Recovery | ⏳ Planned |
| **4** | Testing and CI/CD | ⏳ Planned |
| **5** | AI, RAG, Agents, and ML Hardening | ⏳ Planned |
| **6** | Background Processing and Resilience | ⏳ Planned |
| **7** | Observability and Performance | ⏳ Planned |
| **8** | Production Deployment and Pilot | ⏳ Planned |

---

## 7. License & Attribution

EduIntel AI is an educational technology initiative. All rights reserved.
Developed by the EduIntel Engineering Team.

