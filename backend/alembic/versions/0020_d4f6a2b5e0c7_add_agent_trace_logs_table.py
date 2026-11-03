"""add agent_trace_logs table

Revision ID: d4f6a2b5e0c7
Revises: c3e5f1a4d9b6
Create Date: 2026-09-21 12:30:00.000000

New table for LangGraph agent tracing — see app/observability/models.py:
AgentTraceLog. Chains onto the LLM usage/cost tracking migration
(c3e5f1a4d9b6) you already applied.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d4f6a2b5e0c7"
down_revision = "c3e5f1a4d9b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_trace_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_name", sa.String(length=50), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("node_name", sa.String(length=100), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ok"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_trace_logs_trace_id", "agent_trace_logs", ["trace_id"])
    op.create_index("ix_agent_trace_logs_created_at", "agent_trace_logs", ["created_at"])

    # Same reasoning as add_llm_usage_logs_table.py: server_default only
    # needed so CREATE TABLE is happy; drop it so future inserts rely on
    # the ORM-side default in app/observability/models.py instead of two
    # places defining "ok".
    op.alter_column("agent_trace_logs", "status", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_agent_trace_logs_created_at", table_name="agent_trace_logs")
    op.drop_index("ix_agent_trace_logs_trace_id", table_name="agent_trace_logs")
    op.drop_table("agent_trace_logs")
