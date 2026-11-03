from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.ai_schemas import AICompletionRequest
from app.providers.anthropic_messages import AnthropicMessagesProvider
from app.providers.text_base import TextModelCapabilities
from app.providers.text_errors import TextGenerationProviderError

MCP_BETA = "mcp-client-2025-11-20"  # cek versi terbaru di dokumentasi sebelum rilis
_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class McpServer:
    name: str
    url: str
    token: str | None


def load_mcp_servers_from_env(env: Mapping[str, str] | None = None) -> list[McpServer]:
    """Mengembalikan daftar kosong jika ANTHROPIC_MCP_ENABLED bukan 'true'. Default: nonaktif."""
    source = os.environ if env is None else env
    if source.get("ANTHROPIC_MCP_ENABLED", "false").strip().lower() != "true":
        return []

    try:
        mapping = json.loads(source.get("ANTHROPIC_MCP_SERVERS", "{}"))
    except json.JSONDecodeError as exc:
        raise TextGenerationProviderError(
            "ANTHROPIC_MCP_SERVERS is not valid JSON",
            code="configuration_error",
        ) from exc
    if not isinstance(mapping, dict):
        raise TextGenerationProviderError(
            "ANTHROPIC_MCP_SERVERS must be a JSON object",
            code="configuration_error",
        )

    servers: list[McpServer] = []
    for name, url in mapping.items():
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise TextGenerationProviderError(
                "MCP server name is invalid",
                code="configuration_error",
            )
        if not isinstance(url, str):
            raise TextGenerationProviderError(
                f"MCP server '{name}' URL must be a string",
                code="configuration_error",
            )
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
            raise TextGenerationProviderError(
                f"MCP server '{name}' URL must be HTTPS without embedded credentials",
                code="configuration_error",
            )
        token_key = f"ANTHROPIC_MCP_TOKEN_{name.upper().replace('-', '_')}"
        servers.append(McpServer(name=name, url=url, token=source.get(token_key) or None))
    return servers


class AnthropicMcpProvider(AnthropicMessagesProvider):
    """Anthropic Messages dengan MCP connector. Tidak mendukung streaming."""

    name = "anthropic-messages-mcp"
    capabilities = TextModelCapabilities(streaming=False, tool_calling=True)

    def __init__(self, *args, mcp_servers: list[McpServer], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not mcp_servers:
            raise TextGenerationProviderError(
                "MCP mode requires at least one allowlisted server",
                code="configuration_error",
            )
        self.mcp_servers = tuple(mcp_servers)

    def _headers(self) -> dict[str, str]:
        # Header beta ini juga ikut terkirim ke /v1/models. Tidak berbahaya, tetapi perlu diketahui.
        return {**super()._headers(), "anthropic-beta": MCP_BETA}

    def _extra_payload(self) -> dict[str, object]:
        servers: list[dict[str, str]] = []
        for server in self.mcp_servers:
            entry = {"type": "url", "url": server.url, "name": server.name}
            if server.token:
                entry["authorization_token"] = server.token
            servers.append(entry)
        return {
            "mcp_servers": servers,
            "tools": [
                {"type": "mcp_toolset", "mcp_server_name": server.name}
                for server in self.mcp_servers
            ],
        }

    async def stream(self, request: AICompletionRequest) -> AsyncIterator[str]:
        raise TextGenerationProviderError(
            "MCP mode does not support streaming in this adapter",
            code="unsupported_operation",
        )
        yield ""  # tidak pernah tercapai; membuat fungsi ini async generator
