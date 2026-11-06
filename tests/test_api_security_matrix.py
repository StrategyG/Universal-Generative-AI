from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


client = TestClient(app)


@pytest.mark.security
@pytest.mark.parametrize(
    ("method", "path", "payload", "extra_headers"),
    [
        (
            "POST",
            "/api/v1/generate",
            {"task": "text_to_image", "prompt": "security test", "project_id": "project-a"},
            {},
        ),
        (
            "POST",
            "/api/v1/ai/complete",
            {"project_id": "project-a", "domain": "coding", "objective": "Review a change"},
            {},
        ),
        (
            "POST",
            "/api/v1/reasoning/complete",
            {"project_id": "project-a", "domain": "coding", "objective": "Review a change"},
            {},
        ),
        (
            "POST",
            "/api/v1/tasks",
            {
                "project_id": "project-a",
                "workspace_id": str(uuid4()),
                "intent": "Summarize a notebook",
                "context": "",
                "artifacts": [],
                "requested_capabilities": ["reasoning:read"],
            },
            {"Idempotency-Key": "security-test-001"},
        ),
        (
            "POST",
            "/api/v1/workflows/plan",
            {
                "project_id": "project-a",
                "domain": "coding",
                "title": "Security contract",
                "objective": "Validate authenticated access",
                "steps": [{"step_id": "review", "title": "Review", "action": "review"}],
            },
            {},
        ),
        ("GET", "/api/v1/jobs/nonexistent-job", None, {}),
        (
            "GET",
            f"/api/v1/workflows/plans/{uuid4()}",
            None,
            {},
        ),
    ],
    ids=[
        "generate",
        "ai-completion",
        "reasoning-completion",
        "durable-task-submit",
        "workflow-plan",
        "job-status",
        "workflow-plan-read",
    ],
)
def test_sensitive_user_routes_reject_missing_bearer_credentials(
    monkeypatch, method, path, payload, extra_headers
):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "oidc_issuer", "https://identity.example.test/")
    monkeypatch.setattr(settings, "oidc_audience", "universal-generative-ai")
    monkeypatch.setattr(
        settings,
        "oidc_jwks_url",
        "https://identity.example.test/.well-known/jwks.json",
    )

    response = client.request(
        method,
        path,
        json=payload,
        headers=extra_headers,
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.security
def test_oidc_claim_parser_rejects_non_string_tenant_and_role_shapes(monkeypatch):
    from app.auth import principal_from_claims

    monkeypatch.setattr(settings, "oidc_tenant_claim", "tenant_id")
    monkeypatch.setattr(settings, "oidc_roles_claim", "roles")
    monkeypatch.setattr(settings, "oidc_projects_claim", "project_ids")

    with pytest.raises(ValueError, match="Required tenant claim"):
        principal_from_claims(
            {"sub": "user-a", "tenant_id": ["tenant-a"], "roles": ["developer"]}
        )
    with pytest.raises(ValueError, match="must be a string or array of strings"):
        principal_from_claims(
            {
                "sub": "user-a",
                "tenant_id": "tenant-a",
                "roles": {"developer": True},
                "project_ids": ["project-a"],
            }
        )
