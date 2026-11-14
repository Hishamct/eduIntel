"""stage 7.4 add ai quota plans, provisioning audit, and risk reserve

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-13 14:30:00.000000

Stage 7.4 Additions:
- Creates `ai_quota_plans` catalog table with Starter, Growth, Enterprise, and Custom plan templates.
- Alters `tenant_ai_quotas` to add `plan_id` and `risk_reserve_percent` for explicit provisioning and risk reserve calculation.
- Creates `tenant_quota_provisioning_logs` append-only audit trail for all tenant quota provisioning and plan change events.
- Establishes strict PostgreSQL RLS policies, immutability triggers, and least-privilege grants for runtime role `eduintel_app`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Create table: ai_quota_plans
    # -------------------------------------------------------------------------
    op.create_table(
        "ai_quota_plans",
        sa.Column("plan_id", sa.String(length=50), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("daily_financial_ceiling_inr", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column(
            "risk_reserve_percent",
            sa.Numeric(precision=5, scale=4),
            server_default=sa.text("0.1000"),
            nullable=False,
        ),
        sa.Column("daily_interactive_token_limit", sa.BigInteger(), nullable=False),
        sa.Column("daily_ingestion_token_limit", sa.BigInteger(), nullable=False),
        sa.Column(
            "daily_other_token_limit",
            sa.BigInteger(),
            server_default=sa.text("50000"),
            nullable=False,
        ),
        sa.Column("monthly_total_token_limit", sa.BigInteger(), nullable=True),
        sa.Column(
            "max_tokens_per_request",
            sa.Integer(),
            server_default=sa.text("4096"),
            nullable=False,
        ),
        sa.Column(
            "missing_usage_policy",
            sa.String(length=40),
            server_default=sa.text("'HOLD_UNKNOWN'"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(btrim(plan_id)) > 0", name="ck_ai_quota_plans_id_nonempty"),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_ai_quota_plans_name_nonempty"),
        sa.CheckConstraint("daily_financial_ceiling_inr >= 0", name="ck_ai_quota_plans_ceiling_nonneg"),
        sa.CheckConstraint(
            "risk_reserve_percent >= 0 AND risk_reserve_percent <= 1",
            name="ck_ai_quota_plans_reserve_pct",
        ),
        sa.CheckConstraint("daily_interactive_token_limit >= 0", name="ck_ai_quota_plans_interactive_nonneg"),
        sa.CheckConstraint("daily_ingestion_token_limit >= 0", name="ck_ai_quota_plans_ingestion_nonneg"),
        sa.CheckConstraint("daily_other_token_limit >= 0", name="ck_ai_quota_plans_other_nonneg"),
        sa.CheckConstraint(
            "monthly_total_token_limit IS NULL OR monthly_total_token_limit >= 0",
            name="ck_ai_quota_plans_monthly_nonneg",
        ),
        sa.CheckConstraint("max_tokens_per_request > 0", name="ck_ai_quota_plans_max_tok_pos"),
    )

    # Seed default approved plans: Starter, Growth, Enterprise, Custom
    plans_table = sa.table(
        "ai_quota_plans",
        sa.column("plan_id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("daily_financial_ceiling_inr", sa.Numeric),
        sa.column("risk_reserve_percent", sa.Numeric),
        sa.column("daily_interactive_token_limit", sa.BigInteger),
        sa.column("daily_ingestion_token_limit", sa.BigInteger),
        sa.column("daily_other_token_limit", sa.BigInteger),
        sa.column("monthly_total_token_limit", sa.BigInteger),
        sa.column("max_tokens_per_request", sa.Integer),
        sa.column("missing_usage_policy", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        plans_table,
        [
            {
                "plan_id": "starter",
                "name": "Starter Plan",
                "description": "Entry-level plan for smaller coaching batches (₹100/day, 10% risk reserve)",
                "daily_financial_ceiling_inr": 100.0000,
                "risk_reserve_percent": 0.1000,
                "daily_interactive_token_limit": 100000,
                "daily_ingestion_token_limit": 50000,
                "daily_other_token_limit": 50000,
                "monthly_total_token_limit": 3000000,
                "max_tokens_per_request": 4096,
                "missing_usage_policy": "HOLD_UNKNOWN",
                "is_active": True,
            },
            {
                "plan_id": "growth",
                "name": "Growth Plan",
                "description": "Standard plan for expanding institutes (₹300/day, 10% risk reserve)",
                "daily_financial_ceiling_inr": 300.0000,
                "risk_reserve_percent": 0.1000,
                "daily_interactive_token_limit": 300000,
                "daily_ingestion_token_limit": 200000,
                "daily_other_token_limit": 100000,
                "monthly_total_token_limit": 10000000,
                "max_tokens_per_request": 8192,
                "missing_usage_policy": "HOLD_UNKNOWN",
                "is_active": True,
            },
            {
                "plan_id": "enterprise",
                "name": "Enterprise Plan",
                "description": "High-throughput plan for large institutes (₹750/day, 10% risk reserve)",
                "daily_financial_ceiling_inr": 750.0000,
                "risk_reserve_percent": 0.1000,
                "daily_interactive_token_limit": 750000,
                "daily_ingestion_token_limit": 500000,
                "daily_other_token_limit": 250000,
                "monthly_total_token_limit": 30000000,
                "max_tokens_per_request": 16384,
                "missing_usage_policy": "HOLD_UNKNOWN",
                "is_active": True,
            },
            {
                "plan_id": "custom",
                "name": "Custom Enterprise Plan",
                "description": "Customizable enterprise quota plan with individually negotiated limits",
                "daily_financial_ceiling_inr": 750.0000,
                "risk_reserve_percent": 0.1000,
                "daily_interactive_token_limit": 750000,
                "daily_ingestion_token_limit": 500000,
                "daily_other_token_limit": 250000,
                "monthly_total_token_limit": 30000000,
                "max_tokens_per_request": 16384,
                "missing_usage_policy": "HOLD_UNKNOWN",
                "is_active": True,
            },
        ],
    )

    # -------------------------------------------------------------------------
    # 2. Alter table: tenant_ai_quotas (add plan_id and risk_reserve_percent)
    # -------------------------------------------------------------------------
    op.add_column(
        "tenant_ai_quotas",
        sa.Column("plan_id", sa.String(length=50), nullable=True),
    )
    op.create_foreign_key(
        "fk_tenant_ai_quotas_plan_id",
        "tenant_ai_quotas",
        "ai_quota_plans",
        ["plan_id"],
        ["plan_id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "tenant_ai_quotas",
        sa.Column(
            "risk_reserve_percent",
            sa.Numeric(precision=5, scale=4),
            server_default=sa.text("0.0000"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_tenant_ai_quotas_risk_reserve_pct",
        "tenant_ai_quotas",
        "risk_reserve_percent >= 0 AND risk_reserve_percent <= 1",
    )

    # -------------------------------------------------------------------------
    # 3. Create table: tenant_quota_provisioning_logs (Append-Only Audit Log)
    # -------------------------------------------------------------------------
    op.create_table(
        "tenant_quota_provisioning_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("changed_by_actor", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("previous_plan_id", sa.String(length=50), nullable=True),
        sa.Column("new_plan_id", sa.String(length=50), nullable=False),
        sa.Column("change_reason", sa.String(length=255), nullable=False),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("char_length(btrim(changed_by_actor)) > 0", name="ck_quota_prov_actor_nonempty"),
        sa.CheckConstraint("char_length(btrim(action)) > 0", name="ck_quota_prov_action_nonempty"),
        sa.CheckConstraint("char_length(btrim(change_reason)) > 0", name="ck_quota_prov_reason_nonempty"),
    )
    op.create_index(
        "ix_quota_provisioning_logs_inst_created",
        "tenant_quota_provisioning_logs",
        ["institution_id", "created_at"],
        unique=False,
    )

    # -------------------------------------------------------------------------
    # 4. Immutability Trigger on tenant_quota_provisioning_logs
    # -------------------------------------------------------------------------
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_tenant_quota_provisioning_logs_append_only
            BEFORE UPDATE OR DELETE ON tenant_quota_provisioning_logs
            FOR EACH STATEMENT
            EXECUTE FUNCTION prevent_finops_immutable_mutation();
            """
        )
    )

    # -------------------------------------------------------------------------
    # 5. RLS Policies and Runtime Permissions
    # -------------------------------------------------------------------------
    # 5A. ai_quota_plans (Global catalog)
    op.execute(sa.text("ALTER TABLE ai_quota_plans ENABLE ROW LEVEL SECURITY;"))
    op.execute(sa.text("ALTER TABLE ai_quota_plans FORCE ROW LEVEL SECURITY;"))
    op.execute(
        sa.text(
            """
            CREATE POLICY ai_quota_plans_read_all ON ai_quota_plans
            AS PERMISSIVE FOR SELECT
            TO PUBLIC
            USING (true);
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY ai_quota_plans_admin_manage ON ai_quota_plans
            AS PERMISSIVE FOR ALL
            TO PUBLIC
            USING (current_setting('app.is_platform_admin', true) = 'true')
            WITH CHECK (current_setting('app.is_platform_admin', true) = 'true');
            """
        )
    )
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON ai_quota_plans TO eduintel_app;"))

    # 5B. tenant_quota_provisioning_logs (Tenant-scoped audit ledger)
    op.execute(sa.text("ALTER TABLE tenant_quota_provisioning_logs ENABLE ROW LEVEL SECURITY;"))
    op.execute(sa.text("ALTER TABLE tenant_quota_provisioning_logs FORCE ROW LEVEL SECURITY;"))
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_quota_prov_read ON tenant_quota_provisioning_logs
            AS PERMISSIVE FOR SELECT
            TO PUBLIC
            USING (
                institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                OR current_setting('app.is_platform_admin', true) = 'true'
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_quota_prov_insert ON tenant_quota_provisioning_logs
            AS PERMISSIVE FOR INSERT
            TO PUBLIC
            WITH CHECK (
                current_setting('app.is_platform_admin', true) = 'true'
                OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
            );
            """
        )
    )
    op.execute(sa.text("GRANT SELECT, INSERT ON tenant_quota_provisioning_logs TO eduintel_app;"))


def downgrade() -> None:
    # 1. Drop policies and table: tenant_quota_provisioning_logs
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_tenant_quota_provisioning_logs_append_only ON tenant_quota_provisioning_logs;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_quota_prov_insert ON tenant_quota_provisioning_logs;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_quota_prov_read ON tenant_quota_provisioning_logs;"))
    op.drop_index("ix_quota_provisioning_logs_inst_created", table_name="tenant_quota_provisioning_logs")
    op.drop_table("tenant_quota_provisioning_logs")

    # 2. Alter table: tenant_ai_quotas (remove risk_reserve_percent and plan_id)
    op.drop_constraint("ck_tenant_ai_quotas_risk_reserve_pct", "tenant_ai_quotas", type_="check")
    op.drop_column("tenant_ai_quotas", "risk_reserve_percent")
    op.drop_constraint("fk_tenant_ai_quotas_plan_id", "tenant_ai_quotas", type_="foreignkey")
    op.drop_column("tenant_ai_quotas", "plan_id")

    # 3. Drop policies and table: ai_quota_plans
    op.execute(sa.text("DROP POLICY IF EXISTS ai_quota_plans_admin_manage ON ai_quota_plans;"))
    op.execute(sa.text("DROP POLICY IF EXISTS ai_quota_plans_read_all ON ai_quota_plans;"))
    op.drop_table("ai_quota_plans")

