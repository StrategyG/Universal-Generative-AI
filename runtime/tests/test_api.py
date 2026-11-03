from fastapi.testclient import TestClient

from ugai_rag.api import create_app
from ugai_rag.settings import Settings


class FakeAdapter:
    async def retrieve(self, query, limit, request_id):
        from ugai_rag.contracts import RetrievalResult

        return RetrievalResult.model_validate(
            {
                "request_id": str(request_id),
                "status": "no_evidence",
                "retrieval": {
                    "strategy": "approved_keyword",
                    "corpora": ["institutional_approved"],
                    "candidate_count": 0,
                },
                "evidence": [],
                "warnings": ["No eligible evidence was returned"],
            }
        )


def test_retrieve_requires_service_authentication():
    settings = Settings(api_bearer_token="z" * 40)
    client = TestClient(create_app(settings, FakeAdapter()))
    response = client.post("/v1/knowledge/retrieve", json={"query": "test"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_retrieve_rejects_private_staging_scope():
    settings = Settings(api_bearer_token="z" * 40)
    client = TestClient(create_app(settings, FakeAdapter()))
    response = client.post(
        "/v1/knowledge/retrieve",
        headers={"Authorization": f"Bearer {'z' * 40}"},
        json={"query": "test", "scope": {"corpus": ["private_notebook"]}},
    )
    assert response.status_code == 422


def test_retrieve_returns_explicit_no_evidence_state():
    settings = Settings(api_bearer_token="z" * 40)
    client = TestClient(create_app(settings, FakeAdapter()))
    response = client.post(
        "/v1/knowledge/retrieve",
        headers={"Authorization": f"Bearer {'z' * 40}"},
        json={"query": "test"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_evidence"


def test_invalid_request_uses_stable_error_envelope():
    settings = Settings(api_bearer_token="z" * 40)
    client = TestClient(create_app(settings, FakeAdapter()))
    response = client.post(
        "/v1/knowledge/retrieve",
        headers={"Authorization": f"Bearer {'z' * 40}"},
        json={"query": "   "},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "detail" not in response.json()
