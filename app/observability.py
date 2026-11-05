from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_METRIC_LOCK = threading.Lock()
_REQUEST_COUNTS: dict[tuple[str, int], int] = defaultdict(int)
_REQUEST_DURATION_BUCKETS: dict[tuple[str, int, float], int] = defaultdict(int)
_REQUEST_DURATION_SUM: dict[tuple[str, int], float] = defaultdict(float)
_DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf"))


def current_request_id() -> str:
    return _request_id.get()


def record_request_metric(method: str, status_code: int, duration_seconds: float) -> None:
    """Record low-cardinality request metrics; never label by path, user or tenant."""
    normalized_method = method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER"
    normalized_status = status_code if 100 <= status_code <= 599 else 500
    duration = max(0.0, duration_seconds)
    key = (normalized_method, normalized_status)
    with _METRIC_LOCK:
        _REQUEST_COUNTS[key] += 1
        _REQUEST_DURATION_SUM[key] += duration
        for bucket in _DURATION_BUCKETS:
            if duration <= bucket:
                _REQUEST_DURATION_BUCKETS[(normalized_method, normalized_status, bucket)] += 1


def render_prometheus_metrics() -> str:
    """Render Prometheus text exposition with a bounded label cardinality."""
    with _METRIC_LOCK:
        counts = dict(_REQUEST_COUNTS)
        sums = dict(_REQUEST_DURATION_SUM)
        buckets = dict(_REQUEST_DURATION_BUCKETS)

    lines = [
        "# HELP ugai_http_requests_total Total HTTP requests observed by the API.",
        "# TYPE ugai_http_requests_total counter",
    ]
    for (method, status_code), count in sorted(counts.items()):
        lines.append(
            f'ugai_http_requests_total{{method="{method}",status="{status_code}"}} {count}'
        )

    lines.extend([
        "# HELP ugai_http_request_duration_seconds HTTP request duration in seconds.",
        "# TYPE ugai_http_request_duration_seconds histogram",
    ])
    for (method, status_code), total in sorted(sums.items()):
        for bucket in _DURATION_BUCKETS:
            bucket_label = "+Inf" if bucket == float("inf") else f"{bucket:g}"
            value = buckets.get((method, status_code, bucket), 0)
            lines.append(
                "ugai_http_request_duration_seconds_bucket"
                f'{{method="{method}",status="{status_code}",le="{bucket_label}"}} {value}'
            )
        lines.append(
            f'ugai_http_request_duration_seconds_sum{{method="{method}",status="{status_code}"}} {total:.6f}'
        )
        lines.append(
            f'ugai_http_request_duration_seconds_count{{method="{method}",status="{status_code}"}} '
            f'{counts.get((method, status_code), 0)}'
        )
    return "\n".join(lines) + "\n"


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


class SecurityHeadersMiddleware:
    """Attach conservative browser security headers to API responses."""

    def __init__(self, app, *, enable_hsts: bool = False) -> None:
        self.app = app
        self.enable_hsts = enable_hsts

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                security = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"cache-control", b"no-store"),
                ]
                if self.enable_hsts:
                    security.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                for key, value in security:
                    if key not in existing:
                        headers.append((key, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


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
        method = scope.get("method", "OTHER")
        logger = logging.getLogger("app.request")

        def log_request() -> None:
            duration = time.perf_counter() - started
            record_request_metric(method, status_code, duration)
            logger.info(
                "http_request_completed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": scope.get("path", ""),
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 2),
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
