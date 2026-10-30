# EduIntel AI — Feature Status Matrix

This matrix provides an exhaustive, source-verified audit of all capabilities across EduIntel AI's **16 backend modules** and **21 frontend views** on branch `develop/production-readiness`.

---

## 🚦 Status Legend

| Status | Definition |
|---|---|
| 🟢 **Implemented** | Source code fully present, integrated end-to-end with database/services, and functional. |
| 🟡 **Partially Implemented** | Feature is functional but contains stubs, mock data fallbacks, synchronous blockers, or missing edge case handling. |
| 🔵 **Planned / Roadmap** | Architectural placeholder exists or scheduled for a specific upcoming production-readiness phase. |
| ⚪ **Unverified** | Implementation exists in source but has not yet been subjected to end-to-end automated testing or staging validation. |

---

## 1. Backend Modules Matrix (16 Modules)

### Shared Tier

| Module | Feature / Capability | Status | Source Location | Implementation Notes |
|---|---|:---:|---|---|
| **`core`** | Async Database Engine & Session Pooling | 🟢 Implemented | [`backend/app/core/database.py`](file:///home/dell/projects/eduIntel/backend/app/core/database.py) | SQLAlchemy 2.0 AsyncEngine using `asyncpg`. |
| **`core`** | Global Application Settings | 🟢 Implemented | [`backend/app/core/config.py`](file:///home/dell/projects/eduIntel/backend/app/core/config.py) | Pydantic `BaseSettings` reading environment variables. |
| **`core`** | Base Timestamp Models & Mixins | 🟢 Implemented | [`backend/app/core/models.py`](file:///home/dell/projects/eduIntel/backend/app/core/models.py) | Provides `id`, `created_at`, `updated_at`. |
| **`core`** | Unified LLM Client with Fallback | 🟢 Implemented | [`backend/app/core/llm_client.py`](file:///home/dell/projects/eduIntel/backend/app/core/llm_client.py) | Primary Gemini (`gemini-3.6-flash`), fallback Groq (`openai/gpt-oss-120b`). |
| **`auth`** | User Registration (`/api/auth/signup`) | 🟢 Implemented | [`backend/app/auth/router.py`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py) | Validates unique email, hashes password with passlib/bcrypt. |
| **`auth`** | User Login & JWT Issuance (`/api/auth/login`) | 🟢 Implemented | [`backend/app/auth/router.py`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py) | Issues signed HS256 JWT access token. |
| **`auth`** | Password Reset Token Lifecycle | 🟢 Implemented | [`backend/app/auth/router.py`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py) | Tokens stored in `password_reset_tokens` table with expiry. |
| **`auth`** | Role-Based Access Control & Security | 🟢 Implemented | [`backend/app/auth/security.py`](file:///home/dell/projects/eduIntel/backend/app/auth/security.py) | JWT token creation/decoding, password hashing, and role checks. |
| **`users`** | Current User Profile Retrieval (`/api/users/me`) | 🟢 Implemented | [`backend/app/users/router.py`](file:///home/dell/projects/eduIntel/backend/app/users/router.py) | Returns authenticated user details and profile info. |
| **`users`** | Student/Teacher/Admin Profile Updates | 🟢 Implemented | [`backend/app/users/router.py`](file:///home/dell/projects/eduIntel/backend/app/users/router.py) | Updates contact information, phone, grade/subject metadata. |

### Portal Tier

| Module | Feature / Capability | Status | Source Location | Implementation Notes |
|---|---|:---:|---|---|
| **`student`** | Student Dashboard Summary (`/api/student/dashboard`) | 🟢 Implemented | [`backend/app/student/router.py`](file:///home/dell/projects/eduIntel/backend/app/student/router.py) | Aggregates attendance %, pending homework, recent scores. |
| **`student`** | Homework Submission Upload (`/api/student/homework`) | 🟢 Implemented | [`backend/app/student/router.py`](file:///home/dell/projects/eduIntel/backend/app/student/router.py) | Stores file in `backend/uploads/` and creates DB submission record. |
| **`student`** | Socratic Doubt Forum (`/api/student/doubts`) | 🟢 Implemented | [`backend/app/student/router.py`](file:///home/dell/projects/eduIntel/backend/app/student/router.py) | Threaded discussion with automated Socratic AI assistant reply. |
| **`student`** | Study Material Access (`/api/student/materials`) | 🟢 Implemented | [`backend/app/student/router.py`](file:///home/dell/projects/eduIntel/backend/app/student/router.py) | Lists uploaded notes filtered by subject. |
| **`student`** | Personal Attendance & Exam History | 🟢 Implemented | [`backend/app/student/router.py`](file:///home/dell/projects/eduIntel/backend/app/student/router.py) | Queries student-specific records from `attendance_records` and `exam_results`. |
| **`teacher`** | Teacher Dashboard Summary (`/api/teacher/dashboard`) | 🟢 Implemented | [`backend/app/teacher/router.py`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py) | Metrics on active assignments, pending grading count, class averages. |
| **`teacher`** | Assignment Creation (`/api/teacher/assignments`) | 🟢 Implemented | [`backend/app/teacher/router.py`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py) | Sets due date, subject, title, instructions, max marks. |
| **`teacher`** | Homework Grading & OCR Review (`/api/teacher/grading`) | 🟢 Implemented | [`backend/app/teacher/router.py`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py) | Updates marks, teacher feedback, and views OCR extracted text. |
| **`teacher`** | Study Material Upload & Indexing (`/api/teacher/materials`) | 🟡 Partially Implemented | [`backend/app/teacher/router.py`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py) | File uploaded and saved; vector indexing in ChromaDB is synchronous. |
| **`teacher`** | Exam Result Entry (`/api/teacher/exams`) | 🟢 Implemented | [`backend/app/teacher/router.py`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py) | Bulk or single entry of student exam marks and total marks. |
| **`teacher`** | Flagged / At-Risk Student View (`/api/teacher/flagged`) | 🟢 Implemented | [`backend/app/teacher/router.py`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py) | Displays students flagged by the ML diagnostic pipeline. |
| **`admin`** | Timetable Scheduling (`/api/admin/timetable`) | 🟢 Implemented | [`backend/app/admin/router.py`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py) | CRUD for subject, teacher, day of week, start/end time, room. |
| **`admin`** | Teacher Payroll Management (`/api/admin/salary`) | 🟢 Implemented | [`backend/app/admin/router.py`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py) | Records base salary, bonuses, deductions, payment dates. |
| **`admin`** | Student Fee Tracking (`/api/admin/fees`) | 🟢 Implemented | [`backend/app/admin/router.py`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py) | Installment records, due dates, paid amounts, payment statuses. |
| **`admin`** | Daily Attendance Recording (`/api/admin/attendance`) | 🟢 Implemented | [`backend/app/admin/router.py`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py) | Marks present/absent/late for students across dates. |
| **`admin`** | LangGraph Natural Language Query (`/api/admin/assistant/query`) | 🟢 Implemented | [`backend/app/agents/admin_assistant.py`](file:///home/dell/projects/eduIntel/backend/app/agents/admin_assistant.py) | Contained in Phase 0A: executes 6 safe parameterized reporting tools. |
| **`announcements`** | System-Wide Announcements (`/api/announcements`) | 🟢 Implemented | [`backend/app/announcements/router.py`](file:///home/dell/projects/eduIntel/backend/app/announcements/router.py) | CRUD for broadcast notifications to students, teachers, or all. |

### Intelligence & AI Tier

| Module | Feature / Capability | Status | Source Location | Implementation Notes |
|---|---|:---:|---|---|
| **`ocr`** | Image Preprocessing & PyTesseract OCR | 🟢 Implemented | [`backend/app/ocr/service.py`](file:///home/dell/projects/eduIntel/backend/app/ocr/service.py) | Grayscale, thresholding, contrast adjustment, Tesseract extraction. |
| **`ocr`** | Digital PDF Text Extraction | 🟢 Implemented | [`backend/app/ocr/service.py`](file:///home/dell/projects/eduIntel/backend/app/ocr/service.py) | PyPDF extraction for digital PDF lecture materials. |
| **`rag`** | ChromaDB Collection Management | 🟢 Implemented | [`backend/app/rag/service.py`](file:///home/dell/projects/eduIntel/backend/app/rag/service.py) | Manages `portal_help_docs` and `study_materials` collections. |
| **`rag`** | Gemini Vector Embeddings | 🟢 Implemented | [`backend/app/rag/service.py`](file:///home/dell/projects/eduIntel/backend/app/rag/service.py) | Uses `models/embedding-001` with retry and rate-limit backoff. |
| **`rag`** | Socratic Query Answering | 🟢 Implemented | [`backend/app/rag/service.py`](file:///home/dell/projects/eduIntel/backend/app/rag/service.py) | RAG pipeline that responds using guided pedagogical questions. |
| **`ml`** | XGBoost At-Risk Student Classification | 🟢 Implemented | [`backend/app/ml/diagnosis.py`](file:///home/dell/projects/eduIntel/backend/app/ml/diagnosis.py) | Trained model in `backend/app/ml/models/at_risk_model.joblib`. |
| **`ml`** | Weak Topic Prediction per Subject | 🟢 Implemented | [`backend/app/ml/recommendations.py`](file:///home/dell/projects/eduIntel/backend/app/ml/recommendations.py) | Trained model in `backend/app/ml/models/weak_topic_model.joblib`. |
| **`ml`** | SHAP Feature Explainability Plots | 🟢 Implemented | [`backend/app/ml/explain.py`](file:///home/dell/projects/eduIntel/backend/app/ml/explain.py) | Computes TreeExplainer SHAP values and returns top risk factors. |
| **`ml`** | Model Training Pipelines | 🟢 Implemented | [`backend/app/ml/train_at_risk_model.py`](file:///home/dell/projects/eduIntel/backend/app/ml/train_at_risk_model.py) | Scripts for offline XGBoost training and parameter logging. |
| **`ml`** | Automated Practice Worksheet Generator | 🟢 Implemented | [`backend/app/ml/worksheet_generator.py`](file:///home/dell/projects/eduIntel/backend/app/ml/worksheet_generator.py) | Generates targeted practice problems for identified weak topics. |
| **`agents`** | LangGraph Admin Assistant | 🟢 Implemented | [`backend/app/agents/admin_assistant.py`](file:///home/dell/projects/eduIntel/backend/app/agents/admin_assistant.py) | Stateful graph with 6 safe tools; Phase 0A SQLi risk eliminated. |
| **`agents`** | LangGraph Portal Help Assistant | 🟢 Implemented | [`backend/app/agents/portal_assistant.py`](file:///home/dell/projects/eduIntel/backend/app/agents/portal_assistant.py) | Directs users to relevant system documentation and workflows. |
| **`mcp`** | FastMCP Protocol Server | 🟢 Implemented | [`backend/app/mcp/server.py`](file:///home/dell/projects/eduIntel/backend/app/mcp/server.py) | Exposes `get_student_data` and `send_email` via stdio protocol. |
| **`reports`** | Parent Report Narrative Generator | 🟢 Implemented | [`backend/app/reports/parent_report_agent.py`](file:///home/dell/projects/eduIntel/backend/app/reports/parent_report_agent.py) | Synthesizes academic and attendance telemetry into narrative text. |
| **`reports`** | SMTP Email Dispatch | 🟡 Partially Implemented | [`backend/app/reports/parent_report_agent.py`](file:///home/dell/projects/eduIntel/backend/app/reports/parent_report_agent.py) | Functional via SMTP settings; runs synchronously in HTTP handler. |

### Cross-Cutting Tier

| Module | Feature / Capability | Status | Source Location | Implementation Notes |
|---|---|:---:|---|---|
| **`guardrails`**| In-Flight PII Redaction Engine | 🟢 Implemented | [`backend/app/guardrails/pii_redaction.py`](file:///home/dell/projects/eduIntel/backend/app/guardrails/pii_redaction.py) | Masks Aadhaar, phone, email, IPv4/v6, credit cards with regex. |
| **`guardrails`**| Prompt Injection Defense | 🟢 Implemented | [`backend/app/guardrails/prompt_injection.py`](file:///home/dell/projects/eduIntel/backend/app/guardrails/prompt_injection.py) | Regex heuristics detecting system prompt override attempts. |
| **`guardrails`**| Socratic Anti-Cheating Interceptor | 🟢 Implemented | [`backend/app/guardrails/anti_cheating.py`](file:///home/dell/projects/eduIntel/backend/app/guardrails/anti_cheating.py) | Flags direct-solution prompts (`was_socratic_redirected = True`). |
| **`observability`**| LLM Token & INR Cost Tracking | 🟢 Implemented | [`backend/app/observability/service.py`](file:///home/dell/projects/eduIntel/backend/app/observability/service.py) | Calculates input/output tokens and expenditure in ₹ per request. |
| **`observability`**| Agent Execution Trace Logging | 🟢 Implemented | [`backend/app/observability/tracing.py`](file:///home/dell/projects/eduIntel/backend/app/observability/tracing.py) | Captures graph nodes, tool calls, and latency in `agent_trace_logs`. |
| **`gateway`** | External API / MCP Reverse Proxy Gateway | 🔵 Planned | [`backend/app/gateway/`](file:///home/dell/projects/eduIntel/backend/app/gateway/) | Boundary reserved for API rate limiting, Kong/Envoy, or third-party webhooks. |

---

## 2. Frontend Application Matrix (21 Verified Views)

### Authentication & Common Views

| Route | Page Component | Role Required | Status | Source Location | Description & Capabilities |
|---|---|:---:|:---:|---|---|
| `/login` | `Login.jsx` | Public | 🟢 Implemented | [`frontend/src/pages/auth/Login.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/Login.jsx) | Email/password login, JWT storage, role-based redirection. |
| `/signup` | `Signup.jsx` | Public | 🟢 Implemented | [`frontend/src/pages/auth/Signup.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/Signup.jsx) | User registration with initial role selection. |
| `/password-reset` | `PasswordReset.jsx` | Public | 🟢 Implemented | [`frontend/src/pages/auth/PasswordReset.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/auth/PasswordReset.jsx) | Integrated request & reset flow with token entry. |
| Floating Widget | `PortalAssistantWidget.jsx` | Authenticated | 🟢 Implemented | [`frontend/src/components/PortalAssistantWidget.jsx`](file:///home/dell/projects/eduIntel/frontend/src/components/PortalAssistantWidget.jsx) | Global conversational help widget embedded across pages. |
| Guard | `ProtectedRoute.jsx` | Authenticated | 🟢 Implemented | [`frontend/src/components/ProtectedRoute.jsx`](file:///home/dell/projects/eduIntel/frontend/src/components/ProtectedRoute.jsx) | Route wrapper validating JWT token presence before rendering. |

### Student Portal

| Route | Page Component | Role Required | Status | Source Location | Description & Capabilities |
|---|---|:---:|:---:|---|---|
| `/student/dashboard`| `StudentDashboard.jsx`| `student` | 🟢 Implemented | [`frontend/src/pages/student/StudentDashboard.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/student/StudentDashboard.jsx) | Overview of upcoming assignments, attendance rate, and recent marks. |
| `/student/homework` | `HomeworkUpload.jsx` | `student` | 🟢 Implemented | [`frontend/src/pages/student/HomeworkUpload.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/student/HomeworkUpload.jsx) | List assignments, upload homework files, view teacher grades & feedback. |
| `/student/doubts` | `DoubtForum.jsx` | `student` | 🟢 Implemented | [`frontend/src/pages/student/DoubtForum.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/student/DoubtForum.jsx) | Create doubt threads and converse with Socratic AI Doubt Tutor. |
| `/student/materials`| `StudyMaterials.jsx`| `student` | 🟢 Implemented | [`frontend/src/pages/student/StudyMaterials.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/student/StudyMaterials.jsx) | Browse, search, and download teacher-uploaded notes and PDFs. |
| `/student/self-eval`| `SelfEvaluation.jsx`| `student` | 🟢 Implemented | [`frontend/src/pages/student/SelfEvaluation.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/student/SelfEvaluation.jsx) | Personal exam score trends, weak-topic self-assessment, and progress. |

### Teacher Portal

| Route | Page Component | Role Required | Status | Source Location | Description & Capabilities |
|---|---|:---:|:---:|---|---|
| `/teacher/dashboard`| `TeacherDashboard.jsx`| `teacher` | 🟢 Implemented | [`frontend/src/pages/teacher/TeacherDashboard.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/teacher/TeacherDashboard.jsx) | Class statistics, pending submission counts, quick actions. |
| `/teacher/progress` | `ProgressMonitoring.jsx` | `teacher` | 🟢 Implemented | [`frontend/src/pages/teacher/ProgressMonitoring.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/teacher/ProgressMonitoring.jsx) | Class attendance rosters, exam distributions, and student progress curves. |
| `/teacher/grading` | `AssignmentsGrading.jsx` | `teacher` | 🟢 Implemented | [`frontend/src/pages/teacher/AssignmentsGrading.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/teacher/AssignmentsGrading.jsx) | Review submissions with side-by-side OCR text preview and grading. |
| `/teacher/exams` | `ExamResults.jsx` | `teacher` | 🟢 Implemented | [`frontend/src/pages/teacher/ExamResults.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/teacher/ExamResults.jsx) | Enter and publish exam scores for classes and individual students. |
| `/teacher/materials`| `StudyMaterials.jsx`| `teacher` | 🟢 Implemented | [`frontend/src/pages/teacher/StudyMaterials.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/teacher/StudyMaterials.jsx) | Upload study materials and lecture PDFs for student indexing. |
| `/teacher/flagged` | `FlaggedStudents.jsx` | `teacher` | 🟢 Implemented | [`frontend/src/pages/teacher/FlaggedStudents.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/teacher/FlaggedStudents.jsx) | View students identified by ML diagnostics with SHAP factor breakdowns. |

### Admin Portal

| Route | Page Component | Role Required | Status | Source Location | Description & Capabilities |
|---|---|:---:|:---:|---|---|
| `/admin/dashboard` | `AdminDashboard.jsx` | `admin` | 🟢 Implemented | [`frontend/src/pages/admin/AdminDashboard.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/admin/AdminDashboard.jsx) | High-level KPI analytics, institute financial summaries, and quick links. |
| `/admin/ai-assistant` | `AdminAssistant.jsx` | `admin` | 🟢 Implemented | [`frontend/src/pages/admin/AdminAssistant.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/admin/AdminAssistant.jsx) | Natural language conversational query assistant using safe reporting tools. |
| `/admin/llm-usage` | `LlmUsage.jsx` | `admin` | 🟢 Implemented | [`frontend/src/pages/admin/LlmUsage.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/admin/LlmUsage.jsx) | Token consumption telemetry, provider breakdown, and expenditure in ₹. |
| `/admin/agent-traces` | `AgentTraces.jsx` | `admin` | 🟢 Implemented | [`frontend/src/pages/admin/AgentTraces.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/admin/AgentTraces.jsx) | LangGraph execution graph viewer, node latency, and tool traces. |
| `/admin/students` | `StudentRecords.jsx` | `admin` | 🟢 Implemented | [`frontend/src/pages/admin/StudentRecords.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/admin/StudentRecords.jsx) | Student enrollment rosters, profile details, and fee balances. |
| `/admin/alerts` | `RiskAlerts.jsx` | `admin` | 🟢 Implemented | [`frontend/src/pages/admin/RiskAlerts.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/admin/RiskAlerts.jsx) | Institute-wide at-risk student monitoring and automated report triggers. |
| `/admin/analysis` | `AcademicAnalysis.jsx` | `admin` | 🟢 Implemented | [`frontend/src/pages/admin/AcademicAnalysis.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/admin/AcademicAnalysis.jsx) | Cross-batch academic trends, pass rates, and subject comparisons. |
| `/admin/reports` | `InstitutionalReports.jsx` | `admin` | 🟢 Implemented | [`frontend/src/pages/admin/InstitutionalReports.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/admin/InstitutionalReports.jsx) | Generate and dispatch automated parent progress reports via email. |
| `/admin/timetable` | `TimetableView.jsx` | `admin` | 🟢 Implemented | [`frontend/src/pages/admin/TimetableView.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/admin/TimetableView.jsx) | Weekly class schedule matrix, teacher room assignments, and conflict checks. |
| `/admin/salary` | `SalaryManagement.jsx` | `admin` | 🟢 Implemented | [`frontend/src/pages/admin/SalaryManagement.jsx`](file:///home/dell/projects/eduIntel/frontend/src/pages/admin/SalaryManagement.jsx) | Teacher payroll records, base pay, bonuses, and disbursement statuses. |

---

## 3. High-Priority Gaps & Remediation Schedule

| Component | Identified Limitation | Operational Impact | Scheduled Remediation |
|---|---|---|:---:|
| **Multi-Tenancy** | Schema lacks `institution_id` foreign key isolation. | All records belong to a single institution; cross-tenant leakage if shared. | **Phase 2** (RBAC & Multi-Tenancy) |
| **Async Queues** | SMTP email dispatch, OCR extraction, and ChromaDB vector embeddings run synchronously in the HTTP request. | Slow request latency (2–8 seconds) during PDF uploads and email dispatch. | **Phase 6** (Background Tasks & Resilience) |
| **Duplicate Models** | `User` SQLAlchemy model is declared in both `auth.models` and `users.models`. | Architectural duplication; potential Alembic drift if not unified. | **Phase 3** (Database Optimization) |
| **Missing DB Enums** | Alembic migration references custom enum types, but models fall back to string representations in certain tables. | Schema inconsistency between clean migration and fallback DDL. | **Phase 3** (Database Optimization) |
| **Frontend Styling** | Legacy documentation claimed TailwindCSS, but UI uses custom CSS variables in `ui.css`. | Misleading documentation resolved; UI styling standard maintained. | **Phase 1** (Documentation Foundation) |
