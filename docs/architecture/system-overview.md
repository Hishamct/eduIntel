# EduIntel AI — System Overview & Architecture

## 1. Architectural Philosophy & Principles

EduIntel AI is engineered as a **Modular Monolith**. Rather than prematurely distributing components into isolated microservices with network boundaries, the system is consolidated into a single deployable unit while enforcing rigorous modular boundaries internally. 

### Core Design Principles
1. **Domain Boundary Separation**: The codebase is partitioned into 16 discrete domain modules. Modules interact strictly via exported service interfaces, never by directly mutating foreign database models or bypassing validation.
2. **Polyglot Persistence**: The system selects the optimal persistence mechanism for each data type:
   - *Relational Data (PostgreSQL 16)*: Users, academic grades, finance, schedules, and audit records.
   - *Vector Data (ChromaDB)*: High-dimensional semantic embeddings for study materials and portal help documents.
   - *Model Artifacts & Metrics (MLflow)*: Machine learning parameters, metrics, and trained model artifacts.
   - *Blob / File Storage (Local Filesystem / S3)*: Homework photo uploads, PDF lecture notes, and OCR caches.
3. **Asynchronous Non-Blocking I/O**: The backend leverages Python 3.12's `asyncio` event loop with FastAPI and SQLAlchemy 2.0 AsyncIO to ensure that database queries and network calls do not block concurrent requests.
4. **Defense-in-Depth AI Guardrails**: All AI interactions pass through layered security filters: PII redaction before persistence or LLM invocation, prompt injection detection, and Socratic anti-cheating interception.
5. **AI Provider Redundancy & Resiliency**: The core LLM client implements automatic rate-limit detection on Google Gemini (`gemini-3.6-flash`), immediately falling back to Groq (`openai/gpt-oss-120b`) without failing the user's request.

---

## 2. C4 Architecture Models

### 2.1. C4 Level 1 — System Context Diagram

The System Context diagram illustrates how external actors interact with the EduIntel platform and its external dependencies.

```mermaid
flowchart TD
    subgraph Users ["Human Actors"]
        Student["Student<br><i>Submits homework, asks doubts</i>"]
        Teacher["Teacher<br><i>Grades, tracks risk, uploads notes</i>"]
        Admin["Admin<br><i>Timetables, payroll, fees, analytics</i>"]
        Parent["Parent<br><i>Receives AI progress reports</i>"]
    end

    subgraph EduIntelSystem ["EduIntel AI Platform"]
        Platform["EduIntel AI Decision Intelligence Platform<br><i>Modular Monolith (React + FastAPI)</i>"]
    end

    subgraph ExternalServices ["External Cloud Services"]
        GeminiAPI["Google Gemini AI<br><i>LLM & Embeddings</i>"]
        GroqAPI["Groq AI Cloud<br><i>Rate-Limit LLM Fallback</i>"]
        SMTPServer["SMTP Mail Server<br><i>Parent Email Reports</i>"]
    end

    Student -->|"HTTPS / REST"| Platform
    Teacher -->|"HTTPS / REST"| Platform
    Admin -->|"HTTPS / REST"| Platform
    Platform -->|"Sends Email"| Parent

    Platform -->|"Generates Embeddings & Text"| GeminiAPI
    Platform -->|"Fallback Inference"| GroqAPI
    Platform -->|"Dispatches Reports"| SMTPServer
```

---

### 2.2. C4 Level 2 — Container Diagram

The Container diagram illustrates the high-level technical shape of EduIntel, showing how frontend, backend, and storage containers collaborate.

```mermaid
flowchart TD
    subgraph Client ["Client Browser"]
        SPA["React 18 Single Page App<br><i>Vite, React Router v6, Axios</i>"]
    end

    subgraph Edge ["Edge / Reverse Proxy"]
        Proxy["Caddy Reverse Proxy<br><i>Automatic TLS, Port 80/443</i>"]
    end

    subgraph Application ["Backend Application (FastAPI Modular Monolith)"]
        API["FastAPI 0.111.0 Async Application<br><i>Uvicorn ASGI Server</i>"]
        subgraph Subsystems ["Internal Modular Subsystems"]
            SharedMod["Shared: core, auth, users"]
            PortalMod["Portals: student, teacher, admin, announcements"]
            IntelMod["Intelligence: ocr, rag, ml, agents, mcp, reports"]
            GuardMod["Cross-Cutting: guardrails, observability"]
        end
    end

    subgraph Persistence ["Persistence Layer"]
        PG[("PostgreSQL 16 Engine<br><i>Relational DB, Port 5432</i>")]
        Chroma[("ChromaDB Vector Store<br><i>HNSW Persistent Embeddings</i>")]
        MLflowStore[("MLflow SQLite & Artifacts<br><i>mlflow.db, mlruns/</i>")]
        Disk[("Local Upload Storage<br><i>backend/uploads/</i>")]
    end

    subgraph External ["External AI Providers"]
        GeminiClient["Google Gemini API"]
        GroqClient["Groq Fallback API"]
    end

    SPA -->|"HTTPS REST /api/*"| Proxy
    Proxy -->|"HTTP Proxy"| API
    
    API --> SharedMod
    API --> PortalMod
    API --> IntelMod
    API --> GuardMod

    SharedMod -->|"SQLAlchemy 2.0 Async (asyncpg)"| PG
    PortalMod -->|"SQLAlchemy 2.0 Async"| PG
    IntelMod -->|"SQLAlchemy 2.0 Async"| PG
    IntelMod -->|"ChromaDB Client"| Chroma
    IntelMod -->|"PyTesseract / PyPDF"| Disk
    IntelMod -->|"MLflow Client"| MLflowStore
    IntelMod -->|"HTTPS / REST"| GeminiClient
    IntelMod -->|"HTTPS / REST"| GroqClient
    GuardMod -->|"Audit Logging"| PG
```

---

## 3. Data Persistence Topology

EduIntel decouples storage responsibilities across four distinct engines:

```mermaid
graph LR
    subgraph RelationalData ["1. PostgreSQL 16 (Primary RDBMS)"]
        Users["users, student_profiles, teacher_profiles, admin_profiles"]
        Academic["assignments, homework_submissions, exam_results, study_materials"]
        AdminData["timetable_entries, salary_records, fee_records, attendance_records"]
        Observability["audit_logs, agent_trace_logs, llm_cost_logs"]
    end

    subgraph VectorData ["2. ChromaDB (Vector Engine)"]
        HelpDocs["Collection: portal_help_docs (System Knowledge)"]
        Materials["Collection: study_materials (Subject Notes)"]
    end

    subgraph MLTracking ["3. MLflow (Model Tracking Engine)"]
        Experiments["mlflow.db (SQLite Experiment Registry)"]
        Artifacts["mlruns/ (Model Weights, Metrics, Confusion Matrices)"]
    end

    subgraph BlobStorage ["4. File Storage (Disk / S3)"]
        PDFs["backend/uploads/ (PDF Study Notes, Homework Images)"]
        Models["backend/app/ml/models/ (Exported XGBoost JSON Models)"]
    end
```

---

## 4. Cross-Cutting Execution Flow

Every HTTP request to an authenticated intelligence endpoint (e.g., student doubt query, admin AI query) traverses a standardized pipeline:

```mermaid
sequenceDiagram
    autonumber
    actor User as User (Student/Teacher/Admin)
    participant Edge as Caddy / Web Proxy
    participant Auth as Auth Dependency (require_role)
    participant Guard as Guardrails (PII & Injection)
    participant Service as Domain Service / Agent
    participant LLM as Unified LLM Client
    participant DB as PostgreSQL / ChromaDB

    User->>Edge: POST /api/student/doubts/1/messages (Bearer JWT)
    Edge->>Auth: Forward Request
    Auth->>Auth: Verify JWT signature & extract role claims
    alt Invalid Token / Insufficient Role
        Auth-->>User: 401 Unauthorized / 403 Forbidden
    end
    Auth->>Guard: Pass sanitized request payload
    Guard->>Guard: Check prompt injection & redact PII
    Guard->>Service: Forward clean text + redaction metadata
    Service->>DB: Fetch context / embeddings from ChromaDB
    DB-->>Service: Return matching text chunks
    Service->>LLM: Dispatch prompt (Gemini primary)
    alt Gemini Rate Limit (429)
        LLM->>LLM: Fallback to Groq API
    end
    LLM-->>Service: Generated response
    Service->>Guard: Redact any PII generated by LLM
    Service->>DB: Log token count, latency & ₹ cost to audit_logs
    Service-->>User: Return 200 OK with AI response
```

