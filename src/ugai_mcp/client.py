"""Bounded remote Streamable HTTP client for the IM19 MCP gateway."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from contextlib import suppress
from datetime import timedelta
from types import TracebackType
from typing import Any, Self

from .auth import AccessTokenProvider
from .config import IM19Config
from .policy import ToolPolicy


class MCPIntegrationError(RuntimeError):
    """Base error for safe, fail-closed integration failures."""


class MCPUnavailable(MCPIntegrationError):
    """The remote MCP service could not be reached or authenticated."""


class ToolDenied(MCPIntegrationError):
    """A requested tool is not approved for UGAI exposure."""


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return str(value)


class IM19MCPClient:
    """One scoped MCP session. Instantiate per request/workflow, not per user globally."""

    def __init__(
        self,
        config: IM19Config,
        token_provider: AccessTokenProvider,
        policy: ToolPolicy | None = None,
    ) -> None:
        self._config = config
        self._tokens = token_provider
        self._policy = policy or ToolPolicy(config.allowed_tools)
        self._session: Any = None
        self._transport_cm: Any = None
        self._session_cm: Any = None
        self._tools: dict[str, Any] = {}

    async def __aenter__(self) -> Self:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            token = await self._tokens.get_access_token(resource=self._config.resource)
            if not token or any(ch.isspace() for ch in token):
                raise MCPUnavailable("OAuth provider returned an invalid bearer token")

            timeout = timedelta(seconds=self._config.request_timeout_seconds)
            self._transport_cm = streamablehttp_client(
                self._config.endpoint,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
                sse_read_timeout=timeout,
            )
            read_stream, write_stream, _ = await self._transport_cm.__aenter__()
            self._session_cm = ClientSession(read_stream, write_stream)
            self._session = await self._session_cm.__aenter__()
            await asyncio.wait_for(
                self._session.initialize(),
                timeout=self._config.request_timeout_seconds,
            )
            await self.refresh_tools()
            return self
        except Exception as exc:
            await self._close_safely()
            if isinstance(exc, MCPIntegrationError):
                raise
            raise MCPUnavailable("IM19 MCP initialization failed") from exc

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._close_safely()

    async def _close_safely(self) -> None:
        if self._session_cm is not None:
            with suppress(Exception):
                await self._session_cm.__aexit__(None, None, None)
            self._session_cm = None
        if self._transport_cm is not None:
            with suppress(Exception):
                await self._transport_cm.__aexit__(None, None, None)
            self._transport_cm = None
        self._session = None
        self._tools = {}

    async def refresh_tools(self) -> list[dict[str, Any]]:
        if self._session is None:
            raise MCPUnavailable("MCP session is not initialized")
        try:
            result = await asyncio.wait_for(
                self._session.list_tools(),
                timeout=self._config.request_timeout_seconds,
            )
            discovered = getattr(result, "tools", [])
            approved: dict[str, Any] = {}
            public: list[dict[str, Any]] = []
            for tool in discovered:
                decision = self._policy.evaluate(tool)
                if decision.allowed:
                    name = getattr(tool, "name", None)
                    approved[name] = tool
                    public.append(_plain(tool))
            self._tools = approved
            return public
        except Exception as exc:
            raise MCPUnavailable("IM19 tools/list failed") from exc

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise MCPUnavailable("MCP session is not initialized")
        if name not in self._tools:
            raise ToolDenied("Tool is not in the current approved tools/list snapshot")
        if not isinstance(arguments, Mapping):
            raise ToolDenied("Tool arguments must be a JSON object")

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, arguments=dict(arguments)),
                timeout=self._config.request_timeout_seconds,
            )
            payload = _plain(result)
            encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
            if len(encoded) > self._config.max_result_bytes:
                raise MCPIntegrationError("MCP tool response exceeded configured size limit")
            if getattr(result, "isError", False):
                raise MCPIntegrationError("IM19 tool returned an error")
            return {
                "server": "im19",
                "tool": name,
                "status": "success",
                "result": payload,
            }
        except MCPIntegrationError:
            raise
        except Exception as exc:
            raise MCPUnavailable("IM19 tool execution failed") from exc
