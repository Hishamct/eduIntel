"""add tool_execution_records table with fenced idempotency and rls

Revision ID: d0e1f2a3b4c5
Revises: c9e0f2a1b3c4
Create Date: 2026-11-06 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9e0f2a1b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_execution_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="RESERVED", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("lease_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "last_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_details", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "institution_id",
            "session_id",
            "turn_id",
            "tool_call_id",
            name="uq_tool_execution_call",
        ),
    )
    op.create_index(
        "ix_tool_execution_records_institution_id",
        "tool_execution_records",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        "ix_tool_execution_records_session_id",
        "tool_execution_records",
        ["session_id"],
        unique=False,
    )

    # Enable and Force Row-Level Security
    op.execute(sa.text("ALTER TABLE tool_execution_records ENABLE ROW LEVEL SECURITY;"))
    op.execute(sa.text("ALTER TABLE tool_execution_records FORCE ROW LEVEL SECURITY;"))

    # Permissive policy for application role 'eduintel' (SEC-03: PostgreSQL requires at least one PERMISSIVE policy)
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_app_access_policy ON tool_execution_records
            AS PERMISSIVE
            FOR ALL
            TO eduintel
            USING (true)
            WITH CHECK (true);
            """
        )
    )

    # Split RLS policies adhering to SEC-03
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_read_policy ON tool_execution_records
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
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_insert_policy ON tool_execution_records
            AS RESTRICTIVE
            FOR INSERT
            TO PUBLIC
            WITH CHECK (
                institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_update_policy ON tool_execution_records
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
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_delete_policy ON tool_execution_records
            AS RESTRICTIVE
            FOR DELETE
            TO PUBLIC
            USING (
                institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
            );
            """
        )
    )

    # Grant table permissions to application roles
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel') THEN
                GRANT ALL ON TABLE tool_execution_records TO eduintel;
              END IF;
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel_app') THEN
                GRANT ALL ON TABLE tool_execution_records TO eduintel_app;
              END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_delete_policy ON tool_execution_records;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_update_policy ON tool_execution_records;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_insert_policy ON tool_execution_records;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_read_policy ON tool_execution_records;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_app_access_policy ON tool_execution_records;"))
    op.drop_index("ix_tool_execution_records_session_id", table_name="tool_execution_records")
    op.drop_index("ix_tool_execution_records_institution_id", table_name="tool_execution_records")
    op.drop_table("tool_execution_records")
