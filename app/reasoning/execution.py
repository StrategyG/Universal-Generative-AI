"""Policy-routed text execution with explicit fallback and independent review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.ai_schemas import AICompletionRequest, AICompletionResponse
from app.providers.router import TextModelRouter
from app.providers.text_errors import TextGenerationProviderError

from .routing import (
    ModelRouteDescriptor,
    RoutingDecision,
    RoutingRequirements,
    select_model_routes,
)


class ReasoningRouteConfigurationError(RuntimeError):
    """A policy route does not match an immutable configured provider."""


class ReasoningEvaluatorUnavailable(RuntimeError):
    """A required independent evaluator could not complete its review."""


@dataclass(frozen=True, slots=True)
class PolicyRoutedCompletion:
    decision: RoutingDecision
    execution_route: ModelRouteDescriptor
    completion: AICompletionResponse
    independent_evaluation: AICompletionResponse | None
    fallback_used: bool


class PolicyRoutedTextExecutor:
    """Execute a routing decision through exact provider identities.

    The caller must supply a route catalog whose approval, quality, cost and
    data-region metadata came from an operator-controlled registry. This class
    validates its binding to the configured provider and never infers approval
    from the presence of an API key or provider endpoint.
    """

    def __init__(
        self,
        *,
        router: TextModelRouter,
        routes: Sequence[ModelRouteDescriptor],
    ) -> None:
        if router is None:
            raise ValueError("text_model_router_required")
        if not routes:
            raise ValueError("approved_model_route_catalog_required")
        self._router = router
        self._routes = tuple(routes)
        route_ids = [route.route_id for route in self._routes]
        if len(set(route_ids)) != len(route_ids):
            raise ValueError("model_route_ids_must_be_unique")
        for route in self._routes:
            if not route.approved or not route.enabled:
                raise ReasoningRouteConfigurationError(
                    "Reasoning execution rejects unapproved or disabled model routes"
                )
            self._validate_provider_binding(route)

    def _validate_provider_binding(self, route: ModelRouteDescriptor) -> None:
        try:
            provider = self._router.get_provider(route.provider)
        except TextGenerationProviderError as exc:
            raise ReasoningRouteConfigurationError(
                "An approved reasoning route references an unconfigured provider"
            ) from exc

        if (
            getattr(provider, "model_id", None) != route.model_id
            or getattr(provider, "model_revision", None) != route.model_revision
        ):
            raise ReasoningRouteConfigurationError(
                "The configured provider does not match the approved immutable model identity"
            )

        provider_capabilities = getattr(provider, "capabilities", None)
        supported = {"text"}
        if provider_capabilities is not None:
            for name in ("streaming", "tool_calling", "structured_output", "vision", "audio", "video"):
                if getattr(provider_capabilities, name, False):
                    supported.add(name)
        if not route.capabilities.issubset(supported):
            raise ReasoningRouteConfigurationError(
                "The approved route declares capabilities not provided by its configured adapter"
            )

    async def _invoke(
        self,
        route: ModelRouteDescriptor,
        request: AICompletionRequest,
    ) -> AICompletionResponse:
        result = await self._router.generate_with_provider(
            route.provider,
            request,
            expected_model_id=route.model_id,
            expected_model_revision=route.model_revision,
        )
        response = AICompletionResponse.model_validate(result)
        provider = self._router.get_provider(route.provider)
        if response.provider != provider.name or response.model != provider.model:
            raise TextGenerationProviderError(
                "Provider response identity does not match the selected model route",
                code="provider_identity_mismatch",
            )
        if not response.final_content.strip():
            raise TextGenerationProviderError(
                "The selected model returned an empty completion",
                code="empty_model_completion",
            )
        return response

    async def execute(
        self,
        *,
        request: AICompletionRequest,
        requirements: RoutingRequirements,
    ) -> PolicyRoutedCompletion:
        """Run the approved primary route, explicit fallback, then evaluator.

        Fallback is attempted only after a primary provider error and only when
        the policy selector explicitly returned a fallback. For high/critical
        tasks, a failed independent evaluator blocks acceptance of the result.
        """
        decision = select_model_routes(list(self._routes), requirements)
        execution_route = decision.primary
        fallback_used = False

        try:
            completion = await self._invoke(decision.primary, request)
        except TextGenerationProviderError:
            if decision.fallback is None:
                raise
            execution_route = decision.fallback
            fallback_used = True
            completion = await self._invoke(decision.fallback, request)

        completion = completion.model_copy(
            update={
                "routing": {
                    **completion.routing,
                    "selected_provider": execution_route.provider,
                    "route_id": execution_route.route_id,
                    "role": execution_route.role.value,
                    "model_id": execution_route.model_id,
                    "model_revision": execution_route.model_revision,
                    "fallback_used": fallback_used,
                    "policy_selected": True,
                }
            }
        )

        evaluation: AICompletionResponse | None = None
        if decision.evaluator_required:
            evaluator_route = decision.independent_evaluator
            if evaluator_route is None:
                raise ReasoningEvaluatorUnavailable(
                    "Policy requires an independent evaluator but selected none"
                )

            review_context = (
                f"Original context:\n{request.context}\n\n"
                f"Candidate answer to review:\n{completion.final_content}"
            )
            if len(review_context) > 20_000:
                raise ReasoningEvaluatorUnavailable(
                    "Evaluation context exceeds the configured safe input limit"
                )

            review_request = AICompletionRequest(
                project_id=request.project_id,
                domain=request.domain,
                objective=(
                    "Independently review the candidate answer for factual support, "
                    "missing assumptions, contradictions, policy violations, risk and "
                    "unresolved uncertainty. Return a concise structured critique; "
                    "do not assume the candidate answer is correct."
                ),
                context=review_context,
                output_format="Concise critical review with findings and limitations",
                quality_mode=request.quality_mode,
                temperature=0.0,
                max_output_tokens=request.max_output_tokens,
            )
            try:
                evaluation = await self._invoke(evaluator_route, review_request)
            except TextGenerationProviderError as exc:
                raise ReasoningEvaluatorUnavailable(
                    "Required independent evaluation did not complete"
                ) from exc

        return PolicyRoutedCompletion(
            decision=decision,
            execution_route=execution_route,
            completion=completion,
            independent_evaluation=evaluation,
            fallback_used=fallback_used,
        )
