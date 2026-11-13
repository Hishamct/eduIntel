"""
Tenant-timezone date pinning and month boundary calculations for Stage 7.2 quotas.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.observability.quota.errors import QuotaConfigurationError


def validate_timezone(timezone_name: str) -> ZoneInfo:
    """Resolve an IANA timezone string or raise QuotaConfigurationError."""
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise QuotaConfigurationError(
            "Tenant quota_timezone must be a non-empty IANA timezone identifier",
            code="INVALID_QUOTA_TIMEZONE",
        )
    try:
        return ZoneInfo(timezone_name.strip())
    except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
        raise QuotaConfigurationError(
            f"Unsupported tenant quota_timezone: {timezone_name!r}",
            code="INVALID_QUOTA_TIMEZONE",
        ) from exc


def resolve_tenant_usage_date(
    *,
    quota_timezone: str,
    as_of: datetime | None = None,
) -> date:
    """
    Pin an instant into the tenant's configured IANA timezone calendar date.

    All subsequent reservation lifecycle updates MUST reuse this persisted usage_date
    instead of recomputing a date from current time.
    """
    tz = validate_timezone(quota_timezone)
    moment = as_of if as_of is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("as_of timestamp must be timezone-aware (UTC recommended)")
    return moment.astimezone(tz).date()


def month_date_bounds(usage_date: date) -> tuple[date, date]:
    """Return half-open [month_start, next_month_start) calendar bounds for usage_date."""
    month_start = date(usage_date.year, usage_date.month, 1)
    if usage_date.month == 12:
        next_month_start = date(usage_date.year + 1, 1, 1)
    else:
        next_month_start = date(usage_date.year, usage_date.month + 1, 1)
    return month_start, next_month_start

