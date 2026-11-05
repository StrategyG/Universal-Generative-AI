"""Fail-closed shared API rate limiting.

Production uses Redis over TLS. The in-memory backend exists only for local
development and deterministic tests; it is not safe across processes.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol


class RateLimitBackend(Protocol):
    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Atomically increment a fixed-window counter and return count, TTL."""

    async def close(self) -> None:
        """Release backend resources."""


class InMemoryRateLimitBackend:
    """Single-process fixed-window backend for local development only."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[int, float]] = {}
        self._operations = 0

    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = time.monotonic()
        self._operations += 1
        if self._operations % 256 == 0:
            self._values = {
                item_key: item
                for item_key, item in self._values.items()
                if item[1] > now
            }
        count, expires_at = self._values.get(key, (0, now + window_seconds))
        if expires_at <= now:
            count, expires_at = 0, now + window_seconds
        count += 1
        self._values[key] = (count, expires_at)
        ttl = max(1, int(expires_at - now + 0.999))
        return count, ttl

    async def close(self) -> None:
        self._values.clear()


class RedisRateLimitBackend:
    """Redis fixed-window backend using one atomic Lua operation."""

    _SCRIPT = """
    local count = redis.call('INCR', KEYS[1])
    if count == 1 then
      redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    local ttl = redis.call('TTL', KEYS[1])
    return {count, ttl}
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        count, ttl = await self._client.eval(
            self._SCRIPT, 1, key, str(window_seconds)
        )
        return int(count), max(1, int(ttl))

    async def close(self) -> None:
        await self._client.aclose()


class RateLimiter:
    """Owns backend lifecycle and provides privacy-preserving counter keys."""

    def __init__(
        self,
        *,
        enabled: bool,
        backend: str,
        redis_url: str,
        requests_per_window: int,
        window_seconds: int,
        environment: str,
    ) -> None:
        self.enabled = enabled
        self.backend_name = backend.strip().lower()
        self.redis_url = redis_url
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.environment = environment.strip().lower()
        self._backend: RateLimitBackend | None = (
            InMemoryRateLimitBackend() if self.backend_name == "memory" else None
        )
        self._ready = self.backend_name == "memory" or not enabled

    @property
    def ready(self) -> bool:
        return self._ready

    async def start(self) -> None:
        if not self.enabled or self._ready:
            return
        if self.backend_name != "redis":
            raise RuntimeError("production_rate_limit_backend_must_be_redis")
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
                health_check_interval=30,
            )
            await client.ping()
        except Exception as exc:
            raise RuntimeError("shared_rate_limit_backend_unavailable") from exc
        self._backend = RedisRateLimitBackend(client)
        self._ready = True

    async def close(self) -> None:
        if self._backend is not None:
            await self._backend.close()
        self._ready = self.backend_name == "memory" or not self.enabled

    async def check(self, identity: str) -> tuple[bool, int, int]:
        if not self.enabled:
            return True, self.requests_per_window, 0
        if not self._ready or self._backend is None:
            raise RuntimeError("rate_limit_backend_not_ready")

        window_id = int(time.time()) // self.window_seconds
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        key = f"ugai:ratelimit:v1:{window_id}:{digest}"
        count, retry_after = await self._backend.increment(key, self.window_seconds)
        remaining = max(0, self.requests_per_window - count)
        return count <= self.requests_per_window, remaining, retry_after


class RateLimitMiddleware:
    """Apply IP-based limits; trust forwarded IP only through Uvicorn's proxy allowlist."""

    def __init__(
        self,
        app,
        *,
        limiter: RateLimiter,
        exempt_paths: tuple[str, ...] = ("/health", "/readyz"),
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.exempt_paths = frozenset(exempt_paths)

    async def _reject(self, send, *, status_code: int, body: dict[str, str], headers=()) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
            *headers,
        ]
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": response_headers,
            }
        )
        await send({"type": "http.response.body", "body": payload})

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not self.limiter.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        if not client or not client[0]:
            await self._reject(
                send,
                status_code=503,
                body={"detail": {"code": "client_identity_unavailable"}},
            )
            return

        try:
            allowed, remaining, retry_after = await self.limiter.check(str(client[0]))
        except Exception:
            # Do not turn a failed shared limiter into an unlimited production API.
            await self._reject(
                send,
                status_code=503,
                body={"detail": {"code": "rate_limit_backend_unavailable"}},
            )
            return

        if not allowed:
            await self._reject(
                send,
                status_code=429,
                body={"detail": {"code": "rate_limit_exceeded"}},
                headers=[
                    (b"retry-after", str(retry_after).encode("ascii")),
                    (
                        b"x-ratelimit-limit",
                        str(self.limiter.requests_per_window).encode("ascii"),
                    ),
                    (b"x-ratelimit-remaining", b"0"),
                ],
            )
            return

        await self.app(scope, receive, send)
