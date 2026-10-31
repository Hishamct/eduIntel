"""
backend/app/core/rate_limiter.py

In-memory sliding-window rate limiter for sensitive authentication endpoints.
Provides process-local rate limiting with secure proxy trust and IP validation.
"""

import ipaddress
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

from app.core.config import settings

MAX_TRACKED_BUCKETS = 10_000


class InMemoryRateLimiter:
    """
    Sliding-window in-memory rate limiter keyed by validated client IP.

    Security controls:
    - Never blindly trusts X-Forwarded-For headers.
    - Forwarded client IP is only extracted when the connecting peer is an explicitly
      configured trusted proxy.
    - All extracted IP strings are strictly validated using Python's ipaddress module.
    - Malformed, missing, or spoofed forwarded values fall back safely to the peer IP.
    - Bounded memory to prevent arbitrary header payloads from exhausting memory.
    """

    def __init__(
        self,
        requests_limit: int = 5,
        window_seconds: int = 60,
        trusted_proxies: set[str] | None = None,
    ):
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.trusted_proxies = (
            trusted_proxies
            if trusted_proxies is not None
            else set(getattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1"]))
        )
        self.history: dict[str, list[float]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        """
        Safely resolve client IP with trusted proxy verification and ipaddress validation.
        """
        peer_raw = (
            request.client.host if request.client and request.client.host else "127.0.0.1"
        )

        # 1. Validate peer IP using ipaddress module
        try:
            normalized_peer = str(ipaddress.ip_address(peer_raw))
        except ValueError:
            return "127.0.0.1"

        # 2. If connecting peer is NOT a trusted proxy, DO NOT trust X-Forwarded-For
        if normalized_peer not in self.trusted_proxies:
            return normalized_peer

        # 3. Peer is a trusted proxy: inspect X-Forwarded-For
        forwarded = request.headers.get("x-forwarded-for")
        if not forwarded:
            return normalized_peer

        # 4. Extract and validate client IP from X-Forwarded-For (take the first client IP)
        raw_client = forwarded.split(",")[0].strip()
        try:
            validated_client = str(ipaddress.ip_address(raw_client))
            return validated_client
        except ValueError:
            # Malformed forwarded IP value: fall back safely to peer IP
            return normalized_peer

    def _prune_expired_buckets(self, now: float) -> None:
        """Evict empty or expired IP buckets to prevent unbounded memory growth."""
        expired_keys = [
            ip
            for ip, ts_list in self.history.items()
            if not ts_list or ts_list[-1] <= now - self.window_seconds
        ]
        for k in expired_keys:
            del self.history[k]

    async def __call__(self, request: Request) -> None:
        client_ip = self._get_client_ip(request)
        now = time.monotonic()
        timestamps = self.history[client_ip]

        # Prune timestamps older than sliding window for this IP
        while timestamps and timestamps[0] <= now - self.window_seconds:
            timestamps.pop(0)

        # Periodic cleanup if memory exceeds safety bounds
        if len(self.history) > MAX_TRACKED_BUCKETS:
            self._prune_expired_buckets(now)

        if len(timestamps) >= self.requests_limit:
            retry_after = int(self.window_seconds - (now - timestamps[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many password reset requests. Maximum {self.requests_limit} per minute.",
                headers={"Retry-After": str(max(1, retry_after))},
            )

        timestamps.append(now)

    def reset(self) -> None:
        """Reset recorded history (used for test isolation)."""
        self.history.clear()


# Default singleton instance for password reset requests (5 per minute)
password_reset_limiter = InMemoryRateLimiter(
    requests_limit=getattr(settings, "RATE_LIMIT_PASSWORD_RESET", 5),
    window_seconds=getattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60),
    trusted_proxies=set(getattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1"])),
)
