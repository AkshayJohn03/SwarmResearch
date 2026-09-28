"""API-key authentication for the SwarmResearch serving surface.

Keys are supplied via the ``SWARM_API_KEYS`` environment variable as a
comma-separated list of RAW keys. Only SHA-256 hashes are ever stored or
compared (hash-at-ingest); raw keys are never logged and never echoed back.
When the variable is unset/empty the authenticator is DISABLED (open
service) and a startup warning is emitted, so existing deployments keep
working unchanged. ``/health`` and ``/metrics`` are always exempt.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

logger = logging.getLogger("swarm.serve.auth")

GENERIC_401 = {"detail": "Unauthorized: missing or invalid API key."}
# Operational endpoints are never key-gated (even before they exist).
EXEMPT_PATHS = {"/health", "/metrics"}


def hash_key(raw: str) -> str:
    """SHA-256 of one raw key, hex-encoded. The only form kept at rest."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class APIKeyAuth:
    """Hold-at-rest key hashes; verify presented keys in constant time."""

    def __init__(self, raw_keys: str | None) -> None:
        self.enabled = bool(raw_keys and raw_keys.strip())
        if not self.enabled:
            self._hashes: frozenset[str] = frozenset()
            logger.warning(
                "SWARM_API_KEYS is not set — API-key auth is DISABLED. "
                "Set it (comma-separated keys) before exposing the service."
            )
            return
        keys = [k.strip() for k in raw_keys.split(",")]
        self._hashes = frozenset(hash_key(k) for k in keys if k)
        logger.warning(
            "API-key auth ENABLED with %d key(s); only SHA-256 hashes are stored.", len(self._hashes)
        )

    def verify(self, presented: str | None) -> bool:
        """True iff the presented key matches one enrolled key (constant-time)."""
        if presented is None or not self.enabled:
            return not self.enabled
        return any(hmac.compare_digest(hash_key(presented), h) for h in self._hashes)


class APIKeyMiddleware:
    """Pure-ASGI middleware requiring ``X-API-Key`` on every route but /health and /metrics."""

    def __init__(self, app, auth: APIKeyAuth) -> None:
        self.app = app
        self.auth = auth

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.auth.enabled:
            return await self.app(scope, receive, send)
        if scope.get("path", "") in EXEMPT_PATHS:
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if not self.auth.verify(headers.get("x-api-key")):
            from fastapi.responses import JSONResponse

            await JSONResponse(GENERIC_401, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)


__all__ = ["APIKeyAuth", "APIKeyMiddleware", "EXEMPT_PATHS", "GENERIC_401", "hash_key"]
