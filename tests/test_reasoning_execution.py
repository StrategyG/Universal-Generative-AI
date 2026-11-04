from __future__ import annotations

import asyncio

import pytest

from app.ai_schemas import AICompletionRequest
from app.providers.router import TextModelRouter
from app.providers.text_base import TextModelCapabilities
from app.providers.text_errors import TextGenerationProviderError
from app.reasoning.execution import (
    PolicyRoutedTextExecutor,
    ReasoningEvaluatorUnavailable,
    ReasoningRouteConfigurationError,
)
from app.reasoning.routing import ModelRouteDescriptor, RoutingRequirements


class FakeProvider:
    capabilities = TextModelCapabilities(streaming=False)

    def __init__(self, name: str, *, error: Exception | None = None, content: str = "grounded answer"):
        self.name = name
        self.model = f"{name}-model"
        self.model_id = f"{name}-model-id"
        self.model_revision = "sha256:" + (name[0] * 64)
        self.error = error
        self.content = content
        self.calls = 0
        self.requests: list[AICompletionRequest] = []

    async def generate(self, request: AICompletionRequest) -> dict:
        self.calls += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return {
            "provider": self.name,
            "model": self.model,
            "domain": request.domain,
            "quality_mode": request.quality_mode,
            "final_content": self.content,
            "review_type": "none",
            "verified": False,
            "usage": {},
        }

    async def list_models(self) -> list[str]:
        return [self.model]

    async def stream(self, _request):
        yield "token"


def route(route_id: str, role: str, provider: FakeProvider, family: str, quality: int = 90):
    return ModelRouteDescriptor(
        route_id=route_id,
        role=role,
        provider=provider.name,
        model_id=provider.model_id,
        model_revision=provider.model_revision,
        model_family=family,
        capabilities={"text"},
        data_regions={"ap-southeast-1"},
        max_context_tokens=64_000,
        quality_rank=quality,
        estimated_input_cost_per_million=1.0,
        estimated_output_cost_per_million=2.0,
        approved=True,
        enabled=True,
    )


def request() -> AICompletionRequest:
    return AICompletionRequest(
        project_id="project-1",
        domain="coding",
        objective="Assess the requested change",
        context="Evidence summary supplied by the authorized caller.",
        quality_mode="single",
    )


def requirements(risk: str = "moderate") -> RoutingRequirements:
    return RoutingRequirements(
        risk_tier=risk,
        profile="deep",
        required_capabilities={"text"},
        permitted_data_regions={"ap-southeast-1"},
        estimated_input_tokens=4_000,
        max_output_tokens=2_000,
        max_estimated_cost=1.0,
    )


def test_executor_uses_exact_primary_without_implicit_fallback():
    primary = FakeProvider("primary")
    fallback = FakeProvider("fallback")
    executor = PolicyRoutedTextExecutor(
        router=TextModelRouter([primary, fallback]),
        routes=[
            route("primary-route", "reasoning_primary", primary, "family-a", 95),
            route("fallback-route", "reasoning_fallback", fallback, "family-b", 85),
        ],
    )

    result = asyncio.run(executor.execute(request=request(), requirements=requirements()))

    assert primary.calls == 1
    assert fallback.calls == 0
    assert result.fallback_used is False
    assert result.completion.routing["policy_selected"] is True
    assert result.completion.routing["route_id"] == "primary-route"
    assert result.independent_evaluation is None


def test_executor_uses_explicit_fallback_and_independent_evaluator():
    primary = FakeProvider(
        "primary",
        error=TextGenerationProviderError("unavailable", code="provider_unavailable"),
    )
    fallback = FakeProvider("fallback", content="fallback answer")
    evaluator = FakeProvider("evaluator", content="No critical contradiction found.")
    executor = PolicyRoutedTextExecutor(
        router=TextModelRouter([primary, fallback, evaluator]),
        routes=[
            route("primary-route", "reasoning_primary", primary, "family-a", 95),
            route("fallback-route", "reasoning_fallback", fallback, "family-b", 90),
            route("evaluator-route", "independent_evaluator", evaluator, "family-c", 88),
        ],
    )

    result = asyncio.run(executor.execute(request=request(), requirements=requirements("high")))

    assert primary.calls == 1
    assert fallback.calls == 1
    assert evaluator.calls == 1
    assert result.fallback_used is True
    assert result.execution_route.route_id == "fallback-route"
    assert result.completion.final_content == "fallback answer"
    assert result.completion.routing["fallback_used"] is True
    assert result.independent_evaluation is not None
    assert "candidate answer" in evaluator.requests[0].objective.lower()
    assert "fallback answer" in evaluator.requests[0].context


def test_required_evaluator_failure_blocks_acceptance():
    primary = FakeProvider("primary")
    evaluator = FakeProvider(
        "evaluator",
        error=TextGenerationProviderError("review unavailable", code="provider_unavailable"),
    )
    executor = PolicyRoutedTextExecutor(
        router=TextModelRouter([primary, evaluator]),
        routes=[
            route("primary-route", "reasoning_primary", primary, "family-a", 95),
            route("evaluator-route", "independent_evaluator", evaluator, "family-b", 90),
        ],
    )

    with pytest.raises(ReasoningEvaluatorUnavailable):
        asyncio.run(executor.execute(request=request(), requirements=requirements("critical")))

    assert primary.calls == 1
    assert evaluator.calls == 1


def test_executor_rejects_provider_identity_drift_before_inference():
    provider = FakeProvider("primary")
    route_config = route("primary-route", "reasoning_primary", provider, "family-a")
    route_config = route_config.model_copy(update={"model_revision": "sha256:" + "f" * 64})

    with pytest.raises(ReasoningRouteConfigurationError):
        PolicyRoutedTextExecutor(
            router=TextModelRouter([provider]),
            routes=[route_config],
        )
