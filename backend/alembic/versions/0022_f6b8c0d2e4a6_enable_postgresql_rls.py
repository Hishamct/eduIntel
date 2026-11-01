"""enable postgresql rls

Revision ID: f6b8c0d2e4a6
Revises: e5a7b9c1d3f5
Create Date: 2026-10-31 16:15:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f6b8c0d2e4a6'
down_revision: str | None = 'e5a7b9c1d3f5'
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
    # Ensure application database role 'eduintel' exists
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eduintel') THEN
                    CREATE ROLE eduintel LOGIN;
                END IF;
            END $$;
            """
        )
    )

    for tbl in TENANT_TABLES:
        # 1. Enable RLS
        op.execute(sa.text(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;"))

        # 2. Force RLS to prevent table owner bypass
        op.execute(sa.text(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;"))

        # 3. Create permissive access policy restricted to application role 'eduintel'
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_app_access_policy ON {tbl}
                AS PERMISSIVE
                FOR ALL
                TO eduintel
                USING (true)
                WITH CHECK (true);
                """
            )
        )

        # 4. Create restrictive isolation policy applied universally to PUBLIC.
        # Fails closed if app.current_institution_id is missing, empty, malformed,
        # or does not match row's institution_id.
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_policy ON {tbl}
                AS RESTRICTIVE
                FOR ALL
                TO PUBLIC
                USING (institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid)
                WITH CHECK (institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid);
                """
            )
        )


def downgrade() -> None:
    for tbl in TENANT_TABLES:
        # 1. Drop restrictive fence policy
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {tbl};"))

        # 2. Drop permissive application access policy
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_app_access_policy ON {tbl};"))

        # 3. Disable forced RLS
        op.execute(sa.text(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY;"))

        # 4. Disable RLS
        op.execute(sa.text(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;"))

