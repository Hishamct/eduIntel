# EduIntel AI

**Agentic AI-powered Decision Intelligence Platform for Coaching Institutes and Schools**
Capstone Project — Modular Monolith Architecture (15 modules)

---

## 1. Overview

EduIntel AI is a platform combining three role-based portals (Student, Teacher, Admin), OCR, a RAG-based assistant layer, ML-driven at-risk/weak-topic prediction, and LangGraph-orchestrated agents — built as a **modular monolith**: one deployed application, with each module developed as a self-contained package with clear internal boundaries, so AI-facing modules can be extracted into independent services later without a rewrite.

## 2.Stack:

 FastAPI · PostgreSQL · SQLAlchemy (async) · Alembic · React (Vite) · ChromaDB/FAISS · LangGraph · Docker

---

## 3. Module List (Summary)

### Shared
| Module | Responsibility |
|---|---|
| `core` | Config, DB session management, base models, exception handling, logging |
| `auth` | Login, signup, password-reset, JWT/session handling, RBAC |
| `users` | Profile management, role assignment, account settings |

### Portal
| Module | Responsibility |
|---|---|
| `student` | Homework upload, doubt forum, study material, self-evaluation, study plan |
| `teacher` | Progress monitoring, grading, exam analysis, flagged-students view |
| `admin` | Performance tracking, timetable, salary management, business analytics |

### Intelligence
| Module | Responsibility |
|---|---|
| `ocr` | Converts handwritten/scanned documents into text |
| `rag` | Vector DB (ChromaDB/FAISS), retrieve-and-generate endpoint |
| `ml` | At-risk/weak-topic prediction, forecasting, SHAP explainability |
| `agents` | LangGraph orchestration — Portal Assistant, Admin Assistant, Student Success, Learning Recommendation, Weak-Student Intervention |
| `mcp` | MCP server/tools — DB, ML, question-generator, email as standardized tools |
| `reports` | Parent Report Generation Agent (via `mcp`, email) |

### Cross-cutting
| Module | Responsibility |
|---|---|
| `guardrails` | PII redaction, prompt-injection defense, anti-cheating checks, audit logging |
| `observability` | RAG faithfulness evaluation, agent tracing, LLM cost/latency tracking |
| `gateway` | (In future) Reserved boundary for external API/MCP exposure |

---

## 4. Project Timeline (4 Weeks)

| Week | Theme | Key Deliverable |
|---|---|---|
| 1 | Foundation | DB schema, auth/profile/dashboard APIs, frontend connected to backend |
| 2 | Core Portal Features + OCR | All 3 portals functional (no AI); OCR live; | RAG + Assistants |
| 3 | Contextual Portal Assistant, Admin AI Assistant, RAG pipeline live |ML + Intervention + Reports |     At-risk/weak-topic models live; Intervention flow;
| 4 |  Parent Report Agent |Eval, Explainability, Guardrails | SHAP, RAG evaluation/observability, guardrails, final testing & docs |


---

## 5. Repository Structure

```
eduIntel/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   ├── auth/
│   │   ├── users/
│   │   ├── student/
│   │   ├── teacher/
│   │   ├── admin/
│   │   ├── ocr/
│   │   ├── rag/
│   │   ├── ml/
│   │   ├── agents/
│   │   ├── mcp/
│   │   ├── reports/
│   │   ├── guardrails/
│   │   ├── observability/
│   │   └── gateway/
│   ├── alembic/
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── .env
└── frontend/
    ├── src/
    │   ├── api/
    │   ├── components/
    │   └── pages/
    │       ├── auth/
    │       ├── student/
    │       ├── teacher/
    │       └── admin/
    └── package.json
```

Each backend module folder follows a consistent internal layout: `router.py`, `service.py`, `models.py`, `schemas.py`.

---

## 6. Local Setup

### Prerequisites
- WSL2 (Ubuntu) or Linux
- Python 3.12, Node 20+ (via `nvm`)
- Docker Desktop (WSL2 backend enabled)

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start Postgres
docker compose up -d

# Apply database migrations
alembic upgrade head

# Run the API
uvicorn app.main:app --reload
```
Backend runs at `http://localhost:8000` — interactive API docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```
Frontend runs at `http://localhost:5173`.

### Environment variables (`backend/.env`)

```
DATABASE_URL=postgresql+asyncpg://eduintel:eduintel_dev@localhost:5432/eduintel
JWT_SECRET_KEY=<secret-key>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

---

