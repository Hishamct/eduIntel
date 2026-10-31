# EduIntel AI — API Route Inventory

This inventory documents all **57 endpoints** across the **16 routers** mounted in the FastAPI application ([`backend/app/main.py`](file:///home/dell/projects/eduIntel/backend/app/main.py)) on branch `develop/production-readiness`.

---

## 📑 Router Summary Index

| Router Tag | Prefix | Endpoint Count | Role Requirement |
|---|---|:---:|---|
| **Health & Core** | `/` | 2 | Public |
| **Authentication** | `/api/auth` | 4 | Public |
| **Users & Profiles** | `/api/users` | 3 | Authenticated / Specific Roles |
| **Student Portal** | `/api/student` | 8 | `student` |
| **Teacher Portal** | `/api/teacher` | 8 | `teacher` |
| **Admin Portal** | `/api/admin` | 10 | `admin` |
| **Announcements** | `/api/announcements`| 4 | Authenticated (`admin` for write) |
| **OCR Processing** | `/api/ocr` | 2 | Authenticated (`teacher`/`student`) |
| **RAG & Vectors** | `/api/rag` | 4 | Authenticated |
| **Machine Learning**| `/api/ml` | 4 | Authenticated (`teacher`/`admin`) |
| **AI Agents** | `/api/admin/assistant`, `/api/portal/assistant` | 2 | `admin` / Authenticated |
| **Parent Reports** | `/api/reports` | 2 | `admin` / `teacher` |
| **Observability** | `/api/observability`| 4 | `admin` |
| **Total** | | **57** | |

---

## 1. Health & System Endpoints

| Method | Path | Auth / Role | Description | Request Body | Response |
|---|---|:---:|---|---|---|
| `GET` | `/` | Public | System root check | None | `{"status": "ok", "app": "EduIntel AI"}` |
| `GET` | `/health` | Public | System health status | None | `{"status": "healthy", "database": "connected"}` |

---

## 2. Authentication Router (`/auth`)

| Method | Path | Auth / Role | Description | Request Body | Response |
|---|---|:---:|---|---|---|
| `POST` | `/auth/signup` | **Disabled** | Public self-registration disabled (SEC-02) | None | `403 Forbidden` |
| `POST` | `/auth/login` | Public | Authenticate user, set `HttpOnly` cookie & return JWT (SEC-10) | `LoginRequest` (email, password) | `200 OK` (`TokenResponse` + Cookie) |
| `POST` | `/auth/logout` | Public | Clear `HttpOnly` authentication cookie (SEC-10) | None | `200 OK` (`{"message": "Successfully logged out"}`) |
| `POST` | `/auth/password-reset/request` | Public (Rate Limited) | Request reset link (5 req/min, background SMTP, SEC-01) | `PasswordResetRequest` (email) | `200 OK` (`{"message": "..."}`) |
| `POST` | `/auth/password-reset/confirm` | Public | Reset password using SHA-256 verified token (SEC-01) | `PasswordResetConfirm` (token, new_pw)| `200 OK` (`{"message": "..."}`) |

---

## 3. Users Router (`/api/users`)

| Method | Path | Auth / Role | Description | Request Body | Response |
|---|---|:---:|---|---|---|
| `GET` | `/api/users/me` | Authenticated | Retrieve current user profile | None | `200 OK` (`UserProfileResponse`) |
| `PUT` | `/api/users/me` | Authenticated | Update current user details | `UserUpdateRequest` | `200 OK` (`UserProfileResponse`) |
| `GET` | `/api/users/{user_id}` | `admin` | Retrieve specific user by ID | None | `200 OK` (`UserAdminViewResponse`) |

---

## 4. Student Portal Router (`/api/student`)

| Method | Path | Auth / Role | Description | Request Body / Params | Response |
|---|---|:---:|---|---|---|
| `GET` | `/api/student/dashboard` | `student` | Aggregate dashboard metrics | None | `200 OK` (`StudentDashboardSummary`) |
| `GET` | `/api/student/homework` | `student` | List student's assignments & submissions | `?status=pending/submitted` | `200 OK` (`List[HomeworkItem]`) |
| `POST` | `/api/student/homework` | `student` | Submit homework file | Multipart (`assignment_id`, `file`) | `201 Created` (`SubmissionResponse`) |
| `GET` | `/api/student/doubts` | `student` | List student doubt threads | `?subject=Physics` | `200 OK` (`List[DoubtThreadSummary]`) |
| `POST` | `/api/student/doubts` | `student` | Open new doubt thread | `DoubtCreate` (title, subject, question) | `201 Created` (`DoubtThreadDetail`) |
| `POST` | `/api/student/doubts/{id}/messages`| `student` | Post message & get Socratic AI reply | `MessageCreate` (content) | `200 OK` (`DoubtMessagePair`) |
| `GET` | `/api/student/materials`| `student` | List study notes and PDFs | `?subject=Math` | `200 OK` (`List[StudyMaterialItem]`) |
| `GET` | `/api/student/attendance`| `student` | View personal attendance record | `?month=10&year=2026` | `200 OK` (`AttendanceHistory`) |

---

## 5. Teacher Portal Router (`/api/teacher`)

| Method | Path | Auth / Role | Description | Request Body / Params | Response |
|---|---|:---:|---|---|---|
| `GET` | `/api/teacher/dashboard` | `teacher` | Teacher dashboard stats | None | `200 OK` (`TeacherDashboardSummary`) |
| `GET` | `/api/teacher/assignments` | `teacher` | List teacher's assignments | None | `200 OK` (`List[AssignmentItem]`) |
| `POST` | `/api/teacher/assignments` | `teacher` | Create new assignment | `AssignmentCreate` (title, due_date, max_marks)| `201 Created` (`AssignmentResponse`) |
| `GET` | `/api/teacher/grading` | `teacher` | List pending submissions to grade | `?assignment_id=uuid` | `200 OK` (`List[GradingItem]`) |
| `POST` | `/api/teacher/grading/{submission_id}`| `teacher`| Submit grade and feedback | `GradeSubmissionRequest` (marks, feedback)| `200 OK` (`GradedSubmissionResponse`) |
| `GET` | `/api/teacher/materials` | `teacher` | List uploaded study notes | None | `200 OK` (`List[StudyMaterialItem]`) |
| `POST` | `/api/teacher/materials` | `teacher` | Upload & index new material | Multipart (`title`, `subject`, `file`) | `201 Created` (`MaterialResponse`) |
| `POST` | `/api/teacher/exams` | `teacher` | Record student exam scores | `ExamScoreBatchCreate` | `201 Created` (`ExamBatchResponse`) |

---

## 6. Admin Portal Router (`/api/admin`)

| Method | Path | Auth / Role | Description | Request Body / Params | Response |
|---|---|:---:|---|---|---|
| `GET` | `/api/admin/dashboard` | `admin` | Overall institute KPI metrics | None | `200 OK` (`AdminDashboardKPIs`) |
| `GET` | `/api/admin/timetable` | `admin` | List weekly timetable entries | `?day=Monday&teacher_id=uuid` | `200 OK` (`List[TimetableItem]`) |
| `POST` | `/api/admin/timetable` | `admin` | Create timetable schedule | `TimetableCreate` | `201 Created` (`TimetableItem`) |
| `DELETE`| `/api/admin/timetable/{id}`| `admin`| Remove timetable entry | None | `204 No Content` |
| `GET` | `/api/admin/salary` | `admin` | List teacher payroll records | `?month=10&year=2026` | `200 OK` (`List[SalaryItem]`) |
| `POST` | `/api/admin/salary` | `admin` | Record teacher salary disbursement | `SalaryCreate` (teacher_id, base, bonus)| `201 Created` (`SalaryItem`) |
| `GET` | `/api/admin/fees` | `admin` | List student fee records | `?status=pending/overdue` | `200 OK` (`List[FeeItem]`) |
| `POST` | `/api/admin/fees` | `admin` | Create or update fee installment | `FeeRecordCreate` | `201 Created` (`FeeItem`) |
| `POST` | `/api/admin/attendance` | `admin` | Record daily attendance roster | `AttendanceBatchCreate` | `201 Created` (`BatchAttendanceResponse`) |
| `POST` | `/admin/teachers` | `admin` | Provision new teacher account (SEC-02) | `AdminTeacherCreate` (email, password, name, department) | `201 Created` (`TeacherProfileOut`) |
| `POST` | `/admin/students` | `admin` | Provision new student account (SEC-02) | `AdminStudentCreate` (email, password, name, grade, section) | `201 Created` (`StudentProfileOut`) |
| `POST` | `/admin/administrators` | `admin` | Provision additional administrator (SEC-02) | `AdminCreate` (email, password, name) | `201 Created` (`AdminProfileOut`) |
| `POST` | `/api/admin/assistant/query`| `admin`| LangGraph Admin Assistant QA | `AgentQueryRequest` (prompt) | `200 OK` (`AgentQueryResponse`) |

---

## 7. Announcements Router (`/api/announcements`)

| Method | Path | Auth / Role | Description | Request Body | Response |
|---|---|:---:|---|---|---|
| `GET` | `/api/announcements` | Authenticated | List visible announcements | `?target_role=student/teacher/all` | `200 OK` (`List[AnnouncementItem]`) |
| `POST` | `/api/announcements` | `admin` | Create new announcement | `AnnouncementCreate` | `201 Created` (`AnnouncementItem`) |
| `PUT` | `/api/announcements/{id}`| `admin` | Update announcement | `AnnouncementUpdate` | `200 OK` (`AnnouncementItem`) |
| `DELETE`| `/api/announcements/{id}`| `admin` | Archive/delete announcement| None | `204 No Content` |

---

## 8. OCR Processing Router (`/ocr`)

| Method | Path | Auth / Role | Description | Request Body | Response |
|---|---|:---:|---|---|---|
| `POST` | `/ocr/extract` | Authenticated | Extract text (5 MB limit, magic bytes, concurrency semaphore, SEC-05) | Multipart (`file`, `clean_text=true`) | `200 OK` (`OCRExtractResult`) |
| `GET` | `/ocr/status/{task_id}`| Authenticated | Get OCR extraction status | None | `200 OK` (`OCRStatusResponse`) |

---

## 9. RAG & Vector Router (`/rag`)

| Method | Path | Auth / Role | Description | Request Body | Response |
|---|---|:---:|---|---|---|
| `POST` | `/rag/ingest` | `teacher`/`admin` | Ingest chunks tagged with `institution_id` (SEC-08) | `RAGIngestRequest` (collection, text) | `201 Created` (`IngestResult`) |
| `POST` | `/rag/query` | Authenticated | Search vector collection with mandatory tenant filter (SEC-08) | `RAGQueryRequest` (query, collection, top_k) | `200 OK` (`RAGQueryResult`) |
| `GET` | `/rag/recommendations/{student_id}` | Authenticated | Topic recommendations with tenant isolation (SEC-08) | None | `200 OK` (`List[RAGChunk]`) |
| `GET` | `/rag/debug-query` | `admin` | Debug retrieval with tenant filter (SEC-08) | `?query=...` | `200 OK` (`DebugQueryResult`) |
| `GET` | `/rag/collections` | `admin` | List active ChromaDB collections | None | `200 OK` (`List[CollectionInfo]`) |
| `DELETE`| `/rag/documents/{doc_id}`| `admin` | Remove document from vector index | None | `204 No Content` |

---

## 10. Machine Learning Router (`/ml`)

| Method | Path | Auth / Role | Description | Request Body | Response |
|---|---|:---:|---|---|---|
| `GET` | `/ml/diagnose/{student_id}` | `teacher`/`admin` | At-risk prediction & SHAP factors (timetable section check, SEC-07) | None | `200 OK` (`RiskDiagnosisResponse`) |
| `GET` | `/ml/predict/at-risk/{student_id}` | `teacher`/`admin` | Binary risk prediction (timetable section check, SEC-07) | None | `200 OK` (`RiskPredictionResponse`) |
| `GET` | `/ml/predict/weak-topics/{student_id}`| `teacher`/`admin` | Predict weak topics (timetable section check, SEC-07) | None | `200 OK` (`WeakTopicsResponse`) |
| `GET` | `/ml/explain/at-risk/{student_id}` | `teacher`/`admin` | SHAP explanation breakdown (timetable section check, SEC-07) | None | `200 OK` (`SHAPExplanationResponse`) |
| `GET` | `/ml/recommend-topic` | `teacher`/`admin` | Pedagogical recommendations for weak topic | `?subject=...&topic=...` | `200 OK` (`TopicRecommendation`) |
| `POST` | `/ml/worksheet/generate` | `teacher` | Generate targeted practice questions | `WorksheetGenerateRequest` (student_id, topic)| `200 OK` (`WorksheetResponse`) |
| `POST` | `/ml/retrain` | `admin` | Trigger offline XGBoost retraining | `RetrainParams` | `202 Accepted` (`RetrainJobStatus`) |

---

## 11. AI Agents & Help Router

| Method | Path | Auth / Role | Description | Request Body | Response |
|---|---|:---:|---|---|---|
| `POST` | `/portal/assistant/query` | Authenticated | Chat with Portal Help Assistant | `HelpQueryRequest` (message) | `200 OK` (`HelpQueryResponse`) |
| `POST` | `/agents/admin-assistant/chat` | `admin` | LangGraph Admin Assistant (tenant isolation, aggregation guard, SEC-09) | `AdminAssistantChatRequest` | `200 OK` (`AdminAssistantChatResponse`) |

---

## 12. Parent Reporting Router (`/reports`)

| Method | Path | Auth / Role | Description | Request Body | Response |
|---|---|:---:|---|---|---|
| `POST` | `/reports/parent-report/{student_id}`| `admin`/`teacher` | Generate & email report (timetable check, verified parent_email, SEC-03) | `ParentReportRequest` | `200 OK` (`ParentReportSummary`) |
| `GET` | `/reports/preview/{student_id}` | `admin`/`teacher` | Preview generated narrative report | None | `200 OK` (`ParentReportPreview`) |

---

## 13. Observability Router (`/api/observability`)

| Method | Path | Auth / Role | Description | Request Body | Response |
|---|---|:---:|---|---|---|
| `GET` | `/api/observability/costs` | `admin` | Daily/monthly LLM token & ₹ costs | `?month=10&year=2026` | `200 OK` (`CostMetricsResponse`) |
| `GET` | `/api/observability/traces` | `admin` | Query LangGraph agent trace logs | `?agent=admin_assistant` | `200 OK` (`List[TraceLogItem]`) |
| `GET` | `/api/observability/rag-eval` | `admin` | Retrieve Ragas evaluation metrics | None | `200 OK` (`RAGEvalSummary`) |
| `GET` | `/api/observability/audit-logs`| `admin` | Filter system & AI audit trail | `?user_id=uuid&limit=50` | `200 OK` (`List[AuditLogItem]`) |

