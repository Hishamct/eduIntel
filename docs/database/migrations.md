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
- **Current Head Revision**: `a7c8e9d0b1f2` (`0023_a7c8e9d0b1f2_add_multi_tenant_composite_indexes.py`).

---

## 2. Migration Revision History (23 Revisions)

Below is the chronological sequence of migrations shaping the current database schema, organized with standardized 4-digit sequential numeric prefixes (`0001_` through `0023_`):

| Step | Revision ID | Down Revision | Script Name | Core DDL Operations |
|:---:|---|---|---|---|
| **1** | `f987f78a5191` | None | `0001_f987f78a5191_create_users_and_profile_tables.py` | Creates `users`, `student_profiles`, `teacher_profiles`, `admin_profiles`. Cleanly drops custom user role enums on downgrade. |
| **2** | `461bf0704035` | `f987f78a5191` | `0002_461bf0704035_create_password_reset_tokens_table.py` | Creates `password_reset_tokens` table with token index and expiry. |
| **3** | `7efa432136f2` | `461bf0704035` | `0003_7efa432136f2_make_datetime_columns_timezone_aware.py` | Converts all timestamp columns across tables to `TIMESTAMPTZ`. |
| **4** | `9456897b8a02` | `7efa432136f2` | `0004_9456897b8a02_create_homework_submission_table.py` | Creates `homework_submissions` table for file uploads and status. Cleanly drops submission status enum on downgrade. |
| **5** | `efdeec24077b` | `9456897b8a02` | `0005_efdeec24077b_create_doubt_threads_and_messages_tables.py` | Creates `doubt_threads` and `doubt_messages` for the student forum. Cleanly drops thread status and message sender enums on downgrade. |
| **6** | `88c1537528f3` | `efdeec24077b` | `0006_88c1537528f3_add_grading_fields_to_homework_.py` | Adds `marks_obtained`, `teacher_feedback`, and `graded_by` columns. Drops explicit foreign key constraint `fk_homework_submissions_graded_by_users` on downgrade. |
| **7** | `5e2def47610c` | `88c1537528f3` | `0007_5e2def47610c_create_assignments_table.py` | Creates `assignments` table with teacher foreign key and due dates. |
| **8** | `7cb17547e10e` | `5e2def47610c` | `0008_7cb17547e10e_create_timetable_and_salary_tables.py` | Creates `timetable_entries` and `salary_records` tables. Drops day and salary status enums atomically on downgrade. |
| **9** | `95aa2b163349` | `7cb17547e10e` | `0009_95aa2b163349_add_name_to_users_and_contact_fields_to_.py` | Adds name, phone, and emergency contact columns to user profiles. |
| **10**| `8c280b7df739` | `95aa2b163349` | `0010_8c280b7df739_add_extracted_text_to_homework_.py` | Adds `ocr_extracted_text` column to `homework_submissions`. |
| **11**| `847a7f61eae6` | `8c280b7df739` | `0011_847a7f61eae6_add_study_materials_table.py` | Creates `study_materials` table for teacher-uploaded notes and PDFs. |
| **12**| `29fc63b28fe9` | `847a7f61eae6` | `0012_29fc63b28fe9_add_server_defaults_to_study_materials_.py` | Adds `server_default` for timestamps and boolean indexing flags. |
| **13**| `2d2e369dccb7` | `29fc63b28fe9` | `0013_2d2e369dccb7_add_announcements_table.py` | Creates `announcements` table for institute-wide broadcast notifications. |
| **14**| `851a60e35d84` | `2d2e369dccb7` | `0014_851a60e35d84_add_fee_records_and_attendance_records_.py`| Creates `fee_records` and `attendance_records` tables. Drops fee and attendance enums atomically on downgrade. |
| **15**| `3969e70ec607` | `851a60e35d84` | `0015_3969e70ec607_add_exam_results_table.py` | Creates `exam_results` table for historical student score tracking. |
| **16**| `361abb3e7a6e` | `3969e70ec607` | `0016_361abb3e7a6e_add_audit_logs_table.py` | Creates base `audit_logs` table for tracking system actions. |
| **17**| `a1c3f9e2b7d4` | `361abb3e7a6e` | `0017_a1c3f9e2b7d4_add_audit_log_redaction_columns.py` | Adds `pii_redactions_count` and `prompt_injection_detected` columns. |
| **18**| `b2d4e0f3c8a5` | `a1c3f9e2b7d4` | `0018_b2d4e0f3c8a5_add_audit_log_socratic_columns.py` | Adds `is_socratic_redirect` flag to `doubt_messages` and audit logs. |
| **19**| `c3e5f1a4d9b6` | `b2d4e0f3c8a5` | `0019_c3e5f1a4d9b6_add_llm_usage_logs_table.py` | Creates `llm_cost_logs` table tracking token usage and cost in INR (₹). |
| **20**| `d4f6a2b5e0c7` | `c3e5f1a4d9b6` | `0020_d4f6a2b5e0c7_add_agent_trace_logs_table.py` | Creates `agent_trace_logs` for LangGraph node execution telemetry. |
| **21**| `e5a7b9c1d3f5` | `d4f6a2b5e0c7` | `0021_e5a7b9c1d3f5_create_institutions_and_tenant_schema.py` | Creates `institutions`, `institution_memberships`, adds `institution_id` FKs and composite indexes to all 17 tenant tables, seeds & backfills pilot institution. |
| **22**| `f6b8c0d2e4a6` | `e5a7b9c1d3f5` | `0022_f6b8c0d2e4a6_enable_postgresql_rls.py` | Enables and forces PostgreSQL Row-Level Security (RLS) on all 17 tenant-owned tables with `app.current_institution_id` session policies for unprivileged role `eduintel`. |
| **23**| `a7c8e9d0b1f2` | `f6b8c0d2e4a6` | `0023_a7c8e9d0b1f2_add_multi_tenant_composite_indexes.py` | **(HEAD)** Creates 7 composite multi-tenant B-tree indexes across `attendance_records`, `homework_submissions`, `exam_results`, and `fee_records` with `institution_id` leftmost prefix. |

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

## 4. Migration Hygiene Remediations Completed in Phase 3

During Phase 3 (Database Integrity, Performance & Recovery), the following critical migration chain defects and reversibility blockers were permanently resolved:

1. **PostgreSQL Custom ENUM Dropping (Resolved)**:
   - *Problem*: In migrations `0001`, `0004`, `0005`, `0008`, and `0014`, `alembic downgrade` dropped the tables but left custom PostgreSQL ENUM types in `pg_type`. Subsequent `upgrade head` attempts crashed with `DuplicateObject: type already exists`.
   - *Remediation*: Added explicit, atomic `sa.text("DROP TYPE IF EXISTS ... CASCADE")` executions in reverse topological order across all downgrade functions.
2. **`asyncpg` Prepared Statement Syntax (Resolved)**:
   - *Problem*: Downgrades in `0008` and `0014` executed semicolon-spliced SQL (`DROP TYPE a; DROP TYPE b;`), causing `asyncpg.exceptions.PostgresSyntaxError: cannot insert multiple commands into a prepared statement`.
   - *Remediation*: Split every statement into an individual `op.execute(sa.text(...))` call.
3. **Foreign Key Drop Constraints (Resolved)**:
   - *Problem*: Migration `0006` lacked an explicit constraint name when attempting to drop the foreign key on `graded_by`.
   - *Remediation*: Added explicit constraint drop `op.drop_constraint("fk_homework_submissions_graded_by_users", "homework_submissions", type_="foreignkey")`.
4. **Dynamic Database URL in Alembic (`env.py`) (Resolved)**:
   - *Remediation*: Hardened `backend/alembic/env.py` to source `DATABASE_URL` dynamically from environment overrides, enabling testing against disposable UUID databases without altering `alembic.ini`.

---

## 5. Automated Ephemeral Reversibility Harness (`scripts/verify_migrations.sh`)

To guarantee that the migration DAG is 100% reversible without human error, EduIntel provides an automated verification script:

```bash
./scripts/verify_migrations.sh
```

### Safety Policy & Execution Sequence:
1. **Target Safety Guard:** The harness explicitly refuses to execute against protected databases (`eduintel`, `postgres`, `production`, `staging`).
2. **Ephemeral DB Provisioning:** Provisions an isolated database with a random 8-character hex suffix: `eduintel_migration_verify_<hex>`.
3. **Forward Migration (`upgrade head`):** Applies revisions `0001` through `0023`, creating 21 application tables and 7 composite indexes.
4. **Reverse Migration (`downgrade base`):** Rolls back revisions `0023` down to `0001`, verifying that 0 leftover application tables remain and all ENUM types are dropped.
5. **Replay Forward (`upgrade head`):** Re-applies all migrations to head, asserting 100% schema parity with the initial pass.
6. **Primary DB Protection Check:** Asserts that the primary development database `eduintel` on port 5432 remains completely untouched at head revision `a7c8e9d0b1f2`.
7. **Clean Teardown:** Drops the ephemeral test database with `FORCE`.

