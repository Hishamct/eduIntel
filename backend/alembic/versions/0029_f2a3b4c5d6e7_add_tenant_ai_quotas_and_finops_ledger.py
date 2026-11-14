"""add tenant ai quotas and finops ledger tables

Revision ID: f2a3b4c5d6e7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-11 16:00:00.000000

Stage 7.1 Database Foundation:
Creates 7 tables for multi-tenant AI token quotas, provider attempt accounting,
and FinOps reconciliation:
1. ai_pricing_versions (Global immutable pricing schedule)
2. tenant_ai_quotas (Per-institution quota policies)
3. tenant_daily_ai_usage (Lock Level 1: Daily financial & rollup ledger)
4. tenant_daily_category_usage (Lock Level 2: Daily category token buckets)
5. ai_token_reservations (Lock Level 3: Two-phase reservation ledger)
6. ai_provider_attempts (Lock Level 4: External provider attempt tracking)
7. ai_financial_adjustments (Append-only FinOps adjustment audit log)

Zero unapproved pricing or limit values are seeded.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPERATIONAL_TENANT_TABLES = (
    "tenant_ai_quotas",
    "tenant_daily_ai_usage",
    "tenant_daily_category_usage",
    "ai_token_reservations",
    "ai_provider_attempts",
)

LEDGER_READ_WRITE_TABLES = (
    "tenant_daily_ai_usage",
    "tenant_daily_category_usage",
    "ai_token_reservations",
    "ai_provider_attempts",
)


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. ai_pricing_versions (Global Immutable Reference Table)
    # -------------------------------------------------------------------------
    op.create_table(
        "ai_pricing_versions",
        sa.Column("version_id", sa.String(length=50), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("usd_to_inr_rate", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("rate_source", sa.String(length=100), nullable=False),
        sa.Column("rates_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("version_id"),
        sa.CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency)",
            name="ck_ai_pricing_versions_currency_iso",
        ),
        sa.CheckConstraint("usd_to_inr_rate > 0", name="ck_ai_pricing_versions_rate_pos"),
        sa.CheckConstraint(
            "char_length(btrim(version_id)) > 0",
            name="ck_ai_pricing_versions_version_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(btrim(rate_source)) > 0",
            name="ck_ai_pricing_versions_source_nonempty",
        ),
    )

    # -------------------------------------------------------------------------
    # 2. tenant_ai_quotas (Tenant Quota Policies — No Hardcoded Unapproved Defaults)
    # -------------------------------------------------------------------------
    op.create_table(
        "tenant_ai_quotas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quota_timezone", sa.String(length=64), nullable=False),
        sa.Column("daily_interactive_token_limit", sa.BigInteger(), nullable=False),
        sa.Column("daily_ingestion_token_limit", sa.BigInteger(), nullable=False),
        sa.Column("daily_other_token_limit", sa.BigInteger(), nullable=False),
        sa.Column("monthly_total_token_limit", sa.BigInteger(), nullable=True),
        sa.Column("daily_exposure_limit_inr", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("pending_reserve_cap_percent", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("max_tokens_per_request", sa.Integer(), nullable=False),
        sa.Column("missing_usage_policy", sa.String(length=40), nullable=False),
        sa.Column("is_unlimited", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_suspended", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("suspension_reason", sa.Text(), nullable=True),
        sa.Column("tier_name", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("institution_id", name="uq_tenant_ai_quotas_institution_id"),
        sa.CheckConstraint("daily_interactive_token_limit >= 0", name="ck_tenant_ai_quotas_interactive_nonneg"),
        sa.CheckConstraint("daily_ingestion_token_limit >= 0", name="ck_tenant_ai_quotas_ingestion_nonneg"),
        sa.CheckConstraint("daily_other_token_limit >= 0", name="ck_tenant_ai_quotas_other_nonneg"),
        sa.CheckConstraint(
            "monthly_total_token_limit IS NULL OR monthly_total_token_limit >= 0",
            name="ck_tenant_ai_quotas_monthly_nonneg",
        ),
        sa.CheckConstraint("daily_exposure_limit_inr >= 0", name="ck_tenant_ai_quotas_exposure_nonneg"),
        sa.CheckConstraint(
            "pending_reserve_cap_percent >= 0 AND pending_reserve_cap_percent <= 1",
            name="ck_tenant_ai_quotas_reserve_pct_range",
        ),
        sa.CheckConstraint("max_tokens_per_request > 0", name="ck_tenant_ai_quotas_max_tokens_pos"),
        sa.CheckConstraint("char_length(btrim(quota_timezone)) > 0", name="ck_tenant_ai_quotas_tz_nonempty"),
        sa.CheckConstraint(
            "char_length(btrim(missing_usage_policy)) > 0",
            name="ck_tenant_ai_quotas_missing_policy_nonempty",
        ),
        sa.CheckConstraint("char_length(btrim(tier_name)) > 0", name="ck_tenant_ai_quotas_tier_nonempty"),
    )

    # -------------------------------------------------------------------------
    # 3. tenant_daily_ai_usage (Lock Level 1 — Parent Financial Rollup)
    # -------------------------------------------------------------------------
    op.create_table(
        "tenant_daily_ai_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("committed_cost_inr", sa.Numeric(precision=14, scale=4), server_default=sa.text("0.0000"), nullable=False),
        sa.Column("pending_reserved_cost_inr", sa.Numeric(precision=14, scale=4), server_default=sa.text("0.0000"), nullable=False),
        sa.Column("uncertain_exposure_cost_inr", sa.Numeric(precision=14, scale=4), server_default=sa.text("0.0000"), nullable=False),
        sa.Column("committed_total_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("pending_reserved_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("uncertain_reserved_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("fallback_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unknown_usage_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("institution_id", "usage_date", name="uq_tenant_daily_usage_date"),
        sa.CheckConstraint("committed_cost_inr >= 0", name="ck_tenant_daily_ai_usage_committed_cost_nonneg"),
        sa.CheckConstraint("pending_reserved_cost_inr >= 0", name="ck_tenant_daily_ai_usage_pending_cost_nonneg"),
        sa.CheckConstraint("uncertain_exposure_cost_inr >= 0", name="ck_tenant_daily_ai_usage_uncertain_cost_nonneg"),
        sa.CheckConstraint("committed_total_tokens >= 0", name="ck_tenant_daily_ai_usage_committed_tokens_nonneg"),
        sa.CheckConstraint("pending_reserved_tokens >= 0", name="ck_tenant_daily_ai_usage_pending_tokens_nonneg"),
        sa.CheckConstraint("uncertain_reserved_tokens >= 0", name="ck_tenant_daily_ai_usage_uncertain_tokens_nonneg"),
        sa.CheckConstraint("request_count >= 0", name="ck_tenant_daily_ai_usage_req_count_nonneg"),
        sa.CheckConstraint("fallback_count >= 0", name="ck_tenant_daily_ai_usage_fallback_count_nonneg"),
        sa.CheckConstraint("unknown_usage_count >= 0", name="ck_tenant_daily_ai_usage_unknown_count_nonneg"),
        sa.CheckConstraint("version >= 1", name="ck_tenant_daily_ai_usage_version_pos"),
    )
    op.create_index(
        "ix_tenant_daily_ai_usage_date_inst",
        "tenant_daily_ai_usage",
        ["usage_date", "institution_id"],
        unique=False,
    )

    # -------------------------------------------------------------------------
    # 4. tenant_daily_category_usage (Lock Level 2 — Category Quota Ledger)
    # -------------------------------------------------------------------------
    op.create_table(
        "tenant_daily_category_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("usage_category", sa.String(length=40), nullable=False),
        sa.Column("committed_input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("committed_output_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("committed_total_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("pending_reserved_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("uncertain_reserved_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("committed_cost_inr", sa.Numeric(precision=14, scale=4), server_default=sa.text("0.0000"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["institution_id", "usage_date"],
            ["tenant_daily_ai_usage.institution_id", "tenant_daily_ai_usage.usage_date"],
            ondelete="RESTRICT",
            name="fk_category_usage_daily_parent",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "institution_id",
            "usage_date",
            "usage_category",
            name="uq_tenant_daily_category_date",
        ),
        sa.CheckConstraint(
            "usage_category IN ('interactive_ai', 'ingestion_embeddings', 'other_metered')",
            name="ck_tenant_daily_category_usage_category",
        ),
        sa.CheckConstraint("committed_input_tokens >= 0", name="ck_tenant_daily_cat_committed_in_nonneg"),
        sa.CheckConstraint("committed_output_tokens >= 0", name="ck_tenant_daily_cat_committed_out_nonneg"),
        sa.CheckConstraint("committed_total_tokens >= 0", name="ck_tenant_daily_cat_committed_tot_nonneg"),
        sa.CheckConstraint("pending_reserved_tokens >= 0", name="ck_tenant_daily_cat_pending_nonneg"),
        sa.CheckConstraint("uncertain_reserved_tokens >= 0", name="ck_tenant_daily_cat_uncertain_nonneg"),
        sa.CheckConstraint("committed_cost_inr >= 0", name="ck_tenant_daily_cat_cost_nonneg"),
    )

    # -------------------------------------------------------------------------
    # 5. ai_token_reservations (Lock Level 3 — Two-Phase Reservation Ledger)
    # -------------------------------------------------------------------------
    op.create_table(
        "ai_token_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logical_operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("usage_category", sa.String(length=40), nullable=False),
        sa.Column("endpoint", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'RESERVED'"), nullable=False),
        sa.Column("pricing_version", sa.String(length=50), nullable=False),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_cost_inr", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("actual_input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("actual_output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("actual_total_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("actual_cost_inr", sa.Numeric(precision=12, scale=4), server_default=sa.text("0.0000"), nullable=False),
        sa.Column("uncertain_tokens_held", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("uncertain_cost_held_inr", sa.Numeric(precision=12, scale=4), server_default=sa.text("0.0000"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("reconciliation_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("recovery_state", sa.String(length=40), server_default=sa.text("'NONE'"), nullable=False),
        sa.Column("recovery_reason", sa.String(length=100), nullable=True),
        sa.Column("sweeper_lease_owner", sa.String(length=100), nullable=True),
        sa.Column("sweeper_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_status", sa.String(length=40), server_default=sa.text("'NONE'"), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pricing_version"], ["ai_pricing_versions.version_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["institution_id", "usage_date", "usage_category"],
            [
                "tenant_daily_category_usage.institution_id",
                "tenant_daily_category_usage.usage_date",
                "tenant_daily_category_usage.usage_category",
            ],
            ondelete="RESTRICT",
            name="fk_reservation_category_parent",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("institution_id", "id", name="uq_ai_token_reservations_inst_id"),
        sa.CheckConstraint(
            "status IN ('RESERVED', 'DISPATCHED', 'COMMITTED', 'RELEASED', 'UNKNOWN_USAGE')",
            name="ck_ai_token_reservations_status",
        ),
        sa.CheckConstraint(
            "usage_category IN ('interactive_ai', 'ingestion_embeddings', 'other_metered')",
            name="ck_ai_token_reservations_category",
        ),
        sa.CheckConstraint(
            "recovery_state IN ('NONE', 'SWEEPER_CLAIMED', 'LEASE_EXPIRED_RECOVERED')",
            name="ck_ai_token_reservations_recovery_state",
        ),
        sa.CheckConstraint(
            "review_status IN ('NONE', 'NEEDS_MANUAL_REVIEW', 'MANUALLY_SETTLED', 'LATE_EVIDENCE_REVIEW_REQUIRED')",
            name="ck_ai_token_reservations_review_status",
        ),
        sa.CheckConstraint(
            "status <> 'DISPATCHED' OR dispatched_at IS NOT NULL",
            name="ck_ai_token_reservations_dispatched_ts",
        ),
        sa.CheckConstraint(
            "status <> 'RESERVED' OR dispatched_at IS NULL",
            name="ck_ai_token_reservations_reserved_no_dispatch",
        ),
        sa.CheckConstraint("estimated_input_tokens >= 0", name="ck_ai_res_est_in_nonneg"),
        sa.CheckConstraint("reserved_output_tokens >= 0", name="ck_ai_res_res_out_nonneg"),
        sa.CheckConstraint("total_reserved_tokens >= 0", name="ck_ai_res_tot_res_nonneg"),
        sa.CheckConstraint("reserved_cost_inr >= 0", name="ck_ai_res_cost_nonneg"),
        sa.CheckConstraint("actual_input_tokens >= 0", name="ck_ai_res_act_in_nonneg"),
        sa.CheckConstraint("actual_output_tokens >= 0", name="ck_ai_res_act_out_nonneg"),
        sa.CheckConstraint("actual_total_tokens >= 0", name="ck_ai_res_act_tot_nonneg"),
        sa.CheckConstraint("actual_cost_inr >= 0", name="ck_ai_res_act_cost_nonneg"),
        sa.CheckConstraint("uncertain_tokens_held >= 0", name="ck_ai_res_unc_tok_nonneg"),
        sa.CheckConstraint("uncertain_cost_held_inr >= 0", name="ck_ai_res_unc_cost_nonneg"),
        sa.CheckConstraint("reconciliation_version >= 1", name="ck_ai_res_rec_ver_pos"),
    )
    op.create_index(
        "uq_ai_reservations_idempotency",
        "ai_token_reservations",
        ["institution_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_ai_reservations_recovery",
        "ai_token_reservations",
        ["status", "expires_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('RESERVED', 'DISPATCHED')"),
    )
    op.create_index(
        "ix_ai_reservations_inst_created",
        "ai_token_reservations",
        ["institution_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_reservations_logical_op",
        "ai_token_reservations",
        ["institution_id", "logical_operation_id"],
        unique=False,
    )

    # -------------------------------------------------------------------------
    # 6. ai_provider_attempts (Lock Level 4 — Individual External Attempts)
    # -------------------------------------------------------------------------
    op.create_table(
        "ai_provider_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logical_operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_sequence", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("is_fallback", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_retry", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'DISPATCHED'"), nullable=False),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("pricing_version", sa.String(length=50), nullable=False),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_inr", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_cost_inr", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("manual_settled_tokens", sa.Integer(), nullable=True),
        sa.Column("manual_settled_cost_inr", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("manual_settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("late_reported_input_tokens", sa.Integer(), nullable=True),
        sa.Column("late_reported_output_tokens", sa.Integer(), nullable=True),
        sa.Column("late_reported_cost_inr", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("late_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_classification", sa.String(length=60), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pricing_version"], ["ai_pricing_versions.version_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["institution_id", "reservation_id"],
            ["ai_token_reservations.institution_id", "ai_token_reservations.id"],
            ondelete="RESTRICT",
            name="fk_attempt_reservation_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("institution_id", "id", name="uq_ai_provider_attempts_inst_id"),
        sa.UniqueConstraint("reservation_id", "attempt_sequence", name="uq_ai_attempt_seq"),
        sa.CheckConstraint("attempt_sequence >= 1", name="ck_ai_provider_attempts_seq_pos"),
        sa.CheckConstraint(
            "status IN ('DISPATCHED', 'SUCCEEDED', 'FAILED_CONFIRMED', 'TIMEOUT_UNCERTAIN', 'MANUALLY_SETTLED')",
            name="ck_ai_provider_attempts_status",
        ),
        sa.CheckConstraint("estimated_tokens >= 0", name="ck_ai_att_est_tok_nonneg"),
        sa.CheckConstraint("estimated_cost_inr >= 0", name="ck_ai_att_est_cost_nonneg"),
        sa.CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_att_in_tok_nonneg"),
        sa.CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_att_out_tok_nonneg"),
        sa.CheckConstraint("actual_cost_inr IS NULL OR actual_cost_inr >= 0", name="ck_ai_att_act_cost_nonneg"),
        sa.CheckConstraint(
            "manual_settled_tokens IS NULL OR manual_settled_tokens >= 0",
            name="ck_ai_att_man_tok_nonneg",
        ),
        sa.CheckConstraint(
            "manual_settled_cost_inr IS NULL OR manual_settled_cost_inr >= 0",
            name="ck_ai_att_man_cost_nonneg",
        ),
        sa.CheckConstraint(
            "late_reported_input_tokens IS NULL OR late_reported_input_tokens >= 0",
            name="ck_ai_att_late_in_nonneg",
        ),
        sa.CheckConstraint(
            "late_reported_output_tokens IS NULL OR late_reported_output_tokens >= 0",
            name="ck_ai_att_late_out_nonneg",
        ),
        sa.CheckConstraint(
            "late_reported_cost_inr IS NULL OR late_reported_cost_inr >= 0",
            name="ck_ai_att_late_cost_nonneg",
        ),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_ai_att_latency_nonneg"),
    )
    op.create_index(
        "uq_ai_attempt_provider_req_id",
        "ai_provider_attempts",
        ["institution_id", "provider", "provider_request_id"],
        unique=True,
        postgresql_where=sa.text("provider_request_id IS NOT NULL"),
    )
    op.create_index(
        "ix_ai_attempts_inst_dispatched",
        "ai_provider_attempts",
        ["institution_id", "dispatched_at"],
        unique=False,
    )

    # -------------------------------------------------------------------------
    # 7. ai_financial_adjustments (Append-Only Audit Ledger)
    # -------------------------------------------------------------------------
    op.create_table(
        "ai_financial_adjustments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("adjusted_by_actor", sa.String(length=100), nullable=False),
        sa.Column("adjustment_type", sa.String(length=30), nullable=False),
        sa.Column("token_delta", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_inr_delta", sa.Numeric(precision=12, scale=4), server_default=sa.text("0.0000"), nullable=False),
        sa.Column("adjustment_reason", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["institution_id", "reservation_id"],
            ["ai_token_reservations.institution_id", "ai_token_reservations.id"],
            ondelete="RESTRICT",
            name="fk_adjustment_reservation_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id", "attempt_id"],
            ["ai_provider_attempts.institution_id", "ai_provider_attempts.id"],
            ondelete="RESTRICT",
            name="fk_adjustment_attempt_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "adjustment_type IN ('LATE_SETTLEMENT', 'MANUAL_SETTLE', 'VARIANCE_DEBIT', 'VARIANCE_CREDIT', 'REFUND')",
            name="ck_ai_financial_adjustments_type",
        ),
        sa.CheckConstraint("char_length(btrim(notes)) > 0", name="ck_ai_financial_adjustments_notes_nonempty"),
        sa.CheckConstraint(
            "char_length(btrim(adjustment_reason)) > 0",
            name="ck_ai_financial_adjustments_reason_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(btrim(adjusted_by_actor)) > 0",
            name="ck_ai_financial_adjustments_actor_nonempty",
        ),
    )
    op.create_index(
        "ix_ai_financial_adjustments_inst_created",
        "ai_financial_adjustments",
        ["institution_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_financial_adjustments_reservation",
        "ai_financial_adjustments",
        ["reservation_id"],
        unique=False,
        postgresql_where=sa.text("reservation_id IS NOT NULL"),
    )

    # -------------------------------------------------------------------------
    # 8. Database Immutability Triggers for Pricing Versions & Adjustments
    # -------------------------------------------------------------------------
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_finops_immutable_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Table "%" is strictly immutable/append-only; % operations are prohibited.',
                    TG_TABLE_NAME, TG_OP
                    USING ERRCODE = '42501';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
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

    # -------------------------------------------------------------------------
    # 9. Security Model: RLS Policies & Least-Privilege Grants
    # -------------------------------------------------------------------------
    # 9A. Global pricing schedule (readable globally; insert restricted to platform admin;
    # UPDATE ACL included strictly for child FK FOR KEY SHARE checks while RLS + trigger forbid UPDATE/DELETE)
    op.execute(sa.text("ALTER TABLE ai_pricing_versions ENABLE ROW LEVEL SECURITY;"))
    op.execute(sa.text("ALTER TABLE ai_pricing_versions FORCE ROW LEVEL SECURITY;"))
    op.execute(
        sa.text(
            """
            CREATE POLICY pricing_versions_read_all ON ai_pricing_versions
            AS PERMISSIVE
            FOR SELECT
            TO eduintel
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
            TO eduintel
            WITH CHECK (current_setting('app.is_platform_admin', true) = 'true');
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY pricing_versions_no_update ON ai_pricing_versions
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
            CREATE POLICY pricing_versions_no_delete ON ai_pricing_versions
            AS RESTRICTIVE
            FOR DELETE
            TO PUBLIC
            USING (false);
            """
        )
    )
    op.execute(sa.text("REVOKE ALL ON TABLE ai_pricing_versions FROM PUBLIC;"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel') THEN
                REVOKE ALL ON TABLE ai_pricing_versions FROM eduintel;
                GRANT SELECT, INSERT, UPDATE ON TABLE ai_pricing_versions TO eduintel;
              END IF;
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel_app') THEN
                REVOKE ALL ON TABLE ai_pricing_versions FROM eduintel_app;
                GRANT SELECT, INSERT, UPDATE ON TABLE ai_pricing_versions TO eduintel_app;
              END IF;
            END $$;
            """
        )
    )

    # 9B. Standard Tenant-Isolated Operational Tables (Command-split RLS)
    for tbl in OPERATIONAL_TENANT_TABLES:
        op.execute(sa.text(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;"))
        op.execute(sa.text(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;"))

        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_app_access_policy ON {tbl}
                AS PERMISSIVE
                FOR ALL
                TO eduintel
                USING (true)
                WITH CHECK (true);
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_read_policy ON {tbl}
                AS RESTRICTIVE
                FOR SELECT
                TO PUBLIC
                USING (
                    current_setting('app.is_platform_admin', true) = 'true'
                    OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                );
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_insert_policy ON {tbl}
                AS RESTRICTIVE
                FOR INSERT
                TO PUBLIC
                WITH CHECK (
                    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                );
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_update_policy ON {tbl}
                AS RESTRICTIVE
                FOR UPDATE
                TO PUBLIC
                USING (
                    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                )
                WITH CHECK (
                    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                );
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_delete_policy ON {tbl}
                AS RESTRICTIVE
                FOR DELETE
                TO PUBLIC
                USING (
                    institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
                );
                """
            )
        )

    # Least-privilege grants on tenant_ai_quotas vs ledger tables
    op.execute(sa.text("REVOKE ALL ON TABLE tenant_ai_quotas FROM PUBLIC;"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel') THEN
                REVOKE ALL ON TABLE tenant_ai_quotas FROM eduintel;
                GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE tenant_ai_quotas TO eduintel;
              END IF;
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel_app') THEN
                REVOKE ALL ON TABLE tenant_ai_quotas FROM eduintel_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE tenant_ai_quotas TO eduintel_app;
              END IF;
            END $$;
            """
        )
    )
    for tbl in LEDGER_READ_WRITE_TABLES:
        op.execute(sa.text(f"REVOKE ALL ON TABLE {tbl} FROM PUBLIC;"))
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel') THEN
                    REVOKE ALL ON TABLE {tbl} FROM eduintel;
                    GRANT SELECT, INSERT, UPDATE ON TABLE {tbl} TO eduintel;
                  END IF;
                  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel_app') THEN
                    REVOKE ALL ON TABLE {tbl} FROM eduintel_app;
                    GRANT SELECT, INSERT, UPDATE ON TABLE {tbl} TO eduintel_app;
                  END IF;
                END $$;
                """
            )
        )

    # 9C. Append-Only Tenant Table: ai_financial_adjustments
    op.execute(sa.text("ALTER TABLE ai_financial_adjustments ENABLE ROW LEVEL SECURITY;"))
    op.execute(sa.text("ALTER TABLE ai_financial_adjustments FORCE ROW LEVEL SECURITY;"))
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_app_access_select_policy ON ai_financial_adjustments
            AS PERMISSIVE
            FOR SELECT
            TO eduintel
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
            TO eduintel
            WITH CHECK (true);
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_read_policy ON ai_financial_adjustments
            AS RESTRICTIVE
            FOR SELECT
            TO PUBLIC
            USING (
                current_setting('app.is_platform_admin', true) = 'true'
                OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_insert_policy ON ai_financial_adjustments
            AS RESTRICTIVE
            FOR INSERT
            TO PUBLIC
            WITH CHECK (
                institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_update_policy ON ai_financial_adjustments
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
            CREATE POLICY tenant_isolation_delete_policy ON ai_financial_adjustments
            AS RESTRICTIVE
            FOR DELETE
            TO PUBLIC
            USING (false);
            """
        )
    )
    op.execute(sa.text("REVOKE ALL ON TABLE ai_financial_adjustments FROM PUBLIC;"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel') THEN
                REVOKE ALL ON TABLE ai_financial_adjustments FROM eduintel;
                GRANT SELECT, INSERT ON TABLE ai_financial_adjustments TO eduintel;
              END IF;
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel_app') THEN
                REVOKE ALL ON TABLE ai_financial_adjustments FROM eduintel_app;
                GRANT SELECT, INSERT ON TABLE ai_financial_adjustments TO eduintel_app;
              END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    # 1. Drop append-only triggers & function
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ai_financial_adjustments_append_only ON ai_financial_adjustments;"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ai_pricing_versions_immutable ON ai_pricing_versions;"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_finops_immutable_mutation();"))

    # 2. Drop policies & table: ai_financial_adjustments
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_delete_policy ON ai_financial_adjustments;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_update_policy ON ai_financial_adjustments;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_insert_policy ON ai_financial_adjustments;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_read_policy ON ai_financial_adjustments;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_app_access_insert_policy ON ai_financial_adjustments;"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_app_access_select_policy ON ai_financial_adjustments;"))
    op.drop_index("ix_ai_financial_adjustments_reservation", table_name="ai_financial_adjustments")
    op.drop_index("ix_ai_financial_adjustments_inst_created", table_name="ai_financial_adjustments")
    op.drop_table("ai_financial_adjustments")

    # 3. Drop policies & table: ai_provider_attempts
    for pol in (
        "tenant_isolation_delete_policy",
        "tenant_isolation_update_policy",
        "tenant_isolation_insert_policy",
        "tenant_isolation_read_policy",
        "tenant_app_access_policy",
    ):
        op.execute(sa.text(f"DROP POLICY IF EXISTS {pol} ON ai_provider_attempts;"))
    op.drop_index("ix_ai_attempts_inst_dispatched", table_name="ai_provider_attempts")
    op.drop_index("uq_ai_attempt_provider_req_id", table_name="ai_provider_attempts")
    op.drop_table("ai_provider_attempts")

    # 4. Drop policies & table: ai_token_reservations
    for pol in (
        "tenant_isolation_delete_policy",
        "tenant_isolation_update_policy",
        "tenant_isolation_insert_policy",
        "tenant_isolation_read_policy",
        "tenant_app_access_policy",
    ):
        op.execute(sa.text(f"DROP POLICY IF EXISTS {pol} ON ai_token_reservations;"))
    op.drop_index("ix_ai_reservations_logical_op", table_name="ai_token_reservations")
    op.drop_index("ix_ai_reservations_inst_created", table_name="ai_token_reservations")
    op.drop_index("ix_ai_reservations_recovery", table_name="ai_token_reservations")
    op.drop_index("uq_ai_reservations_idempotency", table_name="ai_token_reservations")
    op.drop_table("ai_token_reservations")

    # 5. Drop policies & table: tenant_daily_category_usage
    for pol in (
        "tenant_isolation_delete_policy",
        "tenant_isolation_update_policy",
        "tenant_isolation_insert_policy",
        "tenant_isolation_read_policy",
        "tenant_app_access_policy",
    ):
        op.execute(sa.text(f"DROP POLICY IF EXISTS {pol} ON tenant_daily_category_usage;"))
    op.drop_table("tenant_daily_category_usage")

    # 6. Drop policies & table: tenant_daily_ai_usage
    for pol in (
        "tenant_isolation_delete_policy",
        "tenant_isolation_update_policy",
        "tenant_isolation_insert_policy",
        "tenant_isolation_read_policy",
        "tenant_app_access_policy",
    ):
        op.execute(sa.text(f"DROP POLICY IF EXISTS {pol} ON tenant_daily_ai_usage;"))
    op.drop_index("ix_tenant_daily_ai_usage_date_inst", table_name="tenant_daily_ai_usage")
    op.drop_table("tenant_daily_ai_usage")

    # 7. Drop policies & table: tenant_ai_quotas
    for pol in (
        "tenant_isolation_delete_policy",
        "tenant_isolation_update_policy",
        "tenant_isolation_insert_policy",
        "tenant_isolation_read_policy",
        "tenant_app_access_policy",
    ):
        op.execute(sa.text(f"DROP POLICY IF EXISTS {pol} ON tenant_ai_quotas;"))
    op.drop_table("tenant_ai_quotas")

    # 8. Drop policies & table: ai_pricing_versions
    op.execute(sa.text("DROP POLICY IF EXISTS pricing_versions_no_delete ON ai_pricing_versions;"))
    op.execute(sa.text("DROP POLICY IF EXISTS pricing_versions_no_update ON ai_pricing_versions;"))
    op.execute(sa.text("DROP POLICY IF EXISTS pricing_versions_admin_insert ON ai_pricing_versions;"))
    op.execute(sa.text("DROP POLICY IF EXISTS pricing_versions_read_all ON ai_pricing_versions;"))
    op.drop_table("ai_pricing_versions")
