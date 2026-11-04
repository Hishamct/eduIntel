"""split rls policies for read write isolation

Revision ID: c9e0f2a1b3c4
Revises: b8d9f0e1c2a3
Create Date: 2026-11-04 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9e0f2a1b3c4'
down_revision: str | None = 'b8d9f0e1c2a3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = [
    'student_profiles',
    'teacher_profiles',
    'admin_profiles',
    'assignments',
    'study_materials',
    'exam_results',
    'homework_submissions',
    'doubt_threads',
    'doubt_messages',
    'timetable_entries',
    'salary_records',
    'fee_records',
    'attendance_records',
    'announcements',
    'audit_logs',
    'llm_usage_logs',
    'agent_trace_logs',
]


def upgrade() -> None:
    # Split tenant_isolation_policy on all 17 tenant tables into command-specific policies.
    # SEC-03: In PostgreSQL, FOR ALL policies apply their USING clause to DELETE operations.
    # Having app.is_platform_admin in a FOR ALL USING clause would permit cross-tenant DELETE.
    # By separating into FOR SELECT (with platform admin read bypass) and FOR INSERT/UPDATE/DELETE
    # (strictly requiring current_institution_id), cross-tenant writes and deletes are blocked.
    for tbl in TENANT_TABLES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_read_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_insert_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_update_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_delete_policy ON {tbl};"))

        # 1. READ POLICY: Platform Admin can read across institutions; ordinary users restricted to their tenant
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_read_policy ON {tbl}
                AS RESTRICTIVE
                FOR SELECT
                TO PUBLIC
                USING (
                    current_setting('app.is_platform_admin', true) = 'true'
                    OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                );
                """
            )
        )

        # 2. INSERT POLICY: All roles must insert rows matching app.current_institution_id
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_insert_policy ON {tbl}
                AS RESTRICTIVE
                FOR INSERT
                TO PUBLIC
                WITH CHECK (
                    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                );
                """
            )
        )

        # 3. UPDATE POLICY: All roles must target rows matching app.current_institution_id
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_update_policy ON {tbl}
                AS RESTRICTIVE
                FOR UPDATE
                TO PUBLIC
                USING (
                    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                )
                WITH CHECK (
                    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                );
                """
            )
        )

        # 4. DELETE POLICY: All roles must target rows matching app.current_institution_id (no cross-tenant delete)
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_delete_policy ON {tbl}
                AS RESTRICTIVE
                FOR DELETE
                TO PUBLIC
                USING (
                    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                );
                """
            )
        )


def downgrade() -> None:
    # Restore tenant_isolation_policy from migration 0024
    for tbl in TENANT_TABLES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_read_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_insert_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_update_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_delete_policy ON {tbl};"))
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_policy ON {tbl}
                AS RESTRICTIVE
                FOR ALL
                TO PUBLIC
                USING (
                    current_setting('app.is_platform_admin', true) = 'true'
                    OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                )
                WITH CHECK (
                    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                );
                """
            )
        )

