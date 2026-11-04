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
    """Select approved hybrid routes with a conservative worst-case cost budget.

    The budget reserves for a primary attempt, a fallback attempt, and an
    independent evaluation when configured. The evaluator must be independent
    from the route that may actually produce the final draft, including fallback.
    """
    eligible = [route for route in routes if _eligible(route, requirements)]
    if len({route.route_id for route in eligible}) != len(eligible):
        raise NoEligibleModelRoute("Model route IDs must be unique")

    evaluator_required = (
        requirements.risk_tier in {RiskTier.HIGH, RiskTier.CRITICAL}
        or requirements.profile == ReasoningProfile.CRITICAL
    )

    primary_candidates = [
        route for route in eligible if route.role == ModelRole.REASONING_PRIMARY
    ]
    if not primary_candidates:
        raise NoEligibleModelRoute("No approved reasoning_primary route meets policy")

    fallback_candidates: list[ModelRouteDescriptor | None] = [None]
    fallback_candidates.extend(
        route for route in eligible if route.role == ModelRole.REASONING_FALLBACK
    )
    evaluator_candidates: list[ModelRouteDescriptor | None] = (
        [
            route
            for route in eligible
            if route.role == ModelRole.INDEPENDENT_EVALUATOR
        ]
        if evaluator_required
        else [None]
    )

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
        for fallback in fallback_candidates:
            if fallback is not None and (
                fallback.route_id == primary.route_id
                or fallback.provider == primary.provider
                or fallback.model_family == primary.model_family
            ):
                continue
            fallback_cost = _estimated_cost(fallback, requirements) if fallback else 0.0

            for evaluator in evaluator_candidates:
                if evaluator is not None:
                    if (
                        evaluator.provider == primary.provider
                        or evaluator.model_family == primary.model_family
                    ):
                        continue
                    if fallback is not None and (
                        evaluator.provider == fallback.provider
                        or evaluator.model_family == fallback.model_family
                    ):
                        continue

                evaluator_cost = (
                    _estimated_cost(evaluator, requirements) if evaluator else 0.0
                )
                # Conservative budget: include the primary attempt even if it
                # fails before fallback, plus fallback and evaluator costs.
                total_cost = primary_cost + fallback_cost + evaluator_cost
                if total_cost <= requirements.max_estimated_cost:
                    decisions.append((primary, fallback, evaluator, total_cost))

    if not decisions:
        if evaluator_required:
            raise NoEligibleModelRoute(
                "No independent evaluator from a different provider and model family "
                "meets the risk, capability, region and total cost policy"
            )
        raise NoEligibleModelRoute(
            "No reasoning route meets the configured total cost and policy limits"
        )

    # Operator-scored quality is primary. Prefer a safe fallback and evaluator
    # where the total worst-case budget permits, then use cost as tie-breaker.
    primary, fallback, evaluator, cost = sorted(
        decisions,
        key=lambda item: (
            -item[0].quality_rank,
            -(item[2].quality_rank if item[2] else 0),
            -(1 if item[1] else 0),
            - (item[1].quality_rank if item[1] else 0),
            item[3],
            item[0].route_id,
            item[1].route_id if item[1] else "",
            item[2].route_id if item[2] else "",
        ),
    )[0]
    return RoutingDecision(
        primary=primary,
        fallback=fallback,
        independent_evaluator=evaluator,
        estimated_total_cost=cost,
        evaluator_required=evaluator_required,
    )
