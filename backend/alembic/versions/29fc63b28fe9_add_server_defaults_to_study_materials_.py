"""add server defaults to study_materials timestamps

Revision ID: 29fc63b28fe9
Revises: 847a7f61eae6
Create Date: 2026-08-12 13:54:50.357872

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '29fc63b28fe9'
down_revision: Union[str, Sequence[str], None] = '847a7f61eae6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None





def upgrade():
    op.alter_column(
        'study_materials', 'created_at',
        server_default=sa.text('now()'),
    )
    op.alter_column(
        'study_materials', 'updated_at',
        server_default=sa.text('now()'),
    )


def downgrade():
    op.alter_column('study_materials', 'created_at', server_default=None)
    op.alter_column('study_materials', 'updated_at', server_default=None)
