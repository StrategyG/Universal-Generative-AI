"""Tool-free Notebook reasoning worker with durable, encrypted result handling.

This first worker deliberately does not execute notebook code, call MCP tools,
or retrieve client artifacts. It returns a candidate and independent critique
that must be reviewed by a human before any consequential action.
"""
from __future__ import annotations

import hashlib
import json
from math import ceil
from uuid import UUID

from app.ai_schemas import AICompletionRequest
from app.config import settings
from app.providers.router import TextModelRouter
from app.reasoning.catalog import ReasoningRouteCatalogError, load_approved_text_routes
from app.reasoning.execution import (
    PolicyRoutedTextExecutor,
    ReasoningRouteConfigurationError,
)
from app.reasoning.routing import NoEligibleModelRoute, RoutingRequirements
from app.reasoning.schemas import ReasoningProfile, RiskTier
from app.workflows.schemas import ProjectDomain
from ugai_workflow.input_vault import WorkflowInputNotFound
from ugai_workflow.postgres_store import WorkflowTask
from ugai_workflow.result_vault import WorkflowResultVault
from ugai_workflow.state_machine import TaskState
from ugai_workflow.worker import ExternalOutcomeUnknown, WorkerOutcome


class NotebookReasoningTaskHandler:
    """Execute only the approved text-reasoning slice of a Notebook task."""

    task_type = "notebook_request"

    def __init__(self, *, runtime) -> None:
        if runtime is None or runtime.inputs is None or runtime.results is None:
            raise ValueError("notebook_workflow_runtime_required")
        self._runtime = runtime
        self._store = runtime.store
        self._inputs = runtime.inputs
        self._results: WorkflowResultVault = runtime.results

    @staticmethod
    def _blocked(reason: str, code: str) -> WorkerOutcome:
        return WorkerOutcome(
            next_state=TaskState.BLOCKED,
            reason_code=reason,
            error_code=code,
        )

    @staticmethod
    def _valid_result(result: dict, task: WorkflowTask) -> bool:
        required = {
            "schema_version",
            "task_id",
            "project_id",
            "workspace_id",
            "candidate_answer",
            "independent_review",
            "selected_route",
            "evaluator_route",
            "verification_status",
            "human_review_required",
            "tool_execution_performed",
            "evidence_grounding",
        }
        return (
            required.issubset(result)
            and result.get("task_id") == str(task.task_id)
            and result.get("project_id") == task.metadata.get("project_id")
            and result.get("workspace_id") == task.metadata.get("workspace_id")
            and result.get("verification_status") == "needs_human_review"
            and result.get("human_review_required") is True
            and result.get("tool_execution_performed") is False
            and result.get("evidence_grounding") == "not_performed"
            and isinstance(result.get("candidate_answer"), str)
            and bool(result["candidate_answer"].strip())
            and isinstance(result.get("independent_review"), str)
            and bool(result["independent_review"].strip())
            and isinstance(result.get("selected_route"), dict)
            and isinstance(result.get("evaluator_route"), dict)
        )

    async def _workspace_is_active(self, task: WorkflowTask) -> bool:
        project_id = task.metadata.get("project_id")
        workspace_value = task.metadata.get("workspace_id")
        if not isinstance(project_id, str) or not isinstance(workspace_value, str):
            return False
        try:
            workspace_id = UUID(workspace_value)
        except ValueError:
            return False
        return await self._store.workspace_is_bound(
            tenant_id=task.tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
        )

    async def _load_result(self, task: WorkflowTask) -> dict | None:
        project_id = task.metadata.get("project_id")
        if not isinstance(project_id, str):
            raise ValueError("task_project_id_missing")
        try:
            return await self._results.get(
                tenant_id=task.tenant_id,
                actor_id=task.actor_id,
                project_id=project_id,
                task_id=task.task_id,
            )
        except WorkflowInputNotFound:
            return None

    async def _generate_result(self, task: WorkflowTask) -> WorkerOutcome:
        project_id = task.metadata.get("project_id")
        workspace_value = task.metadata.get("workspace_id")
        context_ref = task.metadata.get("context_ref")
        if not all(isinstance(value, str) and value.strip() for value in (
            project_id, workspace_value, context_ref
        )):
            return self._blocked(
                "notebook_task_scope_metadata_missing",
                "notebook_task_scope_metadata_missing",
            )
        try:
            workspace_id = UUID(workspace_value)
            input_ref = UUID(context_ref)
        except ValueError:
            return self._blocked(
                "notebook_task_reference_invalid",
                "notebook_task_reference_invalid",
            )

        if not await self._store.workspace_is_bound(
            tenant_id=task.tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
        ):
            return self._blocked(
                "notebook_workspace_binding_revoked",
                "notebook_workspace_binding_revoked",
            )

        payload = await self._inputs.resolve(
            input_ref=input_ref,
            tenant_id=task.tenant_id,
            actor_id=task.actor_id,
            expected_project_id=project_id,
        )
        if payload.get("workspace_id") != workspace_value:
            return self._blocked(
                "notebook_workspace_scope_mismatch",
                "notebook_workspace_scope_mismatch",
            )
        intent = payload.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            return self._blocked(
                "notebook_intent_missing",
                "notebook_intent_missing",
            )

        capabilities = payload.get("requested_capabilities", [])
        if not isinstance(capabilities, list) or any(
            not isinstance(item, str) for item in capabilities
        ):
            return self._blocked(
                "notebook_capabilities_invalid",
                "notebook_capabilities_invalid",
            )
        if set(capabilities) - {"reasoning", "analysis", "reasoning.read"}:
            return self._blocked(
                "notebook_capability_not_configured",
                "notebook_capability_not_configured",
            )
        artifacts = payload.get("artifacts", [])
        if artifacts:
            return self._blocked(
                "notebook_artifact_resolver_not_configured",
                "notebook_artifact_resolver_not_configured",
            )

        permitted_regions = {
            item.strip()
            for item in settings.reasoning_permitted_data_regions.split(",")
            if item.strip()
        }
        if not permitted_regions:
            return self._blocked(
                "reasoning_data_regions_not_configured",
                "reasoning_data_regions_not_configured",
            )
        cell_revision = payload.get("cell_revision")
        context = (
            f"Notebook cell revision: {cell_revision}"
            if isinstance(cell_revision, str) and cell_revision.strip()
            else ""
        )
        request = AICompletionRequest(
            project_id=project_id,
            domain=ProjectDomain.WORKFLOW,
            objective=intent,
            context=context,
            output_format="Markdown with assumptions, risks and limitations",
            quality_mode="rigorous",
            temperature=0.2,
            max_output_tokens=2048,
        )
        requirements = RoutingRequirements(
            risk_tier=RiskTier.HIGH,
            profile=ReasoningProfile.DEEP,
            required_capabilities={"text"},
            permitted_data_regions=permitted_regions,
            estimated_input_tokens=max(1, ceil(len(intent + context) / 4)),
            max_output_tokens=request.max_output_tokens,
            max_estimated_cost=settings.reasoning_max_estimated_cost,
        )

        # Catalog/registry validation is a pre-execution policy gate. Once a
        # provider invocation starts, any uncertain response is quarantined.
        try:
            routes = await load_approved_text_routes()
            executor = PolicyRoutedTextExecutor(
                router=TextModelRouter.from_settings(),
                routes=routes,
            )
        except (
            ReasoningRouteCatalogError,
            ReasoningRouteConfigurationError,
            NoEligibleModelRoute,
        ):
            return self._blocked(
                "notebook_reasoning_policy_blocked",
                "notebook_reasoning_policy_blocked",
            )

        try:
            execution = await executor.execute(
                request=request,
                requirements=requirements,
            )
        except NoEligibleModelRoute:
            # Route selection occurs before any provider call.
            return self._blocked(
                "notebook_reasoning_route_unavailable",
                "notebook_reasoning_route_unavailable",
            )
        except Exception as exc:
            # Once execution starts, a provider or evaluator error may follow a
            # successful upstream completion. Never replay uncertain generation.
            raise ExternalOutcomeUnknown(
                "Notebook provider outcome is uncertain; reconcile before retry"
            ) from exc

        evaluator = execution.decision.independent_evaluator
        if evaluator is None or execution.independent_evaluation is None:
            raise ExternalOutcomeUnknown(
                "Independent evaluator did not produce a durable review"
            )

        result = {
            "schema_version": "1",
            "task_id": str(task.task_id),
            "project_id": project_id,
            "workspace_id": workspace_value,
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
                "Notebook code was not executed.",
                "No MCP tool or external side effect was performed.",
                "Referenced artifacts were not retrieved or evaluated.",
                "A human must review the candidate and independent critique.",
            ],
        }
        canonical = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        try:
            await self._results.put(
                tenant_id=task.tenant_id,
                actor_id=task.actor_id,
                project_id=project_id,
                task_id=task.task_id,
                payload=result,
            )
        except Exception as exc:
            raise ExternalOutcomeUnknown(
                "Notebook result persistence is uncertain; do not rerun provider call"
            ) from exc
        return WorkerOutcome(
            next_state=TaskState.VERIFYING,
            reason_code="notebook_reasoning_result_persisted",
            metadata={
                "evidence_digest": digest,
                "verification_status": "needs_human_review",
            },
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
                reason_code="notebook_execution_started",
            )
        if task.state is TaskState.EXECUTING:
            if not await self._workspace_is_active(task):
                return self._blocked(
                    "notebook_workspace_binding_revoked",
                    "notebook_workspace_binding_revoked",
                )
            # A previous worker may have persisted a result before losing its
            # lease. Read it first so an accepted result is never regenerated.
            existing = await self._load_result(task)
            if existing is not None:
                if not self._valid_result(existing, task):
                    raise ExternalOutcomeUnknown(
                        "Persisted Notebook result failed integrity/schema verification"
                    )
                canonical = json.dumps(
                    existing,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
                return WorkerOutcome(
                    next_state=TaskState.VERIFYING,
                    reason_code="notebook_result_reconciled",
                    metadata={"evidence_digest": hashlib.sha256(canonical).hexdigest()},
                )
            return await self._generate_result(task)
        if task.state is TaskState.VERIFYING:
            if not await self._workspace_is_active(task):
                return self._blocked(
                    "notebook_workspace_binding_revoked",
                    "notebook_workspace_binding_revoked",
                )
            result = await self._load_result(task)
            if result is None or not self._valid_result(result, task):
                return self._blocked(
                    "notebook_result_verification_failed",
                    "notebook_result_verification_failed",
                )
            return WorkerOutcome(
                next_state=TaskState.SUCCEEDED,
                reason_code="notebook_result_verified_for_human_review",
                metadata={"verification_status": "needs_human_review"},
            )
        return self._blocked(
            "notebook_task_state_unsupported",
            "notebook_task_state_unsupported",
        )


async def reconcile_outcome_unknown_once(runtime, *, tenant_id: str, limit: int = 50) -> int:
    """Advance only unknown tasks whose encrypted result already exists and validates."""
    tasks = await runtime.store.list_outcome_unknown(tenant_id=tenant_id, limit=limit)
    reconciled = 0
    for task in tasks:
        project_id = task.metadata.get("project_id")
        if not isinstance(project_id, str):
            continue
        if not await runtime.store.workspace_is_bound(
            tenant_id=task.tenant_id,
            workspace_id=UUID(task.metadata.get("workspace_id", "")),
            project_id=project_id,
        ):
            continue
        try:
            result = await runtime.results.get(
                tenant_id=task.tenant_id,
                actor_id=task.actor_id,
                project_id=project_id,
                task_id=task.task_id,
            )
        except WorkflowInputNotFound:
            continue
        if not NotebookReasoningTaskHandler._valid_result(result, task):
            continue
        canonical = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        try:
            await runtime.store.transition(
                task_id=task.task_id,
                tenant_id=tenant_id,
                expected_version=task.version,
                target=TaskState.VERIFYING,
                actor_id="system:result-reconciler",
                reason_code="encrypted_result_reconciled",
                require_lease=False,
                reconciliation_verified=True,
                metadata={"evidence_digest": digest},
            )
        except Exception:
            # A stale snapshot or an authorization failure remains quarantined.
            continue
        reconciled += 1
    return reconciled
