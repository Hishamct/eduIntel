"""
Pricing version resolution and centralized fixed-point Decimal cost calculation.

Zero hardcoded model rates or USD/INR assumptions are used: every calculation resolves
an explicit AIPricingVersion row and validates rates_json strictly using Decimal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.quota.errors import (
    InvalidPricingSchemaError,
    PricingModelRateNotFoundError,
    PricingVersionNotFoundError,
)
from app.observability.quota.types import (
    INR_QUANTIZE,
    MAX_COST_INR_12_4,
    CostBreakdown,
    PricingRateSpec,
    validate_non_empty_text,
    validate_token_count,
)
from app.observability.quota_models import AIPricingActivation, AIPricingVersion

TOKENS_PER_RATE_UNIT = Decimal("1000")


def _parse_decimal_value(raw: Any, *, field_name: str, version_id: str | None) -> Decimal:
    """Parse an exact finite non-negative Decimal, rejecting floats and booleans."""
    if isinstance(raw, (bool, float)) or raw is None:
        raise InvalidPricingSchemaError(
            f"Pricing field {field_name!r} must be an exact string/int/Decimal, got {type(raw).__name__}",
            version_id=version_id,
        )
    if isinstance(raw, int):
        dec = Decimal(raw)
    elif isinstance(raw, Decimal):
        dec = raw
    elif isinstance(raw, str):
        trimmed = raw.strip()
        if not trimmed:
            raise InvalidPricingSchemaError(
                f"Pricing field {field_name!r} must not be empty",
                version_id=version_id,
            )
        try:
            dec = Decimal(trimmed)
        except InvalidOperation as exc:
            raise InvalidPricingSchemaError(
                f"Pricing field {field_name!r} is not a valid decimal number: {raw!r}",
                version_id=version_id,
            ) from exc
    else:
        raise InvalidPricingSchemaError(
            f"Pricing field {field_name!r} has unsupported type {type(raw).__name__}",
            version_id=version_id,
        )

    if not dec.is_finite() or dec < Decimal("0"):
        raise InvalidPricingSchemaError(
            f"Pricing field {field_name!r} must be finite and >= 0",
            version_id=version_id,
        )
    return dec


async def resolve_active_pricing_version(
    db: AsyncSession,
    *,
    as_of: datetime | None = None,
) -> AIPricingVersion:
    """
    Resolve the currently active AIPricingVersion via the authoritative activation ledger.

    Orders ai_pricing_activations by activation_seq DESC LIMIT 1 and verifies the linked
    ai_pricing_versions row is active and effective as of `as_of`.
    """
    effective_time = as_of if as_of is not None else datetime.now(UTC)
    if effective_time.tzinfo is None:
        raise ValueError("as_of timestamp must be timezone-aware")

    stmt = (
        select(AIPricingVersion)
        .join(
            AIPricingActivation,
            AIPricingActivation.pricing_version == AIPricingVersion.version_id,
        )
        .where(AIPricingActivation.expected_version_active.is_(True))
        .order_by(desc(AIPricingActivation.activation_seq))
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None or not row.is_active:
        raise PricingVersionNotFoundError("No active AI pricing activation record exists")
    if row.effective_from > effective_time:
        raise PricingVersionNotFoundError(
            f"Active pricing version {row.version_id!r} is not yet effective until {row.effective_from.isoformat()}",
            version_id=row.version_id,
        )
    return row


async def resolve_pricing_version_by_id(
    db: AsyncSession,
    version_id: str,
) -> AIPricingVersion:
    """Resolve an immutable AIPricingVersion row by explicit version_id."""
    normalized_id = validate_non_empty_text(version_id, field_name="version_id", max_length=50)
    stmt = select(AIPricingVersion).where(AIPricingVersion.version_id == normalized_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise PricingVersionNotFoundError(
            f"Pricing version {normalized_id!r} does not exist",
            version_id=normalized_id,
        )
    return row


def extract_model_rate_spec(
    pricing_version: AIPricingVersion,
    *,
    provider: str,
    model: str,
) -> PricingRateSpec:
    """
    Validate and extract per-1k token INR rates for `(provider, model)` from rates_json.

    Supported per-model shapes:
      - {"input_inr_per_1k": ..., "output_inr_per_1k": ...} (direct INR)
      - {"input_usd_per_1k": ..., "output_usd_per_1k": ...} (multiplied by usd_to_inr_rate)
      - {"input_1k": ..., "output_1k": ...} or {"input_per_1k": ..., "output_per_1k": ...}
        (interpreted in pricing_version.currency: INR directly, USD * usd_to_inr_rate)
    """
    norm_provider = validate_non_empty_text(provider, field_name="provider", max_length=50)
    norm_model = validate_non_empty_text(model, field_name="model", max_length=100)
    ver_id = pricing_version.version_id

    rates = pricing_version.rates_json
    if not isinstance(rates, dict):
        raise InvalidPricingSchemaError("rates_json must be a JSON object", version_id=ver_id)

    provider_block = rates.get(norm_provider)
    if provider_block is None:
        raise PricingModelRateNotFoundError(
            f"Provider {norm_provider!r} not defined in pricing version {ver_id!r}",
            version_id=ver_id,
            provider=norm_provider,
            model=norm_model,
        )
    if not isinstance(provider_block, dict):
        raise InvalidPricingSchemaError(
            f"rates_json[{norm_provider!r}] must be a JSON object",
            version_id=ver_id,
        )

    model_block = provider_block.get(norm_model)
    if model_block is None:
        raise PricingModelRateNotFoundError(
            f"Model {norm_model!r} for provider {norm_provider!r} not defined in pricing version {ver_id!r}",
            version_id=ver_id,
            provider=norm_provider,
            model=norm_model,
        )
    if not isinstance(model_block, dict):
        raise InvalidPricingSchemaError(
            f"rates_json[{norm_provider!r}][{norm_model!r}] must be a JSON object",
            version_id=ver_id,
        )

    usd_to_inr = _parse_decimal_value(
        pricing_version.usd_to_inr_rate,
        field_name="usd_to_inr_rate",
        version_id=ver_id,
    )
    if usd_to_inr <= Decimal("0"):
        raise InvalidPricingSchemaError("usd_to_inr_rate must be > 0", version_id=ver_id)

    currency = str(pricing_version.currency).strip().upper()
    in_inr, out_inr = _resolve_inr_rates_from_block(
        model_block=model_block,
        currency=currency,
        usd_to_inr=usd_to_inr,
        version_id=ver_id,
    )

    return PricingRateSpec(
        provider=norm_provider,
        model=norm_model,
        input_inr_per_1k=in_inr,
        output_inr_per_1k=out_inr,
        source_currency=currency,
        usd_to_inr_rate=usd_to_inr,
    )


def _resolve_inr_rates_from_block(
    *,
    model_block: dict[str, Any],
    currency: str,
    usd_to_inr: Decimal,
    version_id: str,
) -> tuple[Decimal, Decimal]:
    """Normalize supported per-model rate schemas into INR per 1k tokens."""
    if "input_inr_per_1k" in model_block or "output_inr_per_1k" in model_block:
        in_raw = _parse_decimal_value(
            model_block.get("input_inr_per_1k"),
            field_name="input_inr_per_1k",
            version_id=version_id,
        )
        out_raw = _parse_decimal_value(
            model_block.get("output_inr_per_1k"),
            field_name="output_inr_per_1k",
            version_id=version_id,
        )
        return in_raw, out_raw

    if "input_usd_per_1k" in model_block or "output_usd_per_1k" in model_block:
        in_usd = _parse_decimal_value(
            model_block.get("input_usd_per_1k"),
            field_name="input_usd_per_1k",
            version_id=version_id,
        )
        out_usd = _parse_decimal_value(
            model_block.get("output_usd_per_1k"),
            field_name="output_usd_per_1k",
            version_id=version_id,
        )
        return in_usd * usd_to_inr, out_usd * usd_to_inr

    in_key = "input_1k" if "input_1k" in model_block else "input_per_1k"
    out_key = "output_1k" if "output_1k" in model_block else "output_per_1k"
    if in_key not in model_block or out_key not in model_block:
        raise InvalidPricingSchemaError(
            "Model rate definition must include input_1k/output_1k (or input_per_1k/output_per_1k, "
            "input_inr_per_1k/output_inr_per_1k, or input_usd_per_1k/output_usd_per_1k)",
            version_id=version_id,
        )

    in_val = _parse_decimal_value(model_block[in_key], field_name=in_key, version_id=version_id)
    out_val = _parse_decimal_value(model_block[out_key], field_name=out_key, version_id=version_id)
    if currency == "INR":
        return in_val, out_val
    if currency == "USD":
        return in_val * usd_to_inr, out_val * usd_to_inr

    raise InvalidPricingSchemaError(
        f"Unsupported pricing currency {currency!r} for unit-agnostic rates",
        version_id=version_id,
    )


def calculate_cost_breakdown(
    pricing_version: AIPricingVersion,
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> CostBreakdown:
    """
    Compute fixed-point INR cost breakdown rounded with ROUND_HALF_UP to 4 decimals.
    """
    validate_token_count(input_tokens, field_name="input_tokens")
    validate_token_count(output_tokens, field_name="output_tokens")

    spec = extract_model_rate_spec(pricing_version, provider=provider, model=model)
    raw_in = (Decimal(input_tokens) / TOKENS_PER_RATE_UNIT) * spec.input_inr_per_1k
    raw_out = (Decimal(output_tokens) / TOKENS_PER_RATE_UNIT) * spec.output_inr_per_1k
    raw_total = raw_in + raw_out

    quant_in = raw_in.quantize(INR_QUANTIZE, rounding=ROUND_HALF_UP)
    quant_out = raw_out.quantize(INR_QUANTIZE, rounding=ROUND_HALF_UP)
    quant_total = raw_total.quantize(INR_QUANTIZE, rounding=ROUND_HALF_UP)

    if quant_total > MAX_COST_INR_12_4:
        raise InvalidPricingSchemaError(
            f"Computed total cost INR {quant_total} exceeds NUMERIC(12, 4) column limit",
            version_id=pricing_version.version_id,
        )

    return CostBreakdown(
        pricing_version=pricing_version.version_id,
        provider=spec.provider,
        model=spec.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_cost_inr=quant_in,
        output_cost_inr=quant_out,
        total_cost_inr=quant_total,
    )


def quantize_inr(amount: Decimal) -> Decimal:
    """Validate and quantize an explicit Decimal monetary amount to NUMERIC(12, 4)."""
    if isinstance(amount, (bool, float)) or not isinstance(amount, Decimal):
        raise ValueError("Monetary amount must be a Decimal instance")
    if not amount.is_finite() or amount < Decimal("0"):
        raise ValueError("Monetary amount must be finite and >= 0")
    quantized = amount.quantize(INR_QUANTIZE, rounding=ROUND_HALF_UP)
    if quantized > MAX_COST_INR_12_4:
        raise ValueError(f"Monetary amount {quantized} exceeds NUMERIC(12, 4) limit")
    return quantized
