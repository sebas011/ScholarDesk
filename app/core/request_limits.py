from __future__ import annotations

from collections import deque

from starlette.responses import HTMLResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'none'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'none'"
    ),
}


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP request bodies before FastAPI parses form data."""

    def __init__(self, app: ASGIApp, max_body_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared_length = self._declared_content_length(scope)
        if declared_length is not None and declared_length > self.max_body_bytes:
            await self._send_too_large(scope, receive, send)
            return

        buffered_messages: deque[Message] = deque()
        body_size = 0

        while True:
            message = await receive()

            if message["type"] == "http.disconnect":
                return

            buffered_messages.append(message)

            if message["type"] == "http.request":
                body_size += len(message.get("body", b""))
                if body_size > self.max_body_bytes:
                    await self._send_too_large(scope, receive, send)
                    return

                if not message.get("more_body", False):
                    break

        async def replay_receive() -> Message:
            if buffered_messages:
                return buffered_messages.popleft()
            return await receive()

        await self.app(scope, replay_receive, send)

    def _declared_content_length(self, scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                return int(value)
            except ValueError:
                return self.max_body_bytes + 1
        return None

    async def _send_too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_htmx = any(
            name.lower() == b"hx-request" and value.lower() == b"true"
            for name, value in scope.get("headers", [])
        )
        content = (
            '<div class="alert alert-error">'
            "Request is too large. Please reduce it and try again."
            "</div>"
            if is_htmx
            else (
                "<!DOCTYPE html><html lang=\"en\"><head>"
                "<meta charset=\"UTF-8\"><title>Request too large</title>"
                "</head><body><p>Request is too large. Please reduce it and try again.</p>"
                "</body></html>"
            )
        )
        response = HTMLResponse(
            content=content,
            status_code=413,
            headers=_SECURITY_HEADERS,
        )
        await response(scope, receive, send)
