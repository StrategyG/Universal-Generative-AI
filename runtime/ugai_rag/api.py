from __future__ import annotations

import hmac
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .adapter import (
    IntegrationDisabled,
    InstitutionalRagAdapter,
    RAGIntegrationError,
    ReleaseGateBlocked,
)
from .contracts import RetrievalResult
from .settings import Settings


class RetrievalScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corpus: list[str] = Field(
        default_factory=lambda: ["institutional_approved"], min_length=1, max_length=1
    )

    @field_validator("corpus")
    @classmethod
    def only_institutional_corpus(cls, value: list[str]) -> list[str]:
        if value != ["institutional_approved"]:
            raise ValueError("Only institutional_approved is available on this route")
        return value


class KnowledgeRetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    request_id: UUID = Field(default_factory=uuid4)
    scope: RetrievalScope = Field(default_factory=RetrievalScope)
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query cannot be blank")
        if len(normalized.encode("utf-8")) > 8000:
            raise ValueError("query exceeds the UTF-8 byte limit")
        return normalized


def create_app(
    settings: Settings | None = None,
    adapter: InstitutionalRagAdapter | None = None,
) -> FastAPI:
    configured = settings or Settings.from_env()
    rag = adapter or InstitutionalRagAdapter(configured)
    app = FastAPI(
        title="Universal Generative AI Runtime",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    async def require_service_token(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        expected = configured.api_bearer_token
        if not configured.api_auth_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "API_AUTH_NOT_CONFIGURED"},
            )
        supplied = authorization or ""
        if not hmac.compare_digest(supplied, f"Bearer {expected}"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "AUTH_REQUIRED"},
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"service": "ugai-runtime", "status": "alive"}

    @app.get("/readyz")
    async def readyz() -> dict:
        ready = configured.gateway_configured and configured.api_auth_configured
        return {
            "service": "ugai-runtime",
            "ready": ready,
            "institutional_rag_configured": configured.gateway_configured,
            "api_auth_configured": configured.api_auth_configured,
        }

    @app.post(
        "/v1/knowledge/retrieve",
        response_model=RetrievalResult,
        dependencies=[Depends(require_service_token)],
    )
    async def retrieve_knowledge(payload: KnowledgeRetrieveRequest) -> RetrievalResult:
        try:
            return await rag.retrieve(payload.query, payload.limit, payload.request_id)
        except ReleaseGateBlocked as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": exc.code,
                    "message": str(exc),
                    "request_id": str(payload.request_id),
                },
            ) from exc
        except IntegrationDisabled as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": exc.code,
                    "message": str(exc),
                    "request_id": str(payload.request_id),
                },
            ) from exc
        except RAGIntegrationError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": exc.code,
                    "message": str(exc),
                    "request_id": str(payload.request_id),
                },
            ) from exc

    return app


app = create_app()
