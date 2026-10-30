# EduIntel AI — Database Migrations Architecture

This document specifies the migration architecture, revision history, and schema management practices for EduIntel's PostgreSQL database using Alembic.

---

## 1. Migration Framework & Engine

- **Tooling**: Alembic 1.13+ with SQLAlchemy 2.0 AsyncIO.
- **Async Runner**: Because EduIntel uses the `asyncpg` driver (`postgresql+asyncpg://`), [`backend/alembic/env.py`](file:///home/dell/projects/eduIntel/backend/alembic/env.py) implements an asynchronous migration runner:
  ```python
  async def run_async_migrations():
      connectable = async_engine_from_config(
          config.get_section(config.config_ini_section),
          prefix="sqlalchemy.",
          poolclass=pool.NullPool,
      )
      async with connectable.connect() as connection:
          await connection.run_sync(do_run_migrations)
      await connectable.dispose()
  ```
- **Tracking Table**: Current migration state is tracked in the `alembic_version` table in PostgreSQL.
- **Current Head Revision**: `d4f6a2b5e0c7` (`add_agent_trace_logs_table.py`).

---

## 2. Migration Revision History (20 Revisions)

Below is the chronological sequence of migrations shaping the current database schema:

| Step | Revision ID | Down Revision | Script Name | Core DDL Operations |
|:---:|---|---|---|---|
| **1** | `f987f78a5191` | None | `create_users_and_profile_tables.py` | Creates `users`, `student_profiles`, `teacher_profiles`, `admin_profiles`. |
| **2** | `461bf0704035` | `f987f78a5191` | `create_password_reset_tokens_table.py` | Creates `password_reset_tokens` table with token index and expiry. |
| **3** | `95aa2b163349` | `461bf0704035` | `add_name_to_users_and_contact_fields_to_.py` | Adds name, phone, and emergency contact columns to user profiles. |
| **4** | `5e2def47610c` | `95aa2b163349` | `create_assignments_table.py` | Creates `assignments` table with teacher foreign key and due dates. |
| **5** | `9456897b8a02` | `5e2def47610c` | `create_homework_submission_table.py` | Creates `homework_submissions` table for file uploads and status. |
| **6** | `8c280b7df739` | `9456897b8a02` | `add_extracted_text_to_homework_.py` | Adds `ocr_extracted_text` column to `homework_submissions`. |
| **7** | `88c1537528f3` | `8c280b7df739` | `add_grading_fields_to_homework_.py` | Adds `marks_obtained`, `teacher_feedback`, and `graded_by` columns. |
| **8** | `efdeec24077b` | `88c1537528f3` | `create_doubt_threads_and_messages_tables.py` | Creates `doubt_threads` and `doubt_messages` for the student forum. |
| **9** | `847a7f61eae6` | `efdeec24077b` | `add_study_materials_table.py` | Creates `study_materials` table for teacher-uploaded notes and PDFs. |
| **10**| `29fc63b28fe9` | `847a7f61eae6` | `add_server_defaults_to_study_materials_.py` | Adds `server_default` for timestamps and boolean indexing flags. |
| **11**| `3969e70ec607` | `29fc63b28fe9` | `add_exam_results_table.py` | Creates `exam_results` table for historical student score tracking. |
| **12**| `7cb17547e10e` | `3969e70ec607` | `create_timetable_and_salary_tables.py` | Creates `timetable_entries` and `salary_records` tables. |
| **13**| `851a60e35d84` | `7cb17547e10e` | `add_fee_records_and_attendance_records_.py`| Creates `fee_records` and `attendance_records` tables. |
| **14**| `2d2e369dccb7` | `851a60e35d84` | `add_announcements_table.py` | Creates `announcements` table for institute-wide broadcast notifications. |
| **15**| `361abb3e7a6e` | `2d2e369dccb7` | `add_audit_logs_table.py` | Creates base `audit_logs` table for tracking system actions. |
| **16**| `a1b2c3d4e5f6` | `361abb3e7a6e` | `add_audit_log_redaction_columns.py` | Adds `pii_redactions_count` and `prompt_injection_detected` columns. |
| **17**| `b2c3d4e5f6a7` | `a1b2c3d4e5f6` | `add_audit_log_socratic_columns.py` | Adds `is_socratic_redirect` flag to `doubt_messages` and audit logs. |
| **18**| `c3d4e5f6a7b8` | `b2c3d4e5f6a7` | `add_llm_usage_logs_table.py` | Creates `llm_cost_logs` table tracking token usage and cost in INR (₹). |
| **19**| `7efa432136f2` | `c3d4e5f6a7b8` | `make_datetime_columns_timezone_aware.py` | Converts all timestamp columns across tables to `TIMESTAMPTZ`. |
| **20**| `d4f6a2b5e0c7` | `7efa432136f2` | `add_agent_trace_logs_table.py` | **(HEAD)** Creates `agent_trace_logs` for LangGraph node execution telemetry. |

---

## 3. Developer Migration Workflow

### 3.1. Generating a New Migration
When SQLAlchemy models in `backend/app/*/models.py` are modified:
```bash
cd backend
source venv/bin/activate

# Auto-generate migration script by inspecting models vs current database
alembic revision --autogenerate -m "descriptive_migration_name"
```
*Always inspect the generated file in `backend/alembic/versions/` to verify foreign keys, nullability, and index creation before applying.*

### 3.2. Applying Migrations
```bash
# Upgrade database to latest revision
alembic upgrade head

# Upgrade by a specific number of steps
alembic upgrade +1

# Inspect current revision status
alembic current
```

### 3.3. Rolling Back Migrations
```bash
# Downgrade by 1 revision
alembic downgrade -1

# Roll back to a specific revision ID
alembic downgrade 7efa432136f2
```

---

## 4. Migration Hygiene Gaps & Phase 3 Roadmap

During the Phase 0 and Phase 1 technical audits, the following migration hygiene gaps were cataloged for remediation in Phase 3 (Database Optimization):

1. **Duplicate User Model Definition**: Both `backend/app/auth/models.py` and `backend/app/users/models.py` define a `User` class mapping to `users`. While functionally identical, this creates potential schema drift when generating autogenerated migrations.
   - *Phase 3 Action*: Consolidate all user model declarations into `backend/app/users/models.py` and import into `auth`.
2. **Revision Naming Consistency**: Revisions 16–18 and 20 used manual IDs (`add_agent_trace_logs_table.py`, etc.) rather than standard Alembic generated hexadecimal prefix hashes.
   - *Phase 3 Action*: Standardize all future migration file names to `<hash>_<description>.py`.
3. **Downgrade Verification**: Several early migrations lack complete `downgrade()` drop cascade logic for PostgreSQL enum types.
   - *Phase 3 Action*: Audit and execute bidirectional migration tests (`upgrade head` -> `downgrade base` -> `upgrade head`) in a temporary container.

