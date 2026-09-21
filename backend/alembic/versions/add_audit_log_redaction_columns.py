"""add pii redaction columns to audit_logs

Revision ID: a1c3f9e2b7d4
Revises: 361abb3e7a6e
Create Date: 2026-09-21 01:20:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "a1c3f9e2b7d4"
down_revision = "361abb3e7a6e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("was_redacted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "audit_logs",
        sa.Column("redaction_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "audit_logs",
        sa.Column("redacted_types", sa.Text(), nullable=True),
    )
    op.alter_column("audit_logs", "was_redacted", server_default=None)
    op.alter_column("audit_logs", "redaction_count", server_default=None)


def downgrade() -> None:
    op.drop_column("audit_logs", "redacted_types")
    op.drop_column("audit_logs", "redaction_count")
    op.drop_column("audit_logs", "was_redacted")
