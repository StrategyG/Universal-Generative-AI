"""Validated, secret-free configuration for the IM19 remote MCP adapter."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Raised when remote MCP configuration is unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class IM19Config:
    endpoint: str
    resource: str
    allowed_tools: frozenset[str]
    request_timeout_seconds: float = 20.0
    max_result_bytes: int = 1_000_000

    @classmethod
    def from_env(cls) -> "IM19Config":
        endpoint = os.getenv("IM19_MCP_URL", "").strip()
        resource = os.getenv("IM19_MCP_RESOURCE", "").strip()
        raw_tools = os.getenv("IM19_ALLOWED_READ_TOOLS", "")
        allowed_tools = frozenset(
            item.strip() for item in raw_tools.split(",") if item.strip()
        )
        try:
            timeout = float(os.getenv("IM19_MCP_TIMEOUT_SECONDS", "20"))
            max_bytes = int(os.getenv("IM19_MCP_MAX_RESULT_BYTES", "1000000"))
        except ValueError as exc:
            raise ConfigurationError("Invalid MCP timeout or response-size setting") from exc

        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ConfigurationError("IM19_MCP_URL must be an absolute HTTPS URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError("MCP endpoint must not contain credentials, query, or fragment")
        if parsed.path.rstrip("/") != "/mcp":
            raise ConfigurationError("IM19_MCP_URL must point to the exact /mcp resource")
        if not resource:
            raise ConfigurationError("IM19_MCP_RESOURCE must be configured")
        if timeout <= 0 or timeout > 120:
            raise ConfigurationError("MCP timeout must be between 0 and 120 seconds")
        if max_bytes < 1_024 or max_bytes > 10_000_000:
            raise ConfigurationError("MCP max result size must be between 1 KiB and 10 MB")
        return cls(
            endpoint=endpoint,
            resource=resource,
            allowed_tools=allowed_tools,
            request_timeout_seconds=timeout,
            max_result_bytes=max_bytes,
        )
