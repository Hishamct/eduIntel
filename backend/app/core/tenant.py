"""
backend/app/core/tenant.py

Trusted multi-tenant context resolution.
Ensures that tenant identity is derived strictly from server-side verified state,
preventing client-controlled parameter tampering or tenant spoofing.
"""

from app.core.config import settings
from app.users.models import User


def get_trusted_tenant_id(user: User | None = None) -> str | None:
    """
    Resolves tenant identity exclusively from trusted server-side context.
    Never accepts client-supplied tenant identifiers.

    1. If user has an explicit institution_id attribute (e.g. Phase 2C/4 DB column), use it.
    2. If ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE is explicitly enabled in settings,
       use settings.DEFAULT_INSTITUTION_ID.
    3. Otherwise, returns None (triggering fail-closed behavior for tenant-scoped resources).
    """
    if user is not None:
        user_tenant = getattr(user, "institution_id", None)
        if user_tenant:
            return str(user_tenant)

    if settings.ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE and settings.DEFAULT_INSTITUTION_ID:
        return str(settings.DEFAULT_INSTITUTION_ID)

    return None

