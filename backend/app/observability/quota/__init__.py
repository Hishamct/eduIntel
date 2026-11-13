"""
Stage 7.2 Pricing, FinOps Ledger & Atomic Tenant Quota Engine package.
"""

from app.observability.quota.adapter import (
    get_current_metered_context,
    get_main_event_loop,
    get_metered_ai_service,
    metered_execution_context,
    register_main_event_loop,
    reset_current_metered_context,
    run_metered_coro_sync,
    set_current_metered_context,
    set_metered_ai_service,
)
from app.observability.quota.context import MeteredRequestContext
from app.observability.quota.engine import TenantQuotaEngine
from app.observability.quota.errors import (
    AttemptNotFoundError,
    DatabaseContentionError,
    IdempotencyConflictError,
    InvalidPricingSchemaError,
    InvalidStateTransitionError,
    MissingUsagePolicyPendingError,
    PricingModelRateNotFoundError,
    PricingVersionNotFoundError,
    QuotaConfigurationError,
    QuotaEngineError,
    QuotaExceededError,
    ReservationExpiredError,
    ReservationNotFoundError,
    TenantQuotaNotConfiguredError,
    TenantQuotaSuspendedError,
    UncertainCommitRecoveryError,
)
from app.observability.quota.normalizer import (
    NormalizedUsage,
    ProviderUsageNormalizer,
)
from app.observability.quota.observability_adapter import ObservabilityAdapter
from app.observability.quota.policy import (
    FailClosedMissingUsagePolicyResolver,
    MissingUsageContext,
    MissingUsagePolicyResolver,
    MissingUsageResolution,
)
from app.observability.quota.pricing import (
    calculate_cost_breakdown,
    extract_model_rate_spec,
    quantize_inr,
    resolve_active_pricing_version,
    resolve_pricing_version_by_id,
)
from app.observability.quota.provisioning import (
    InstitutionNotFoundError,
    QuotaPlanInactiveError,
    QuotaPlanNotFoundError,
    QuotaProvisioningService,
)
from app.observability.quota.reporting import FinOpsReportingService
from app.observability.quota.retry import (
    DEFAULT_RETRY_POLICY,
    TRANSIENT_SQLSTATES,
    RetryPolicy,
    bind_tenant_rls_context,
    execute_with_retry,
    extract_sqlstate,
    is_transient_db_error,
)
from app.observability.quota.service import (
    MeteredAIResult,
    MeteredAIService,
    MeteredEmbeddingResult,
    MeteredToolResult,
)
from app.observability.quota.sweeper import (
    QuotaReconciliationSweeper,
    SweepResult,
)
from app.observability.quota.timezone import (
    month_date_bounds,
    resolve_tenant_usage_date,
    validate_timezone,
)
from app.observability.quota.types import (
    AdjustmentSnapshot,
    AdmissionResult,
    AttemptDispatchRequest,
    AttemptSnapshot,
    CostBreakdown,
    PricingRateSpec,
    ReconciliationResult,
    ReservationCreateRequest,
    ReservationSnapshot,
)
from app.observability.quota_models import (
    AIPricingActivation,
    AIPricingVersion,
    AIQuotaPlan,
    TenantAIQuota,
    TenantQuotaProvisioningLog,
)

__all__ = [
    "AIPricingActivation",
    "AIPricingVersion",
    "AIQuotaPlan",
    "AdmissionResult",
    "AdjustmentSnapshot",
    "AttemptDispatchRequest",
    "AttemptNotFoundError",
    "AttemptSnapshot",
    "CostBreakdown",
    "DEFAULT_RETRY_POLICY",
    "DatabaseContentionError",
    "FailClosedMissingUsagePolicyResolver",
    "FinOpsReportingService",
    "IdempotencyConflictError",
    "InstitutionNotFoundError",
    "InvalidPricingSchemaError",
    "InvalidStateTransitionError",
    "MeteredAIResult",
    "MeteredAIService",
    "MeteredEmbeddingResult",
    "MeteredRequestContext",
    "MeteredToolResult",
    "MissingUsageContext",
    "MissingUsagePolicyPendingError",
    "MissingUsagePolicyResolver",
    "MissingUsageResolution",
    "NormalizedUsage",
    "ObservabilityAdapter",
    "PricingModelRateNotFoundError",
    "PricingRateSpec",
    "PricingVersionNotFoundError",
    "ProviderUsageNormalizer",
    "QuotaConfigurationError",
    "QuotaEngineError",
    "QuotaExceededError",
    "QuotaPlanInactiveError",
    "QuotaPlanNotFoundError",
    "QuotaProvisioningService",
    "QuotaReconciliationSweeper",
    "ReconciliationResult",
    "ReservationCreateRequest",
    "ReservationExpiredError",
    "ReservationNotFoundError",
    "ReservationSnapshot",
    "RetryPolicy",
    "SweepResult",
    "TRANSIENT_SQLSTATES",
    "TenantAIQuota",
    "TenantQuotaEngine",
    "TenantQuotaNotConfiguredError",
    "TenantQuotaProvisioningLog",
    "TenantQuotaSuspendedError",
    "UncertainCommitRecoveryError",
    "bind_tenant_rls_context",
    "calculate_cost_breakdown",
    "execute_with_retry",
    "extract_model_rate_spec",
    "extract_sqlstate",
    "get_current_metered_context",
    "get_main_event_loop",
    "get_metered_ai_service",
    "is_transient_db_error",
    "metered_execution_context",
    "month_date_bounds",
    "quantize_inr",
    "register_main_event_loop",
    "reset_current_metered_context",
    "resolve_active_pricing_version",
    "resolve_pricing_version_by_id",
    "resolve_tenant_usage_date",
    "run_metered_coro_sync",
    "set_current_metered_context",
    "set_metered_ai_service",
    "validate_timezone",
]
