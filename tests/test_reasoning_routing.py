import pytest

from app.reasoning.routing import (
    ModelRouteDescriptor,
    NoEligibleModelRoute,
    RoutingRequirements,
    select_model_routes,
)


def route(route_id, role, provider, family, quality=90, input_cost=1.0, output_cost=2.0):
    return ModelRouteDescriptor(
        route_id=route_id,
        role=role,
        provider=provider,
        model_id=f"{route_id}-model",
        model_revision="sha256:" + "a" * 64,
        model_family=family,
        capabilities={"text", "structured_output"},
        data_regions={"ap-southeast-1"},
        max_context_tokens=64000,
        quality_rank=quality,
        estimated_input_cost_per_million=input_cost,
        estimated_output_cost_per_million=output_cost,
        approved=True,
        enabled=True,
    )


def requirements(risk="moderate"):
    return RoutingRequirements(
        risk_tier=risk,
        profile="deep",
        required_capabilities={"text"},
        permitted_data_regions={"ap-southeast-1"},
        estimated_input_tokens=4000,
        max_output_tokens=2000,
        max_estimated_cost=1.0,
    )


def test_selects_highest_quality_approved_primary_and_explicit_fallback():
    primary = route("primary", "reasoning_primary", "provider-a", "family-a", 95)
    lower = route("lower", "reasoning_primary", "provider-b", "family-b", 80)
    fallback = route("fallback", "reasoning_fallback", "provider-c", "family-c", 85)

    decision = select_model_routes([lower, fallback, primary], requirements())

    assert decision.primary.route_id == "primary"
    assert decision.fallback.route_id == "fallback"
    assert decision.independent_evaluator is None
    assert decision.evaluator_required is False


def test_high_risk_requires_independent_provider_and_model_family():
    primary = route("primary", "reasoning_primary", "provider-a", "family-a")
    same_provider = route("eval-same-provider", "independent_evaluator", "provider-a", "family-b")

    with pytest.raises(NoEligibleModelRoute):
        select_model_routes([primary, same_provider], requirements("high"))

    evaluator = route("evaluator", "independent_evaluator", "provider-b", "family-b", 88)
    decision = select_model_routes([primary, evaluator], requirements("high"))

    assert decision.independent_evaluator.route_id == "evaluator"
    assert decision.evaluator_required is True


def test_unapproved_or_wrong_region_routes_are_never_selected():
    candidate = route("primary", "reasoning_primary", "provider-a", "family-a")
    candidate = candidate.model_copy(update={"approved": False})

    with pytest.raises(NoEligibleModelRoute):
        select_model_routes([candidate], requirements())


def test_cost_budget_failure_fails_closed():
    expensive = route("primary", "reasoning_primary", "provider-a", "family-a", input_cost=1000)
    req = requirements().model_copy(update={"max_estimated_cost": 0.001})

    with pytest.raises(NoEligibleModelRoute):
        select_model_routes([expensive], req)


def test_uses_lower_ranked_evaluator_when_best_route_exceeds_budget():
    primary = route("primary", "reasoning_primary", "provider-a", "family-a", 95)
    too_expensive = route(
        "evaluator-expensive",
        "independent_evaluator",
        "provider-b",
        "family-b",
        99,
        input_cost=200000,
        output_cost=200000,
    )
    affordable = route(
        "evaluator-affordable",
        "independent_evaluator",
        "provider-c",
        "family-c",
        80,
    )

    decision = select_model_routes(
        [primary, too_expensive, affordable],
        requirements("critical"),
    )

    assert decision.independent_evaluator.route_id == "evaluator-affordable"


def test_critical_profile_requires_quality_floor_and_independent_evaluator():
    primary = route("primary", "reasoning_primary", "provider-a", "family-a", 95)
    evaluator = route("evaluator", "independent_evaluator", "provider-b", "family-b", 92)
    req = requirements("moderate").model_copy(update={"profile": "critical"})

    decision = select_model_routes([primary, evaluator], req)

    assert decision.evaluator_required is True
    assert decision.independent_evaluator.route_id == "evaluator"

    low_quality_primary = primary.model_copy(update={"quality_rank": 89})
    with pytest.raises(NoEligibleModelRoute):
        select_model_routes([low_quality_primary, evaluator], req)
