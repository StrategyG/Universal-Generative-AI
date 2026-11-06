from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.ai_schemas import AICompletionRequest
from app.config import settings
from app.providers import router as router_module
from app.providers.router import TextModelRouter
from app.providers.text_base import TextModelCapabilities
from app.providers.text_errors import TextGenerationProviderError


def request():
    return AICompletionRequest(
        project_id="project-1",
        domain="coding",
        objective="Exercise provider routing",
        quality_mode="single",
    )


class Provider:
    capabilities = TextModelCapabilities(streaming=True)

    def __init__(self, name="provider", *, model=None, result=None, error=None, models=None):
        self.name = name
        self.model = model or name + "-model"
        self.model_id = "model-id"
        self.model_revision = "revision-1"
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
        self.models = models
        self.calls = 0

    async def generate(self, _request):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.result)

    async def list_models(self):
        if isinstance(self.models, Exception):
            raise self.models
        return list(self.models or [])

    async def stream(self, _request):
        yield self.name + "-token"


def clear_provider_settings(monkeypatch):
    for name in (
        "text_generation_base_url",
        "text_generation_model",
        "text_generation_fallback_base_url",
        "text_generation_fallback_model",
        "text_generation_fallback_api_key",
        "text_generation_fallback_model_id",
        "text_generation_fallback_model_revision",
        "anthropic_api_key",
        "anthropic_model",
        "gemini_api_key",
        "gemini_model",
    ):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(
        settings,
        "text_generation_provider_order",
        "openai-compatible-chat,openai-compatible-chat-fallback,anthropic-messages,gemini-generate-content",
    )
    monkeypatch.setattr(settings, "text_generation_max_retries", 1)
    monkeypatch.setattr(settings, "text_generation_retry_backoff_seconds", 0.5)


def test_router_rejects_empty_provider_list_and_invalid_names():
    with pytest.raises(ValueError, match="At least one"):
        TextModelRouter([])
    with pytest.raises(ValueError, match="stable non-empty name"):
        TextModelRouter([Provider(name=" ")])


def test_router_clamps_retry_and_backoff_configuration():
    router = TextModelRouter([Provider()], max_retries=99, retry_backoff_seconds=99)
    assert router.max_retries == 3
    assert router.retry_backoff_seconds == 10.0
    no_retry = TextModelRouter([Provider()], max_retries=-5, retry_backoff_seconds=-1)
    assert no_retry.max_retries == 0
    assert no_retry.retry_backoff_seconds == 0.0


def test_from_settings_rejects_missing_and_partial_primary_route(monkeypatch):
    clear_provider_settings(monkeypatch)
    with pytest.raises(TextGenerationProviderError) as missing:
        TextModelRouter.from_settings()
    assert missing.value.code == "configuration_error"

    monkeypatch.setattr(settings, "text_generation_base_url", "https://model.example.test/v1")
    with pytest.raises(TextGenerationProviderError, match="Primary OpenAI-compatible route"):
        TextModelRouter.from_settings()


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("text_generation_fallback_base_url", "https://fallback.example.test/v1", "Fallback route"),
        ("anthropic_api_key", "anthropic-test-key", "Anthropic route"),
        ("gemini_api_key", "gemini-test-key", "Gemini route"),
    ],
)
def test_from_settings_rejects_partial_fallback_provider_configuration(monkeypatch, key, value, message):
    clear_provider_settings(monkeypatch)
    monkeypatch.setattr(settings, key, value)
    with pytest.raises(TextGenerationProviderError, match=message):
        TextModelRouter.from_settings()


def test_from_settings_rejects_unknown_and_omitted_configured_providers(monkeypatch):
    clear_provider_settings(monkeypatch)
    monkeypatch.setattr(settings, "text_generation_provider_order", "unknown-provider")
    with pytest.raises(TextGenerationProviderError, match="Unknown provider names"):
        TextModelRouter.from_settings()

    monkeypatch.setattr(settings, "text_generation_base_url", "https://model.example.test/v1")
    monkeypatch.setattr(settings, "text_generation_model", "model-a")
    monkeypatch.setattr(settings, "text_generation_provider_order", "anthropic-messages")
    with pytest.raises(TextGenerationProviderError, match="missing from TEXT_GENERATION_PROVIDER_ORDER"):
        TextModelRouter.from_settings()


def test_from_settings_builds_only_explicitly_ordered_configured_routes(monkeypatch):
    clear_provider_settings(monkeypatch)
    monkeypatch.setattr(settings, "text_generation_base_url", "https://model.example.test/v1")
    monkeypatch.setattr(settings, "text_generation_model", "model-a")
    monkeypatch.setattr(settings, "text_generation_provider_order", "openai-compatible-chat")
    primary = Provider("openai-compatible-chat")
    monkeypatch.setattr(
        router_module.OpenAICompatibleTextProvider,
        "from_settings",
        classmethod(lambda _cls: primary),
    )
    router = TextModelRouter.from_settings()
    assert router.providers == (primary,)


def test_discovery_handles_unsupported_unavailable_and_unlisted_catalogs():
    unsupported = SimpleNamespace(name="unsupported", model="m1")
    unavailable = Provider(
        "unavailable",
        models=TextGenerationProviderError("catalog offline", code="catalog_unavailable"),
    )
    unlisted = Provider("unlisted", models=["other-model"])
    router = TextModelRouter([unsupported, unavailable, unlisted])

    result = asyncio.run(router.discover_models())
    assert [item["status"] for item in result["routes"]] == [
        "discovery_unsupported",
        "discovery_unavailable",
        "configured_model_not_listed",
    ]


def test_exact_provider_lookup_rejects_blank_name():
    router = TextModelRouter([Provider()])
    with pytest.raises(TextGenerationProviderError) as caught:
        router.get_provider(" ")
    assert caught.value.code == "configuration_error"


def test_exact_provider_route_requires_both_expected_model_identity_fields():
    router = TextModelRouter([Provider()])
    with pytest.raises(ValueError, match="must_be_supplied_together"):
        asyncio.run(
            router.generate_with_provider(
                "provider", request(), expected_model_id="model-id"
            )
        )


def test_exact_provider_route_retries_only_retryable_errors(monkeypatch):
    selected = Provider(
        "selected",
        error=TextGenerationProviderError(
            "temporarily unavailable",
            code="provider_timeout",
            retryable=True,
            retry_after_seconds=0,
        ),
    )
    router = TextModelRouter([selected], max_retries=1, retry_backoff_seconds=0)
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(router_module.asyncio, "sleep", fake_sleep)
    with pytest.raises(TextGenerationProviderError) as caught:
        asyncio.run(router.generate_with_provider("selected", request()))
    assert caught.value.code == "provider_timeout"
    assert selected.calls == 2
    assert sleeps == [0]


def test_discovery_and_generation_do_not_invent_a_route_when_none_is_eligible():
    router = TextModelRouter([Provider()])
    router.eligible_providers = lambda **_kwargs: ()
    with pytest.raises(TextGenerationProviderError) as generated:
        asyncio.run(router.generate(request()))
    assert generated.value.code == "capability_unavailable"


def test_streaming_empty_provider_returns_empty_stream():
    class EmptyProvider(Provider):
        async def stream(self, _request):
            if False:
                yield ""

    async def collect():
        return [item async for item in TextModelRouter([EmptyProvider()]).stream(request())]

    assert asyncio.run(collect()) == []


def test_streaming_error_after_first_token_is_not_switched_to_another_provider():
    class PartialFailureProvider(Provider):
        async def stream(self, _request):
            yield "first-token"
            raise TextGenerationProviderError(
                "connection failed after token", code="stream_interrupted", retryable=True
            )

    first = PartialFailureProvider("first")
    fallback = Provider("fallback")
    router = TextModelRouter([first, fallback])

    async def collect():
        output = []
        async for token in router.stream(request()):
            output.append(token)
        return output

    async def run_and_capture():
        iterator = router.stream(request())
        first_token = await anext(iterator)
        assert first_token == "first-token"
        with pytest.raises(TextGenerationProviderError) as caught:
            await anext(iterator)
        return caught.value

    error = asyncio.run(run_and_capture())
    assert error.code == "stream_interrupted"
    assert fallback.calls == 0


def test_from_settings_builds_explicit_fallback_provider(monkeypatch):
    clear_provider_settings(monkeypatch)
    monkeypatch.setattr(settings, "text_generation_base_url", "https://primary.example.test/v1")
    monkeypatch.setattr(settings, "text_generation_model", "primary-model")
    monkeypatch.setattr(settings, "text_generation_fallback_base_url", "https://fallback.example.test/v1")
    monkeypatch.setattr(settings, "text_generation_fallback_model", "fallback-model")
    monkeypatch.setattr(
        settings,
        "text_generation_provider_order",
        "openai-compatible-chat,openai-compatible-chat-fallback",
    )

    class FakeOpenAI:
        @classmethod
        def from_settings(cls):
            return Provider("openai-compatible-chat")

        def __init__(self, **kwargs):
            self.name = "openai-compatible-chat-fallback"
            self.model = kwargs["model"]
            self.model_id = kwargs["model_id"]
            self.model_revision = kwargs["model_revision"]
            self.capabilities = TextModelCapabilities(streaming=True)

    monkeypatch.setattr(router_module, "OpenAICompatibleTextProvider", FakeOpenAI)
    router = TextModelRouter.from_settings()
    assert [provider.name for provider in router.providers] == [
        "openai-compatible-chat",
        "openai-compatible-chat-fallback",
    ]


def test_stream_retries_before_first_token_and_never_splices_after_emission():
    class RetryBeforeToken(Provider):
        def __init__(self):
            super().__init__("retry-before-token")
            self.stream_calls = 0

        async def stream(self, _request):
            self.stream_calls += 1
            if self.stream_calls == 1:
                raise TextGenerationProviderError(
                    "temporary stream startup failure",
                    code="stream_startup",
                    retryable=True,
                    retry_after_seconds=0,
                )
            yield "recovered-token"

    provider = RetryBeforeToken()
    router = TextModelRouter([provider], max_retries=1, retry_backoff_seconds=0)

    async def collect():
        return [token async for token in router.stream(request())]

    assert asyncio.run(collect()) == ["recovered-token"]
    assert provider.stream_calls == 2


def test_stream_falls_back_only_before_the_first_token_and_reports_no_capability():
    class FailingBeforeToken(Provider):
        async def stream(self, _request):
            if False:
                yield ""
            raise TextGenerationProviderError(
                "provider unavailable before first token",
                code="stream_startup",
                retryable=False,
            )

    first = FailingBeforeToken("first")
    second = Provider("second")
    router = TextModelRouter([first, second])

    async def collect():
        return [token async for token in router.stream(request())]

    assert asyncio.run(collect()) == ["second-token"]

    class NoStreamingProvider(Provider):
        capabilities = TextModelCapabilities(streaming=False)

    no_stream = TextModelRouter([NoStreamingProvider("text-only")])

    async def collect_without_capability():
        return [token async for token in no_stream.stream(request())]

    with pytest.raises(TextGenerationProviderError) as caught:
        asyncio.run(collect_without_capability())
    assert caught.value.code == "capability_unavailable"
