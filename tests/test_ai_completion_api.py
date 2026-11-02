from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_ai_completion_endpoint_uses_domain_provider(monkeypatch):
    from app.ai_schemas import GenerationQualityMode
    from app.config import settings

    class FakeProvider:
        async def generate(self, request):
            assert request.domain.value == "film"
            assert request.quality_mode == GenerationQualityMode.RIGOROUS
            return {
                "provider": "test-provider",
                "model": "test-model",
                "domain": request.domain,
                "quality_mode": request.quality_mode,
                "draft": "draft",
                "critique": "critique",
                "final_content": "revised screenplay",
                "review_type": "same_model_critique_and_revision",
                "verified": False,
                "usage": {"total_tokens": 30},
            }

    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "model_registry_enforcement", False)
    class FakeRouter:
        providers = []

        async def generate(self, request):
            return await FakeProvider().generate(request)

    monkeypatch.setattr("app.main.TextModelRouter.from_settings", lambda: FakeRouter())
    response = client.post("/api/v1/ai/complete", json={
        "project_id": "local-project",
        "domain": "film",
        "objective": "Write an animated short screenplay",
        "quality_mode": "rigorous",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["final_content"] == "revised screenplay"
    assert body["verified"] is False
    assert body["review_type"] == "same_model_critique_and_revision"


def test_ai_completion_endpoint_fails_closed_when_provider_unconfigured(monkeypatch):
    from app.config import settings
    from app.providers.openai_compatible_text import TextGenerationProviderError

    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "model_registry_enforcement", False)

    def disabled():
        raise TextGenerationProviderError("Text generation is disabled")

    monkeypatch.setattr("app.main.TextModelRouter.from_settings", disabled)
    response = client.post("/api/v1/ai/complete", json={
        "project_id": "local-project",
        "domain": "coding",
        "objective": "Design a REST API",
    })
    assert response.status_code == 503
