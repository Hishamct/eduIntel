"""add socratic-redirect columns to audit_logs

Revision ID: b2d4e0f3c8a5
Revises: a1c3f9e2b7d4
Create Date: 2026-09-21 01:45:00.000000

Adds the two columns audit_logs picked up in app/observability/models.py
for the anti-cheating guardrail: was_socratic_redirected,
socratic_trigger_pattern. Chains directly onto the PII-redaction migration
(a1c3f9e2b7d4) you already applied.
"""
from alembic import op
import sqlalchemy as sa


revision = "b2d4e0f3c8a5"
down_revision = "a1c3f9e2b7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("was_socratic_redirected", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "audit_logs",
        sa.Column("socratic_trigger_pattern", sa.Text(), nullable=True),
    )
    op.alter_column("audit_logs", "was_socratic_redirected", server_default=None)


def downgrade() -> None:
    op.drop_column("audit_logs", "socratic_trigger_pattern")
    op.drop_column("audit_logs", "was_socratic_redirected")
