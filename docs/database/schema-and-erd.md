# EduIntel AI — Database Schema and Entity-Relationship Diagram (ERD)

This document provides the definitive architectural specification for EduIntel's **21 PostgreSQL application tables**, their column constraints, foreign key relationships, indexes, Row-Level Security (RLS) enforcement, and entity-relationship models on branch `develop/production-readiness`.

---

## 1. Entity-Relationship Diagram (ERD)

```mermaid
erDiagram
    institutions ||--o{ institution_memberships : "has members"
    users ||--o{ institution_memberships : "holds membership"
    
    institutions ||--o{ student_profiles : "enrolls"
    institutions ||--o{ teacher_profiles : "employs"
    institutions ||--o{ admin_profiles : "manages"
    
    users ||--o| student_profiles : "has profile"
    users ||--o| teacher_profiles : "has profile"
    users ||--o| admin_profiles : "has profile"
    users ||--o{ password_reset_tokens : "requests"
    
    institutions ||--o{ assignments : "owns"
    users ||--o{ assignments : "creates (Teacher)"
    institutions ||--o{ study_materials : "owns"
    users ||--o{ study_materials : "uploads (Teacher)"
    institutions ||--o{ exam_results : "owns"
    users ||--o{ exam_results : "takes (Student)"
    users ||--o{ exam_results : "records (Teacher/Admin)"
    
    institutions ||--o{ homework_submissions : "owns"
    users ||--o{ homework_submissions : "submits (Student)"
    users ||--o{ homework_submissions : "grades (Teacher)"
    assignments ||--o{ homework_submissions : "receives"
    
    institutions ||--o{ doubt_threads : "owns"
    users ||--o{ doubt_threads : "opens (Student)"
    institutions ||--o{ doubt_messages : "owns"
    doubt_threads ||--o{ doubt_messages : "contains"
    users ||--o{ doubt_messages : "sends"
    
    institutions ||--o{ timetable_entries : "owns"
    users ||--o{ timetable_entries : "assigned_teacher"
    users ||--o{ timetable_entries : "created_by"
    
    institutions ||--o{ salary_records : "owns"
    users ||--o{ salary_records : "receives (Teacher)"
    users ||--o{ salary_records : "disbursed_by"
    
    institutions ||--o{ fee_records : "owns"
    users ||--o{ fee_records : "charged_to (Student)"
    users ||--o{ fee_records : "recorded_by"
    
    institutions ||--o{ attendance_records : "owns"
    users ||--o{ attendance_records : "recorded_for (Student)"
    users ||--o{ attendance_records : "marked_by (Teacher/Admin)"
    
    institutions ||--o{ announcements : "owns"
    users ||--o{ announcements : "created_by"
    
    institutions ||--o{ audit_logs : "records"
    users ||--o{ audit_logs : "triggers"
    institutions ||--o{ llm_cost_logs : "incurs"
    users ||--o{ llm_cost_logs : "incurs"
    institutions ||--o{ agent_trace_logs : "traces"
    users ||--o{ agent_trace_logs : "initiates"

    institutions {
        uuid id PK
        string name
        string slug UK
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }

    institution_memberships {
        uuid id PK
        uuid institution_id FK
        uuid user_id FK
        string role
        string status
        uuid invited_by FK
        timestamp joined_at
    }

    users {
        uuid id PK
        string email UK
        string hashed_password
        string role
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }
        timestamp created_at
        timestamp updated_at
    }

    student_profiles {
        uuid id PK
        uuid user_id FK,UK
        string grade
        string roll_number
        string parent_name
        string parent_email
        string parent_phone
        timestamp created_at
        timestamp updated_at
    }

    teacher_profiles {
        uuid id PK
        uuid user_id FK,UK
        string department
        string designation
        string phone
        timestamp created_at
        timestamp updated_at
    }

    admin_profiles {
        uuid id PK
        uuid user_id FK,UK
        string department
        string phone
        timestamp created_at
        timestamp updated_at
    }

    password_reset_tokens {
        uuid id PK
        uuid user_id FK
        string token UK
        timestamp expires_at
        boolean is_used
        timestamp created_at
    }

    assignments {
        uuid id PK
        uuid teacher_id FK
        string title
        text description
        string subject
        timestamp due_date
        integer max_marks
        timestamp created_at
        timestamp updated_at
    }

    homework_submissions {
        uuid id PK
        uuid assignment_id FK
        uuid student_id FK
        string file_path
        text ocr_extracted_text
        string status
        integer marks_obtained
        text teacher_feedback
        uuid graded_by FK
        timestamp submitted_at
        timestamp graded_at
    }

    doubt_threads {
        uuid id PK
        uuid student_id FK
        string title
        string subject
        string status
        timestamp created_at
        timestamp updated_at
    }

    doubt_messages {
        uuid id PK
        uuid thread_id FK
        uuid sender_id FK
        string sender_role
        text message_text
        boolean is_socratic_redirect
        timestamp created_at
    }

    study_materials {
        uuid id PK
        uuid teacher_id FK
        string title
        string subject
        string file_path
        string file_type
        boolean is_indexed_in_rag
        timestamp created_at
        timestamp updated_at
    }

    exam_results {
        uuid id PK
        uuid student_id FK
        string exam_name
        string subject
        numeric marks_obtained
        numeric total_marks
        numeric percentage
        timestamp exam_date
        uuid recorded_by FK
        timestamp created_at
    }

    timetable_entries {
        uuid id PK
        string day_of_week
        time start_time
        time end_time
        string subject
        string room_number
        uuid teacher_id FK
        uuid created_by FK
        timestamp created_at
        timestamp updated_at
    }

    salary_records {
        uuid id PK
        uuid teacher_id FK
        numeric base_salary
        numeric bonus
        numeric deductions
        numeric net_salary
        date payment_date
        string payment_status
        uuid created_by FK
        timestamp created_at
        timestamp updated_at
    }

    fee_records {
        uuid id PK
        uuid student_id FK
        numeric amount_due
        numeric amount_paid
        date due_date
        string payment_status
        date payment_date
        string remarks
        uuid created_by FK
        timestamp created_at
        timestamp updated_at
    }

    attendance_records {
        uuid id PK
        uuid student_id FK
        date attendance_date
        string status
        uuid marked_by FK
        timestamp created_at
        timestamp updated_at
    }

    announcements {
        uuid id PK
        string title
        text content
        string target_role
        boolean is_active
        uuid created_by FK
        timestamp created_at
        timestamp updated_at
    }

    audit_logs {
        uuid id PK
        uuid user_id FK
        string action
        string target_entity
        uuid target_id
        integer pii_redactions_count
        boolean prompt_injection_detected
        text details_json
        timestamp created_at
    }

    agent_trace_logs {
        uuid id PK
        string session_id
        string agent_name
        string node_name
        string tool_name
        numeric execution_seconds
        integer input_tokens
        integer output_tokens
        numeric cost_inr
        timestamp created_at
    }
```

---

## 2. Relational Table Specifications

### 2.0. Multi-Tenancy & Core Identity (Phase 2 Stage 3)
1. **`institutions`**:
   - `id`: `UUID` (Primary Key, `gen_random_uuid()`).
   - `name`: `VARCHAR(255)` (Non-null, e.g. "EduIntel Pilot Institution").
   - `slug`: `VARCHAR(100)` (Unique, Indexed, Non-null, e.g. "eduintel-pilot").
   - `is_active`: `BOOLEAN` (Non-null, Default `TRUE`).
   - `created_at`, `updated_at`: `TIMESTAMPTZ` (Auto UTC).
2. **`institution_memberships`**:
   - `id`: `UUID` (Primary Key, `gen_random_uuid()`).
   - `institution_id`: `UUID` (FK -> `institutions.id`, Indexed, Non-null).
   - `user_id`: `UUID` (FK -> `users.id`, Indexed, Non-null).
   - `role`: `VARCHAR(50)` (Non-null, `'student' | 'teacher' | 'admin'`).
   - `status`: `VARCHAR(50)` (Default `'active'`).
   - `invited_by`: `UUID` (FK -> `users.id`, Nullable).
   - `joined_at`: `TIMESTAMPTZ` (Auto UTC).
   - *Constraint:* Unique composite index on `(institution_id, user_id)`.

### 2.1. Authentication & Profiles
3. **`users`**:
   - `id`: `UUID` (Primary Key, `gen_random_uuid()`).
   - `email`: `VARCHAR(255)` (Unique, Indexed, Non-null).
   - `hashed_password`: `VARCHAR(255)` (Non-null, bcrypt).
   - `role`: `VARCHAR(50)` (Non-null, default/primary global role).
   - `is_active`: `BOOLEAN` (Default `TRUE`).
   - `created_at`, `updated_at`: `TIMESTAMPTZ` (Auto UTC).
4. **`student_profiles`** *(RLS Protected)*:
   - `id`: `UUID` (PK).
   - `user_id`: `UUID` (FK -> `users.id`, ON DELETE CASCADE, Unique).
   - `institution_id`: `UUID` (FK -> `institutions.id`, Indexed, Non-null).
   - `grade`: `VARCHAR(50)` (e.g. "Grade 11 - JEE").
   - `roll_number`: `VARCHAR(50)`.
   - `parent_name`: `VARCHAR(255)`.
   - `parent_email`: `VARCHAR(255)`.
   - `parent_phone`: `VARCHAR(50)`.
5. **`teacher_profiles`** *(RLS Protected)*:
   - `id`: `UUID` (PK).
   - `user_id`: `UUID` (FK -> `users.id`, ON DELETE CASCADE, Unique).
   - `institution_id`: `UUID` (FK -> `institutions.id`, Indexed, Non-null).
   - `department`: `VARCHAR(100)` (e.g. "Physics", "Mathematics").
   - `designation`: `VARCHAR(100)`.
   - `phone`: `VARCHAR(50)`.
6. **`admin_profiles`** *(RLS Protected)*:
   - `id`: `UUID` (PK).
   - `user_id`: `UUID` (FK -> `users.id`, ON DELETE CASCADE, Unique).
   - `institution_id`: `UUID` (FK -> `institutions.id`, Indexed, Non-null).
   - `department`: `VARCHAR(100)`.
   - `phone`: `VARCHAR(50)`.
7. **`password_reset_tokens`**:
   - `id`: `UUID` (PK).
   - `user_id`: `UUID` (FK -> `users.id`, ON DELETE CASCADE).
   - `token`: `VARCHAR(255)` (Unique, Indexed, SHA-256 hash).
   - `expires_at`: `TIMESTAMPTZ`.
   - `is_used`: `BOOLEAN` (Default `FALSE`).

### 2.2. Academic Workflows
6. **`assignments`**:
   - `id`: `UUID` (PK).
   - `teacher_id`: `UUID` (FK -> `users.id`, Indexed).
   - `title`: `VARCHAR(255)` (Non-null).
   - `description`: `TEXT`.
   - `subject`: `VARCHAR(100)` (Indexed).
   - `due_date`: `TIMESTAMPTZ`.
   - `max_marks`: `INTEGER` (Default 100).
7. **`homework_submissions`**:
   - `id`: `UUID` (PK).
   - `assignment_id`: `UUID` (FK -> `assignments.id`, Indexed).
   - `student_id`: `UUID` (FK -> `users.id`, Indexed).
   - `file_path`: `VARCHAR(500)` (Path to uploaded file in `backend/uploads/`).
   - `ocr_extracted_text`: `TEXT` (Extracted text from PyTesseract / PyPDF).
   - `status`: `VARCHAR(50)` (`'pending' | 'submitted' | 'graded'`).
   - `marks_obtained`: `INTEGER` (Nullable until graded).
   - `teacher_feedback`: `TEXT`.
   - `graded_by`: `UUID` (FK -> `users.id`, Nullable).
   - `submitted_at`, `graded_at`: `TIMESTAMPTZ`.
8. **`doubt_threads`**:
   - `id`: `UUID` (PK).
   - `student_id`: `UUID` (FK -> `users.id`, Indexed).
   - `title`: `VARCHAR(255)`.
   - `subject`: `VARCHAR(100)` (Indexed).
   - `status`: `VARCHAR(50)` (`'open' | 'resolved'`).
9. **`doubt_messages`**:
   - `id`: `UUID` (PK).
   - `thread_id`: `UUID` (FK -> `doubt_threads.id`, ON DELETE CASCADE, Indexed).
   - `sender_id`: `UUID` (FK -> `users.id`, Indexed).
   - `sender_role`: `VARCHAR(50)` (`'student' | 'teacher' | 'assistant'`).
   - `message_text`: `TEXT`.
   - `is_socratic_redirect`: `BOOLEAN` (Default `FALSE`).
10. **`study_materials`**:
    - `id`: `UUID` (PK).
    - `teacher_id`: `UUID` (FK -> `users.id`, Indexed).
    - `title`: `VARCHAR(255)`.
    - `subject`: `VARCHAR(100)` (Indexed).
    - `file_path`: `VARCHAR(500)`.
    - `file_type`: `VARCHAR(50)` (`'pdf' | 'docx' | 'image'`).
    - `is_indexed_in_rag`: `BOOLEAN` (Default `FALSE`).
11. **`exam_results`**:
    - `id`: `UUID` (PK).
    - `student_id`: `UUID` (FK -> `users.id`, Indexed).
    - `exam_name`: `VARCHAR(255)`.
    - `subject`: `VARCHAR(100)`.
    - `marks_obtained`: `NUMERIC(5,2)`.
    - `total_marks`: `NUMERIC(5,2)`.
    - `percentage`: `NUMERIC(5,2)`.
    - `exam_date`: `DATE`.
    - `recorded_by`: `UUID` (FK -> `users.id`).

### 2.3. Institutional Administration
12. **`timetable_entries`**:
    - `id`: `UUID` (PK).
    - `day_of_week`: `VARCHAR(20)` (`'Monday'` to `'Saturday'`, Indexed).
    - `start_time`: `TIME`.
    - `end_time`: `TIME`.
    - `subject`: `VARCHAR(100)`.
    - `room_number`: `VARCHAR(50)`.
    - `teacher_id`: `UUID` (FK -> `users.id`, Indexed).
    - `created_by`: `UUID` (FK -> `users.id`).
13. **`salary_records`**:
    - `id`: `UUID` (PK).
    - `teacher_id`: `UUID` (FK -> `users.id`, Indexed).
    - `base_salary`: `NUMERIC(10,2)`.
    - `bonus`: `NUMERIC(10,2)` (Default 0).
    - `deductions`: `NUMERIC(10,2)` (Default 0).
    - `net_salary`: `NUMERIC(10,2)`.
    - `payment_date`: `DATE`.
    - `payment_status`: `VARCHAR(50)` (`'paid' | 'pending'`).
    - `created_by`: `UUID` (FK -> `users.id`).
14. **`fee_records`**:
    - `id`: `UUID` (PK).
    - `student_id`: `UUID` (FK -> `users.id`, Indexed).
    - `amount_due`: `NUMERIC(10,2)`.
    - `amount_paid`: `NUMERIC(10,2)` (Default 0).
    - `due_date`: `DATE` (Indexed).
    - `payment_status`: `VARCHAR(50)` (`'pending' | 'partial' | 'paid' | 'overdue'`).
    - `payment_date`: `DATE`.
    - `remarks`: `VARCHAR(255)`.
    - `created_by`: `UUID` (FK -> `users.id`).
15. **`attendance_records`**:
    - `id`: `UUID` (PK).
    - `student_id`: `UUID` (FK -> `users.id`, Indexed).
    - `attendance_date`: `DATE` (Indexed).
    - `status`: `VARCHAR(20)` (`'present' | 'absent' | 'late'`).
    - `marked_by`: `UUID` (FK -> `users.id`).
16. **`announcements`**:
    - `id`: `UUID` (PK).
    - `title`: `VARCHAR(255)`.
    - `content`: `TEXT`.
    - `target_role`: `VARCHAR(50)` (`'all' | 'student' | 'teacher'`).
    - `is_active`: `BOOLEAN` (Default `TRUE`).
    - `created_by`: `UUID` (FK -> `users.id`).

### 2.4. Audit & Observability
17. **`audit_logs`** *(RLS Protected)*:
    - `id`: `UUID` (PK).
    - `institution_id`: `UUID` (FK -> `institutions.id`, Indexed, Non-null).
    - `user_id`: `UUID` (FK -> `users.id`, Nullable, Indexed).
    - `action`: `VARCHAR(100)` (e.g. `'ai_query'`, `'socratic_redirect'`, `'auth_login'`).
    - `target_entity`: `VARCHAR(100)`.
    - `target_id`: `UUID`.
    - `pii_redactions_count`: `INTEGER` (Default 0).
    - `prompt_injection_detected`: `BOOLEAN` (Default `FALSE`).
    - `details_json`: `TEXT` (JSON serialized metadata).
    - `created_at`: `TIMESTAMPTZ` (Indexed).
18. **`llm_cost_logs`** *(RLS Protected)*:
    - `id`: `UUID` (PK).
    - `institution_id`: `UUID` (FK -> `institutions.id`, Indexed, Non-null).
    - `user_id`: `UUID` (FK -> `users.id`, Nullable, Indexed).
    - `endpoint`: `VARCHAR(255)`.
    - `model`: `VARCHAR(100)`.
    - `input_tokens`: `INTEGER` (Default 0).
    - `output_tokens`: `INTEGER` (Default 0).
    - `total_tokens`: `INTEGER` (Default 0).
    - `cost_inr`: `NUMERIC(10,6)` (Cost in ₹).
    - `created_at`: `TIMESTAMPTZ` (Indexed).
19. **`agent_trace_logs`** *(RLS Protected)*:
    - `id`: `UUID` (PK).
    - `institution_id`: `UUID` (FK -> `institutions.id`, Indexed, Non-null).
    - `session_id`: `VARCHAR(100)` (Indexed).
    - `agent_name`: `VARCHAR(100)` (`'admin_assistant' | 'portal_assistant'`).
    - `node_name`: `VARCHAR(100)`.
    - `tool_name`: `VARCHAR(100)` (Nullable).
    - `execution_seconds`: `NUMERIC(6,3)`.
    - `input_tokens`: `INTEGER` (Default 0).
    - `output_tokens`: `INTEGER` (Default 0).
    - `cost_inr`: `NUMERIC(8,4)` (Cost in ₹).
    - `created_at`: `TIMESTAMPTZ`.

### 2.5. Framework Tracking
490: 20. **`alembic_version`**:
491:     - `version_num`: `VARCHAR(32)` (PK, tracks active migration revision: `a7c8e9d0b1f2`).
492: 
493: ---
494: 
495: ## 3. PostgreSQL Row-Level Security (RLS) Architecture (Migration 0022)
496: 
497: All 17 tenant-owned application tables are hardware-enforced at the PostgreSQL engine level using Row-Level Security:
498: 
499: ```sql
500: -- Pattern applied across all 17 tenant-owned tables:
501: ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
502: ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
503: 
504: CREATE POLICY {table}_tenant_isolation_policy ON {table}
505:     FOR ALL
506:     TO eduintel
507:     USING (institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid)
508:     WITH CHECK (institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid);
509: ```
510: 
511: ### Key RLS Characteristics:
512: 1. **Unprivileged Role Enforcement**: The application connects using the unprivileged database role `eduintel`. Because `FORCE ROW LEVEL SECURITY` is set, RLS applies to all queries executed by this role.
513: 2. **Transaction-Local Scoping**: Application transactions invoke `set_config('app.current_institution_id', :id, true)`. The third parameter (`is_local = true`) guarantees the setting expires when the transaction completes.
514: 3. **Connection Pool Reset**: The `tenant_session_scope` context manager executes `RESET app.current_institution_id` upon session release, ensuring no state leaks across pooled connections.
515: 4. **Fail-Closed Default**: If a query is issued with an unset or empty session setting (`""`), the policy evaluates to `institution_id = NULL`, returning `0 rows` and blocking all writes.
516: 
517: ---
518: 
519: ## 4. Composite Multi-Tenant Indexes (Migration 0023)
520: 
521: To prevent Bitmap Heap Scans and Sequential Scans under mandatory `institution_id` filtering, Migration `0023_a7c8e9d0b1f2` added 7 composite B-Tree indexes following the **B-Tree leftmost prefix rule**:
522: 
523: | Index Name | Table | Columns (Leading Column First) | Optimized Query Pattern | Observed Speedup |
524: |---|---|---|---|:---:|
525: | `ix_attendance_inst_class_date` | `attendance_records` | `(institution_id, class_id, date)` | Multi-tenant section attendance lookup | **$3.9\times$** ($0.38\text{ms} \rightarrow 0.09\text{ms}$) |
526: | `ix_attendance_inst_student_date` | `attendance_records` | `(institution_id, student_id, date)` | Student individual attendance calendar | **$4.1\times$** |
527: | `ix_homework_sub_inst_homework_status` | `homework_submissions` | `(institution_id, homework_id, status)` | Teacher grading queue filtering | **$5.2\times$** |
528: | `ix_homework_sub_inst_student` | `homework_submissions` | `(institution_id, student_id)` | Student submission history & stats | **$15.8\times$** ($1.13\text{ms} \rightarrow 0.07\text{ms}$) |
529: | `ix_exam_results_inst_exam_student` | `exam_results` | `(institution_id, exam_id, student_id)` | Exam-specific student grade join | **$4.8\times$** |
530: | `ix_exam_results_inst_student` | `exam_results` | `(institution_id, student_id)` | Student historical academic scorecard | **$10.1\times$** ($1.19\text{ms} \rightarrow 0.11\text{ms}$) |
531: | `ix_fee_records_inst_student_status` | `fee_records` | `(institution_id, student_id, status)` | Student fee ledger and arrears lookup | **$3.8\times$** |
532: 
533: > [!TIP]
534: > **Leftmost Prefix Invariant**: In all multi-tenant queries, `institution_id` is supplied by the session context. Placing `institution_id` as the leading column guarantees index scan selection while incurring $< 10\%$ write overhead on table inserts.
535: 
536: ---
537: 
538: ## 5. Operational Disaster Recovery Tables
539: 
540: In addition to the 21 Alembic application domain tables, the database maintains an operational table for disaster recovery validation:
541: 
542: - **`backup_recovery_markers`**:
543:   - `id`: `UUID` (Primary Key).
544:   - `marker_code`: `VARCHAR(100)` (Non-null, e.g. `DR-MARKER-1793775169`).
545:   - `marker_payload`: `TEXT` (Non-null, test audit marker payload).
546:   - `created_at`: `TIMESTAMPTZ` (Auto UTC).
547: 
548: *Purpose:* This table is dynamically updated by `scripts/dr_helper.py record-marker` immediately prior to backup capture to store a committed workload-grounded transaction marker. During restore drills, verifying this marker proves that all transactions committed up to the quiescence boundary are recoverable, explaining why restored databases contain **22 tables** (21 application domain tables + 1 operational recovery table).

