from __future__ import annotations

import json
import logging
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach a validated request ID and emit metadata-only request telemetry."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = (
            incoming
            if len(incoming) <= 64 and re.fullmatch(r"[A-Za-z0-9._-]+", incoming)
            else uuid4().hex
        )
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status_code = 500
        logger = logging.getLogger("app.request")
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "http_request_completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            _request_id.reset(token)
