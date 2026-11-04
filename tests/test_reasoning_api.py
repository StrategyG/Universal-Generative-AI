from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth import Principal
from app.reasoning.api import (
    ReasoningCompletionRequest,
    complete_reasoning,
)
from app.reasoning.routing import ModelRouteDescriptor
from app.reasoning.schemas import ModelRole, RiskTier, ReasoningProfile, VerificationStatus
from app.ai_schemas import AICompletionResponse


def principal(*, roles=frozenset({"developer"}), project_ids=frozenset({"project-1"})):
    return Principal(
        subject="user-1",
        tenant_id="tenant-1",
        roles=roles,
        project_ids=project_ids,
        auth_mode="oidc",
    )


def route(role: ModelRole, route_id: str, provider: str, family: str):
    return ModelRouteDescriptor(
        route_id=route_id,
        role=role,
        provider=provider,
        model_id=f"{provider}-model",
        model_revision="a" * 40,
        model_family=family,
        capabilities={"text"},
        data_regions={"ap-southeast-1"},
        max_context_tokens=64_000,
        quality_rank=95,
        estimated_input_cost_per_million=1.0,
        estimated_output_cost_per_million=2.0,
        approved=True,
        enabled=True,
    )


def response(provider: str, content: str):
    return AICompletionResponse(
        provider=provider,
        model=f"{provider}-model",
        domain="coding",
        quality_mode="single",
        final_content=content,
        review_type="none",
        verified=False,
        usage={},
        routing={"selected_provider": provider},
    )


def request():
    return ReasoningCompletionRequest(
        project_id="project-1",
        domain="coding",
        objective="Analyze a proposed software change",
        context="Authorized context supplied by the caller.",
    )


def test_reasoning_endpoint_enforces_server_risk_and_independent_review(monkeypatch):
    primary = route(ModelRole.REASONING_PRIMARY, "primary", "provider-a", "family-a")
    evaluator = route(ModelRole.INDEPENDENT_EVALUATOR, "evaluator", "provider-b", "family-b")
    captured = {}

    class FakeExecutor:
        def __init__(self, *, router, routes):
            captured["router"] = router
            captured["routes"] = routes

        async def execute(self, *, request, requirements):
            captured["requirements"] = requirements
            captured["completion_request"] = request
            return SimpleNamespace(
                decision=SimpleNamespace(independent_evaluator=evaluator),
                execution_route=primary,
                completion=response("provider-a", "Candidate answer"),
                independent_evaluation=response("provider-b", "Independent critique"),
                fallback_used=False,
            )

    monkeypatch.setattr(
        "app.reasoning.api.TextModelRouter.from_settings",
        staticmethod(lambda: "fake-router"),
    )

    async def load_routes():
        return [primary, evaluator]

    monkeypatch.setattr("app.reasoning.api.load_approved_text_routes", load_routes)
    monkeypatch.setattr("app.reasoning.api.PolicyRoutedTextExecutor", FakeExecutor)

    result = asyncio.run(complete_reasoning(request(), principal()))

    assert captured["requirements"].risk_tier is RiskTier.HIGH
    assert captured["requirements"].profile is ReasoningProfile.DEEP
    assert captured["requirements"].required_capabilities == {"text"}
    assert result.candidate_answer == "Candidate answer"
    assert result.independent_review == "Independent critique"
    assert result.human_review_required is True
    assert result.verification_status is VerificationStatus.NEEDS_HUMAN_REVIEW
    assert result.tool_execution_performed is False
    assert result.evidence_grounding == "not_performed"


def test_reasoning_endpoint_rejects_project_outside_verified_principal(monkeypatch):
    async def must_not_load_routes():
        raise AssertionError("routing must not load before project authorization")

    monkeypatch.setattr("app.reasoning.api.load_approved_text_routes", must_not_load_routes)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            complete_reasoning(
                request(),
                principal(project_ids=frozenset({"another-project"})),
            )
        )
    assert caught.value.status_code == 403


def test_reasoning_endpoint_rejects_caller_supplied_risk_downgrade():
    with pytest.raises(ValueError):
        ReasoningCompletionRequest(
            project_id="project-1",
            domain="coding",
            objective="Run a privileged action",
            risk_tier="low",
        )


def test_reasoning_endpoint_rejects_missing_independent_review(monkeypatch):
    primary = route(ModelRole.REASONING_PRIMARY, "primary", "provider-a", "family-a")

    class FakeExecutor:
        def __init__(self, *, router, routes):
            pass

        async def execute(self, *, request, requirements):
            return SimpleNamespace(
                decision=SimpleNamespace(independent_evaluator=None),
                execution_route=primary,
                completion=response("provider-a", "Candidate answer"),
                independent_evaluation=None,
                fallback_used=False,
            )

    monkeypatch.setattr(
        "app.reasoning.api.TextModelRouter.from_settings",
        staticmethod(lambda: "fake-router"),
    )

    async def load_routes():
        return [primary]

    monkeypatch.setattr("app.reasoning.api.load_approved_text_routes", load_routes)
    monkeypatch.setattr("app.reasoning.api.PolicyRoutedTextExecutor", FakeExecutor)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(complete_reasoning(request(), principal()))
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "required_independent_review_missing"


def test_reasoning_endpoint_is_mounted_on_fastapi_app():
    from app.main import app

    # FastAPI's newer router implementation may expose lazy IncludedRouter
    # entries in app.routes; OpenAPI materializes the effective route table.
    paths = app.openapi()["paths"]
    assert "/api/v1/reasoning/complete" in paths
