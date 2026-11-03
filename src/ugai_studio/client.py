"""Authenticated, bounded client for the AI Notebook Studio execution API."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx


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


class StudioExecutionClient:
    """UGAI-side adapter; it never sends raw notebook source or provider secrets."""

    def __init__(
        self,
        *,
        base_url: str,
        resource: str,
        token_provider: StudioTokenProvider,
        timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Studio execution URL must be an HTTPS origin")
        if not resource or len(resource) > 255:
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
        if not actor_id or len(actor_id) > 255:
            raise ValueError("A trusted actor identity is required")
        token = await self._tokens.get_access_token(
            resource=self._resource,
            scopes=("studio:execution:write",),
            actor_id=actor_id,
            tenant_id=tenant_id,
        )
        if not token or any(ch.isspace() for ch in token):
            raise StudioUnavailable("Token provider returned an invalid service token")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": str(request_id),
            "Accept": "application/json",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = str(idempotency_key)
        return headers

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
        payload = {
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
            response = await self._http.post(
                f"{self._base_url}/api/v1/internal/executions",
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            body = response.json()
            receipt = ExecutionReceipt(
                execution_id=UUID(body["execution_id"]),
                task_id=UUID(body["task_id"]),
                state=str(body["state"]),
            )
            if receipt.task_id != request.task_id:
                raise ValueError("Studio returned a receipt for a different task")
            return receipt
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise StudioUnavailable(
                "Studio execution submission failed or returned an invalid receipt; reconcile before retry"
            ) from exc

    async def get_status(
        self, execution_id: UUID, *, actor_id: str, tenant_id: UUID, request_id: UUID
    ) -> dict[str, object]:
        headers = await self._headers(
            actor_id=actor_id, tenant_id=tenant_id, request_id=request_id
        )
        try:
            response = await self._http.get(
                f"{self._base_url}/api/v1/internal/executions/{execution_id}",
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or body.get("execution_id") != str(execution_id):
                raise ValueError("Invalid execution status response")
            return body
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise StudioUnavailable("Studio execution status request failed") from exc

    async def cancel(
        self, execution_id: UUID, *, actor_id: str, tenant_id: UUID, request_id: UUID
    ) -> dict[str, object]:
        headers = await self._headers(
            actor_id=actor_id, tenant_id=tenant_id, request_id=request_id
        )
        try:
            response = await self._http.post(
                f"{self._base_url}/api/v1/internal/executions/{execution_id}/cancel",
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or body.get("execution_id") != str(execution_id):
                raise ValueError("Invalid cancellation response")
            return body
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise StudioUnavailable("Studio cancellation request failed") from exc
