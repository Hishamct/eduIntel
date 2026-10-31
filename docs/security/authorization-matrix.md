# EduIntel AI — Complete Authorization & RBAC Matrix

**Audit Date:** October 30, 2026  
**Auditor:** Principal Software Architect & Application Security Engineer  
**Scope:** All 57 API endpoints mounted in [`backend/app/main.py`](file:///home/dell/projects/eduIntel/backend/app/main.py)  
**Classification:** Internal Architectural & Security Assessment

---

## 1. Executive Summary

EduIntel's existing authorization system relies on a **flat, single-dimension role string** (`role = 'student' | 'teacher' | 'admin'`) stored directly on the `users` table, enforced through FastAPI's `require_role(*allowed_roles)` dependency in [`backend/app/users/dependencies.py`](file:///home/dell/projects/eduIntel/backend/app/users/dependencies.py).

### Critical Findings:
1. **Total Absence of Multi-Tenancy:** Not a single endpoint or database query validates institution ownership or tenant boundaries. Every query executes across the entire shared database table.
2. **Missing Platform Administrator Role:** There is no distinct platform-level administrative role (`platform_admin` / `super_admin`). All administrative functions are held by institute-level `admin` users, meaning any admin has full visibility and control over all global data.
3. **Completely Unauthenticated Sensitive Endpoints:**
   - `POST /reports/parent-report/{student_id}`: Allows anonymous users to trigger LLM parent reports and dispatch emails to arbitrary recipients.
   - `POST /ocr/extract`: Allows anonymous image upload and CPU-heavy Tesseract OCR extraction.
   - `GET /rag/collections`: Exposes vector collection names and counts to anonymous callers.
4. **Severe IDOR Vulnerabilities Across Portals:**
   - Teachers can grade or download homework submissions from *any* student in the database.
   - Students can download study materials uploaded by teachers of *any* institute.
   - Teachers can inspect ML risk scores, SHAP explanations, and topic diagnoses for *any* student UUID.
   - Admins can modify profile details for any student across the database.
5. **Privilege Escalation via Public Registration:**
   - `POST /auth/signup` permits arbitrary self-registration with `role: "admin"`.
6. **Frontend Demo Mode Bypass:**
   - `localStorage.getItem("demo_mode")` allows unauthenticated navigation past React route guards.

---

## 2. Comprehensive Endpoint Authorization Matrix

The table below catalogs every endpoint, the source file and line defining it, its current authentication and authorization enforcement, verified runtime behavior, cross-tenant risk, and recommended target RBAC/ABAC rules.

### Legend:
- 🟢 **Enforced**: Role correctly checked on the backend.
- 🟡 **Partial / Weak**: Role checked, but lacks resource ownership, tenant validation, or parameter binding.
- 🔴 **Vulnerable / Missing**: Missing authentication, IDOR, or unrestricted access.

| # | Method | Endpoint Path | Source File & Function | Current Auth Dependency | Verified Runtime Behavior | Multi-Tenant Cross-Tenant Risk | Recommended Target Role & Scope |
|---|---|---|---|---|---|---|---|
| **Health & Core** | | | | | | | |
| 1 | `GET` | `/health` | [`main.py:42`](file:///home/dell/projects/eduIntel/backend/app/main.py#L42) `health_check` | None (Public) | Returns `{"status": "ok"}` | None (System status) | Public |
| **Authentication Router (`/auth`)** | | | | | | | |
| 2 | `POST` | `/auth/signup` | [`auth/router.py:19`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py#L19) `signup` | None | Returns `403 Forbidden` | 🟢 **Remediated (SEC-02):** Public self-registration completely disabled | Disabled (Accounts provisioned via `/admin/*`) |
| 3 | `POST` | `/auth/login` | [`auth/router.py:29`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py#L29) `login` | None (Public) | Verifies email & bcrypt password, sets `HttpOnly` cookie | 🟢 **Remediated (SEC-10):** Cookie with `HttpOnly`, `SameSite=Strict`, `Path=/`, environment-aware `Secure` | Public |
| 4 | `POST` | `/auth/password-reset/request` | [`auth/router.py:38`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py#L38) `password_reset_request` | `Depends(password_reset_limiter)` | Generates 32-byte token, hashes with SHA-256 at rest, dispatches email in background | 🟢 **Remediated (SEC-01):** Zero token disclosure; IP/email rate limiter (5 req/min) | Public |
| 5 | `POST` | `/auth/password-reset/confirm` | [`auth/router.py:53`](file:///home/dell/projects/eduIntel/backend/app/auth/router.py#L53) `password_reset_confirm` | None (Public) | Hashes supplied token via SHA-256, matches hash at rest, single-use consumed | 🟢 **Remediated (SEC-01):** Cryptographic verification; invalidates upon use | Public |
| **Users Router (`/users`)** | | | | | | | |
| 6 | `GET` | `/users/me` | [`users/router.py:19`](file:///home/dell/projects/eduIntel/backend/app/users/router.py#L19) `get_current_user_profile` | `get_current_user` | Returns user details and profile | 🟡 Returns single profile, lacks tenant membership list | Authenticated User (Scoped to active tenant) |
| 7 | `PUT` | `/users/me` | [`users/router.py:28`](file:///home/dell/projects/eduIntel/backend/app/users/router.py#L28) `update_user_profile` | `get_current_user` | Updates user's own profile fields | 🟢 Scoped to `current_user.id` | Authenticated User (Own profile) |
| **Student Portal Router (`/student`)** | | | | | | | |
| 8 | `GET` | `/student/dashboard` | [`student/router.py:34`](file:///home/dell/projects/eduIntel/backend/app/student/router.py#L34) `student_dashboard` | `require_role("student")` | Scoped to `current_user.id` | 🟢 Low (User-scoped) | `student` (Own tenant & profile) |
| 9 | `POST` | `/student/homework/upload` | [`student/router.py:50`](file:///home/dell/projects/eduIntel/backend/app/student/router.py#L50) `upload_homework` | `require_role("student")` | Saves file to shared `uploads/homework` | 🟡 No tenant folder separation; filename collision risk | `student` (Own tenant submission) |
| 10 | `GET` | `/student/homework` | [`student/router.py:70`](file:///home/dell/projects/eduIntel/backend/app/student/router.py#L70) `list_homework` | `require_role("student")` | Returns submissions for `current_user.id` | 🟢 Low (User-scoped) | `student` (Own submissions) |
| 11 | `POST` | `/student/doubts` | [`student/router.py:84`](file:///home/dell/projects/eduIntel/backend/app/student/router.py#L84) `post_doubt` | `require_role("student")` | Creates thread for `current_user.id` | 🟡 No institution ID on thread | `student` (Scoped to tenant & class) |
| 12 | `GET` | `/student/doubts` | [`student/router.py:100`](file:///home/dell/projects/eduIntel/backend/app/student/router.py#L100) `get_doubts` | `require_role("student")` | Lists threads for `current_user.id` | 🟢 Low (User-scoped) | `student` (Own threads within tenant) |
| 13 | `POST` | `/student/doubts/{thread_id}/messages` | [`student/router.py:109`](file:///home/dell/projects/eduIntel/backend/app/student/router.py#L109) `reply_to_doubt` | `require_role("student")` | Adds message to `thread_id` | 🔴 **High (IDOR):** Any student can reply to any other student's thread across institutes | `student` (Thread owner or classmate in same tenant) |
| 14 | `GET` | `/student/assignments` | [`student/router.py:126`](file:///home/dell/projects/eduIntel/backend/app/student/router.py#L126) `get_student_assignments` | `require_role("student")` | Returns ALL assignments in entire DB | 🔴 **High:** Leaks all assignments from all institutes | `student` (Enrolled sections in same tenant) |
| 15 | `GET` | `/student/study-materials` | [`student/router.py:139`](file:///home/dell/projects/eduIntel/backend/app/student/router.py#L139) `get_study_materials` | `require_role("student")` | Returns ALL study materials in DB | 🔴 **High:** Leaks proprietary study materials across institutes | `student` (Enrolled sections in same tenant) |
| 16 | `GET` | `/student/study-materials/{material_id}/file` | [`student/router.py:148`](file:///home/dell/projects/eduIntel/backend/app/student/router.py#L148) `download_study_material_file` | `require_role("student")` | Downloads file by `material_id` UUID | 🟢 **Remediated (SEC-06):** Section enrollment verified before file returned | `student` (Section-enrolled student) |
| **Teacher Portal Router (`/teacher`)** | | | | | | | |
| 17 | `GET` | `/teacher/dashboard` | [`teacher/router.py:31`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py#L31) `teacher_dashboard` | `require_role("teacher")` | Aggregates DB-wide student/grading counts | 🔴 **High:** Aggregates data across all institutes | `teacher` (Scoped to teacher's classes in tenant) |
| 18 | `PATCH` | `/teacher/homework/{submission_id}/grade` | [`teacher/router.py:46`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py#L46) `grade_homework` | `require_role("teacher")` | Updates marks and feedback on submission | 🔴 **High (IDOR):** Any teacher can grade any submission across institutes | `teacher` (Assigned teacher in same tenant) |
| 19 | `GET` | `/teacher/homework` | [`teacher/router.py:64`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py#L64) `get_all_submissions` | `require_role("teacher")` | Returns all submissions in entire DB | 🔴 **High:** Leaks all student homework globally | `teacher` (Assigned classes in same tenant) |
| 20 | `POST` | `/teacher/assignments` | [`teacher/router.py:75`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py#L75) `post_assignment` | `require_role("teacher")` | Creates assignment with `teacher_id` | 🟡 No tenant ID stored | `teacher` (Active tenant & assigned class) |
| 21 | `GET` | `/teacher/assignments` | [`teacher/router.py:94`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py#L94) `get_assignments` | `require_role("teacher")` | Lists all assignments in DB | 🔴 **High:** Leaks assignments across institutes | `teacher` (Created by self or dept in same tenant) |
| 22 | `POST` | `/teacher/study-materials/upload` | [`teacher/router.py:104`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py#L104) `upload_study_material` | `require_role("teacher")` | Uploads file and ingests into ChromaDB | 🟡 Flat file directory; ChromaDB lacks tenant metadata | `teacher` (Active tenant directory & metadata) |
| 23 | `GET` | `/teacher/study-materials` | [`teacher/router.py:123`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py#L123) `get_study_materials` | `require_role("teacher")` | Lists all study materials globally | 🔴 **High:** Cross-tenant study material exposure | `teacher` (Active tenant) |
| 24 | `GET` | `/teacher/homework/{submission_id}/file` | [`teacher/router.py:137`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py#L137) `download_homework_file` | `require_role("teacher")` | Returns physical file for `submission_id` | 🟢 **Remediated (SEC-06):** Verifies student ownership or teacher timetable/grader assignment | `teacher` (Assigned grader or student owner) |
| 25 | `GET` | `/teacher/students` | [`teacher/router.py:161`](file:///home/dell/projects/eduIntel/backend/app/teacher/router.py#L161) `get_teacher_students` | `require_role("teacher")` | Lists students from DB | 🔴 **High:** Returns students from all institutes | `teacher` (Students enrolled in teacher's sections) |
| **Admin Portal Router (`/admin`)** | | | | | | | |
| 26 | `GET` | `/admin/dashboard` | [`admin/router.py:34`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L34) `admin_dashboard` | `require_role("admin")` | Returns total student & teacher counts DB-wide | 🔴 **High:** Global cross-tenant metrics | `institute_admin` (Tenant-scoped counts) |
| 27 | `POST` | `/admin/timetable` | [`admin/router.py:51`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L51) `post_timetable_entry` | `require_role("admin")` | Inserts timetable entry | 🟡 No tenant ID recorded | `institute_admin` (Active tenant) |
| 28 | `GET` | `/admin/timetable` | [`admin/router.py:69`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L69) `get_timetable` | `require_role("admin")` | Lists all timetables globally | 🔴 **High:** Leaks room/teacher schedules across institutes | `institute_admin` (Active tenant) |
| 29 | `POST` | `/admin/salary` | [`admin/router.py:79`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L79) `post_salary_record` | `require_role("admin")` | Records teacher salary disbursement | 🟡 Does not verify if `teacher_id` belongs to admin's institute | `institute_admin` (Teacher verified in tenant) |
| 30 | `GET` | `/admin/salary` | [`admin/router.py:98`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L98) `get_salary_records` | `require_role("admin")` | Lists all salary records in DB | 🔴 **Critical:** Leaks confidential teacher compensation globally | `institute_admin` (Own tenant teachers only) |
| 31 | `GET` | `/admin/teachers` | [`admin/router.py:108`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L108) `get_teachers` | `require_role("admin")` | Lists all teachers in DB | 🔴 **High:** Exposes full teacher directory of all institutes | `institute_admin` (Own tenant teachers only) |
| 32 | `POST` | `/admin/students` | [`admin/router.py:117`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L117) `post_student` | `require_role("admin")` | Enrolls new student | 🟡 Creates user globally without tenant association | `institute_admin` (Enrolls student into own tenant) |
| 33 | `GET` | `/admin/students` | [`admin/router.py:140`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L140) `get_students` | `require_role("admin")` | Lists all students in DB | 🔴 **High:** Exposes all students and guardian PII across institutes | `institute_admin` (Own tenant students only) |
| 34 | `PATCH` | `/admin/students/{student_id}` | [`admin/router.py:163`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L163) `patch_student` | `require_role("admin")` | Modifies student profile by UUID | 🔴 **Critical (IDOR):** Any admin can modify another institute's student records | `institute_admin` (Verified student in own tenant) |
| 35 | `GET` | `/admin/debug/student-teacher-counts` | [`admin/router.py:185`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L185) `debug_student_teacher_counts` | `require_role("admin")` | Returns global student/teacher count | 🔴 **High:** Cross-tenant aggregation | Platform Admin only or tenant-scoped |
| 36 | `GET` | `/admin/debug/salary-summary` | [`admin/router.py:193`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L193) `debug_salary_summary` | `require_role("admin")` | Returns global salary sums and status | 🔴 **Critical:** Leaks total institutional payroll amounts | `institute_admin` (Tenant-scoped) / `platform_admin` |
| 37 | `GET` | `/admin/debug/timetable-coverage` | [`admin/router.py:202`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L202) `debug_timetable_coverage` | `require_role("admin")` | Returns global timetable slot coverage | 🔴 **High:** Cross-tenant scheduling metrics | `institute_admin` (Tenant-scoped) |
| 38 | `GET` | `/admin/debug/teacher-grading-performance` | [`admin/router.py:211`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L211) `debug_teacher_grading_performance` | `require_role("admin")` | Returns grading turnaround for all teachers | 🔴 **High:** Teacher performance leaked across institutes | `institute_admin` (Tenant-scoped) |
| 39 | `GET` | `/admin/debug/revenue-summary` | [`admin/router.py:219`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L219) `debug_revenue_summary` | `require_role("admin")` | Returns global fee collections and arrears | 🔴 **Critical:** Institutional financial leak | `institute_admin` (Tenant-scoped) / `platform_admin` |
| 40 | `GET` | `/admin/debug/attendance-stats` | [`admin/router.py:228`](file:///home/dell/projects/eduIntel/backend/app/admin/router.py#L228) `debug_attendance_stats` | `require_role("admin")` | Returns global attendance rates | 🔴 **High:** Cross-tenant attendance metrics | `institute_admin` (Tenant-scoped) |
| **AI Agents Router (`/agents`)** | | | | | | | |
| 41 | `POST` | `/agents/portal-assistant/chat` | [`agents/router.py:14`](file:///home/dell/projects/eduIntel/backend/app/agents/router.py#L14) `portal_assistant_chat` | `require_role("student")` | Queries ChromaDB `portal_help_docs` | 🟡 `session_id` untrusted from client; no tenant metadata | `student` (Session tied to user & tenant) |
| 42 | `POST` | `/agents/admin-assistant/chat` | [`agents/router.py:51`](file:///home/dell/projects/eduIntel/backend/app/agents/router.py#L51) `admin_assistant_chat` | `require_role("admin")` | Executes 6 tools calling DB services | 🟢 **Remediated (SEC-09):** `TenantAggregationBlockedError` fails closed on multi-tenant aggregation; session memory isolated | `institute_admin` (Tenant-scoped session and tools) |
| **Announcements Router (`/announcements`)** | | | | | | | |
| 43 | `GET` | `/announcements` | [`announcements/router.py:15`](file:///home/dell/projects/eduIntel/backend/app/announcements/router.py#L15) `get_announcements` | `get_current_user` | Lists announcements filtered by role | 🔴 **High:** Announcements from Institute A visible to Institute B | Authenticated User (Scoped to tenant & role) |
| 44 | `POST` | `/announcements` | [`announcements/router.py:35`](file:///home/dell/projects/eduIntel/backend/app/announcements/router.py#L35) `post_announcement` | `require_role("admin")` | Publishes announcement globally | 🟡 No tenant ID on announcement record | `institute_admin` (Scoped to active tenant) |
| **OCR Router (`/ocr`)** | | | | | | | |
| 45 | `POST` | `/ocr/extract` | [`ocr/router.py:11`](file:///home/dell/projects/eduIntel/backend/app/ocr/router.py#L11) `extract_text_from_image` | `get_current_user` | Executes Tesseract OCR with 5 MB limit, magic bytes, worker semaphore | 🟢 **Remediated (SEC-05):** Auth enforced; DoS mitigations active (`MAX_CONCURRENT_OCR_WORKERS=2`, 10s timeout) | Authenticated User (`student` or `teacher`) |
| **RAG Router (`/rag`)** | | | | | | | |
| 46 | `GET` | `/rag/collections` | [`rag/router.py:20`](file:///home/dell/projects/eduIntel/backend/app/rag/router.py#L20) `list_collection_status` | None (**Unauthenticated!**) | Returns document counts of vector collections | 🟡 Exposes internal collection metrics | `platform_admin` or Authenticated Admin |
| 47 | `POST` | `/rag/query` | [`rag/router.py:33`](file:///home/dell/projects/eduIntel/backend/app/rag/router.py#L33) `query_rag` | `get_current_user` | Queries ChromaDB with mandatory tenant filter | 🟢 **Remediated (SEC-08):** `where={"institution_id": ...}` enforced; fails closed on missing tenant | Authenticated User (Metadata filtered by `institution_id`) |
| 48 | `GET` | `/rag/debug-query` | [`rag/router.py:64`](file:///home/dell/projects/eduIntel/backend/app/rag/router.py#L64) `debug_query` | `require_role("admin")` | Raw vector similarity search with tenant filter | 🟢 **Remediated (SEC-08):** Restricted to `admin` with mandatory tenant filtering | `admin` (Tenant-scoped) |
| **Machine Learning Router (`/ml`)** | | | | | | | |
| 49 | `GET` | `/ml/predict/at-risk/{student_id}` | [`ml/router.py:16`](file:///home/dell/projects/eduIntel/backend/app/ml/router.py#L16) `predict_at_risk` | `require_role("teacher", "admin")` | Runs XGBoost on student's full history | 🟢 **Remediated (SEC-07):** Teacher section assignment verified via timetable; admin oversight | `teacher` (Assigned section) / `admin` |
| 50 | `GET` | `/ml/predict/at-risk-admin/{student_id}` | [`ml/router.py:26`](file:///home/dell/projects/eduIntel/backend/app/ml/router.py#L26) `predict_at_risk_admin` | `require_role("admin")` | Runs XGBoost on student's full history | 🟢 **Remediated (SEC-07):** Preserved for admin oversight with student profile validation | `admin` (Verified student) |
| 51 | `GET` | `/ml/explain/at-risk/{student_id}` | [`ml/router.py:36`](file:///home/dell/projects/eduIntel/backend/app/ml/router.py#L36) `explain_at_risk` | `require_role("teacher", "admin")` | Computes SHAP values on student history | 🟢 **Remediated (SEC-07):** Teacher section assignment verified via timetable; admin oversight | `teacher` (Assigned section) / `admin` |
| 52 | `GET` | `/ml/predict/weak-topics/{student_id}` | [`ml/router.py:46`](file:///home/dell/projects/eduIntel/backend/app/ml/router.py#L46) `predict_weak_topics` | `require_role("teacher", "admin")` | Evaluates subject/topic weakness model | 🟢 **Remediated (SEC-07):** Teacher section assignment verified via timetable; admin oversight | `teacher` (Assigned section) / `admin` |
| 53 | `GET` | `/ml/diagnose/{student_id}` | [`ml/router.py:59`](file:///home/dell/projects/eduIntel/backend/app/ml/router.py#L59) `diagnose_student_endpoint` | `require_role("teacher", "admin")` | Generates diagnostic summary | 🟢 **Remediated (SEC-07):** Teacher section assignment verified via timetable; admin oversight | `teacher` (Assigned section) / `admin` |
| 54 | `GET` | `/ml/diagnose-with-recommendations/{student_id}` | [`ml/router.py:73`](file:///home/dell/projects/eduIntel/backend/app/ml/router.py#L73) `diagnose_with_recommendations` | `require_role("teacher", "admin")` | Diagnosis + RAG study material lookup | 🟢 **Remediated (SEC-07, SEC-08):** Teacher section check + RAG tenant metadata filter | `teacher` (Assigned section) / `admin` |
| 55 | `GET` | `/ml/recommend-topic` | [`ml/router.py:91`](file:///home/dell/projects/eduIntel/backend/app/ml/router.py#L91) `recommend_for_topic` | `require_role("teacher", "admin")` | RAG retrieval on subject/topic | 🟢 **Remediated (SEC-08):** Queries tenant-filtered ChromaDB study materials | `teacher` (Tenant-scoped study materials) |
| 56 | `GET` | `/ml/generate-worksheet` | [`ml/router.py:114`](file:///home/dell/projects/eduIntel/backend/app/ml/router.py#L114) `generate_worksheet` | `require_role("teacher")` | Generates PDF worksheet via ReportLab | 🟢 Safe (Procedural generation) | `teacher` (Scoped to tenant curriculum) |
| **Reports Router (`/reports`)** | | | | | | | |
| 57 | `POST` | `/reports/parent-report/{student_id}` | [`reports/router.py:18`](file:///home/dell/projects/eduIntel/backend/app/reports/router.py#L18) `trigger_parent_report` | `require_role("teacher", "admin")` | Generates LLM narrative and dispatches to verified parent email | 🟢 **Remediated (SEC-03):** Multi-factor timetable/submissions authorization; no email override | `teacher` (Assigned section/submissions) / `admin` |
| **Observability Router (`/observability`)** | | | | | | | |
| 58 | `GET` | `/observability/summary` | [`observability/router.py:19`](file:///home/dell/projects/eduIntel/backend/app/observability/router.py#L19) `get_observability_summary` | `require_role("admin")` | Returns global LLM tokens, costs in ₹, and quotas | 🔴 **High:** Leaks entire platform LLM billing to any institute admin | `platform_admin` (Global) / `institute_admin` (Tenant tokens only) |
| 59 | `GET` | `/observability/traces` | [`observability/router.py:36`](file:///home/dell/projects/eduIntel/backend/app/observability/router.py#L36) `get_agent_traces` | `require_role("admin")` | Lists LangGraph node traces across all users | 🔴 **High:** Any admin sees agent execution traces of other institutes | `platform_admin` / Tenant-scoped |
| 60 | `GET` | `/observability/audit-logs` | [`observability/router.py:53`](file:///home/dell/projects/eduIntel/backend/app/observability/router.py#L53) `get_audit_logs` | `require_role("admin")` | Returns raw audit logs containing unredacted `query_text` | 🔴 **Critical:** Exposes prompts, queries, and PII across all tenants | `platform_admin` / Tenant-scoped with PII masking |

*(Note: Total endpoints count is 60 including root `/health`, `/admin/debug/*` endpoints, and `/observability` routes).*

---

## 3. High-Level Resource Permissions Matrix

This matrix maps user roles to major domain resources in the **target multi-tenant architecture**:

| Domain Resource | Platform Admin | Institute Admin | Teacher | Student | Public / Anonymous |
|---|:---:|:---:|:---:|:---:|:---:|
| **Manage Institutions** | ✅ Full CRUD | ❌ No | ❌ No | ❌ No | ❌ No |
| **Institute Configuration** | ✅ Override | ✅ Own Institute | ❌ No | ❌ No | ❌ No |
| **Invite & Assign Users** | ✅ Global | ✅ Own Institute | ❌ No | ❌ No | ❌ No |
| **View Students** | ✅ Audit Mode | ✅ Own Institute | ✅ Assigned Classes | ❌ Self Only | ❌ No |
| **Modify Student Profile** | ✅ Audit Mode | ✅ Own Institute | 🟡 Notes/Grade Only | 🟡 Basic Info Only | ❌ No |
| **View Attendance** | ✅ Audit Mode | ✅ Own Institute | ✅ Assigned Classes | ✅ Own History | ❌ No |
| **Mark Attendance** | ❌ No | ✅ Own Institute | ✅ Assigned Classes | ❌ No | ❌ No |
| **Create Assignments** | ❌ No | ✅ Own Institute | ✅ Assigned Classes | ❌ No | ❌ No |
| **Submit Homework** | ❌ No | ❌ No | ❌ No | ✅ Own Classes | ❌ No |
| **Grade Submissions** | ❌ No | 🟡 View Only | ✅ Assigned Classes | ❌ No | ❌ No |
| **Download Submissions** | ❌ No | 🟡 Audit Mode | ✅ Assigned Classes | ✅ Own Files | ❌ No |
| **Post Study Materials** | ❌ No | ✅ Own Institute | ✅ Own Subject | ❌ No | ❌ No |
| **Download Study Materials**| ❌ No | ✅ Own Institute | ✅ Own Institute | ✅ Enrolled Classes | ❌ No |
| **Create Examinations** | ❌ No | ✅ Own Institute | ✅ Assigned Subject | ❌ No | ❌ No |
| **Record Exam Results** | ❌ No | ✅ Own Institute | ✅ Assigned Subject | ❌ No | ❌ No |
| **View Exam Results** | ✅ Audit Mode | ✅ Own Institute | ✅ Assigned Classes | ✅ Own Results | ❌ No |
| **Timetable Management** | ❌ No | ✅ Own Institute | 👁️ View Assigned | 👁️ View Class | ❌ No |
| **Salary / Payroll Records**| ❌ No | ✅ Own Institute | 👁️ Own Salary | ❌ No | ❌ No |
| **Fee / Revenue Records** | ❌ No | ✅ Own Institute | ❌ No | 👁️ Own Fees | ❌ No |
| **AI Portal Assistant** | ❌ No | ❌ No | ❌ No | ✅ Scoped Session | ❌ No |
| **AI Admin Assistant** | ❌ No | ✅ Own Institute | ❌ No | ❌ No | ❌ No |
| **Trigger Parent Reports** | ❌ No | ✅ Own Institute | ✅ Assigned Students| ❌ No | ❌ No |
| **ML Predictions & SHAP** | ❌ No | ✅ Own Institute | ✅ Assigned Students| ❌ No | ❌ No |
| **Global Observability** | ✅ All Tenants | ❌ No | ❌ No | ❌ No | ❌ No |
| **Tenant Token Usage** | ✅ All Tenants | ✅ Own Institute | ❌ No | ❌ No | ❌ No |
| **Audit Logs** | ✅ Platform-wide | ✅ Own Institute | ❌ No | ❌ No | ❌ No |

---

## 4. Key Authorization Defect Patterns & Remediation

### 4.1. The Missing Tenant Context Pattern
- **Defect:** Routes currently verify identity (`User.id`) and role string (`User.role`), but queries do not filter by institution (`institution_id`).
- **Remediation:** Introduce a mandatory tenant-context extraction dependency `get_current_tenant_membership()` that injects both the user's active `institution_id` and their institution-specific role into request state, backed by PostgreSQL Row-Level Security (`SET LOCAL app.current_institution_id`).

### 4.2. Insecure Direct Object References (IDOR)
- **Defect:** Routes like `/teacher/homework/{submission_id}/file` and `/ml/predict/at-risk/{student_id}` accept a path parameter and query the entity directly without verifying whether it belongs to the caller's institution or class assignment.
- **Remediation:** Enforce two-stage authorization:
  1. **Database RLS:** The query automatically filters out records where `institution_id != app.current_institution_id`, returning HTTP 404 if the resource belongs to another institution.
  2. **Application ABAC:** For resources within the same institution, verify fine-grained ownership (e.g. `teacher.id in assignment.teachers` or `submission.student_id == current_user.id`).

### 4.3. Unauthenticated Public Endpoints
- **Defect:** `/ocr/extract` and `/reports/parent-report/{student_id}` lack all authentication decorators.
- **Remediation:**
  - Add `Depends(get_current_user)` and `Depends(require_role("teacher", "admin"))` to `/reports/parent-report/{student_id}`.
  - Add `Depends(get_current_user)` and rate limiting to `/ocr/extract`.

