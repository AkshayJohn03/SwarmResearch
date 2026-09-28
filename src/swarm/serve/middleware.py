"""Cross-cutting HTTP middleware for the serving surface (pure ASGI).

- CorrelationIdMiddleware : inbound ``X-Correlation-ID`` or generated uuid4,
  echoed on every response; handlers read it from ``scope["correlation_id"]``.
- BodySizeLimitMiddleware : rejects request bodies above ``max_bytes`` (413)
  on the configured paths; the buffered body is re-injected downstream so
  exactly-one-consumer ASGI receive semantics are preserved.
"""

from __future__ import annotations

import uuid

CORRELATION_HEADER = "X-Correlation-ID"
MAX_REQUEST_BODY_BYTES = 8 * 1024  # 8 KiB cap on research query bodies -> 413


class CorrelationIdMiddleware:
    """Attach a correlation id to every request/response pair."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        correlation_id = headers.get("x-correlation-id") or uuid.uuid4().hex
        # Bound hostile/inordinately long client ids.
        correlation_id = correlation_id[:128]
        scope["correlation_id"] = correlation_id
        await self.app(
            scope, receive, _header_injecting_send(send, CORRELATION_HEADER, correlation_id)
        )


class BodySizeLimitMiddleware:
    """Reject bodies larger than ``max_bytes`` on protected paths with 413."""

    def __init__(self, app, max_bytes: int, protected_paths: set[str]) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.protected_paths = protected_paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "") not in self.protected_paths:
            return await self.app(scope, receive, send)
        if scope.get("method", "").upper() not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)

        body = bytearray()
        too_large = False
        while True:
            message = await receive()
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
                if len(body) > self.max_bytes:
                    too_large = True
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                return

        if too_large:
            from fastapi.responses import JSONResponse

            await JSONResponse(
                {"detail": f"Request body exceeds {self.max_bytes} bytes."}, status_code=413
            )(scope, receive, send)
            return

        replayed = {"done": False}

        async def replay_receive():
            if not replayed["done"]:
                replayed["done"] = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)


def _header_injecting_send(send, name: str, value: str):
    target = name.lower().encode("latin-1")

    async def wrapped(message) -> None:
        if message["type"] == "http.response.start":
            raw_headers = [(k, v) for k, v in message.get("headers", []) if k != target]
            raw_headers.append((target, value.encode("latin-1")))
            message = {**message, "headers": raw_headers}
        await send(message)

    return wrapped


__all__ = [
    "CORRELATION_HEADER",
    "MAX_REQUEST_BODY_BYTES",
    "BodySizeLimitMiddleware",
    "CorrelationIdMiddleware",
]
