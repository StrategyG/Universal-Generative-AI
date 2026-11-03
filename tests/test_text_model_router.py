import asyncio

import pytest

from app.ai_schemas import AICompletionRequest
from app.providers.router import TextModelRouter
from app.providers.text_base import TextModelCapabilities
from app.providers.text_errors import TextGenerationProviderError


def request():
    return AICompletionRequest(
        project_id="project-1",
        domain="coding",
        objective="Create a tested API",
        quality_mode="single",
    )


class FakeProvider:
    capabilities = TextModelCapabilities(streaming=True)

    def __init__(self, name, result=None, error=None, stream_error=None):
        self.name = name
        self.model = name + "-model"
        self.model_id = ""
        self.model_revision = ""
        self.result = result or {
            "provider": name,
            "model": self.model,
            "domain": "coding",
            "quality_mode": "single",
            "final_content": "ok",
            "review_type": "none",
            "verified": False,
            "usage": {},
        }
        self.error = error
        self.stream_error = stream_error
        self.calls = 0

    async def generate(self, _request):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.result)

    async def list_models(self):
        return [self.model]

    async def stream(self, _request):
        if self.stream_error:
            raise self.stream_error
        yield self.name + "-token"


def test_router_retries_transient_error_then_uses_fallback():
    primary = FakeProvider(
        "primary",
        error=TextGenerationProviderError(
            "temporary", code="provider_timeout", retryable=True
        ),
    )
    fallback = FakeProvider("fallback")
    router = TextModelRouter([primary, fallback], max_retries=1, retry_backoff_seconds=0)

    result = asyncio.run(router.generate(request()))

    assert primary.calls == 2
    assert fallback.calls == 1
    assert result["routing"]["selected_provider"] == "fallback"
    assert result["routing"]["fallback_used"] is True


def test_router_does_not_retry_permanent_model_error():
    primary = FakeProvider(
        "primary",
        error=TextGenerationProviderError(
            "missing model", code="model_or_endpoint_not_found", retryable=False
        ),
    )
    fallback = FakeProvider("fallback")
    router = TextModelRouter([primary, fallback], max_retries=3, retry_backoff_seconds=0)

    result = asyncio.run(router.generate(request()))

    assert primary.calls == 1
    assert fallback.calls == 1
    assert result["routing"]["selected_provider"] == "fallback"


def test_stream_router_falls_back_only_before_first_token():
    primary = FakeProvider(
        "primary",
        stream_error=TextGenerationProviderError(
            "unavailable", code="provider_unavailable", retryable=True
        ),
    )
    fallback = FakeProvider("fallback")
    router = TextModelRouter([primary, fallback], max_retries=0)

    async def collect():
        return [token async for token in router.stream(request())]

    assert asyncio.run(collect()) == ["fallback-token"]


def test_stream_router_rejects_when_no_provider_supports_streaming():
    provider = FakeProvider("no-stream")
    provider.capabilities = TextModelCapabilities(streaming=False)
    router = TextModelRouter([provider])

    async def collect():
        return [token async for token in router.stream(request())]

    with pytest.raises(TextGenerationProviderError) as caught:
        asyncio.run(collect())
    assert caught.value.code == "capability_unavailable"



def test_router_discovers_models_for_each_route():
    primary = FakeProvider("primary")
    fallback = FakeProvider("fallback")
    router = TextModelRouter([primary, fallback])

    result = asyncio.run(router.discover_models())

    assert len(result["routes"]) == 2
    assert result["routes"][0]["configured_model_available"] is True
    assert result["routes"][1]["status"] == "available"
