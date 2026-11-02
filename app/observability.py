from __future__ import annotations

import json
import logging
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str:
    return _request_id.get()


class JsonLogFormatter(logging.Formatter):
    """Emit a small allow-listed JSON record; never serialize arbitrary extras."""

    SAFE_FIELDS = (
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "provider",
        "model",
        "fallback_used",
        "failure_count",
        "error_code",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.SAFE_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        handler = logging.StreamHandler()
        root.addHandler(handler)
    for handler in root.handlers:
        handler.setFormatter(JsonLogFormatter())


class RequestObservabilityMiddleware:
    """Pure ASGI middleware that keeps request context for streaming responses."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = next(
            (
                value.decode("latin-1")
                for key, value in scope.get("headers", [])
                if key.lower() == b"x-request-id"
            ),
            "",
        )
        request_id = (
            incoming
            if len(incoming) <= 64 and re.fullmatch(r"[A-Za-z0-9._-]+", incoming)
            else uuid4().hex
        )
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status_code = 500
        completed = False
        logger = logging.getLogger("app.request")

        def log_request() -> None:
            logger.info(
                "http_request_completed",
                extra={
                    "request_id": request_id,
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )

        async def send_with_request_id(message) -> None:
            nonlocal status_code, completed
            outgoing = message
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                if not any(key.lower() == b"x-request-id" for key, _ in headers):
                    headers.append((b"x-request-id", request_id.encode("ascii")))
                outgoing = {**message, "headers": headers}
            await send(outgoing)
            if (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
                and not completed
            ):
                completed = True
                log_request()

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            if not completed:
                log_request()
            _request_id.reset(token)
