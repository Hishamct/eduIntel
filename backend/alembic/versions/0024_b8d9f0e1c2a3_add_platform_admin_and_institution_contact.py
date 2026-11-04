"""add platform admin and institution contact

Revision ID: b8d9f0e1c2a3
Revises: a7c8e9d0b1f2
Create Date: 2026-11-04 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d9f0e1c2a3'
down_revision: str | None = 'a7c8e9d0b1f2'
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
    # 1. Add is_platform_admin column to users table with B-tree index
    op.add_column(
        'users',
        sa.Column(
            'is_platform_admin',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )
    op.create_index('ix_users_is_platform_admin', 'users', ['is_platform_admin'])

    # 2. Add contact_email column to institutions table
    op.add_column(
        'institutions',
        sa.Column('contact_email', sa.String(), nullable=True),
    )

    # 3. Update tenant_isolation_policy on all 17 tenant tables to allow
    # READ-ONLY cross-tenant access for verified platform admin sessions.
    # Note: WITH CHECK remains strictly bound to institution_id to forbid cross-tenant writes.
    for tbl in TENANT_TABLES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {tbl};"))
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


def downgrade() -> None:
    # 1. Restore tenant_isolation_policy on all 17 tenant tables to Phase 2 strict single-tenant definition
    for tbl in TENANT_TABLES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {tbl};"))
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_policy ON {tbl}
                AS RESTRICTIVE
                FOR ALL
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

    # 2. Drop contact_email from institutions table
    op.drop_column('institutions', 'contact_email')

    # 3. Drop index and is_platform_admin column from users table
    op.drop_index('ix_users_is_platform_admin', table_name='users')
    op.drop_column('users', 'is_platform_admin')
