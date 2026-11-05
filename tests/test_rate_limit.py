from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.rate_limit import InMemoryRateLimitBackend, RateLimiter, RateLimitMiddleware


@pytest.mark.asyncio
async def test_in_memory_backend_enforces_fixed_window_limit():
    limiter = RateLimiter(
        enabled=True,
        backend="memory",
        redis_url="",
        requests_per_window=2,
        window_seconds=60,
        environment="test",
    )
    assert await limiter.check("client-1") == (True, 1, 60)
    assert await limiter.check("client-1") == (True, 0, 60)
    allowed, remaining, retry_after = await limiter.check("client-1")
    assert allowed is False
    assert remaining == 0
    assert retry_after >= 1


@pytest.mark.asyncio
async def test_memory_backend_reclaims_expired_keys():
    backend = InMemoryRateLimitBackend()
    await backend.increment("client-a", 60)
    assert "client-a" in backend._values
    await backend.close()
    assert backend._values == {}


def test_rate_limit_middleware_returns_429_after_limit():
    limiter = RateLimiter(
        enabled=True,
        backend="memory",
        redis_url="",
        requests_per_window=1,
        window_seconds=60,
        environment="test",
    )
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/resource")
    async def resource():
        return {"ok": True}

    client = TestClient(app)
    first = client.get("/resource")
    second = client.get("/resource")
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"]
    assert second.headers["x-ratelimit-remaining"] == "0"


def test_rate_limit_middleware_exempts_health_endpoint():
    limiter = RateLimiter(
        enabled=True,
        backend="memory",
        redis_url="",
        requests_per_window=1,
        window_seconds=60,
        environment="test",
    )
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/health")
    async def health():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200


def test_rate_limit_middleware_fails_closed_when_backend_is_unavailable():
    limiter = RateLimiter(
        enabled=True,
        backend="memory",
        redis_url="",
        requests_per_window=10,
        window_seconds=60,
        environment="test",
    )
    limiter._ready = False
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/resource")
    async def resource():
        return {"ok": True}

    response = TestClient(app).get("/resource")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rate_limit_backend_unavailable"


def test_disabled_rate_limiter_does_not_reject_requests():
    limiter = RateLimiter(
        enabled=False,
        backend="memory",
        redis_url="",
        requests_per_window=1,
        window_seconds=60,
        environment="test",
    )
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/resource")
    async def resource():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/resource").status_code == 200
    assert client.get("/resource").status_code == 200
