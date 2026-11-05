import asyncio
import json

import httpx
import pytest

from app.ai_schemas import AICompletionRequest
from app.providers.anthropic_mcp import (
    MCP_BETA,
    AnthropicMcpProvider,
    McpServer,
    load_mcp_servers_from_env,
)
from app.providers.anthropic_messages import AnthropicMessagesProvider
from app.providers.text_errors import TextGenerationProviderError


def request():
    return AICompletionRequest(
        project_id="project-mcp",
        domain="coding",
        objective="Answer using the docs tool",
        quality_mode="single",
    )


def test_mcp_provider_sends_servers_tools_and_beta_header_and_keeps_only_text():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["beta"] = req.headers.get("anthropic-beta")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={
            "content": [
                {"type": "mcp_tool_use", "id": "t1", "name": "search",
                 "input": {"q": "rate limit"}, "server_name": "docs"},
                {"type": "mcp_tool_result", "tool_use_id": "t1",
                 "content": [{"type": "text", "text": "raw tool output"}]},
                {"type": "text", "text": "Rate limit is 60 per minute."},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 7},
        })

    provider = AnthropicMcpProvider(
        api_key="key",
        model="claude-test",
        base_url="https://anthropic.test",
        transport=httpx.MockTransport(handler),
        mcp_servers=[
            McpServer(name="docs", url="https://mcp.example.test/sse", token="secret-token"),
        ],
    )
    result = asyncio.run(provider.generate(request()))

    assert seen["path"] == "/v1/messages"
    assert seen["beta"] == MCP_BETA
    assert seen["body"]["mcp_servers"] == [{
        "type": "url",
        "url": "https://mcp.example.test/sse",
        "name": "docs",
        "authorization_token": "secret-token",
    }]
    assert seen["body"]["tools"] == [{"type": "mcp_toolset", "mcp_server_name": "docs"}]
    assert result["final_content"] == "Rate limit is 60 per minute."
    assert "raw tool output" not in result["final_content"]


def test_plain_anthropic_provider_does_not_send_mcp_fields_or_beta_header():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["beta"] = req.headers.get("anthropic-beta")
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    provider = AnthropicMessagesProvider(
        api_key="key",
        model="claude-test",
        base_url="https://anthropic.test",
        transport=httpx.MockTransport(handler),
    )
    asyncio.run(provider.generate(request()))

    assert "mcp_servers" not in seen["body"]
    assert "tools" not in seen["body"]
    assert seen["beta"] is None


def test_mcp_provider_refuses_streaming_and_does_not_advertise_it():
    provider = AnthropicMcpProvider(
        api_key="key",
        model="claude-test",
        base_url="https://anthropic.test",
        transport=httpx.MockTransport(lambda req: httpx.Response(500)),
        mcp_servers=[McpServer(name="docs", url="https://mcp.example.test/sse", token=None)],
    )
    assert provider.capabilities.streaming is False

    async def collect():
        return [item async for item in provider.stream(request())]

    with pytest.raises(TextGenerationProviderError, match="streaming"):
        asyncio.run(collect())


def test_mcp_provider_requires_at_least_one_server():
    with pytest.raises(TextGenerationProviderError, match="at least one"):
        AnthropicMcpProvider(
            api_key="key",
            model="claude-test",
            base_url="https://anthropic.test",
            mcp_servers=[],
        )


def test_mcp_is_disabled_by_default():
    env = {
        "ANTHROPIC_MCP_SERVERS": json.dumps({"docs": "https://mcp.example.test/sse"}),
    }
    assert load_mcp_servers_from_env(env) == []


def test_mcp_loads_allowlisted_server_with_per_server_token():
    env = {
        "ANTHROPIC_MCP_ENABLED": "true",
        "ANTHROPIC_MCP_SERVERS": json.dumps({"docs-search": "https://mcp.example.test/sse"}),
        "ANTHROPIC_MCP_TOKEN_DOCS_SEARCH": "secret",
    }
    assert load_mcp_servers_from_env(env) == [
        McpServer(name="docs-search", url="https://mcp.example.test/sse", token="secret"),
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.example.test/sse",
        "https://user:pass@mcp.example.test/sse",
        "https://",
    ],
)
def test_mcp_rejects_unsafe_urls(url):
    env = {
        "ANTHROPIC_MCP_ENABLED": "true",
        "ANTHROPIC_MCP_SERVERS": json.dumps({"docs": url}),
    }
    with pytest.raises(TextGenerationProviderError, match="HTTPS"):
        load_mcp_servers_from_env(env)


def test_mcp_rejects_invalid_server_names():
    env = {
        "ANTHROPIC_MCP_ENABLED": "true",
        "ANTHROPIC_MCP_SERVERS": json.dumps({"Docs Search": "https://mcp.example.test/sse"}),
    }
    with pytest.raises(TextGenerationProviderError, match="name"):
        load_mcp_servers_from_env(env)
