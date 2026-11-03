"""Authenticated, bounded client for the AI Notebook Studio execution API."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx


MAX_RESPONSE_BYTES = 65_536
MAX_BEARER_TOKEN_LENGTH = 8_192
EXECUTION_STATES = frozenset(
    {
        "ACCEPTED",
        "QUEUED",
        "CREATED",
        "PLANNED",
        "ASSIGNED",
        "RUNNING",
        "WAITING",
        "BLOCKED",
        "REVIEW",
        "VALIDATION",
        "APPROVAL",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "EXPIRED",
    }
)


class StudioExecutionError(RuntimeError):
    """Base error for Studio execution integration failures."""


class StudioUnavailable(StudioExecutionError):
    """Studio could not be reached or returned an invalid response."""


class StudioTokenProvider(Protocol):
    async def get_access_token(
        self, *, resource: str, scopes: tuple[str, ...], actor_id: str, tenant_id: UUID
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    cpu_millis: int = 1000
    memory_mib: int = 1024
    wall_time_seconds: int = 300
    output_bytes: int = 1_048_576

    def validate(self) -> None:
        if not 100 <= self.cpu_millis <= 8000:
            raise ValueError("cpu_millis outside permitted bounds")
        if not 128 <= self.memory_mib <= 8192:
            raise ValueError("memory_mib outside permitted bounds")
        if not 1 <= self.wall_time_seconds <= 1800:
            raise ValueError("wall_time_seconds outside permitted bounds")
        if not 1024 <= self.output_bytes <= 10_485_760:
            raise ValueError("output_bytes outside permitted bounds")


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    task_id: UUID
    notebook_id: UUID
    source_sha256: str
    runtime_profile: str
    limits: ExecutionLimits = ExecutionLimits()

    def validate(self) -> None:
        if not re.fullmatch(r"[a-fA-F0-9]{64}", self.source_sha256):
            raise ValueError("source_sha256 must be a SHA-256 digest")
        if self.runtime_profile not in {"python-3.11", "python-3.12"}:
            raise ValueError("runtime_profile is not approved")
        self.limits.validate()


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    execution_id: UUID
    task_id: UUID
    state: str


async def _read_json_object(response: httpx.Response) -> dict[str, object]:
    """Read a bounded JSON response; reject redirects, HTML and oversized bodies."""
    response.raise_for_status()
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise ValueError("Studio response content type is not JSON")

    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise ValueError("Studio response has an invalid content length") from exc
        if declared_size < 0 or declared_size > MAX_RESPONSE_BYTES:
            raise ValueError("Studio response exceeds the permitted size")

    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
            raise ValueError("Studio response exceeds the permitted size")
        body.extend(chunk)

    payload = httpx.Response(200, content=bytes(body)).json()
    if not isinstance(payload, dict):
        raise TypeError("Studio response must be a JSON object")
    return payload


def _validate_execution_state(value: object) -> str:
    if not isinstance(value, str) or value not in EXECUTION_STATES:
        raise ValueError("Studio returned an unknown execution state")
    return value


class StudioExecutionClient:
    """UGAI-side adapter; it never sends raw notebook source or provider secrets.

    Responses are size-limited and state-validated. A submission failure is
    treated as uncertain: callers must reconcile with the same idempotency key
    rather than issue a new submission blindly.
    """

    def __init__(
        self,
        *,
        base_url: str,
        resource: str,
        token_provider: StudioTokenProvider,
        timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        try:
            parsed = urlparse(base_url)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Studio execution URL must be a valid HTTPS origin") from exc
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Studio execution URL must be an HTTPS origin")
        if not resource or len(resource) > 255 or any(ch.isspace() for ch in resource):
            raise ValueError("A bounded Studio resource identifier is required")
        if not 0 < timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between 0 and 60")
        self._base_url = base_url.rstrip("/")
        self._resource = resource
        self._tokens = token_provider
        self._timeout = timeout_seconds
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_http = http_client is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _headers(
        self,
        *,
        actor_id: str,
        tenant_id: UUID,
        request_id: UUID,
        idempotency_key: UUID | None = None,
    ) -> dict[str, str]:
        if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 255:
            raise ValueError("A trusted actor identity is required")
        token = await self._tokens.get_access_token(
            resource=self._resource,
            scopes=("studio:execution:write",),
            actor_id=actor_id,
            tenant_id=tenant_id,
        )
        if (
            not isinstance(token, str)
            or not token
            or len(token) > MAX_BEARER_TOKEN_LENGTH
            or any(ord(ch) < 33 or ord(ch) == 127 for ch in token)
        ):
            raise StudioUnavailable("Token provider returned an invalid service token")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": str(request_id),
            "Accept": "application/json",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = str(idempotency_key)
        return headers

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        async with self._http.stream(
            method,
            f"{self._base_url}{path}",
            headers=headers,
            json=payload,
            timeout=self._timeout,
        ) as response:
            return await _read_json_object(response)

    async def submit(
        self,
        request: ExecutionRequest,
        *,
        actor_id: str,
        tenant_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> ExecutionReceipt:
        request.validate()
        headers = await self._headers(
            actor_id=actor_id,
            tenant_id=tenant_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        payload: dict[str, object] = {
            "task_id": str(request.task_id),
            "notebook_id": str(request.notebook_id),
            "source_sha256": request.source_sha256.lower(),
            "runtime_profile": request.runtime_profile,
            "limits": {
                "cpu_millis": request.limits.cpu_millis,
                "memory_mib": request.limits.memory_mib,
                "wall_time_seconds": request.limits.wall_time_seconds,
                "output_bytes": request.limits.output_bytes,
            },
        }
        try:
            body = await self._request_json(
                "POST", "/api/v1/internal/executions", headers=headers, payload=payload
            )
            receipt = ExecutionReceipt(
                execution_id=UUID(str(body["execution_id"])),
                task_id=UUID(str(body["task_id"])),
                state=_validate_execution_state(body["state"]),
            )
            if receipt.task_id != request.task_id:
                raise ValueError("Studio returned a receipt for a different task")
            return receipt
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise StudioUnavailable(
                "Studio execution submission failed or returned an invalid receipt; "
                "reconcile before retry"
            ) from exc

    async def get_status(
        self, execution_id: UUID, *, actor_id: str, tenant_id: UUID, request_id: UUID
    ) -> dict[str, object]:
        headers = await self._headers(
            actor_id=actor_id, tenant_id=tenant_id, request_id=request_id
        )
        try:
            body = await self._request_json(
                "GET", f"/api/v1/internal/executions/{execution_id}", headers=headers
            )
            if body.get("execution_id") != str(execution_id):
                raise ValueError("Invalid execution status response")
            _validate_execution_state(body.get("state"))
            return body
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise StudioUnavailable("Studio execution status request failed") from exc

    async def cancel(
        self, execution_id: UUID, *, actor_id: str, tenant_id: UUID, request_id: UUID
    ) -> dict[str, object]:
        headers = await self._headers(
            actor_id=actor_id, tenant_id=tenant_id, request_id=request_id
        )
        try:
            body = await self._request_json(
                "POST",
                f"/api/v1/internal/executions/{execution_id}/cancel",
                headers=headers,
            )
            if body.get("execution_id") != str(execution_id):
                raise ValueError("Invalid cancellation response")
            _validate_execution_state(body.get("state"))
            return body
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise StudioUnavailable("Studio cancellation request failed") from exc
