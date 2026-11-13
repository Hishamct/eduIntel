"""stage 7.1r2 final security, activation sequence, and integrity hardening

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-11 18:20:00.000000

Stage 7.1R2 Final Hardening:
- R-01: Harden `ai_pricing_activations.activation_seq` to `GENERATED ALWAYS AS IDENTITY`,
  add `ck_ai_pricing_activations_seq_pos` (`activation_seq >= 1`), revoke direct runtime
  privileges on `ai_pricing_activations_activation_seq_seq`, and enforce sequence
  integrity against `OVERRIDING SYSTEM VALUE` bypass via `BEFORE INSERT` row trigger
  `trg_ai_pricing_activations_enforce_seq`.
- R-02: Explicitly revoke all privileges (removing residual `TRUNCATE`, `TRIGGER`,
  `REFERENCES`) from `PUBLIC` and `eduintel_app` across `agent_sessions`,
  `agent_session_messages`, `tool_execution_records`, and all legacy operational
  tables before re-granting strict DML (`SELECT, INSERT, UPDATE, DELETE`); scrub
  sequence `UPDATE`/`setval` and unsafe `pg_default_acl` entries across roles/schemas.
- R-03: Enforce `expires_at >= created_at`, `reconciled_at >= dispatched_at` when both
  present, `reconciled_at IS NULL` on `UNKNOWN_USAGE`, consistent token upper bounds
  (`<= 10^15` term / `<= 2*10^15` combined op / `<= 10^17` daily aggregate) to prevent
  `INT8` overflow, and replace `ix_ai_pricing_activations_active_lookup` with non-
  redundant FK/history index `ix_ai_pricing_activations_version_seq`.
  NOTE (R-03.4): `tenant_ai_quotas.missing_usage_policy` value enumeration remains
  deferred/blocked pending stakeholder approval of Stage 7 Business Decision #4; zero
  unapproved policy names are invented.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
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


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Pre-Flight Role Separation & Non-Destructive Data Invariant Checks
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
                        'FATAL (Stage 7.1R2): Alembic migration 0031 must execute as the migration/schema-owner role, NEVER as runtime role eduintel_app.'
                        USING ERRCODE = '42501';
                END IF;

                SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb
                INTO v_app
                FROM pg_roles
                WHERE rolname = 'eduintel_app';

                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'DEPLOYMENT PREREQUISITE MISSING (Stage 7.1R2): Runtime role "eduintel_app" does not exist.'
                        USING ERRCODE = '42501';
                END IF;

                IF v_app.rolsuper OR v_app.rolbypassrls OR v_app.rolcreaterole OR v_app.rolcreatedb THEN
                    RAISE EXCEPTION
                        'SECURITY VIOLATION (Stage 7.1R2): Role "eduintel_app" holds privileged attributes (rolsuper=%, rolbypassrls=%, rolcreaterole=%, rolcreatedb=%).'
                        , v_app.rolsuper, v_app.rolbypassrls, v_app.rolcreaterole, v_app.rolcreatedb
                        USING ERRCODE = '42501';
                END IF;

                -- Ensure runtime role owns no relations or functions in schema public
                FOR v_obj IN
                    SELECT c.relname, c.relkind
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relkind IN ('r', 'p', 'S', 'v', 'm')
                      AND pg_get_userbyid(c.relowner) = 'eduintel_app'
                LOOP
                    IF v_obj.relkind = 'S' THEN
                        EXECUTE format('ALTER SEQUENCE public.%I OWNER TO %I;', v_obj.relname, current_user);
                    ELSIF v_obj.relkind = 'v' THEN
                        EXECUTE format('ALTER VIEW public.%I OWNER TO %I;', v_obj.relname, current_user);
                    ELSIF v_obj.relkind = 'm' THEN
                        EXECUTE format('ALTER MATERIALIZED VIEW public.%I OWNER TO %I;', v_obj.relname, current_user);
                    ELSE
                        EXECUTE format('ALTER TABLE public.%I OWNER TO %I;', v_obj.relname, current_user);
                    END IF;
                END LOOP;

                FOR v_obj IN
                    SELECT p.oid::regprocedure AS proc_sig
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public'
                      AND pg_get_userbyid(p.proowner) = 'eduintel_app'
                LOOP
                    EXECUTE format('ALTER FUNCTION %s OWNER TO %I;', v_obj.proc_sig, current_user);
                END LOOP;

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
                          SELECT 1 FROM pg_class c
                          JOIN pg_namespace n ON n.oid = c.relnamespace
                          WHERE n.nspname = 'public'
                            AND c.relkind IN ('r', 'p', 'S', 'v', 'm')
                            AND pg_get_userbyid(c.relowner) = rt.rolname
                      )
                      OR EXISTS (
                          SELECT 1 FROM pg_proc p
                          JOIN pg_namespace n ON n.oid = p.pronamespace
                          WHERE n.nspname = 'public'
                            AND pg_get_userbyid(p.proowner) = rt.rolname
                      )
                  )
                LIMIT 1;

                IF FOUND THEN
                    RAISE EXCEPTION
                        'ROLE SEPARATION PREREQUISITE FAILED (Stage 7.1R2): Runtime role "eduintel_app" is still a member of privileged/owner role "%" (can_inherit=%, can_set=%).',
                        v_violation.rolname, v_violation.can_inherit, v_violation.can_set
                        USING ERRCODE = '42501';
                END IF;
            END $$;
            """
        )
    )

    # NOTE on data preconditions (R-01 / R-03): All new CHECK constraints below validate
    # the physical heap natively across every row regardless of RLS (`NOBYPASSRLS` migrator
    # safe) and roll back cleanly with SQLSTATE 23514 if any pre-existing row violates them,
    # without rewriting or deleting any existing record.

    # -------------------------------------------------------------------------
    # 2. R-01: Pricing Activation Sequence Integrity
    # -------------------------------------------------------------------------
    # Monotonically synchronize sequence against visible existing rows without ever
    # resetting the sequence downward (critical when table has FORCE RLS under NOBYPASSRLS).
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                v_has_rows BOOLEAN;
                v_max_seq BIGINT;
                v_seq_last BIGINT;
                v_seq_called BOOLEAN;
            BEGIN
                SELECT last_value, is_called
                INTO v_seq_last, v_seq_called
                FROM public.ai_pricing_activations_activation_seq_seq;

                SELECT EXISTS (SELECT 1 FROM public.ai_pricing_activations),
                       COALESCE(MAX(activation_seq), 0)
                INTO v_has_rows, v_max_seq
                FROM public.ai_pricing_activations;

                IF v_has_rows AND ((NOT v_seq_called) OR v_max_seq > v_seq_last) THEN
                    PERFORM pg_catalog.setval(
                        'public.ai_pricing_activations_activation_seq_seq',
                        GREATEST(v_max_seq, v_seq_last),
                        true
                    );
                END IF;
            END $$;
            """
        )
    )
    op.execute(sa.text("ALTER TABLE public.ai_pricing_activations ALTER COLUMN activation_seq SET GENERATED ALWAYS;"))
    op.create_check_constraint(
        "ck_ai_pricing_activations_seq_pos",
        "ai_pricing_activations",
        "activation_seq >= 1",
    )

    # Guard against INSERT ... OVERRIDING SYSTEM VALUE bypassing GENERATED ALWAYS.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION public.enforce_ai_pricing_activation_seq()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                v_curr BIGINT;
            BEGIN
                BEGIN
                    v_curr := pg_catalog.currval('public.ai_pricing_activations_activation_seq_seq');
                EXCEPTION WHEN object_not_in_prerequisite_state THEN
                    RAISE EXCEPTION
                        'Explicit activation_seq override is prohibited on ai_pricing_activations; activation_seq is strictly database-generated.'
                        USING ERRCODE = '42501';
                END;

                IF NEW.activation_seq IS NULL OR NEW.activation_seq <> v_curr THEN
                    RAISE EXCEPTION
                        'Explicit activation_seq (%) is prohibited on ai_pricing_activations (expected database-generated identity value %).',
                        NEW.activation_seq, v_curr
                        USING ERRCODE = '42501';
                END IF;

                RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(sa.text("REVOKE ALL ON FUNCTION public.enforce_ai_pricing_activation_seq() FROM PUBLIC, eduintel_app;"))
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_ai_pricing_activations_enforce_seq ON public.ai_pricing_activations;")
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_ai_pricing_activations_enforce_seq
            BEFORE INSERT ON public.ai_pricing_activations
            FOR EACH ROW
            EXECUTE FUNCTION public.enforce_ai_pricing_activation_seq();
            """
        )
    )

    # -------------------------------------------------------------------------
    # 3. R-02: Legacy Tenant-Table, Sequence, and Default-Privilege Hardening
    # -------------------------------------------------------------------------
    for tbl in LEGACY_RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE public.{tbl} ENABLE ROW LEVEL SECURITY;"))
        op.execute(sa.text(f"ALTER TABLE public.{tbl} FORCE ROW LEVEL SECURITY;"))
        op.execute(sa.text(f"REVOKE ALL ON TABLE public.{tbl} FROM PUBLIC, eduintel_app;"))
        op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{tbl} TO eduintel_app;"))

    for tbl in LEGACY_NON_RLS_OPERATIONAL_TABLES:
        op.execute(sa.text(f"REVOKE ALL ON TABLE public.{tbl} FROM PUBLIC, eduintel_app;"))
        op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{tbl} TO eduintel_app;"))

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF to_regclass('public.backup_recovery_markers') IS NOT NULL THEN
                    EXECUTE 'REVOKE ALL ON TABLE public.backup_recovery_markers FROM PUBLIC, eduintel_app;';
                END IF;
            END $$;
            """
        )
    )

    # Enforce zero PUBLIC/runtime privileges across sequences and default ACLs.
    op.execute(sa.text("REVOKE CREATE ON SCHEMA public FROM PUBLIC, eduintel_app;"))
    op.execute(sa.text("GRANT USAGE ON SCHEMA public TO eduintel_app;"))
    op.execute(sa.text("REVOKE ALL ON TABLE public.alembic_version FROM PUBLIC, eduintel_app;"))
    op.execute(sa.text("GRANT SELECT ON TABLE public.alembic_version TO eduintel_app;"))
    op.execute(sa.text("REVOKE ALL ON FUNCTION public.prevent_finops_immutable_mutation() FROM PUBLIC, eduintel_app;"))

    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                v_seq RECORD;
                v_def RECORD;
                v_is_super BOOLEAN;
                v_creator NAME;
                v_schema NAME;
                v_obj_kw TEXT;
                v_stmt TEXT;
            BEGIN
                -- 3A. Revoke ALL sequence privileges from PUBLIC and eduintel_app.
                -- `GENERATED ALWAYS AS IDENTITY` advances the internal sequence using
                -- table-owner privileges so eduintel_app never needs direct sequence ACLs.
                FOR v_seq IN
                    SELECT n.nspname, c.relname
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind = 'S'
                      AND n.nspname NOT LIKE 'pg_%'
                      AND n.nspname <> 'information_schema'
                LOOP
                    EXECUTE format(
                        'REVOKE ALL ON SEQUENCE %I.%I FROM PUBLIC, eduintel_app;',
                        v_seq.nspname,
                        v_seq.relname
                    );
                END LOOP;

                -- 3B. Scrub default privileges for the executing migration role in both
                -- schema `public` and cluster-global scope.
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, eduintel_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC, eduintel_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM eduintel_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TYPES FROM PUBLIC, eduintel_app;

                ALTER DEFAULT PRIVILEGES REVOKE ALL ON TABLES FROM PUBLIC, eduintel_app;
                ALTER DEFAULT PRIVILEGES REVOKE ALL ON SEQUENCES FROM PUBLIC, eduintel_app;
                ALTER DEFAULT PRIVILEGES REVOKE ALL ON FUNCTIONS FROM eduintel_app;
                ALTER DEFAULT PRIVILEGES REVOKE ALL ON TYPES FROM PUBLIC, eduintel_app;

                -- 3C. Inspect every entry in pg_default_acl across all roles & schemas
                -- so pre-existing creator roles (e.g. `eduintel` on legacy clusters)
                -- cannot leave lingering default GRANTS to `eduintel_app` or PUBLIC.
                SELECT rolsuper INTO v_is_super FROM pg_roles WHERE rolname = current_user;

                FOR v_def IN
                    SELECT d.defaclrole, d.defaclnamespace, d.defaclobjtype,
                           r.rolname AS creator_name, n.nspname AS schema_name,
                           d.defaclacl::text AS acl_text
                    FROM pg_default_acl d
                    JOIN pg_roles r ON r.oid = d.defaclrole
                    LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
                    WHERE d.defaclacl::text ~ '(eduintel_app=|(^|[{,])=)'
                LOOP
                    v_creator := v_def.creator_name;
                    v_schema := v_def.schema_name;
                    v_obj_kw := CASE v_def.defaclobjtype
                        WHEN 'r' THEN 'TABLES'
                        WHEN 'S' THEN 'SEQUENCES'
                        WHEN 'f' THEN 'FUNCTIONS'
                        WHEN 'T' THEN 'TYPES'
                        WHEN 'n' THEN 'SCHEMAS'
                        ELSE NULL
                    END;

                    IF v_obj_kw IS NULL THEN
                        CONTINUE;
                    END IF;

                    IF NOT (v_is_super OR v_creator = current_user OR pg_has_role(current_user, v_def.defaclrole, 'SET')) THEN
                        RAISE EXCEPTION
                            'DEFAULT PRIVILEGE REMEDIATION BLOCKED (Stage 7.1R2): Role "%" holds unsafe pg_default_acl (%) on % in schema "%" that current role "%" lacks permission to alter.',
                            v_creator, v_def.acl_text, v_obj_kw, COALESCE(v_schema, '<GLOBAL>'), current_user
                            USING ERRCODE = '42501';
                    END IF;

                    IF v_schema IS NOT NULL THEN
                        v_stmt := format(
                            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON %s FROM PUBLIC, eduintel_app;',
                            v_creator, v_schema, v_obj_kw
                        );
                    ELSE
                        v_stmt := format(
                            'ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON %s FROM PUBLIC, eduintel_app;',
                            v_creator, v_obj_kw
                        );
                    END IF;
                    EXECUTE v_stmt;
                END LOOP;
            END $$;
            """
        )
    )

    # -------------------------------------------------------------------------
    # 4. R-03: Integrity Constraints & Activation Index Hardening
    # -------------------------------------------------------------------------
    # 4A. Reservation timestamp & UNKNOWN_USAGE reconciliation invariants + uncertain bound
    op.drop_constraint(
        "ck_ai_token_reservations_reconciled_ts",
        "ai_token_reservations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_token_reservations_reconciled_ts",
        "ai_token_reservations",
        "(status NOT IN ('COMMITTED', 'RELEASED') OR reconciled_at IS NOT NULL) "
        "AND (status NOT IN ('RESERVED', 'DISPATCHED', 'UNKNOWN_USAGE') OR reconciled_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_ai_token_reservations_expires_after_created",
        "ai_token_reservations",
        "expires_at >= created_at",
    )
    op.create_check_constraint(
        "ck_ai_token_reservations_reconciled_after_dispatch",
        "ai_token_reservations",
        "dispatched_at IS NULL OR reconciled_at IS NULL OR reconciled_at >= dispatched_at",
    )
    op.create_check_constraint(
        "ck_ai_res_unc_tok_bounds",
        "ai_token_reservations",
        "uncertain_tokens_held <= 2000000000000000",
    )

    # 4B. Attempt token bounds aligned with reservation term/combined bounds
    op.create_check_constraint(
        "ck_ai_att_est_tok_bounds",
        "ai_provider_attempts",
        "estimated_tokens <= 2000000000000000",
    )
    op.create_check_constraint(
        "ck_ai_att_in_tok_bounds",
        "ai_provider_attempts",
        "input_tokens IS NULL OR input_tokens <= 1000000000000000",
    )
    op.create_check_constraint(
        "ck_ai_att_out_tok_bounds",
        "ai_provider_attempts",
        "output_tokens IS NULL OR output_tokens <= 1000000000000000",
    )
    op.create_check_constraint(
        "ck_ai_att_man_tok_bounds",
        "ai_provider_attempts",
        "manual_settled_tokens IS NULL OR manual_settled_tokens <= 2000000000000000",
    )
    op.create_check_constraint(
        "ck_ai_att_late_in_bounds",
        "ai_provider_attempts",
        "late_reported_input_tokens IS NULL OR late_reported_input_tokens <= 1000000000000000",
    )
    op.create_check_constraint(
        "ck_ai_att_late_out_bounds",
        "ai_provider_attempts",
        "late_reported_output_tokens IS NULL OR late_reported_output_tokens <= 1000000000000000",
    )

    # 4C. Aggregate daily ledger & adjustment overflow bounds
    op.create_check_constraint(
        "ck_tenant_daily_ai_usage_tok_bounds",
        "tenant_daily_ai_usage",
        "committed_total_tokens <= 100000000000000000 "
        "AND pending_reserved_tokens <= 100000000000000000 "
        "AND uncertain_reserved_tokens <= 100000000000000000",
    )
    op.create_check_constraint(
        "ck_tenant_daily_cat_tok_bounds",
        "tenant_daily_category_usage",
        "committed_input_tokens <= 100000000000000000 "
        "AND committed_output_tokens <= 100000000000000000 "
        "AND committed_total_tokens <= 100000000000000000 "
        "AND pending_reserved_tokens <= 100000000000000000 "
        "AND uncertain_reserved_tokens <= 100000000000000000",
    )
    op.create_check_constraint(
        "ck_ai_financial_adjustments_token_delta_bounds",
        "ai_financial_adjustments",
        "token_delta >= -2000000000000000 AND token_delta <= 2000000000000000",
    )

    # 4D. Replace redundant/misordered activation index with FK & per-version history index.
    # Global `ORDER BY activation_seq DESC LIMIT 1` already uses `uq_ai_pricing_activations_seq`.
    op.drop_index("ix_ai_pricing_activations_active_lookup", table_name="ai_pricing_activations")
    op.create_index(
        "ix_ai_pricing_activations_version_seq",
        "ai_pricing_activations",
        ["pricing_version", "activation_seq"],
        unique=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF current_user = 'eduintel_app' THEN
                    RAISE EXCEPTION
                        'FATAL (Stage 7.1R2): Alembic downgrade from 0031 must execute as the migration/schema-owner role, NEVER as eduintel_app.'
                        USING ERRCODE = '42501';
                END IF;
            END $$;
            """
        )
    )

    # 1. Revert R-03 index & constraints
    op.drop_index("ix_ai_pricing_activations_version_seq", table_name="ai_pricing_activations")
    op.create_index(
        "ix_ai_pricing_activations_active_lookup",
        "ai_pricing_activations",
        ["activated_at", "activation_seq"],
        unique=False,
    )

    op.drop_constraint(
        "ck_ai_financial_adjustments_token_delta_bounds",
        "ai_financial_adjustments",
        type_="check",
    )
    op.drop_constraint("ck_tenant_daily_cat_tok_bounds", "tenant_daily_category_usage", type_="check")
    op.drop_constraint("ck_tenant_daily_ai_usage_tok_bounds", "tenant_daily_ai_usage", type_="check")

    for name in (
        "ck_ai_att_late_out_bounds",
        "ck_ai_att_late_in_bounds",
        "ck_ai_att_man_tok_bounds",
        "ck_ai_att_out_tok_bounds",
        "ck_ai_att_in_tok_bounds",
        "ck_ai_att_est_tok_bounds",
    ):
        op.drop_constraint(name, "ai_provider_attempts", type_="check")

    op.drop_constraint("ck_ai_res_unc_tok_bounds", "ai_token_reservations", type_="check")
    op.drop_constraint(
        "ck_ai_token_reservations_reconciled_after_dispatch",
        "ai_token_reservations",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_token_reservations_expires_after_created",
        "ai_token_reservations",
        type_="check",
    )
    op.drop_constraint("ck_ai_token_reservations_reconciled_ts", "ai_token_reservations", type_="check")
    op.create_check_constraint(
        "ck_ai_token_reservations_reconciled_ts",
        "ai_token_reservations",
        "(status NOT IN ('COMMITTED', 'RELEASED') OR reconciled_at IS NOT NULL) "
        "AND (status NOT IN ('RESERVED', 'DISPATCHED') OR reconciled_at IS NULL)",
    )

    # 2. Safe R-02 policy on downgrade: intentionally DO NOT re-grant TRUNCATE,
    # TRIGGER, REFERENCES, sequence UPDATE/setval, or unsafe pg_default_acl grants.
    # Only restore narrow `USAGE, SELECT` on activation sequence required when reverting
    # `activation_seq` back to `GENERATED BY DEFAULT` at revision 0030.
    op.execute(
        sa.text("GRANT USAGE, SELECT ON SEQUENCE public.ai_pricing_activations_activation_seq_seq TO eduintel_app;")
    )

    # 3. Revert R-01 activation sequence hardening cleanly while preserving existing sequence position
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_ai_pricing_activations_enforce_seq ON public.ai_pricing_activations;")
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS public.enforce_ai_pricing_activation_seq();"))
    op.drop_constraint("ck_ai_pricing_activations_seq_pos", "ai_pricing_activations", type_="check")
    op.execute(
        sa.text("ALTER TABLE public.ai_pricing_activations ALTER COLUMN activation_seq SET GENERATED BY DEFAULT;")
    )
