"""create institutions and tenant schema

Revision ID: e5a7b9c1d3f5
Revises: d4f6a2b5e0c7
Create Date: 2026-10-31 16:00:00.000000

"""
from collections.abc import Sequence
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e5a7b9c1d3f5'
down_revision: str | None = 'd4f6a2b5e0c7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PILOT_INSTITUTION_ID = '00000000-0000-0000-0000-000000000001'

TENANT_TABLES = [
    'student_profiles',
    'teacher_profiles',
    'admin_profiles',
    'assignments',
    'study_materials',
    'exam_results',
    'homework_submissions',
    'doubt_threads',
    'doubt_messages',
    'timetable_entries',
    'salary_records',
    'fee_records',
    'attendance_records',
    'announcements',
    'audit_logs',
    'llm_usage_logs',
    'agent_trace_logs',
]


def upgrade() -> None:
    # 1. Create institutions table
    op.create_table(
        'institutions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index(op.f('ix_institutions_slug'), 'institutions', ['slug'], unique=True)

    # 2. Create institution_memberships table
    op.create_table(
        'institution_memberships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('institution_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('institution_id', 'user_id', name='uq_institution_memberships_inst_user'),
    )
    op.create_index(op.f('ix_institution_memberships_institution_id'), 'institution_memberships', ['institution_id'], unique=False)
    op.create_index(op.f('ix_institution_memberships_user_id'), 'institution_memberships', ['user_id'], unique=False)

    # 3. Seed canonical Pilot Institution
    op.execute(
        sa.text(
            f"""
            INSERT INTO institutions (id, name, slug, is_active, created_at, updated_at)
            VALUES ('{PILOT_INSTITUTION_ID}'::uuid, 'EduIntel Pilot Institution', 'eduintel-pilot', true, now(), now())
            ON CONFLICT (id) DO NOTHING;
            """
        )
    )

    # 4. Backfill existing users into pilot institution memberships
    op.execute(
        sa.text(
            f"""
            INSERT INTO institution_memberships (id, institution_id, user_id, role, status, created_at, updated_at)
            SELECT gen_random_uuid(), '{PILOT_INSTITUTION_ID}'::uuid, id, role, 'active', now(), now()
            FROM users
            ON CONFLICT (institution_id, user_id) DO NOTHING;
            """
        )
    )

    # 5. Pre-migration uniqueness audit before adding composite constraints
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE dup_count INT;
            BEGIN
                -- Audit duplicate roll numbers in student_profiles
                SELECT COUNT(*) INTO dup_count FROM (
                    SELECT roll_number FROM student_profiles WHERE roll_number IS NOT NULL GROUP BY roll_number HAVING COUNT(*) > 1
                ) d;
                IF dup_count > 0 THEN
                    RAISE EXCEPTION 'Pre-migration audit failed: % duplicate roll_numbers found in student_profiles', dup_count;
                END IF;

                -- Audit duplicate timetable slot keys in timetable_entries
                SELECT COUNT(*) INTO dup_count FROM (
                    SELECT class_section, day_of_week, period FROM timetable_entries GROUP BY class_section, day_of_week, period HAVING COUNT(*) > 1
                ) d2;
                IF dup_count > 0 THEN
                    RAISE EXCEPTION 'Pre-migration audit failed: % duplicate slot keys found in timetable_entries', dup_count;
                END IF;
            END $$;
            """
        )
    )

    # 6. Add institution_id to all 17 tenant tables, backfill, verify 0 NULLs, set NOT NULL, FK, index
    for tbl in TENANT_TABLES:
        # Add column as nullable first
        op.add_column(tbl, sa.Column('institution_id', postgresql.UUID(as_uuid=True), nullable=True))

        # Backfill with pilot UUID
        op.execute(
            sa.text(
                f"UPDATE {tbl} SET institution_id = '{PILOT_INSTITUTION_ID}'::uuid WHERE institution_id IS NULL"
            )
        )

        # Fail closed if any NULL remains
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM {tbl} WHERE institution_id IS NULL) THEN
                        RAISE EXCEPTION 'Backfill failed: NULL institution_id found in table %', '{tbl}';
                    END IF;
                END $$;
                """
            )
        )

        # Enforce NOT NULL
        op.alter_column(tbl, 'institution_id', nullable=False)

        # Foreign Key with ON DELETE RESTRICT (prevent accidental tenant data wiping)
        op.create_foreign_key(
            f"fk_{tbl}_institution_id",
            tbl,
            "institutions",
            ["institution_id"],
            ["id"],
            ondelete="RESTRICT",
        )

        # Tenant lookup index
        op.create_index(f"ix_{tbl}_institution_id", tbl, ["institution_id"], unique=False)

    # 7. Add composite unique constraints
    op.create_unique_constraint(
        "uq_student_profiles_institution_roll",
        "student_profiles",
        ["institution_id", "roll_number"],
    )
    op.create_unique_constraint(
        "uq_timetable_entries_institution_class_day_period",
        "timetable_entries",
        ["institution_id", "class_section", "day_of_week", "period"],
    )


def downgrade() -> None:
    # Fail-closed downgrade preconditions:
    # Downgrade is ONLY permitted if no non-pilot institutions, memberships, or tenant rows exist,
    # and no NULL institution_id rows exist. If foreign tenant data exists, abort immediately to prevent data loss.
    op.execute(
        sa.text(
            f"""
            DO $$
            DECLARE
                non_pilot_inst_count INT;
                non_pilot_mem_count INT;
                t_name TEXT;
                non_pilot_rows INT;
                null_rows INT;
            BEGIN
                -- 1. Check for non-pilot institutions
                SELECT COUNT(*) INTO non_pilot_inst_count
                FROM institutions
                WHERE id != '{PILOT_INSTITUTION_ID}'::uuid;

                IF non_pilot_inst_count > 0 THEN
                    RAISE EXCEPTION 'Downgrade aborted: % non-pilot institution(s) exist. Downgrade is only permitted for single-tenant pilot schema. Mandatory backup/PITR required.', non_pilot_inst_count;
                END IF;

                -- 2. Check for non-pilot memberships
                SELECT COUNT(*) INTO non_pilot_mem_count
                FROM institution_memberships
                WHERE institution_id != '{PILOT_INSTITUTION_ID}'::uuid;

                IF non_pilot_mem_count > 0 THEN
                    RAISE EXCEPTION 'Downgrade aborted: % non-pilot membership(s) exist. Mandatory backup/PITR required.', non_pilot_mem_count;
                END IF;

                -- 3. Check every tenant table for non-pilot or NULL institution_id records
                FOR t_name IN SELECT unnest(ARRAY[
                    'student_profiles', 'teacher_profiles', 'admin_profiles',
                    'assignments', 'study_materials', 'exam_results',
                    'homework_submissions', 'doubt_threads', 'doubt_messages',
                    'timetable_entries', 'salary_records', 'fee_records',
                    'attendance_records', 'announcements', 'audit_logs',
                    'llm_usage_logs', 'agent_trace_logs'
                ]) LOOP
                    EXECUTE format('SELECT COUNT(*) FROM %I WHERE institution_id != ''%s''::uuid', t_name, '{PILOT_INSTITUTION_ID}') INTO non_pilot_rows;
                    IF non_pilot_rows > 0 THEN
                        RAISE EXCEPTION 'Downgrade aborted: Table % contains % non-pilot records. Mandatory backup/PITR required.', t_name, non_pilot_rows;
                    END IF;

                    EXECUTE format('SELECT COUNT(*) FROM %I WHERE institution_id IS NULL', t_name) INTO null_rows;
                    IF null_rows > 0 THEN
                        RAISE EXCEPTION 'Downgrade aborted: Table % contains % NULL institution_id records.', t_name, null_rows;
                    END IF;
                END LOOP;
            END $$;
            """
        )
    )

    # 1. Drop composite unique constraints
    op.drop_constraint("uq_timetable_entries_institution_class_day_period", "timetable_entries", type_="unique")
    op.drop_constraint("uq_student_profiles_institution_roll", "student_profiles", type_="unique")

    # 2. For each tenant table, drop index, FK, and institution_id column
    for tbl in TENANT_TABLES:
        op.drop_index(f"ix_{tbl}_institution_id", table_name=tbl)
        op.drop_constraint(f"fk_{tbl}_institution_id", tbl, type_="foreignkey")
        op.drop_column(tbl, "institution_id")

    # 3. Drop institution_memberships table
    op.drop_index(op.f('ix_institution_memberships_user_id'), table_name='institution_memberships')
    op.drop_index(op.f('ix_institution_memberships_institution_id'), table_name='institution_memberships')
    op.drop_table('institution_memberships')

    # 4. Drop institutions table
    op.drop_index(op.f('ix_institutions_slug'), table_name='institutions')
    op.drop_table('institutions')

