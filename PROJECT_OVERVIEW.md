# EduIntel AI — Project Overview & Architecture Documentation

**Agentic AI-Powered Decision Intelligence Platform for Coaching Institutes and Schools**

---

## 1. Executive Summary

**EduIntel AI** is an enterprise-grade, agentic AI-driven educational decision intelligence platform designed to empower educational institutes, coaching centers, and K-12 schools. By combining role-based portals (**Student**, **Teacher**, **Admin**) with automated document OCR, Socratic RAG (Retrieval-Augmented Generation), machine learning for at-risk student diagnosis, and LangGraph-orchestrated AI agents, EduIntel AI bridges the gap between administrative operations and academic outcome optimization.

Built as a **Modular Monolith**, EduIntel AI maintains strict architectural boundaries between its 15 distinct domain modules. This allows for simple unified deployment while preserving the ability to decompose AI and analytical workflows into microservices as scaling demands require.

---

## 2. Platform Architecture & Tech Stack

```
                                  ┌────────────────────────────────┐
                                  │      React (Vite) Frontend     │
                                  │   Student | Teacher | Admin    │
                                  └───────────────┬────────────────┘
                                                  │ REST APIs / JSON
                                                  ▼
                                  ┌────────────────────────────────┐
                                  │    FastAPI Backend Application │
                                  │       (Modular Monolith)       │
                                  └───────────────┬────────────────┘
                                                  │
          ┌──────────────────────┬────────────────┼────────────────┬──────────────────────┐
          │                      │                │                │                      │
          ▼                      ▼                ▼                ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌────────────┐  ┌───────────────┐  ┌─────────────────┐
│ PostgreSQL RDBMS │  │ ChromaDB Vector  │  │ MLflow DB  │  │ File Storage  │  │ Tesseract OCR   │
│ (Primary Engine) │  │ (Gemini Vectors) │  │ (ML Log)   │  │ (PDF/Uploads) │  │ (Doc Digitizing)│
└──────────────────┘  └──────────────────┘  └────────────┘  └───────────────┘  └─────────────────┘
```

### Technology Stack Overview

* **Backend Framework**: Python 3.12, FastAPI (Async)
* **ORM & Database**: SQLAlchemy 2.0 (AsyncIO), Alembic (Migrations), PostgreSQL 15+
* **Frontend Framework**: React 18, Vite, React Router v6, TailwindCSS / CSS Modules, Lucide React Icons
* **AI & Agent Orchestration**: LangGraph, LangChain, Google Gemini API (`gemini-1.5-flash`, `gemini-embedding-001`), Groq API (Rate-Limit Fallback Provider)
* **Vector Store**: ChromaDB (Persistent storage with HNSW indexing)
* **Machine Learning & Analytics**: Scikit-Learn (Random Forest, Logistic Regression), SHAP (SHapley Additive exPlanations), MLflow
* **OCR Engine**: PyTesseract (Tesseract OCR Engine)
* **Containerization & Tooling**: Docker, Docker Compose, Pytest, Ruff (Linting)

---

## 3. Modular Monolith Architecture (15 Domain Modules)

The system is organized into 15 domain modules grouped into four functional tiers:

```
├── Shared Modules       : core | auth | users
├── Portal Modules       : student | teacher | admin
├── Intelligence Modules : ocr | rag | ml | agents | mcp | reports
└── Cross-Cutting        : guardrails | observability | gateway
```

### 3.1. Shared Modules
1. **`core`** ([`backend/app/core`](file:///home/dell/projects/eduIntel/backend/app/core)): Async database session management (`database.py`), global configuration settings (`config.py`), base timestamp mixins (`models.py`), and LLM client wrappers (`llm_client.py`).
2. **`auth`** ([`backend/app/auth`](file:///home/dell/projects/eduIntel/backend/app/auth)): JWT access token issuance, password hashing (Passlib/Bcrypt), signup/login endpoints, password reset tokens, and Role-Based Access Control (RBAC) dependencies.
3. **`users`** ([`backend/app/users`](file:///home/dell/projects/eduIntel/backend/app/users)): User profile management (`User`, `StudentProfile`, `TeacherProfile`, `AdminProfile`), role switching, and contact detail updates.

### 3.2. Portal Modules
4. **`student`** ([`backend/app/student`](file:///home/dell/projects/eduIntel/backend/app/student)): Homework submission uploads, Socratic doubt resolution threads, study material access, and student dashboard statistics.
5. **`teacher`** ([`backend/app/teacher`](file:///home/dell/projects/eduIntel/backend/app/teacher)): Assignment creation, homework grading (with OCR preview), exam results recording, and study material uploads.
6. **`admin`** ([`backend/app/admin`](file:///home/dell/projects/eduIntel/backend/app/admin)): Class timetable scheduling, teacher payroll/salary records, student fee management, daily attendance recording, and institute-wide analytics.

### 3.3. Intelligence & AI Modules
7. **`ocr`** ([`backend/app/ocr`](file:///home/dell/projects/eduIntel/backend/app/ocr)): Document image preprocessing, Tesseract text extraction, and confidence scoring for handwritten homework and PDF study notes.
8. **`rag`** ([`backend/app/rag`](file:///home/dell/projects/eduIntel/backend/app/rag)): Dual ChromaDB collection vector management (`portal_help_docs`, `study_materials`), Gemini embeddings, document chunking, and retrieve-and-generate pipelines.
9. **`ml`** ([`backend/app/ml`](file:///home/dell/projects/eduIntel/backend/app/ml)): Predictive ML models for at-risk student classification, weak topic prediction per subject, SHAP feature importance explainability, and automated worksheet generation.
10. **`agents`** ([`backend/app/agents`](file:///home/dell/projects/eduIntel/backend/app/agents)): Stateful LangGraph agent implementations including **Admin Assistant** (SQL tool calling) and **Portal Assistant** (System documentation RAG).
11. **`mcp`** ([`backend/app/mcp`](file:///home/dell/projects/eduIntel/backend/app/mcp)): Model Context Protocol server exposing database access, ML inference, and email dispatch tools as standardized protocols.
12. **`reports`** ([`backend/app/reports`](file:///home/dell/projects/eduIntel/backend/app/reports)): Parent Report Generation pipeline using LLM narrative generation, PII redaction, and SMTP email distribution.

### 3.4. Cross-Cutting & Observability Modules
13. **`guardrails`** ([`backend/app/guardrails`](file:///home/dell/projects/eduIntel/backend/app/guardrails)): Security layer enforcing PII redaction (Regex for Email, Phone, Aadhaar, IP, Credit Cards), prompt injection blocking, and anti-cheating Socratic redirection.
14. **`observability`** ([`backend/app/observability`](file:///home/dell/projects/eduIntel/backend/app/observability)): RAG evaluation metrics (Faithfulness & Context Precision), LLM token/cost tracking in INR (₹), and LangGraph node step tracing (`agent_trace_logs`).
15. **`gateway`** ([`backend/app/gateway`](file:///home/dell/projects/eduIntel/backend/app/gateway)): Architectural boundary reserved for external API rate limiting, routing, and third-party integrations.

---

## 4. Key AI Capabilities & Workflows

### 4.1. Socratic AI Doubt Tutor
Unlike generic chatbots that provide direct homework solutions, EduIntel's Doubt Forum agent enforces **Socratic Learning Guardrails**:
* If a student asks *"What is the answer to question 3?"*, the guardrail intercepts the query (`was_socratic_redirected = True`).
* The assistant guides the student through underlying concepts, asking leading questions to build problem-solving skills without giving away raw answers.

### 4.2. LangGraph AI Admin Assistant
The Admin Assistant empowers institute owners to query complex administrative databases using natural language:
* Uses LangGraph tool-calling nodes to query timetable coverage, teacher payroll totals, fee collection status, and attendance rates.
* Formulates executive summaries without requiring admins to manually navigate complex reporting dashboards.

### 4.3. ML At-Risk Student Diagnosis & SHAP Explainability
* **Diagnostic Features**: Analyzes attendance rates, homework submission rates, score trends over time, and doubt forum activity.
* **Explainable AI (SHAP)**: Identifies concrete contributing factors (e.g., *"Exam scores declined by 6.5 points over 3 weeks"*) to generate actionable teacher interventions rather than opaque risk scores.

### 4.4. Security, Privacy & Guardrails
* **PII Redaction Engine**: Automatically redacts sensitive personal identifiable information before responses are returned or logged in audit trails.
* **Append-Only Audit Logging**: All AI assistant queries, guardrail blocks, PII redaction counts, and Socratic redirections are logged to the `audit_logs` database table.

---

## 5. Repository Layout

```
eduIntel/
├── backend/
│   ├── alembic/                  # Database migration scripts
│   ├── app/
│   │   ├── admin/                # Admin domain (timetable, salary, fees, attendance)
│   │   ├── agents/               # LangGraph stateful AI agents
│   │   ├── announcements/        # System announcements
│   │   ├── auth/                 # Authentication & JWT tokens
│   │   ├── core/                 # App config, database, base models
│   │   ├── gateway/              # API Gateway entry points
│   │   ├── guardrails/           # PII redaction & prompt injection defense
│   │   ├── main.py               # FastAPI entrypoint & router mounts
│   │   ├── mcp/                  # Model Context Protocol server
│   │   ├── ml/                   # ML models, SHAP, diagnosis, worksheets
│   │   ├── observability/        # RAG evaluation, LLM cost & trace logs
│   │   ├── ocr/                  # Tesseract OCR processing service
│   │   ├── rag/                  # ChromaDB client, RAG service & router
│   │   ├── reports/              # Parent report generation pipeline
│   │   ├── student/              # Student homework & doubt forum
│   │   ├── teacher/              # Teacher assignments, grading & materials
│   │   └── users/                # User profiles & identity
│   ├── chroma_data/              # Persistent ChromaDB vector collections
│   ├── docker-compose.yml        # PostgreSQL container setup
│   ├── mlflow.db                 # MLflow SQLite tracking database
│   ├── requirements.txt          # Python dependencies
│   └── uploads/                  # User file uploads (Study notes, Homework)
├── frontend/
│   ├── src/
│   │   ├── api/                  # Axios HTTP client & API bindings
│   │   ├── components/           # Reusable UI components & layouts
│   │   ├── context/              # AuthContext & global state
│   │   └── pages/                # Role-specific portal pages
│   │       ├── admin/            # Admin Analytics, Fees, Timetable, Risk Alerts
│   │       ├── auth/             # Login, Signup, Password Reset
│   │       ├── student/          # Student Dashboard, Doubts, Homework, Study
│   │       └── teacher/          # Teacher Dashboard, Grading, Materials
│   └── package.json              # Frontend dependencies & Vite scripts
├── database_design.md            # Complete DB schema & ERD documentation
├── modules.md                    # Module responsibility reference
└── PROJECT_OVERVIEW.md           # Master project overview documentation
```

---

## 6. Quick Start & Setup Guide

### Prerequisites
* **Python**: 3.12+
* **Node.js**: 20+ (with npm)
* **Docker & Docker Compose**: For PostgreSQL
* **Tesseract OCR**: Optional local binary for OCR capabilities (`sudo apt install tesseract-ocr`)

### Step 1: Environment Configuration
Create `backend/.env` with required configuration:

```env
DATABASE_URL=postgresql+asyncpg://eduintel:eduintel_dev@localhost:5432/eduintel
JWT_SECRET_KEY=your_super_secret_jwt_key_here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=43200
GEMINI_API_KEY=your_gemini_api_key_here
```

### Step 2: Database & Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start PostgreSQL database container
docker compose up -d

# Run Alembic migrations to build database tables
alembic upgrade head

# Start FastAPI development server
uvicorn app.main:app --reload --port 8000
```
Backend API will be accessible at `http://localhost:8000`.
Interactive Swagger API documentation is available at `http://localhost:8000/docs`.

### Step 3: Frontend Setup

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```
Frontend Web Portal will be accessible at `http://localhost:5173`.

---

## 7. Verification & Testing

To run automated backend tests across all modules:

```bash
cd backend
pytest -v
```

Tests validate:
* Password hashing and JWT authentication routines
* Role-based access control restrictions
* OCR extraction and confidence scoring
* RAG retrieval and vector collection management
* Socratic guardrail redirection logic
* LangGraph agent state transitions
