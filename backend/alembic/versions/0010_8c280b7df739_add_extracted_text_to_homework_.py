"""add extracted_text to homework_submission

Revision ID: 8c280b7df739
Revises: 95aa2b163349
Create Date: 2026-08-12 12:35:14.929573

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c280b7df739'
down_revision: Union[str, Sequence[str], None] = '95aa2b163349'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('homework_submissions', sa.Column('extracted_text', sa.Text(), nullable=True))
    op.add_column('homework_submissions', sa.Column('ocr_confidence', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('homework_submissions', 'ocr_confidence')
    op.drop_column('homework_submissions', 'extracted_text')