# ADR 0005: Multi-Institution Tenant Isolation Architecture

- **Status**: Proposed (Scheduled for Phase 2)
- **Deciders**: EduIntel Engineering Team, Database Architect
- **Date**: 2026-10-25

---

## Context and Problem Statement

EduIntel currently operates with a **single-institution data model**. Every database record in PostgreSQL (e.g., users, timetables, fees, exam scores) implicitly belongs to the same institution.

As EduIntel scales from a single pilot school/coaching institute to a commercial Multi-Tenant SaaS platform serving dozens of independent institutes, complete data isolation between institutions is non-negotiable. A breach where an administrator or teacher from Institute A views or queries students or finances from Institute B would cause catastrophic reputational and regulatory failure.

We must evaluate multi-tenancy models:
1. **Database-per-Tenant**: Completely separate PostgreSQL database instances for each institution.
2. **Schema-per-Tenant**: Single PostgreSQL database with a separate schema namespace (e.g. `tenant_123.users`) for each institution.
3. **Shared Database, Shared Schema with Discriminator Column (`institution_id`) & Row-Level Security (RLS)**: Single relational schema with `institution_id` on all tenant-scoped tables, enforced via application middleware and PostgreSQL RLS policies.

---

## Proposed Decision Outcome

We propose adopting **Shared Database, Shared Schema with Discriminator Column (`institution_id`) backed by PostgreSQL Row-Level Security (RLS)**.

### Proposed Architecture:
1. **Schema Migration**:
   - Create an `institutions` table (`id`, `name`, `slug`, `domain`, `is_active`, `created_at`).
   - Add `institution_id UUID NOT NULL REFERENCES institutions(id)` to all 17 tenant-owned tables (`users`, `timetable_entries`, `fee_records`, `assignments`, etc.).
   - Composite indexes created on `(institution_id, id)` and critical foreign key pairs.
2. **Context Propagation**:
   - Inject `institution_id` into the JWT claims upon authentication.
   - Implement FastAPI dependency `get_current_tenant()` extracting tenant context from the validated token.
   - Set PostgreSQL session variable `SET LOCAL app.current_institution_id = :tenant_id` at the start of each SQLAlchemy async transaction.
3. **Database-Level Defense**:
   - Enable PostgreSQL Row-Level Security (RLS) on all tenant tables:
     ```sql
     CREATE POLICY tenant_isolation_policy ON users
     USING (institution_id = current_setting('app.current_institution_id')::uuid);
     ```

---

## Consequences

### Positive Consequences
- **Cost Effective & Scalable**: A single shared database instance can comfortably support hundreds of small coaching institutes without incurring per-database RDS provisioning costs.
- **Defense in Depth**: Even if a developer accidentally omits `WHERE institution_id = :id` in application code, PostgreSQL RLS blocks cross-tenant data leaks at the database engine level.
- **Simplified Migrations**: Running Alembic migrations updates a single schema rather than executing across dozens of separate tenant databases or schemas.

### Negative Consequences
- **Migration Effort (Phase 2)**: Adding `institution_id` to 17 tables, backfilling historical data for the existing institution, and updating all SQLAlchemy queries and Pydantic schemas represents substantial engineering effort.
- **Connection Pool Overhead with RLS**: Running `SET LOCAL` requires managing transaction scopes carefully to avoid session variable leakage across pooled connections.

---

## Alternatives Considered

- **Database-per-Tenant**: Rejected due to high infrastructure cost and connection pool overhead on AWS RDS for small schools with modest budgets.
- **Schema-per-Tenant**: Rejected because running Alembic migrations across hundreds of dynamic PostgreSQL schemas introduces high maintenance complexity and schema drift risks.

