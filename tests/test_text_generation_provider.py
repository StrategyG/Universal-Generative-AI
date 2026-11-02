import asyncio

import httpx
import pytest

from app.ai_schemas import AICompletionRequest
from app.providers.openai_compatible_text import (
    OpenAICompatibleTextProvider,
    TextGenerationProviderError,
)


def make_provider(handler):
    transport = httpx.MockTransport(handler)
    return OpenAICompatibleTextProvider(
        base_url="https://llm.example.test/v1",
        model="test-model",
        api_key="test-api-key",
        transport=transport,
    )


def test_rigorous_mode_runs_draft_critique_and_revision_without_claiming_verification():
    calls = []

    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-api-key"
        body = __import__("json").loads(request.content)
        calls.append(body)
        content = ["draft v1", "review: add failure handling", "final v2"][len(calls) - 1]
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        })

    provider = make_provider(handler)
    request = AICompletionRequest(
        project_id="project-1",
        domain="coding",
        objective="Design a tenant-scoped application API",
        context="Use PostgreSQL",
        quality_mode="rigorous",
    )
    result = asyncio.run(provider.generate(request))

    assert len(calls) == 3
    assert result["draft"] == "draft v1"
    assert result["critique"] == "review: add failure handling"
    assert result["final_content"] == "final v2"
    assert result["review_type"] == "same_model_critique_and_revision"
    assert result["verified"] is False
    assert result["usage"]["total_tokens"] == 90
    assert "principal software architect" in calls[0]["messages"][0]["content"].lower()


def test_single_mode_calls_provider_once():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "generated result"}}],
            "usage": {},
        })

    provider = make_provider(handler)
    result = asyncio.run(provider.generate(AICompletionRequest(
        project_id="project-1",
        domain="film",
        objective="Write a short film beat sheet",
        quality_mode="single",
    )))
    assert len(calls) == 1
    assert result["final_content"] == "generated result"
    assert result["draft"] is None
    assert result["verified"] is False


def test_provider_rejects_remote_plain_http():
    with pytest.raises(TextGenerationProviderError, match="HTTPS"):
        OpenAICompatibleTextProvider(
            base_url="http://llm.example.test/v1",
            model="test-model",
        )


def test_provider_rejects_tool_calls_in_text_only_mode():
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{"id": "call-1", "type": "function"}],
                },
            }],
        })

    provider = make_provider(handler)
    with pytest.raises(TextGenerationProviderError, match="tool calls"):
        asyncio.run(provider.generate(AICompletionRequest(
            project_id="project-1",
            domain="workflow",
            objective="Classify an intake request",
            quality_mode="single",
        )))



def test_provider_classifies_model_not_found_as_permanent():
    def handler(request):
        return httpx.Response(404, json={"error": {"message": "private upstream detail"}})

    provider = make_provider(handler)
    with pytest.raises(TextGenerationProviderError) as caught:
        asyncio.run(provider.generate(AICompletionRequest(
            project_id="project-1",
            domain="coding",
            objective="Inspect a repository",
            quality_mode="single",
        )))
    assert caught.value.code == "model_or_endpoint_not_found"
    assert caught.value.retryable is False
    assert "private upstream detail" not in str(caught.value)


def test_provider_classifies_rate_limit_as_retryable_and_honors_retry_after():
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": "limited"})

    provider = make_provider(handler)
    with pytest.raises(TextGenerationProviderError) as caught:
        asyncio.run(provider.generate(AICompletionRequest(
            project_id="project-1",
            domain="coding",
            objective="Inspect a repository",
            quality_mode="single",
        )))
    assert caught.value.code == "rate_limited"
    assert caught.value.retryable is True
    assert caught.value.retry_after_seconds == 2.0


def test_provider_streams_server_sent_event_deltas():
    body = (
        'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
        'data: [DONE]\n\n'
    )

    def handler(request):
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    provider = make_provider(handler)

    async def collect():
        return [chunk async for chunk in provider.stream(AICompletionRequest(
            project_id="project-1",
            domain="coding",
            objective="Stream a response",
            quality_mode="single",
        ))]

    assert asyncio.run(collect()) == ["hello ", "world"]
