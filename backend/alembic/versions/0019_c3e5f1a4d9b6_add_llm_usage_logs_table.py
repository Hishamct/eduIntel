"""add llm_usage_logs table

Revision ID: c3e5f1a4d9b6
Revises: b2d4e0f3c8a5
Create Date: 2026-09-21 02:00:00.000000

New table for LLM cost/latency tracking — see app/observability/models.py:
LLMUsageLog. Chains onto the anti-cheating audit-log migration
(b2d4e0f3c8a5) you already applied.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c3e5f1a4d9b6"
down_revision = "b2d4e0f3c8a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("used_fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("estimated_cost_inr", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_llm_usage_logs_endpoint", "llm_usage_logs", ["endpoint"])
    op.create_index("ix_llm_usage_logs_created_at", "llm_usage_logs", ["created_at"])

    # server_default was only needed so CREATE TABLE has something to put in
    # existing-row-free new rows consistently with your other guardrail
    # migrations; drop it so future inserts rely on the ORM-side defaults in
    # app/observability/models.py instead of two places defining it.
    op.alter_column("llm_usage_logs", "used_fallback", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_llm_usage_logs_created_at", table_name="llm_usage_logs")
    op.drop_index("ix_llm_usage_logs_endpoint", table_name="llm_usage_logs")
    op.drop_table("llm_usage_logs")
