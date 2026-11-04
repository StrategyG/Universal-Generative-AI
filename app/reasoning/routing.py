from __future__ import annotations

from pydantic import FiniteFloat, Field

from app.reasoning.schemas import (
    ModelRole,
    ReasoningProfile,
    RiskTier,
    StrictContract,
)


class ModelRouteDescriptor(StrictContract):
    route_id: str = Field(min_length=1, max_length=120)
    role: ModelRole
    provider: str = Field(min_length=1, max_length=120)
    model_id: str = Field(min_length=1, max_length=200)
    model_revision: str = Field(min_length=1, max_length=200)
    model_family: str = Field(min_length=1, max_length=120)
    capabilities: set[str] = Field(default_factory=set, max_length=32)
    data_regions: set[str] = Field(default_factory=set, max_length=32)
    max_context_tokens: int = Field(ge=1)
    quality_rank: int = Field(ge=1, le=100)
    estimated_input_cost_per_million: FiniteFloat = Field(ge=0.0)
    estimated_output_cost_per_million: FiniteFloat = Field(ge=0.0)
    approved: bool = False
    enabled: bool = False


class RoutingRequirements(StrictContract):
    risk_tier: RiskTier
    profile: ReasoningProfile = ReasoningProfile.STANDARD
    required_capabilities: set[str] = Field(default_factory=set, max_length=32)
    permitted_data_regions: set[str] = Field(min_length=1, max_length=32)
    estimated_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=1)
    max_estimated_cost: FiniteFloat = Field(gt=0.0)


class RoutingDecision(StrictContract):
    primary: ModelRouteDescriptor
    fallback: ModelRouteDescriptor | None = None
    independent_evaluator: ModelRouteDescriptor | None = None
    estimated_total_cost: FiniteFloat = Field(ge=0.0)
    evaluator_required: bool


class NoEligibleModelRoute(ValueError):
    """Raised when policy cannot safely select the required model roles."""


def _estimated_cost(route: ModelRouteDescriptor, requirements: RoutingRequirements) -> float:
    return (
        requirements.estimated_input_tokens * route.estimated_input_cost_per_million
        + requirements.max_output_tokens * route.estimated_output_cost_per_million
    ) / 1_000_000


def _minimum_quality(profile: ReasoningProfile) -> int:
    return {
        ReasoningProfile.STANDARD: 50,
        ReasoningProfile.DEEP: 75,
        ReasoningProfile.CRITICAL: 90,
    }[profile]


def _eligible(
    route: ModelRouteDescriptor,
    requirements: RoutingRequirements,
) -> bool:
    return (
        route.approved
        and route.enabled
        and route.quality_rank >= _minimum_quality(requirements.profile)
        and route.max_context_tokens
        >= requirements.estimated_input_tokens + requirements.max_output_tokens
        and requirements.required_capabilities.issubset(route.capabilities)
        and bool(requirements.permitted_data_regions.intersection(route.data_regions))
    )


def select_model_routes(
    routes: list[ModelRouteDescriptor],
    requirements: RoutingRequirements,
) -> RoutingDecision:
    """Select approved hybrid routes deterministically; never invent a provider fallback."""
    eligible = [route for route in routes if _eligible(route, requirements)]
    evaluator_required = (
        requirements.risk_tier in {RiskTier.HIGH, RiskTier.CRITICAL}
        or requirements.profile == ReasoningProfile.CRITICAL
    )

    primary_candidates = [
        route for route in eligible if route.role == ModelRole.REASONING_PRIMARY
    ]
    if not primary_candidates:
        raise NoEligibleModelRoute("No approved reasoning_primary route meets policy")

    decisions: list[
        tuple[
            ModelRouteDescriptor,
            ModelRouteDescriptor | None,
            ModelRouteDescriptor | None,
            float,
        ]
    ] = []
    for primary in primary_candidates:
        primary_cost = _estimated_cost(primary, requirements)
        if primary_cost > requirements.max_estimated_cost:
            continue

        fallback_candidates = [
            route for route in eligible
            if route.role == ModelRole.REASONING_FALLBACK
            and route.route_id != primary.route_id
            and _estimated_cost(route, requirements) <= requirements.max_estimated_cost
        ]
        fallback = sorted(
            fallback_candidates,
            key=lambda route: (
                -route.quality_rank,
                _estimated_cost(route, requirements),
                route.route_id,
            ),
        )[0] if fallback_candidates else None

        if evaluator_required:
            evaluator_candidates = [
                route for route in eligible
                if route.role == ModelRole.INDEPENDENT_EVALUATOR
                and route.provider != primary.provider
                and route.model_family != primary.model_family
            ]
        else:
            evaluator_candidates = [None]

        for evaluator in evaluator_candidates:
            cost = primary_cost + (
                _estimated_cost(evaluator, requirements) if evaluator else 0.0
            )
            if cost <= requirements.max_estimated_cost:
                decisions.append((primary, fallback, evaluator, cost))

    if not decisions:
        if evaluator_required:
            raise NoEligibleModelRoute(
                "No independent evaluator from a different provider and model family "
                "meets the risk, capability, region and cost policy"
            )
        raise NoEligibleModelRoute("No reasoning route meets the configured cost and policy limits")

    # Quality is operator-assessed and registry-controlled; cost breaks quality ties.
    primary, fallback, evaluator, cost = sorted(
        decisions,
        key=lambda item: (
            -item[0].quality_rank,
            item[3],
            -(item[2].quality_rank if item[2] else 0),
            item[0].route_id,
        ),
    )[0]
    return RoutingDecision(
        primary=primary,
        fallback=fallback,
        independent_evaluator=evaluator,
        estimated_total_cost=cost,
        evaluator_required=evaluator_required,
    )
