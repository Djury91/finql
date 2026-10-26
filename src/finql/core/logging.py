"""Structured logging: structlog for our code, the same pipeline for stdlib loggers
(uvicorn, SQLAlchemy).

Every log line inside a request carries its request_id (bound by RequestContextMiddleware).
"""

import logging
import time
import uuid
from collections.abc import MutableMapping
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
_ALLOWED_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")

logger = structlog.get_logger("finql.request")


def configure_logging(level: str = "INFO", *, json_logs: bool) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    renderer: Any = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    final: list[Any] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if json_logs:
        final.append(structlog.processors.dict_tracebacks)
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(foreign_pre_chain=shared, processors=[*final, renderer])
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Our middleware logs every request with its id and duration; uvicorn's access log would
    # only repeat it.
    logging.getLogger("uvicorn.access").disabled = True


def current_request_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("request_id")
    return value if isinstance(value, str) else None


def _incoming_request_id(scope: Scope) -> str | None:
    """Accept a caller's id (e.g. from a gateway) only if it is short and harmless to log."""
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER.encode():
            candidate: str = value.decode("latin-1")
            if 0 < len(candidate) <= 64 and set(candidate) <= _ALLOWED_ID_CHARS:
                return candidate
    return None


class RequestContextMiddleware:
    """Request id (X-Request-ID in and out), bound to every log line, plus one access log entry.

    Pure ASGI rather than BaseHTTPMiddleware, so streaming responses (SSE, phase 6) pass through
    untouched.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        # Cleared at the start, not the end: the 500 handler runs after this middleware unwinds
        # and still needs the id.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        state: MutableMapping[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        status_code = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                # Error responses already carry it (see errors.error_response).
                if all(name.lower() != REQUEST_ID_HEADER.encode() for name, _ in headers):
                    headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            logger.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
