from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from ugai_rag.adapter import (
    IntegrationDisabled,
    InstitutionalRagAdapter,
    ReleaseGateBlocked,
    RetrievalContractError,
)
from ugai_rag.settings import Settings


def valid_payload(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "status": "evidence_found",
        "retrieval": {
            "strategy": "approved_keyword",
            "corpora": ["institutional_approved"],
            "candidate_count": 1,
        },
        "evidence": [
            {
                "evidence_id": "chunk-1",
                "corpus_id": "institutional_approved",
                "source_id": "doc-1",
                "chunk_id": "chunk-1",
                "source_title": "Approved source",
                "source_hash": "a" * 64,
                "locator": {
                    "locator_type": "pdf_page",
                    "page_start": 3,
                    "page_end": 3,
                },
                "excerpt": "Evidence excerpt",
                "retrieval_method": "keyword",
                "relevance_score": 0.91,
                "rank": 1,
                "evidence_tier": "approved",
                "review_status": "approved",
                "publication_state": "published",
                "trusted": True,
                "user_citation_eligible": True,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "warnings": [],
    }


def make_settings(**overrides) -> Settings:
    values = {
        "api_bearer_token": "x" * 40,
        "institutional_gateway_url": "https://project.example/functions/v1/ugai-institutional-retrieve",
        "institutional_service_key": "y" * 48,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_retrieve_sends_only_institutional_scope_and_validates_result():
    request_id = uuid4()
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["body"] = await request.aread()
        return httpx.Response(200, json=valid_payload(str(request_id)))

    adapter = InstitutionalRagAdapter(
        make_settings(), transport=httpx.MockTransport(handler)
    )
    result = await adapter.retrieve("policy risk", 5, request_id)

    assert result.request_id == str(request_id)
    assert result.evidence[0].trusted is True
    assert seen["headers"]["x-ugai-service-key"] == "y" * 48
    assert b'"institutional_approved"' in seen["body"]
    assert b"private_notebook" not in seen["body"]


@pytest.mark.asyncio
async def test_missing_gateway_configuration_fails_closed():
    adapter = InstitutionalRagAdapter(
        make_settings(institutional_gateway_url="", institutional_service_key="")
    )
    with pytest.raises(IntegrationDisabled):
        await adapter.retrieve("test", 5, uuid4())


@pytest.mark.asyncio
async def test_release_gate_no_go_blocks_retrieval():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"code": "RELEASE_GATE_NO_GO", "message": "not ready"}},
        )

    adapter = InstitutionalRagAdapter(
        make_settings(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ReleaseGateBlocked):
        await adapter.retrieve("test", 5, uuid4())


@pytest.mark.asyncio
async def test_response_request_id_must_match():
    request_id = uuid4()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=valid_payload(str(uuid4())))

    adapter = InstitutionalRagAdapter(
        make_settings(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RetrievalContractError):
        await adapter.retrieve("test", 5, request_id)


@pytest.mark.asyncio
async def test_forged_approved_evidence_is_rejected():
    request_id = uuid4()
    payload = valid_payload(str(request_id))
    payload["evidence"][0]["trusted"] = False

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter = InstitutionalRagAdapter(
        make_settings(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RetrievalContractError):
        await adapter.retrieve("test", 5, request_id)
