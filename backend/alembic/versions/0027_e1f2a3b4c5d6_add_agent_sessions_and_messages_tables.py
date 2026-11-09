"""add agent_sessions and agent_session_messages tables with composite integrity and rls

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-07 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TARGET_TABLES = [
    "agent_sessions",
    "agent_session_messages",
]


def upgrade() -> None:
    # 1. Create agent_sessions table
    op.create_table(
        "agent_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_name", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), server_default="New Conversation", nullable=False),
        sa.Column("is_expired", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("turn_counter", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_generating", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("generation_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_client_turn_id", sa.String(length=100), nullable=True),
        sa.Column("generation_fence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("generation_owner_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_accessed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("institution_id", "id", name="uq_agent_sessions_institution_id"),
        sa.CheckConstraint("turn_counter >= 0", name="ck_agent_sessions_turn_counter_nonneg"),
        sa.CheckConstraint("generation_fence >= 0", name="ck_agent_sessions_generation_fence_nonneg"),
    )
    op.create_index("ix_agent_sessions_institution_id", "agent_sessions", ["institution_id"], unique=False)
    op.create_index("ix_agent_sessions_user_id", "agent_sessions", ["user_id"], unique=False)
    op.create_index(
        "ix_agent_sessions_inst_user_access",
        "agent_sessions",
        ["institution_id", "user_id", "last_accessed_at"],
        unique=False,
        postgresql_where=sa.text("is_deleted = FALSE"),
    )
    op.create_index(
        "ix_agent_sessions_lifecycle_purge",
        "agent_sessions",
        ["is_deleted", "deleted_at", "is_expired", "expired_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_sessions_lease",
        "agent_sessions",
        ["is_generating", "generation_lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("is_generating = TRUE"),
    )

    # 2. Create agent_session_messages table
    op.create_table(
        "agent_session_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="COMPLETED", nullable=False),
        sa.Column("client_turn_id", sa.String(length=100), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("llm_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["institution_id", "session_id"],
            ["agent_sessions.institution_id", "agent_sessions.id"],
            ondelete="CASCADE",
            name="fk_agent_session_messages_session",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "institution_id",
            "session_id",
            "turn_id",
            "role",
            name="uq_session_turn_role",
        ),
        sa.CheckConstraint(
            "status IN ('COMPLETED', 'TRUNCATED', 'BLOCKED', 'FAILED')",
            name="ck_agent_session_messages_status",
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_agent_session_messages_role",
        ),
        sa.CheckConstraint("turn_id >= 1", name="ck_agent_session_messages_turn_id_pos"),
    )
    op.create_index(
        "ix_agent_session_messages_institution_id",
        "agent_session_messages",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_session_messages_session_id",
        "agent_session_messages",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_session_messages_session_turn",
        "agent_session_messages",
        ["institution_id", "session_id", "turn_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_session_messages_client_turn",
        "agent_session_messages",
        ["institution_id", "client_turn_id"],
        unique=False,
        postgresql_where=sa.text("client_turn_id IS NOT NULL"),
    )

    # 3. Configure Row-Level Security on both tables
    for tbl in TARGET_TABLES:
        op.execute(sa.text(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;"))
        op.execute(sa.text(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;"))

        # Permissive policy for application role 'eduintel'
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

        # Restrictive Split RLS Policies adhering to SEC-03
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

        # Grant table permissions to application roles
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel') THEN
                    GRANT ALL ON TABLE {tbl} TO eduintel;
                  END IF;
                  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel_app') THEN
                    GRANT ALL ON TABLE {tbl} TO eduintel_app;
                  END IF;
                END $$;
                """
            )
        )


def downgrade() -> None:
    for tbl in reversed(TARGET_TABLES):
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_delete_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_update_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_insert_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_read_policy ON {tbl};"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_app_access_policy ON {tbl};"))

    op.drop_index("ix_agent_session_messages_client_turn", table_name="agent_session_messages")
    op.drop_index("ix_agent_session_messages_session_turn", table_name="agent_session_messages")
    op.drop_index("ix_agent_session_messages_session_id", table_name="agent_session_messages")
    op.drop_index("ix_agent_session_messages_institution_id", table_name="agent_session_messages")
    op.drop_table("agent_session_messages")

    op.drop_index("ix_agent_sessions_lease", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_lifecycle_purge", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_inst_user_access", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_user_id", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_institution_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")

