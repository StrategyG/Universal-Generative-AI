import asyncio
import json

import httpx
import pytest

from app.ai_schemas import AICompletionRequest
from app.config import settings
from app.providers.anthropic_messages import AnthropicMessagesProvider
from app.providers.gemini_generate_content import GeminiGenerateContentProvider
from app.providers.native_text import NativeTextProvider
from app.providers.router import TextModelRouter
from app.providers.text_errors import TextGenerationProviderError


def request(quality_mode="single"):
    return AICompletionRequest(
        project_id="project-native",
        domain="coding",
        objective="Create a secure and tested API",
        quality_mode=quality_mode,
    )


def test_anthropic_native_messages_request_and_usage_normalization():
    def handler(req):
        assert req.url.path == "/v1/messages"
        assert req.headers["x-api-key"] == "anthropic-test-key"
        assert req.headers["anthropic-version"] == "2026-10-21"
        body = json.loads(req.content)
        assert body["model"] == "claude-test"
        assert body["system"]
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(200, json={
            "content": [
                {"type": "text", "text": "Secure "},
                {"type": "text", "text": "implementation"},
            ],
            "usage": {"input_tokens": 12, "output_tokens": 9},
        })

    provider = AnthropicMessagesProvider(
        api_key="anthropic-test-key",
        model="claude-test",
        base_url="https://anthropic.test",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(provider.generate(request()))
    assert result["final_content"] == "Secure implementation"
    assert result["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 9,
        "total_tokens": 21,
    }
    assert result["verified"] is False


def test_anthropic_native_stream_and_model_catalog():
    def handler(req):
        if req.url.path == "/v1/models":
            return httpx.Response(200, json={
                "data": [{"id": "claude-z"}, {"id": "claude-a"}],
                "has_more": False,
            })
        return httpx.Response(
            200,
            content=(
                'event: content_block_delta\n'
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hello "}}\n\n'
                'event: content_block_delta\n'
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"claude"}}\n\n'
                'event: message_stop\n'
                'data: {"type":"message_stop"}\n\n'
            ),
            headers={"content-type": "text/event-stream"},
        )

    provider = AnthropicMessagesProvider(
        api_key="key",
        model="claude-a",
        base_url="https://anthropic.test",
        transport=httpx.MockTransport(handler),
    )

    async def collect():
        return [item async for item in provider.stream(request())]

    assert asyncio.run(collect()) == ["hello ", "claude"]
    assert asyncio.run(provider.list_models()) == ["claude-a", "claude-z"]


def test_gemini_native_generate_content_and_usage_normalization():
    def handler(req):
        assert req.url.path == "/v1beta/models/gemini-test:generateContent"
        assert req.headers["x-goog-api-key"] == "gemini-test-key"
        body = json.loads(req.content)
        assert body["systemInstruction"]["parts"][0]["text"]
        assert body["contents"][0]["role"] == "user"
        assert body["generationConfig"]["maxOutputTokens"] > 0
        return httpx.Response(200, json={
            "candidates": [{
                "content": {"parts": [{"text": "Gemini "}, {"text": "result"}]}
            }],
            "usageMetadata": {
                "promptTokenCount": 15,
                "candidatesTokenCount": 10,
                "totalTokenCount": 25,
            },
        })

    provider = GeminiGenerateContentProvider(
        api_key="gemini-test-key",
        model="gemini-test",
        base_url="https://gemini.test/v1beta",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(provider.generate(request()))
    assert result["final_content"] == "Gemini result"
    assert result["usage"] == {
        "prompt_tokens": 15,
        "completion_tokens": 10,
        "total_tokens": 25,
    }


def test_gemini_native_stream_and_model_catalog():
    def handler(req):
        if req.url.path == "/v1beta/models":
            return httpx.Response(200, json={
                "models": [
                    {"name": "models/gemini-a", "baseModelId": "gemini-a"},
                    {"name": "models/gemini-b"},
                ],
            })
        assert req.url.path.endswith(":streamGenerateContent")
        assert req.url.params.get("alt") == "sse"
        return httpx.Response(
            200,
            content=(
                'data: {"candidates":[{"content":{"parts":[{"text":"hello "}]}}]}\n\n'
                'data: {"candidates":[{"content":{"parts":[{"text":"gemini"}]}}]}\n\n'
            ),
            headers={"content-type": "text/event-stream"},
        )

    provider = GeminiGenerateContentProvider(
        api_key="key",
        model="gemini-a",
        base_url="https://gemini.test/v1beta",
        transport=httpx.MockTransport(handler),
    )

    async def collect():
        return [item async for item in provider.stream(request())]

    assert asyncio.run(collect()) == ["hello ", "gemini"]
    assert asyncio.run(provider.list_models()) == ["gemini-a", "gemini-b"]


def test_native_provider_rigorous_mode_does_not_claim_independent_verification():
    responses = iter([
        {"content": [{"type": "text", "text": "draft"}],
         "usage": {"input_tokens": 1, "output_tokens": 2}},
        {"content": [{"type": "text", "text": "critique"}],
         "usage": {"input_tokens": 2, "output_tokens": 3}},
        {"content": [{"type": "text", "text": "final"}],
         "usage": {"input_tokens": 3, "output_tokens": 4}},
    ])

    def handler(req):
        return httpx.Response(200, json=next(responses))

    provider = AnthropicMessagesProvider(
        api_key="key",
        model="claude-test",
        base_url="https://anthropic.test",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(provider.generate(request("rigorous")))
    assert result["draft"] == "draft"
    assert result["critique"] == "critique"
    assert result["final_content"] == "final"
    assert result["review_type"] == "same_model_critique_and_revision"
    assert result["verified"] is False
    assert result["usage"]["total_tokens"] == 15


def test_native_provider_configuration_rejects_non_https_endpoint():
    with pytest.raises(TextGenerationProviderError, match="HTTPS"):
        AnthropicMessagesProvider(
            api_key="key", model="claude-test", base_url="http://anthropic.test"
        )
    with pytest.raises(TextGenerationProviderError, match="HTTPS"):
        GeminiGenerateContentProvider(
            api_key="key", model="gemini-test", base_url="http://gemini.test/v1beta"
        )


def test_router_factory_builds_native_routes_in_configured_order(monkeypatch):
    monkeypatch.setattr(settings, "text_generation_base_url", "")
    monkeypatch.setattr(settings, "text_generation_model", "")
    monkeypatch.setattr(settings, "text_generation_fallback_base_url", "")
    monkeypatch.setattr(settings, "text_generation_fallback_model", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "anthropic-key")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-test")
    monkeypatch.setattr(
        settings,
        "text_generation_provider_order",
        "gemini-generate-content,anthropic-messages",
    )

    router = TextModelRouter.from_settings()
    assert [provider.name for provider in router.providers] == [
        "gemini-generate-content",
        "anthropic-messages",
    ]
    assert all(isinstance(provider, NativeTextProvider) for provider in router.providers)


def test_router_factory_fails_closed_for_partial_native_configuration(monkeypatch):
    monkeypatch.setattr(settings, "text_generation_base_url", "")
    monkeypatch.setattr(settings, "text_generation_model", "")
    monkeypatch.setattr(settings, "text_generation_fallback_base_url", "")
    monkeypatch.setattr(settings, "text_generation_fallback_model", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "anthropic-key")
    monkeypatch.setattr(settings, "anthropic_model", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "gemini_model", "")

    with pytest.raises(TextGenerationProviderError, match="Anthropic route"):
        TextModelRouter.from_settings()
