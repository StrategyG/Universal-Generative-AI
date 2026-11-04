"""Durable, tool-free reasoning handler for Notebook tasks.

This handler deliberately does not execute notebook code, call IM19 tools, or
read artifacts. Those capabilities require separately approved workers and
resource-specific authorization. It produces a human-reviewable reasoning
artifact only.
"""

from __future__ import annotations

from math import ceil

from app.ai_schemas import AICompletionRequest
from app.config import settings
from app.providers.router import TextModelRouter
from app.providers.text_errors import TextGenerationProviderError
from app.reasoning.catalog import ReasoningRouteCatalogError, load_approved_text_routes
from app.reasoning.execution import (
    PolicyRoutedTextExecutor,
    ReasoningEvaluatorUnavailable,
    ReasoningRouteConfigurationError,
)
from app.reasoning.routing import NoEligibleModelRoute, RoutingRequirements
from app.reasoning.schemas import ReasoningProfile, RiskTier
from app.tasks.schemas import TaskSubmission
from app.tasks.service import UGAITaskService
from app.workflows.schemas import ProjectDomain
from ugai_workflow.postgres_store import TaskNotFound, WorkflowTask
from ugai_workflow.state_machine import TaskState
from ugai_workflow.worker import RetryableWorkerError, WorkerOutcome


class NotebookReasoningTaskHandler:
    """Advance one notebook reasoning task through durable, evidence-safe states."""

    task_type = "notebook.request"

    def __init__(self, *, task_service: UGAITaskService) -> None:
        if task_service is None:
            raise ValueError("task_service_required")
        self._tasks = task_service

    @staticmethod
    def _blocked(reason: str, code: str) -> WorkerOutcome:
        return WorkerOutcome(
            next_state=TaskState.BLOCKED,
            reason_code=reason,
            error_code=code,
        )

    async def handle(self, task: WorkflowTask) -> WorkerOutcome:
        if task.task_type != self.task_type:
            raise ValueError("notebook_task_type_mismatch")

        if task.state is TaskState.RECEIVED:
            return WorkerOutcome(
                next_state=TaskState.OBSERVING,
                reason_code="notebook_request_received",
            )
        if task.state is TaskState.OBSERVING:
            return WorkerOutcome(
                next_state=TaskState.PLANNING,
                reason_code="notebook_request_observed",
            )
        if task.state is TaskState.PLANNING:
            return WorkerOutcome(
                next_state=TaskState.EXECUTING,
                reason_code="notebook_reasoning_plan_approved",
            )
        if task.state is TaskState.EXECUTING:
            # A worker may have committed the result and then lost its lease
            # before the state transition. Reconcile before invoking a model again.
            try:
                await self._tasks.load_result(
                    task_id=task.task_id,
                    tenant_id=task.tenant_id,
                    actor_id=task.actor_id,
                )
                return WorkerOutcome(
                    next_state=TaskState.VERIFYING,
                    reason_code="notebook_result_reconciled",
                )
            except TaskNotFound:
                pass

            payload = await self._tasks.load_payload(
                task_id=task.task_id,
                tenant_id=task.tenant_id,
            )
            submission = TaskSubmission.model_validate(payload)

            unsupported_capabilities = set(submission.requested_capabilities) - {
                "reasoning",
                "analysis",
            }
            if unsupported_capabilities:
                return self._blocked(
                    "notebook_capability_not_configured",
                    "notebook_capability_not_configured",
                )
            if submission.artifacts:
                return self._blocked(
                    "notebook_artifact_resolver_not_configured",
                    "notebook_artifact_resolver_not_configured",
                )

            permitted_regions = {
                value.strip()
                for value in settings.reasoning_permitted_data_regions.split(",")
                if value.strip()
            }
            if not permitted_regions:
                return self._blocked(
                    "reasoning_data_regions_not_configured",
                    "reasoning_data_regions_not_configured",
                )

            request = AICompletionRequest(
                project_id=str(submission.workspace_id),
                domain=ProjectDomain.WORKFLOW,
                objective=submission.intent,
                context=submission.context,
                output_format="Markdown with clear headings, assumptions, risks and limitations",
                quality_mode="rigorous",
                temperature=0.2,
                max_output_tokens=2048,
            )
            requirements = RoutingRequirements(
                risk_tier=RiskTier.HIGH,
                profile=ReasoningProfile.DEEP,
                required_capabilities={"text"},
                permitted_data_regions=permitted_regions,
                estimated_input_tokens=max(
                    1, ceil((len(submission.intent) + len(submission.context)) / 4)
                ),
                max_output_tokens=request.max_output_tokens,
                max_estimated_cost=settings.reasoning_max_estimated_cost,
            )

            try:
                executor = PolicyRoutedTextExecutor(
                    router=TextModelRouter.from_settings(),
                    routes=await load_approved_text_routes(),
                )
                execution = await executor.execute(
                    request=request,
                    requirements=requirements,
                )
            except TextGenerationProviderError as exc:
                if exc.retryable:
                    raise RetryableWorkerError("notebook_reasoning_provider_retryable") from exc
                return self._blocked(
                    "notebook_reasoning_provider_blocked",
                    "notebook_reasoning_provider_blocked",
                )
            except (
                ReasoningRouteCatalogError,
                ReasoningRouteConfigurationError,
                ReasoningEvaluatorUnavailable,
                NoEligibleModelRoute,
            ):
                return self._blocked(
                    "notebook_reasoning_policy_blocked",
                    "notebook_reasoning_policy_blocked",
                )

            evaluator = execution.decision.independent_evaluator
            if evaluator is None or execution.independent_evaluation is None:
                return self._blocked(
                    "independent_review_missing",
                    "independent_review_missing",
                )

            result = {
                "schema_version": "1",
                "task_id": str(task.task_id),
                "workspace_id": str(submission.workspace_id),
                "candidate_answer": execution.completion.final_content,
                "independent_review": execution.independent_evaluation.final_content,
                "selected_route": {
                    "route_id": execution.execution_route.route_id,
                    "provider": execution.execution_route.provider,
                    "model_id": execution.execution_route.model_id,
                    "model_revision": execution.execution_route.model_revision,
                },
                "evaluator_route": {
                    "route_id": evaluator.route_id,
                    "provider": evaluator.provider,
                    "model_id": evaluator.model_id,
                    "model_revision": evaluator.model_revision,
                },
                "fallback_used": execution.fallback_used,
                "verification_status": "needs_human_review",
                "human_review_required": True,
                "tool_execution_performed": False,
                "evidence_grounding": "not_performed",
                "limitations": [
                    "No notebook code was executed.",
                    "No MCP tool or external side effect was performed.",
                    "Referenced artifacts were not retrieved or evaluated.",
                    "A human must review the candidate and independent critique.",
                ],
            }
            await self._tasks.save_result(
                task_id=task.task_id,
                tenant_id=task.tenant_id,
                actor_id=task.actor_id,
                result=result,
            )
            return WorkerOutcome(
                next_state=TaskState.VERIFYING,
                reason_code="notebook_reasoning_result_persisted",
            )

        if task.state is TaskState.VERIFYING:
            try:
                result = await self._tasks.load_result(
                    task_id=task.task_id,
                    tenant_id=task.tenant_id,
                    actor_id=task.actor_id,
                )
            except TaskNotFound:
                return self._blocked(
                    "notebook_result_missing_at_verification",
                    "notebook_result_missing",
                )
            required = {
                "task_id",
                "workspace_id",
                "candidate_answer",
                "independent_review",
                "selected_route",
                "evaluator_route",
                "verification_status",
                "human_review_required",
            }
            if (
                not required.issubset(result)
                or result.get("task_id") != str(task.task_id)
                or result.get("workspace_id") != task.metadata.get("workspace_id")
                or result.get("verification_status") != "needs_human_review"
                or result.get("human_review_required") is not True
                or not isinstance(result.get("candidate_answer"), str)
                or not result["candidate_answer"].strip()
                or not isinstance(result.get("independent_review"), str)
                or not result["independent_review"].strip()
            ):
                return self._blocked(
                    "notebook_result_verification_failed",
                    "notebook_result_verification_failed",
                )
            return WorkerOutcome(
                next_state=TaskState.SUCCEEDED,
                reason_code="notebook_reasoning_result_verified",
            )

        return self._blocked(
            "notebook_task_state_unsupported",
            "notebook_task_state_unsupported",
        )
