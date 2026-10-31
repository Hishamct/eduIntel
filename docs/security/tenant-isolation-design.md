# EduIntel AI — Multi-Tenant Isolation Architecture & Design Specification

**Audit Date:** October 30, 2026  
**Auditor:** Principal Software Architect, Application Security Engineer & Database Architect  
**Branch:** `develop/production-readiness`  
**Classification:** Architecture Specification (Scheduled for Phase 2 Implementation)

---

## 1. Executive Summary

As EduIntel evolves from a single-institute deployment into a commercial Multi-Tenant SaaS platform, tenant isolation is the primary architectural requirement. 

This document evaluates the three fundamental multi-tenancy models for relational databases, selects the optimal architecture for EduIntel's operational profile, and defines the technical implementation specification for **PostgreSQL Row-Level Security (RLS) combined with transaction-scoped tenant context propagation**.

---

## 2. Multi-Tenancy Architecture Options Evaluation (Workstream D)

| Evaluation Dimension | Option 1: Shared Database, Shared Schema (Application-Level Filter Only) | Option 2: Shared Database, Shared Schema with PostgreSQL Row-Level Security (RLS) | Option 3: Separate Database or Schema per Institution |
|---|---|---|---|
| **Architectural Model** | Single PostgreSQL DB; single schema; `WHERE institution_id = :id` appended in application code. | Single PostgreSQL DB; single schema; `institution_id` on all tables enforced by database engine policies. | Separate PostgreSQL database or schema per tenant (`tenant_123.users`). |
| **Security & Defense-in-Depth** | 🔴 **Weak.** A single missing `where()` clause in SQLAlchemy leaks cross-tenant records. High developer-error risk. | 🟢 **Strong.** Database engine prevents data leakage even if application queries omit the filter. | 🟢 **Strongest.** Physical or namespace boundary prevents cross-tenant relational queries. |
| **Infrastructure Cost** | 🟢 **Lowest.** Single small-to-medium database instance (e.g. Supabase Pro $25/mo or AWS RDS t4g.medium). | 🟢 **Lowest.** Same infrastructure footprint as Option 1. RLS adds negligible overhead (< 2%). | 🔴 **Highest.** Provisioning dozens/hundreds of RDS instances or high-memory DBs for schemas is cost-prohibitive. |
| **Operational & Migration Complexity** | 🟢 **Lowest.** Single Alembic migration runs once on the shared schema. | 🟢 **Low.** Single Alembic migration; policies defined in declarative migrations. | 🔴 **High.** Running migrations across hundreds of tenant schemas/databases leads to failure and schema drift. |
| **Connection Pooling Compatibility** | 🟢 **High.** Standard connection pooling across all tenants. | 🟢 **High (with `SET LOCAL`).** Works seamlessly with PgBouncer/Supavisor when scoped to transactions. | 🔴 **Poor.** Connection pools fragmented per tenant; exhausts DB connection limits. |
| **Cross-Tenant Aggregation (Platform Admin)** | 🟢 **Trivial.** Simple SQL queries without tenant filter. | 🟢 **Simple.** Platform admin role bypasses RLS via session flag. | 🔴 **Very Difficult.** Requires cross-database federated queries (FDW) or ETL replication. |
| **Backup & Disaster Recovery** | 🟡 Single backup covers all tenants; tenant-specific restore requires selective dump. | 🟡 Single backup; tenant-specific logical dump using `pg_dump --where`. | 🟢 Per-tenant database backup and restore is fully isolated. |
| **Scalability (SaaS Growth)** | 🟢 Scales to thousands of small-to-medium institutions comfortably. | 🟢 Scales to thousands of small-to-medium institutions. | 🟡 Hard limit on number of schemas (PostgreSQL catalog contention > 1,000 schemas). |

### Architectural Recommendation: **Option 2 (Shared Database + PostgreSQL RLS)**
Option 2 delivers enterprise-grade defense-in-depth with the operational simplicity and cost-efficiency of a single database. Option 3 is rejected due to prohibitive RDS hosting costs and severe migration drift risks across hundreds of coaching institutes.

---

## 3. PostgreSQL Row-Level Security (RLS) Design Specification

### 3.1. The Connection Pooling Safety Dilemma
In modern async FastAPI applications, database connections are managed via a connection pool (SQLAlchemy `AsyncEngine` with `asyncpg`, or external poolers like PgBouncer / Supavisor).

> [!CAUTION]
> **The Session Pollution Trap:** Executing `SET app.current_institution_id = '...'` sets a **session-level** variable. If the connection is checked back into the pool without resetting, the next HTTP request using that connection inherits the previous tenant's context, causing catastrophic cross-tenant data leakage!

### 3.2. The Solution: Transaction-Scoped `SET LOCAL`
`SET LOCAL` binds configuration parameters strictly to the **current active transaction**. When the transaction commits or rolls back, PostgreSQL automatically clears the variable:

```sql
BEGIN;
-- Variable is active ONLY within this transaction
SET LOCAL app.current_institution_id = 'b45c71d2-98e3-4d61-b75a-5264b971a100';

SELECT * FROM users; -- Automatically filtered to institution b45c...

COMMIT; -- Variable is completely cleared; connection is returned clean to the pool!
```

---

## 4. Application-to-Database Context Propagation

### 4.1. Step 1: JWT Verification & Tenant Extraction
The client sends an access token containing `institution_id`. The FastAPI dependency verifies the membership and returns a `TenantContext` object:

```python
class TenantContext:
    def __init__(self, user_id: uuid.UUID, institution_id: uuid.UUID, role: str, is_platform_admin: bool = False):
        self.user_id = user_id
        self.institution_id = institution_id
        self.role = role
        self.is_platform_admin = is_platform_admin
```

### 4.2. Step 2: Session Initialization with `SET LOCAL`
A dedicated FastAPI database dependency initializes the transaction with the tenant setting:

```python
async def get_tenant_db(
    tenant: TenantContext = Depends(get_current_tenant),
) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():  # Explicit transaction block
            # Set the tenant ID for this transaction only
            await session.execute(
                text("SET LOCAL app.current_institution_id = :tenant_id"),
                {"tenant_id": str(tenant.institution_id)},
            )
            if tenant.is_platform_admin:
                await session.execute(text("SET LOCAL app.is_platform_admin = 'true'"))
            else:
                await session.execute(text("SET LOCAL app.is_platform_admin = 'false'"))
            
            yield session
        # Transaction committed or rolled back; SET LOCAL cleared automatically
```

---

## 5. PostgreSQL Row-Level Security Policies Specification

### 5.1. Enabling RLS on Tenant Tables
RLS must be enabled on all 17 tenant-owned tables:
```sql
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE homework_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE doubt_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE doubt_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE study_materials ENABLE ROW LEVEL SECURITY;
ALTER TABLE exam_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE timetable_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE salary_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE fee_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE announcements ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_trace_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE teacher_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_profiles ENABLE ROW LEVEL SECURITY;
```

### 5.2. Standard Tenant Isolation Policy Template
```sql
-- Read Policy
CREATE POLICY tenant_isolation_select_policy ON assignments
FOR SELECT
USING (
    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
    OR current_setting('app.is_platform_admin', true) = 'true'
);

-- Write Policies (INSERT, UPDATE, DELETE)
CREATE POLICY tenant_isolation_insert_policy ON assignments
FOR INSERT
WITH CHECK (
    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
);

CREATE POLICY tenant_isolation_update_policy ON assignments
FOR UPDATE
USING (
    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
    OR current_setting('app.is_platform_admin', true) = 'true'
)
WITH CHECK (
    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
);

CREATE POLICY tenant_isolation_delete_policy ON assignments
FOR DELETE
USING (
    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
    OR current_setting('app.is_platform_admin', true) = 'true'
);
```

### 5.3. Superuser & Migration Bypass
To allow Alembic migrations and database backup tools (`pg_dump`) to operate globally, migrations execute as the PostgreSQL superuser (`eduintel`) or a dedicated migration role with `BYPASSRLS` attribute:
```sql
ALTER ROLE eduintel_migrator WITH BYPASSRLS;
```
Application connections connect as an unprivileged user `eduintel_app` that does **NOT** have `BYPASSRLS`.

---

## 6. Composite Keys, Constraints & Indexing Strategy

### 6.1. Composite Foreign Keys
To guarantee that child records cannot reference parent records belonging to a different tenant, critical relationships use **composite foreign keys**:

```sql
-- Example: homework_submissions referencing assignments
ALTER TABLE assignments 
ADD CONSTRAINT uq_assignments_tenant_id UNIQUE (institution_id, id);

ALTER TABLE homework_submissions
ADD CONSTRAINT fk_submissions_assignment_tenant
FOREIGN KEY (institution_id, assignment_id)
REFERENCES assignments(institution_id, id)
ON DELETE CASCADE;
```

### 6.2. Tenant-Aware Unique Constraints
Global unique constraints must be scoped to `institution_id`:
1. **Student Roll Numbers:**
   `UNIQUE (institution_id, roll_number)` — Allows different institutes to have roll number "101".
2. **Class Sections:**
   `UNIQUE (institution_id, class_section, day_of_week, period)` — Prevents timetable collision within the institute.
3. **User Memberships:**
   `UNIQUE (institution_id, user_id)` — Connects a user once to an institute.

### 6.3. Indexing Strategy for RLS Performance
Because PostgreSQL RLS injects `WHERE institution_id = :id` into every query plan, single-column indexes on `id` are insufficient. All primary lookups and foreign keys must have **composite indexes leading with `institution_id`**:

```sql
CREATE INDEX idx_users_institution_id ON users (institution_id);
CREATE INDEX idx_assignments_tenant_subject ON assignments (institution_id, subject);
CREATE INDEX idx_submissions_tenant_student ON homework_submissions (institution_id, student_id);
CREATE INDEX idx_attendance_tenant_date ON attendance_records (institution_id, attendance_date);
CREATE INDEX idx_salary_tenant_month ON salary_records (institution_id, month);
CREATE INDEX idx_fees_tenant_status ON fee_records (institution_id, payment_status);
```

---

## 7. Background Processing & Non-HTTP Tenant Context

Background jobs (e.g. OCR processing, batch email dispatch, RAG evaluation) execute outside the HTTP request/response cycle.

### Context Propagation Protocol:
1. **Enqueueing:** The task payload MUST explicitly include `institution_id` and `triggered_by_user_id`:
   ```json
   {
     "task": "process_homework_ocr",
     "submission_id": "...",
     "institution_id": "b45c71d2-98e3-4d61-b75a-5264b971a100"
   }
   ```
2. **Worker Execution:** The worker opens a database transaction and executes `SET LOCAL app.current_institution_id = :institution_id` before invoking any domain service functions.
3. **Audit Trail:** Background operations log the `institution_id` in `audit_logs` and `agent_trace_logs`.

