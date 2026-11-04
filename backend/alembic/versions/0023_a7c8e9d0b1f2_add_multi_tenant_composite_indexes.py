"""add multi tenant composite indexes

Revision ID: a7c8e9d0b1f2
Revises: f6b8c0d2e4a6
Create Date: 2026-11-03 19:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c8e9d0b1f2'
down_revision: str | None = 'f6b8c0d2e4a6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. attendance_records: Composite index for multi-tenant daily roster and section lookups
    op.create_index(
        'ix_attendance_inst_class_date',
        'attendance_records',
        ['institution_id', 'class_section', 'date'],
        unique=False,
    )

    # 2. fee_records: Composite indexes for student invoices and payment status aggregation
    op.create_index(
        'ix_fee_records_inst_student',
        'fee_records',
        ['institution_id', 'student_id'],
        unique=False,
    )
    op.create_index(
        'ix_fee_records_inst_status',
        'fee_records',
        ['institution_id', 'payment_status'],
        unique=False,
    )

    # 3. exam_results: Composite indexes for student academic history and class subject distributions
    op.create_index(
        'ix_exam_results_inst_student',
        'exam_results',
        ['institution_id', 'student_id'],
        unique=False,
    )
    op.create_index(
        'ix_exam_results_inst_class_sub',
        'exam_results',
        ['institution_id', 'class_section', 'subject'],
        unique=False,
    )

    # 4. homework_submissions: Composite indexes for student homework queues and teacher grading status
    op.create_index(
        'ix_homework_sub_inst_student',
        'homework_submissions',
        ['institution_id', 'student_id'],
        unique=False,
    )
    op.create_index(
        'ix_homework_sub_inst_status',
        'homework_submissions',
        ['institution_id', 'status'],
        unique=False,
    )


def downgrade() -> None:
    # 1. Drop homework_submissions composite indexes
    op.drop_index('ix_homework_sub_inst_status', table_name='homework_submissions')
    op.drop_index('ix_homework_sub_inst_student', table_name='homework_submissions')

    # 2. Drop exam_results composite indexes
    op.drop_index('ix_exam_results_inst_class_sub', table_name='exam_results')
    op.drop_index('ix_exam_results_inst_student', table_name='exam_results')

    # 3. Drop fee_records composite indexes
    op.drop_index('ix_fee_records_inst_status', table_name='fee_records')
    op.drop_index('ix_fee_records_inst_student', table_name='fee_records')

    # 4. Drop attendance_records composite index
    op.drop_index('ix_attendance_inst_class_date', table_name='attendance_records')

