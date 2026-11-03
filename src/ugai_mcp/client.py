"""Bounded remote Streamable HTTP client for the IM19 MCP gateway."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Mapping
from contextlib import suppress
from types import TracebackType
from typing import Any, Self

from .audit import AuditSink, make_audit_event
from .auth import IM19_REQUIRED_SCOPES, AccessTokenProvider
from .config import IM19Config
from .policy import ToolPolicy

logger = logging.getLogger(__name__)


class MCPIntegrationError(RuntimeError):
    """Base error for safe, fail-closed integration failures."""


class MCPUnavailable(MCPIntegrationError):
    """The remote MCP service could not be reached or authenticated."""


class ToolDenied(MCPIntegrationError):
    """A requested tool is not approved for UGAI exposure."""


class AuditUnavailable(MCPIntegrationError):
    """The durable audit sink failed; inspect the event before retrying."""

    def __init__(self, message: str, *, execution_may_have_completed: bool = False) -> None:
        super().__init__(message)
        self.execution_may_have_completed = execution_may_have_completed


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
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
    """One authenticated and audited MCP session per request/workflow."""

    def __init__(
        self,
        config: IM19Config,
        token_provider: AccessTokenProvider,
        audit_sink: AuditSink,
        actor_id: str,
        policy: ToolPolicy | None = None,
    ) -> None:
        if not actor_id or not actor_id.strip():
            raise ValueError("A trusted authenticated actor_id is required")
        self._config = config
        self._tokens = token_provider
        self._audit = audit_sink
        self._actor_id = actor_id
        self._policy = policy or ToolPolicy(config.allowed_tools)
        self._session: Any = None
        self._transport_cm: Any = None
        self._http_client_cm: Any = None
        self._session_cm: Any = None
        self._tools: dict[str, Any] = {}

    async def __aenter__(self) -> Self:
        try:
            import httpx2
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client

            token = await self._tokens.get_access_token(
                resource=self._config.resource,
                scopes=IM19_REQUIRED_SCOPES,
            )
            if not token or any(ch.isspace() for ch in token):
                raise MCPUnavailable("OAuth provider returned an invalid bearer token")

            timeout = httpx2.Timeout(
                self._config.request_timeout_seconds,
                read=max(300.0, self._config.request_timeout_seconds),
            )
            limits = httpx2.Limits(max_connections=8, max_keepalive_connections=4)
            self._http_client_cm = httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
                limits=limits,
                follow_redirects=False,
            )
            await self._http_client_cm.__aenter__()
            self._transport_cm = streamable_http_client(
                self._config.endpoint,
                http_client=self._http_client_cm,
                max_sse_event_size=self._config.max_result_bytes,
            )
            read_stream, write_stream = await self._transport_cm.__aenter__()
            self._session_cm = ClientSession(read_stream, write_stream)
            self._session = await self._session_cm.__aenter__()
            await asyncio.wait_for(
                self._session.initialize(),
                timeout=self._config.request_timeout_seconds,
            )
            await self.refresh_tools()
            return self
        except BaseException as exc:
            await asyncio.shield(self._close_safely())
            if isinstance(exc, (MCPIntegrationError, asyncio.CancelledError)):
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
        if self._http_client_cm is not None:
            with suppress(Exception):
                await self._http_client_cm.__aexit__(None, None, None)
            self._http_client_cm = None
        self._session = None
        self._tools = {}

    async def _write_audit(
        self,
        *,
        request_id: str,
        tool_name: str,
        outcome: str,
        started_at: float,
        error_code: str | None = None,
        execution_may_have_completed: bool = False,
    ) -> None:
        event = make_audit_event(
            request_id=request_id,
            actor_id=self._actor_id,
            tool_name=tool_name,
            outcome=outcome,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            error_code=error_code,
        )
        try:
            await self._audit.write(event)
        except Exception as exc:
            raise AuditUnavailable(
                "Durable MCP audit write failed; do not retry blindly",
                execution_may_have_completed=execution_may_have_completed,
            ) from exc

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

        request_id = str(uuid.uuid4())
        started_at = time.monotonic()
        await self._write_audit(
            request_id=request_id,
            tool_name=name,
            outcome="STARTED",
            started_at=started_at,
        )
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, arguments=dict(arguments)),
                timeout=self._config.request_timeout_seconds,
            )
            payload = _plain(result)
            encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
            if len(encoded) > self._config.max_result_bytes:
                await self._write_audit(
                    request_id=request_id,
                    tool_name=name,
                    outcome="REJECTED_OVERSIZE",
                    started_at=started_at,
                    error_code="RESULT_LIMIT_EXCEEDED",
                    execution_may_have_completed=True,
                )
                raise MCPIntegrationError("MCP tool response exceeded configured size limit")
            if getattr(result, "is_error", getattr(result, "isError", False)):
                await self._write_audit(
                    request_id=request_id,
                    tool_name=name,
                    outcome="FAILED",
                    started_at=started_at,
                    error_code="REMOTE_TOOL_ERROR",
                    execution_may_have_completed=True,
                )
                raise MCPIntegrationError("IM19 tool returned an error")
            await self._write_audit(
                request_id=request_id,
                tool_name=name,
                outcome="SUCCEEDED",
                started_at=started_at,
                execution_may_have_completed=True,
            )
            return {
                "server": "im19",
                "tool": name,
                "request_id": request_id,
                "status": "success",
                "result": payload,
            }
        except (MCPIntegrationError, AuditUnavailable):
            raise
        except asyncio.CancelledError:
            try:
                await asyncio.shield(self._write_audit(
                    request_id=request_id,
                    tool_name=name,
                    outcome="CANCELLED_UNCERTAIN",
                    started_at=started_at,
                    error_code="CALL_CANCELLED",
                    execution_may_have_completed=True,
                ))
            except AuditUnavailable:
                logger.warning("ugai_mcp_cancel_audit_failed")
            raise
        except Exception as exc:
            await self._write_audit(
                request_id=request_id,
                tool_name=name,
                outcome="FAILED",
                started_at=started_at,
                error_code="REMOTE_CALL_FAILED",
                execution_may_have_completed=True,
            )
            raise MCPUnavailable("IM19 tool execution failed; inspect audit before retry") from exc
