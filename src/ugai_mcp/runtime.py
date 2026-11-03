"""Framework-neutral UGAI tool-provider facade for a scoped IM19 session."""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

from .audit import AuditSink
from .auth import AccessTokenProvider
from .client import IM19MCPClient
from .config import IM19Config
from .policy import ToolPolicy


class IM19ToolProvider:
    """Expose only operator-approved tools to a UGAI workflow runtime.

    Construct per authenticated workflow/request. actor_id must come from the
    trusted UGAI authentication context, never from model-generated arguments.
    """

    def __init__(
        self,
        *,
        config: IM19Config,
        token_provider: AccessTokenProvider,
        audit_sink: AuditSink,
        actor_id: str,
    ) -> None:
        if not actor_id or not actor_id.strip():
            raise ValueError("A trusted authenticated actor_id is required")
        self.actor_id = actor_id
        self._client = IM19MCPClient(
            config=config,
            token_provider=token_provider,
            audit_sink=audit_sink,
            actor_id=actor_id,
            policy=ToolPolicy(config.allowed_tools),
        )

    async def __aenter__(self) -> Self:
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc, tb)

    async def discover(self) -> list[dict[str, Any]]:
        """Return the currently approved MCP tool definitions."""
        return await self._client.refresh_tools()

    async def execute(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one allowlisted tool; arguments are treated as untrusted input."""
        return await self._client.call_tool(tool_name, arguments)
