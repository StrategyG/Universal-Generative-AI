"""Authenticated, read-only reasoning completion API.

The endpoint is deliberately conservative: callers cannot choose a lower risk
classification, and model output cannot authorize tools or external actions.
"""

from __future__ import annotations

from math import ceil
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.ai_schemas import AICompletionRequest
from app.auth import (
    Principal,
    ensure_project_access,
    get_current_principal,
    require_generation_role,
)
from app.config import settings
from app.providers.router import TextModelRouter
from app.providers.text_errors import TextGenerationProviderError
from app.reasoning.catalog import (
    ReasoningRouteCatalogError,
    load_approved_text_routes,
)
from app.reasoning.execution import (
    PolicyRoutedTextExecutor,
    ReasoningEvaluatorUnavailable,
    ReasoningRouteConfigurationError,
)
from app.reasoning.routing import NoEligibleModelRoute, RoutingRequirements
from app.reasoning.schemas import ReasoningProfile, RiskTier, VerificationStatus

router = APIRouter()


class ReasoningCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str = Field(min_length=1, max_length=128)
    domain: str = Field(min_length=1, max_length=64)
    objective: str = Field(min_length=1, max_length=8_000)
    context: str = Field(default="", max_length=20_000)
    output_format: str = Field(
        default="Markdown with clear headings",
        min_length=1,
        max_length=120,
    )
    max_output_tokens: int = Field(default=2_048, ge=256, le=8_192)


class ReasoningCompletionResponse(BaseModel):
    request_id: str
    project_id: str
    policy_version: str
    risk_tier: RiskTier
    profile: ReasoningProfile
    candidate_answer: str
    independent_review: str
    selected_route_id: str
    selected_provider: str
    model_id: str
    model_revision: str
    fallback_used: bool
    evaluator_route_id: str
    evaluator_provider: str
    evaluator_model_id: str
    evaluator_model_revision: str
    verification_status: VerificationStatus
    human_review_required: bool
    tool_execution_performed: bool = False
    evidence_grounding: str = "not_performed"


def _permitted_regions() -> set[str]:
    values = {
        value.strip()
        for value in settings.reasoning_permitted_data_regions.split(",")
        if value.strip()
    }
    if not values:
        raise HTTPException(
            status_code=503,
            detail={"code": "reasoning_regions_not_configured"},
        )
    return values


@router.post(
    f"{settings.api_prefix}/reasoning/complete",
    response_model=ReasoningCompletionResponse,
)
async def complete_reasoning(
    request: ReasoningCompletionRequest,
    principal: Principal = Depends(get_current_principal),
) -> ReasoningCompletionResponse:
    """Produce a candidate and independent critique; never perform external actions."""
    require_generation_role(principal)
    ensure_project_access(principal, request.project_id)

    # High risk is assigned server-side for this initial endpoint. The client
    # cannot downgrade its own risk tier to avoid independent evaluation.
    risk_tier = RiskTier.HIGH
    profile = ReasoningProfile.DEEP

    try:
        text_router = TextModelRouter.from_settings()
        routes = await load_approved_text_routes()
        executor = PolicyRoutedTextExecutor(router=text_router, routes=routes)
        estimated_input_tokens = max(
            1,
            ceil((len(request.objective) + len(request.context)) / 4),
        )
        requirements = RoutingRequirements(
            risk_tier=risk_tier,
            profile=profile,
            required_capabilities={"text"},
            permitted_data_regions=_permitted_regions(),
            estimated_input_tokens=estimated_input_tokens,
            max_output_tokens=request.max_output_tokens,
            max_estimated_cost=settings.reasoning_max_estimated_cost,
        )
        completion_request = AICompletionRequest(
            project_id=request.project_id,
            domain=request.domain,
            objective=request.objective,
            context=request.context,
            output_format=request.output_format,
            quality_mode="single",
            temperature=0.2,
            max_output_tokens=request.max_output_tokens,
        )
        result = await executor.execute(
            request=completion_request,
            requirements=requirements,
        )
    except ReasoningRouteCatalogError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "reasoning_route_catalog_unavailable", "message": str(exc)},
        ) from exc
    except (ReasoningRouteConfigurationError, NoEligibleModelRoute) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "reasoning_route_policy_blocked", "message": str(exc)},
        ) from exc
    except ReasoningEvaluatorUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "independent_evaluator_unavailable", "message": str(exc)},
        ) from exc
    except TextGenerationProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": exc.code,
                "message": str(exc),
                "retryable": exc.retryable,
            },
        ) from exc
    except RuntimeError as exc:
        # Includes unavailable model registry/database. Do not treat this as
        # permission to fall back to an unregistered model.
        raise HTTPException(
            status_code=503,
            detail={"code": "reasoning_runtime_unavailable"},
        ) from exc

    evaluator = result.decision.independent_evaluator
    if evaluator is None or result.independent_evaluation is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "required_independent_review_missing"},
        )

    return ReasoningCompletionResponse(
        request_id=str(uuid4()),
        project_id=request.project_id,
        policy_version="reasoning-policy-v1",
        risk_tier=risk_tier,
        profile=profile,
        candidate_answer=result.completion.final_content,
        independent_review=result.independent_evaluation.final_content,
        selected_route_id=result.execution_route.route_id,
        selected_provider=result.execution_route.provider,
        model_id=result.execution_route.model_id,
        model_revision=result.execution_route.model_revision,
        fallback_used=result.fallback_used,
        evaluator_route_id=evaluator.route_id,
        evaluator_provider=evaluator.provider,
        evaluator_model_id=evaluator.model_id,
        evaluator_model_revision=evaluator.model_revision,
        verification_status=VerificationStatus.NEEDS_HUMAN_REVIEW,
        human_review_required=True,
    )
