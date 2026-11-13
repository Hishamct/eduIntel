"""remediate stage 7.1 security, role separation, pricing activation, and structural constraints

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-11-11 17:00:00.000000

Stage 7.1R Audit Remediation:
- F-01 (High): Enforce strict separation between migration/schema-owner role and
  runtime role `eduintel_app`; transfer any `eduintel_app`-owned objects back to
  migration owner; fail closed if `eduintel_app` is missing, privileged, or a
  member of privileged/owner roles; retarget permissive RLS policies `TO eduintel_app`
  (both Stage 7.1 and pre-existing RLS tables) so `GRANT eduintel TO eduintel_app`
  is completely unnecessary; revoke schema CREATE and trigger-function EXECUTE.
- F-02 (Medium): Remove redundant `UPDATE` ACL on `ai_pricing_versions`; resolve the
  `is_active` vs immutability contradiction by keeping `ai_pricing_versions` strictly
  immutable (eligibility flag) and adding append-only `ai_pricing_activations` for
  auditable active-version selection without UPDATEs or unapproved pricing seeds.
- F-03 (Medium): Enforce `dispatched_at` for DISPATCHED/COMMITTED/UNKNOWN_USAGE and
  `reconciled_at` invariants; widen reservation/attempt token counts to BIGINT; add
  token-sum and overflow-safe bounds; add composite FK
  `(institution_id, reservation_id, attempt_id)` and null guard on
  `ai_financial_adjustments`.
- F-04 (Low): Add non-empty trimmed checks for vendor/request/endpoint identifiers and
  extend immutability triggers to cover `BEFORE TRUNCATE`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_RLS_TABLES = (
    "student_profiles",
    "teacher_profiles",
    "admin_profiles",
    "assignments",
    "study_materials",
    "exam_results",
    "homework_submissions",
    "doubt_threads",
    "doubt_messages",
    "timetable_entries",
    "salary_records",
    "fee_records",
    "attendance_records",
    "announcements",
    "audit_logs",
    "llm_usage_logs",
    "agent_trace_logs",
    "tool_execution_records",
    "agent_sessions",
    "agent_session_messages",
)

LEGACY_NON_RLS_OPERATIONAL_TABLES = (
    "users",
    "password_reset_tokens",
    "institutions",
    "institution_memberships",
)

STAGE7_OPERATIONAL_TABLES = (
    "tenant_ai_quotas",
    "tenant_daily_ai_usage",
    "tenant_daily_category_usage",
    "ai_token_reservations",
    "ai_provider_attempts",
)

STAGE7_LEDGER_READ_WRITE_TABLES = (
    "tenant_daily_ai_usage",
    "tenant_daily_category_usage",
    "ai_token_reservations",
    "ai_provider_attempts",
)


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. F-01 Pre-Flight Role Separation & Prerequisite Verification
    # -------------------------------------------------------------------------
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                v_app RECORD;
                v_obj RECORD;
                v_violation RECORD;
            BEGIN
                IF current_user = 'eduintel_app' THEN
                    RAISE EXCEPTION
                        'FATAL (Stage 7.1R): Alembic migration 0030 must execute as the migration/schema-owner role (e.g., eduintel or eduintel_migrator), NEVER as runtime role eduintel_app.'
                        USING ERRCODE = '42501';
                END IF;

                SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb
                INTO v_app
                FROM pg_roles
                WHERE rolname = 'eduintel_app';

                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'DEPLOYMENT PREREQUISITE MISSING (Stage 7.1R): Runtime role "eduintel_app" does not exist. Provision via: CREATE ROLE eduintel_app WITH LOGIN PASSWORD ''...'' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;'
                        USING ERRCODE = '42501';
                END IF;

                IF v_app.rolsuper OR v_app.rolbypassrls OR v_app.rolcreaterole OR v_app.rolcreatedb THEN
                    RAISE EXCEPTION
                        'SECURITY VIOLATION (Stage 7.1R): Role "eduintel_app" holds privileged attributes (rolsuper=%, rolbypassrls=%, rolcreaterole=%, rolcreatedb=%). Remediate via ALTER ROLE eduintel_app NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOINHERIT;',
                        v_app.rolsuper, v_app.rolbypassrls, v_app.rolcreaterole, v_app.rolcreatedb
                        USING ERRCODE = '42501';
                END IF;

                -- Transfer any objects erroneously owned by runtime role eduintel_app
                -- (for instance from prior test runs) back to the migration role.
                FOR v_obj IN
                    SELECT c.relname, c.relkind
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relkind IN ('r', 'p', 'S')
                      AND pg_get_userbyid(c.relowner) = 'eduintel_app'
                LOOP
                    IF v_obj.relkind = 'S' THEN
                        EXECUTE format('ALTER SEQUENCE public.%I OWNER TO %I;', v_obj.relname, current_user);
                    ELSE
                        EXECUTE format('ALTER TABLE public.%I OWNER TO %I;', v_obj.relname, current_user);
                    END IF;
                END LOOP;

                IF EXISTS (
                    SELECT 1
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public'
                      AND p.proname = 'prevent_finops_immutable_mutation'
                      AND pg_get_userbyid(p.proowner) = 'eduintel_app'
                ) THEN
                    EXECUTE format('ALTER FUNCTION public.prevent_finops_immutable_mutation() OWNER TO %I;', current_user);
                END IF;

                -- Fail closed if eduintel_app still inherits or can SET ROLE into
                -- current_user, eduintel, any schema/table/function owner, or any privileged role.
                WITH RECURSIVE role_tree AS (
                    SELECT r.oid, r.rolname, r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb,
                           true AS can_inherit, true AS can_set, 0 AS depth
                    FROM pg_roles r
                    WHERE r.rolname = 'eduintel_app'
                    UNION ALL
                    SELECT parent.oid, parent.rolname, parent.rolsuper, parent.rolbypassrls,
                           parent.rolcreaterole, parent.rolcreatedb,
                           (rt.can_inherit AND m.inherit_option),
                           (rt.can_set AND m.set_option),
                           rt.depth + 1
                    FROM pg_auth_members m
                    JOIN role_tree rt ON m.member = rt.oid
                    JOIN pg_roles parent ON m.roleid = parent.oid
                    WHERE rt.depth < 16
                )
                SELECT DISTINCT rt.rolname, rt.rolsuper, rt.rolbypassrls, rt.rolcreaterole, rt.rolcreatedb,
                                rt.can_inherit, rt.can_set
                INTO v_violation
                FROM role_tree rt
                WHERE rt.depth > 0
                  AND (rt.can_inherit OR rt.can_set)
                  AND (
                      rt.rolsuper
                      OR rt.rolbypassrls
                      OR rt.rolcreaterole
                      OR rt.rolcreatedb
                      OR rt.rolname IN (current_user, 'eduintel', 'eduintel_migrator', 'pg_database_owner')
                      OR EXISTS (
                          SELECT 1
                          FROM pg_class c
                          JOIN pg_namespace n ON n.oid = c.relnamespace
                          WHERE n.nspname = 'public'
                            AND c.relkind IN ('r', 'p', 'S')
                            AND pg_get_userbyid(c.relowner) = rt.rolname
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM pg_proc p
                          JOIN pg_namespace n ON n.oid = p.pronamespace
                          WHERE n.nspname = 'public'
                            AND pg_get_userbyid(p.proowner) = rt.rolname
                      )
                  )
                LIMIT 1;

                IF FOUND THEN
                    RAISE EXCEPTION
                        'ROLE SEPARATION PREREQUISITE FAILED (Stage 7.1R): Runtime role "eduintel_app" is still a member of privileged/owner role "%" (can_inherit=%, can_set=%). Run cluster-level provisioning first: REVOKE % FROM eduintel_app; ALTER ROLE eduintel_app NOINHERIT;',
                        v_violation.rolname, v_violation.can_inherit, v_violation.can_set, v_violation.rolname
                        USING ERRCODE = '42501';
                END IF;
            END $$;
            """
        )
    )

    # Hardening schema & trigger function ACLs
    op.execute(sa.text("REVOKE CREATE ON SCHEMA public FROM PUBLIC;"))
    op.execute(sa.text("REVOKE CREATE ON SCHEMA public FROM eduintel_app;"))
    op.execute(sa.text("GRANT USAGE ON SCHEMA public TO eduintel_app;"))
    op.execute(sa.text("REVOKE ALL ON FUNCTION prevent_finops_immutable_mutation() FROM PUBLIC;"))
    op.execute(sa.text("REVOKE ALL ON FUNCTION prevent_finops_immutable_mutation() FROM eduintel_app;"))

    # -------------------------------------------------------------------------
    # 2. F-02: Separate Append-Only Pricing Activation Table
    # -------------------------------------------------------------------------
    op.create_unique_constraint(
        "uq_ai_pricing_versions_id_active",
        "ai_pricing_versions",
        ["version_id", "is_active"],
    )

    op.create_table(
        "ai_pricing_activations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activation_seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("pricing_version", sa.String(length=50), nullable=False),
        sa.Column(
            "expected_version_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("activated_by_actor", sa.String(length=100), nullable=False),
        sa.Column("activation_reason", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activation_seq", name="uq_ai_pricing_activations_seq"),
        sa.ForeignKeyConstraint(
            ["pricing_version"],
            ["ai_pricing_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pricing_version", "expected_version_active"],
            ["ai_pricing_versions.version_id", "ai_pricing_versions.is_active"],
            ondelete="RESTRICT",
            name="fk_pricing_activation_eligible_version",
        ),
        sa.CheckConstraint(
            "expected_version_active = true",
            name="ck_ai_pricing_activations_must_be_active",
        ),
        sa.CheckConstraint(
            "char_length(btrim(activated_by_actor)) > 0",
            name="ck_ai_pricing_activations_actor_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(btrim(activation_reason)) > 0",
            name="ck_ai_pricing_activations_reason_nonempty",
        ),
    )
    op.create_index(
        "ix_ai_pricing_activations_active_lookup",
        "ai_pricing_activations",
        ["activated_at", "activation_seq"],
        unique=False,
    )

    # -------------------------------------------------------------------------
    # 3. F-03 & F-04: Column Widenings & Structural Constraints
    # -------------------------------------------------------------------------
    # 3A. Widen reservation and attempt token fields from INTEGER to BIGINT
    for col_name in (
        "estimated_input_tokens",
        "reserved_output_tokens",
        "total_reserved_tokens",
        "actual_input_tokens",
        "actual_output_tokens",
        "actual_total_tokens",
        "uncertain_tokens_held",
    ):
        op.alter_column(
            "ai_token_reservations",
            col_name,
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )

    for col_name, nullable in (
        ("estimated_tokens", False),
        ("input_tokens", True),
        ("output_tokens", True),
        ("manual_settled_tokens", True),
        ("late_reported_input_tokens", True),
        ("late_reported_output_tokens", True),
    ):
        op.alter_column(
            "ai_provider_attempts",
            col_name,
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=nullable,
        )

    # 3B. Reservation timestamp, token arithmetic, overflow bounds, and trimmed string checks
    op.drop_constraint(
        "ck_ai_token_reservations_dispatched_ts",
        "ai_token_reservations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_token_reservations_dispatched_ts",
        "ai_token_reservations",
        "status NOT IN ('DISPATCHED', 'COMMITTED', 'UNKNOWN_USAGE') OR dispatched_at IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_ai_token_reservations_reconciled_ts",
        "ai_token_reservations",
        "(status NOT IN ('COMMITTED', 'RELEASED') OR reconciled_at IS NOT NULL) "
        "AND (status NOT IN ('RESERVED', 'DISPATCHED') OR reconciled_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_ai_res_reserved_bounds",
        "ai_token_reservations",
        "estimated_input_tokens <= 1000000000000000 AND reserved_output_tokens <= 1000000000000000",
    )
    op.create_check_constraint(
        "ck_ai_res_tot_res_sum",
        "ai_token_reservations",
        "total_reserved_tokens = estimated_input_tokens + reserved_output_tokens",
    )
    op.create_check_constraint(
        "ck_ai_res_actual_bounds",
        "ai_token_reservations",
        "actual_input_tokens <= 1000000000000000 AND actual_output_tokens <= 1000000000000000",
    )
    op.create_check_constraint(
        "ck_ai_res_act_tot_sum",
        "ai_token_reservations",
        "actual_total_tokens = actual_input_tokens + actual_output_tokens",
    )
    op.create_check_constraint(
        "ck_ai_res_endpoint_nonempty",
        "ai_token_reservations",
        "char_length(btrim(endpoint)) > 0",
    )
    op.create_check_constraint(
        "ck_ai_res_idem_key_nonempty",
        "ai_token_reservations",
        "idempotency_key IS NULL OR char_length(btrim(idempotency_key)) > 0",
    )

    # 3C. Provider attempt uniqueness & non-empty identifier checks
    op.create_unique_constraint(
        "uq_ai_provider_attempts_inst_res_id",
        "ai_provider_attempts",
        ["institution_id", "reservation_id", "id"],
    )
    op.create_check_constraint(
        "ck_ai_att_provider_nonempty",
        "ai_provider_attempts",
        "char_length(btrim(provider)) > 0",
    )
    op.create_check_constraint(
        "ck_ai_att_model_nonempty",
        "ai_provider_attempts",
        "char_length(btrim(model)) > 0",
    )
    op.create_check_constraint(
        "ck_ai_att_provider_req_id_nonempty",
        "ai_provider_attempts",
        "provider_request_id IS NULL OR char_length(btrim(provider_request_id)) > 0",
    )

    # 3D. Financial adjustment composite FK binding (institution_id, reservation_id, attempt_id)
    op.drop_constraint(
        "fk_adjustment_attempt_tenant",
        "ai_financial_adjustments",
        type_="foreignkey",
    )
    op.create_check_constraint(
        "ck_ai_financial_adjustments_attempt_requires_res",
        "ai_financial_adjustments",
        "attempt_id IS NULL OR reservation_id IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_adjustment_res_attempt_tenant",
        "ai_financial_adjustments",
        "ai_provider_attempts",
        ["institution_id", "reservation_id", "attempt_id"],
        ["institution_id", "reservation_id", "id"],
        ondelete="RESTRICT",
    )

    # -------------------------------------------------------------------------
    # 4. F-04: Harden Immutability & Append-Only Triggers to Block TRUNCATE
    # -------------------------------------------------------------------------
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ai_pricing_versions_immutable ON ai_pricing_versions;"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_ai_pricing_versions_immutable
            BEFORE UPDATE OR DELETE OR TRUNCATE ON ai_pricing_versions
            FOR EACH STATEMENT
            EXECUTE FUNCTION prevent_finops_immutable_mutation();
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ai_financial_adjustments_append_only ON ai_financial_adjustments;"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_ai_financial_adjustments_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE ON ai_financial_adjustments
            FOR EACH STATEMENT
            EXECUTE FUNCTION prevent_finops_immutable_mutation();
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_ai_pricing_activations_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE ON ai_pricing_activations
            FOR EACH STATEMENT
            EXECUTE FUNCTION prevent_finops_immutable_mutation();
            """
        )
    )

    # -------------------------------------------------------------------------
    # 5. F-01 & F-02: Retarget Permissive Policies TO eduintel_app & Tighten ACLs
    # -------------------------------------------------------------------------
    # 5A. Pre-existing RLS tables: point tenant_app_access_policy directly to eduintel_app
    # so eduintel_app never requires inherited membership in eduintel.
    for tbl in LEGACY_RLS_TABLES:
        op.execute(sa.text(f"ALTER POLICY tenant_app_access_policy ON {tbl} TO eduintel_app;"))
        op.execute(sa.text(f"REVOKE ALL ON TABLE {tbl} FROM PUBLIC;"))
        op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {tbl} TO eduintel_app;"))

    for tbl in LEGACY_NON_RLS_OPERATIONAL_TABLES:
        op.execute(sa.text(f"REVOKE ALL ON TABLE {tbl} FROM PUBLIC;"))
        op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {tbl} TO eduintel_app;"))

    op.execute(sa.text("REVOKE ALL ON TABLE alembic_version FROM PUBLIC;"))
    op.execute(sa.text("REVOKE ALL ON TABLE alembic_version FROM eduintel_app;"))
    op.execute(sa.text("GRANT SELECT ON TABLE alembic_version TO eduintel_app;"))
    op.execute(sa.text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO eduintel_app;"))

    # 5B. Stage 7.1 ai_pricing_versions: remove UPDATE ACL and target eduintel_app in RLS
    op.execute(sa.text("DROP POLICY IF EXISTS pricing_versions_read_all ON ai_pricing_versions;"))
    op.execute(sa.text("DROP POLICY IF EXISTS pricing_versions_admin_insert ON ai_pricing_versions;"))
    op.execute(
        sa.text(
            """
            CREATE POLICY pricing_versions_read_all ON ai_pricing_versions
            AS PERMISSIVE
            FOR SELECT
            TO eduintel_app
            USING (true);
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY pricing_versions_admin_insert ON ai_pricing_versions
            AS PERMISSIVE
            FOR INSERT
            TO eduintel_app
            WITH CHECK (current_setting('app.is_platform_admin', true) = 'true');
            """
        )
    )
    op.execute(sa.text("REVOKE ALL ON TABLE ai_pricing_versions FROM PUBLIC, eduintel_app;"))
    op.execute(sa.text("GRANT SELECT, INSERT ON TABLE ai_pricing_versions TO eduintel_app;"))

    # 5C. New Stage 7.1R ai_pricing_activations: append-only admin activation ledger
    op.execute(sa.text("ALTER TABLE ai_pricing_activations ENABLE ROW LEVEL SECURITY;"))
    op.execute(sa.text("ALTER TABLE ai_pricing_activations FORCE ROW LEVEL SECURITY;"))
    op.execute(
        sa.text(
            """
            CREATE POLICY pricing_activations_read_all ON ai_pricing_activations
            AS PERMISSIVE
            FOR SELECT
            TO eduintel_app
            USING (true);
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY pricing_activations_admin_insert ON ai_pricing_activations
            AS PERMISSIVE
            FOR INSERT
            TO eduintel_app
            WITH CHECK (current_setting('app.is_platform_admin', true) = 'true');
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY pricing_activations_no_update ON ai_pricing_activations
            AS RESTRICTIVE
            FOR UPDATE
            TO PUBLIC
            USING (false)
            WITH CHECK (false);
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY pricing_activations_no_delete ON ai_pricing_activations
            AS RESTRICTIVE
            FOR DELETE
            TO PUBLIC
            USING (false);
            """
        )
    )
    op.execute(sa.text("REVOKE ALL ON TABLE ai_pricing_activations FROM PUBLIC, eduintel_app;"))
    op.execute(sa.text("GRANT SELECT, INSERT ON TABLE ai_pricing_activations TO eduintel_app;"))
    op.execute(
        sa.text("GRANT USAGE, SELECT ON SEQUENCE ai_pricing_activations_activation_seq_seq TO eduintel_app;")
    )

    # 5D. Stage 7.1 tenant operational tables
    for tbl in STAGE7_OPERATIONAL_TABLES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_app_access_policy ON {tbl};"))
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_app_access_policy ON {tbl}
                AS PERMISSIVE
                FOR ALL
                TO eduintel_app
                USING (true)
                WITH CHECK (true);
                """
            )
        )
        op.execute(sa.text(f"REVOKE ALL ON TABLE {tbl} FROM PUBLIC, eduintel_app;"))

    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE tenant_ai_quotas TO eduintel_app;"))
    for tbl in STAGE7_LEDGER_READ_WRITE_TABLES:
        op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE ON TABLE {tbl} TO eduintel_app;"))

    # 5E. Stage 7.1 ai_financial_adjustments
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_app_access_select_policy ON ai_financial_adjustments;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_app_access_insert_policy ON ai_financial_adjustments;"))
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_app_access_select_policy ON ai_financial_adjustments
            AS PERMISSIVE
            FOR SELECT
            TO eduintel_app
            USING (true);
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_app_access_insert_policy ON ai_financial_adjustments
            AS PERMISSIVE
            FOR INSERT
            TO eduintel_app
            WITH CHECK (true);
            """
        )
    )
    op.execute(sa.text("REVOKE ALL ON TABLE ai_financial_adjustments FROM PUBLIC, eduintel_app;"))
    op.execute(sa.text("GRANT SELECT, INSERT ON TABLE ai_financial_adjustments TO eduintel_app;"))


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF current_user = 'eduintel_app' THEN
                    RAISE EXCEPTION
                        'FATAL (Stage 7.1R): Alembic downgrade from 0030 must execute as the migration/schema-owner role, never as eduintel_app.'
                        USING ERRCODE = '42501';
                END IF;
            END $$;
            """
        )
    )

    # 1. Restore permissive policies to eduintel (if present) matching 0029 & pre-0030 baselines
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eduintel') THEN
                    DROP POLICY IF EXISTS tenant_app_access_select_policy ON ai_financial_adjustments;
                    DROP POLICY IF EXISTS tenant_app_access_insert_policy ON ai_financial_adjustments;
                    CREATE POLICY tenant_app_access_select_policy ON ai_financial_adjustments
                        AS PERMISSIVE FOR SELECT TO eduintel USING (true);
                    CREATE POLICY tenant_app_access_insert_policy ON ai_financial_adjustments
                        AS PERMISSIVE FOR INSERT TO eduintel WITH CHECK (true);

                    DROP POLICY IF EXISTS tenant_app_access_policy ON tenant_ai_quotas;
                    CREATE POLICY tenant_app_access_policy ON tenant_ai_quotas
                        AS PERMISSIVE FOR ALL TO eduintel USING (true) WITH CHECK (true);

                    DROP POLICY IF EXISTS tenant_app_access_policy ON tenant_daily_ai_usage;
                    CREATE POLICY tenant_app_access_policy ON tenant_daily_ai_usage
                        AS PERMISSIVE FOR ALL TO eduintel USING (true) WITH CHECK (true);

                    DROP POLICY IF EXISTS tenant_app_access_policy ON tenant_daily_category_usage;
                    CREATE POLICY tenant_app_access_policy ON tenant_daily_category_usage
                        AS PERMISSIVE FOR ALL TO eduintel USING (true) WITH CHECK (true);

                    DROP POLICY IF EXISTS tenant_app_access_policy ON ai_token_reservations;
                    CREATE POLICY tenant_app_access_policy ON ai_token_reservations
                        AS PERMISSIVE FOR ALL TO eduintel USING (true) WITH CHECK (true);

                    DROP POLICY IF EXISTS tenant_app_access_policy ON ai_provider_attempts;
                    CREATE POLICY tenant_app_access_policy ON ai_provider_attempts
                        AS PERMISSIVE FOR ALL TO eduintel USING (true) WITH CHECK (true);

                    DROP POLICY IF EXISTS pricing_versions_read_all ON ai_pricing_versions;
                    DROP POLICY IF EXISTS pricing_versions_admin_insert ON ai_pricing_versions;
                    CREATE POLICY pricing_versions_read_all ON ai_pricing_versions
                        AS PERMISSIVE FOR SELECT TO eduintel USING (true);
                    CREATE POLICY pricing_versions_admin_insert ON ai_pricing_versions
                        AS PERMISSIVE FOR INSERT TO eduintel
                        WITH CHECK (current_setting('app.is_platform_admin', true) = 'true');
                END IF;
            END $$;
            """
        )
    )
    for tbl in LEGACY_RLS_TABLES:
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eduintel') THEN
                        ALTER POLICY tenant_app_access_policy ON {tbl} TO eduintel;
                    END IF;
                END $$;
                """
            )
        )

    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON TABLE ai_pricing_versions TO eduintel_app;"))
    op.execute(sa.text("GRANT EXECUTE ON FUNCTION prevent_finops_immutable_mutation() TO PUBLIC;"))

    # 2. Restore 0029 triggers without TRUNCATE
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ai_pricing_activations_append_only ON ai_pricing_activations;"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ai_financial_adjustments_append_only ON ai_financial_adjustments;"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_ai_financial_adjustments_append_only
            BEFORE UPDATE OR DELETE ON ai_financial_adjustments
            FOR EACH STATEMENT
            EXECUTE FUNCTION prevent_finops_immutable_mutation();
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ai_pricing_versions_immutable ON ai_pricing_versions;"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_ai_pricing_versions_immutable
            BEFORE UPDATE OR DELETE ON ai_pricing_versions
            FOR EACH STATEMENT
            EXECUTE FUNCTION prevent_finops_immutable_mutation();
            """
        )
    )

    # 3. Revert structural constraints & composite FK
    op.drop_constraint(
        "fk_adjustment_res_attempt_tenant",
        "ai_financial_adjustments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_ai_financial_adjustments_attempt_requires_res",
        "ai_financial_adjustments",
        type_="check",
    )
    op.create_foreign_key(
        "fk_adjustment_attempt_tenant",
        "ai_financial_adjustments",
        "ai_provider_attempts",
        ["institution_id", "attempt_id"],
        ["institution_id", "id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint("ck_ai_att_provider_req_id_nonempty", "ai_provider_attempts", type_="check")
    op.drop_constraint("ck_ai_att_model_nonempty", "ai_provider_attempts", type_="check")
    op.drop_constraint("ck_ai_att_provider_nonempty", "ai_provider_attempts", type_="check")
    op.drop_constraint("uq_ai_provider_attempts_inst_res_id", "ai_provider_attempts", type_="unique")

    op.drop_constraint("ck_ai_res_idem_key_nonempty", "ai_token_reservations", type_="check")
    op.drop_constraint("ck_ai_res_endpoint_nonempty", "ai_token_reservations", type_="check")
    op.drop_constraint("ck_ai_res_act_tot_sum", "ai_token_reservations", type_="check")
    op.drop_constraint("ck_ai_res_actual_bounds", "ai_token_reservations", type_="check")
    op.drop_constraint("ck_ai_res_tot_res_sum", "ai_token_reservations", type_="check")
    op.drop_constraint("ck_ai_res_reserved_bounds", "ai_token_reservations", type_="check")
    op.drop_constraint("ck_ai_token_reservations_reconciled_ts", "ai_token_reservations", type_="check")
    op.drop_constraint("ck_ai_token_reservations_dispatched_ts", "ai_token_reservations", type_="check")
    op.create_check_constraint(
        "ck_ai_token_reservations_dispatched_ts",
        "ai_token_reservations",
        "status <> 'DISPATCHED' OR dispatched_at IS NOT NULL",
    )

    # Revert BIGINT widenings back to INTEGER
    for col_name, nullable in (
        ("estimated_tokens", False),
        ("input_tokens", True),
        ("output_tokens", True),
        ("manual_settled_tokens", True),
        ("late_reported_input_tokens", True),
        ("late_reported_output_tokens", True),
    ):
        op.alter_column(
            "ai_provider_attempts",
            col_name,
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=nullable,
        )

    for col_name in (
        "estimated_input_tokens",
        "reserved_output_tokens",
        "total_reserved_tokens",
        "actual_input_tokens",
        "actual_output_tokens",
        "actual_total_tokens",
        "uncertain_tokens_held",
    ):
        op.alter_column(
            "ai_token_reservations",
            col_name,
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

    # 4. Drop ai_pricing_activations table & uq_ai_pricing_versions_id_active
    op.execute(sa.text("DROP POLICY IF EXISTS pricing_activations_no_delete ON ai_pricing_activations;"))
    op.execute(sa.text("DROP POLICY IF EXISTS pricing_activations_no_update ON ai_pricing_activations;"))
    op.execute(sa.text("DROP POLICY IF EXISTS pricing_activations_admin_insert ON ai_pricing_activations;"))
    op.execute(sa.text("DROP POLICY IF EXISTS pricing_activations_read_all ON ai_pricing_activations;"))
    op.drop_index("ix_ai_pricing_activations_active_lookup", table_name="ai_pricing_activations")
    op.drop_table("ai_pricing_activations")
    op.drop_constraint("uq_ai_pricing_versions_id_active", "ai_pricing_versions", type_="unique")

