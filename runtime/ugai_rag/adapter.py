from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError

from .contracts import RetrievalResult
from .settings import Settings


class RAGIntegrationError(RuntimeError):
    code = "RETRIEVAL_UNAVAILABLE"


class IntegrationDisabled(RAGIntegrationError):
    code = "INTEGRATION_DISABLED"


class ReleaseGateBlocked(RAGIntegrationError):
    code = "RELEASE_GATE_NO_GO"


class RetrievalAuthenticationError(RAGIntegrationError):
    code = "UPSTREAM_AUTH_FAILED"


class RetrievalContractError(RAGIntegrationError):
    code = "UPSTREAM_CONTRACT_INVALID"


class InstitutionalRagAdapter:
    """Calls only the dedicated fail-closed Supabase gateway."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def retrieve(self, query: str, limit: int, request_id: UUID) -> RetrievalResult:
        if not self._settings.gateway_configured:
            raise IntegrationDisabled("Institutional RAG gateway is not configured")
        if not query or len(query) > self._settings.max_query_chars:
            raise ValueError("query must contain 1-2000 characters")
        if not 1 <= limit <= 10:
            raise ValueError("limit must be between 1 and 10")

        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "x-ugai-service-key": self._settings.institutional_service_key,
        }
        payload = {
            "request_id": str(request_id),
            "query": query,
            "limit": limit,
            "scope": {"corpus": ["institutional_approved"]},
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.request_timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    self._settings.institutional_gateway_url,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise RAGIntegrationError("Institutional RAG gateway timed out") from exc
        except httpx.RequestError as exc:
            raise RAGIntegrationError("Institutional RAG gateway is unreachable") from exc

        if response.status_code in (401, 403):
            raise RetrievalAuthenticationError(
                "Institutional RAG gateway rejected service authentication"
            )
        if response.status_code == 503:
            try:
                body: Any = response.json()
            except ValueError:
                body = {}
            error = body.get("error", {}) if isinstance(body, dict) else {}
            if isinstance(error, dict) and error.get("code") == "RELEASE_GATE_NO_GO":
                raise ReleaseGateBlocked("Institutional RAG production release gate is not GO")
            raise RAGIntegrationError("Institutional RAG gateway is temporarily unavailable")
        if response.status_code < 200 or response.status_code >= 300:
            raise RAGIntegrationError(
                f"Institutional RAG gateway returned HTTP {response.status_code}"
            )

        try:
            result = RetrievalResult.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise RetrievalContractError(
                "Institutional RAG response failed contract validation"
            ) from exc
        if result.request_id != str(request_id):
            raise RetrievalContractError("Institutional RAG response request_id mismatch")
        return result
