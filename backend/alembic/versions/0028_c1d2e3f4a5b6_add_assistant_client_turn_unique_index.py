"""add assistant client_turn partial unique index for completed responses

Revision ID: c1d2e3f4a5b6
Revises: e1f2a3b4c5d6
Create Date: 2026-11-07 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_agent_messages_client_turn_assistant_completed",
        "agent_session_messages",
        ["institution_id", "session_id", "client_turn_id"],
        unique=True,
        postgresql_where=sa.text("client_turn_id IS NOT NULL AND role = 'assistant' AND status = 'COMPLETED'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_agent_messages_client_turn_assistant_completed",
        table_name="agent_session_messages",
    )

