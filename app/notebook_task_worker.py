"""Reasoning-only worker for durable AI Notebook tasks.

This first production slice deliberately performs no notebook code execution,
artifact retrieval, MCP/tool invocation, workspace writes, or deployment.
"""
from __future__ import annotations

import hashlib
import json
from math import ceil
from typing import Any
from uuid import uuid4

from app.ai_schemas import AICompletionRequest
from app.config import settings
from app.reasoning.catalog import (
    ReasoningRouteCatalogError,
    load_approved_text_routes,
)
from app.reasoning.execution import (
    PolicyRoutedTextExecutor,
    ReasoningRouteConfigurationError,
)
from app.reasoning.routing import (
    NoEligibleModelRoute,
    RoutingRequirements,
    select_model_routes,
)
from app.reasoning.schemas import ReasoningProfile, RiskTier
from app.task_api import TaskSubmission
from app.workflows.schemas import ProjectDomain
from ugai_workflow.payload_cipher import TaskPayloadCipher
from ugai_workflow.postgres_store import PostgresWorkflowStore, WorkflowTask
from ugai_workflow.state_machine import TaskState
from ugai_workflow.worker import ExternalOutcomeUnknown, WorkerOutcome

_NOTEBOOK_TASK_TYPE = "notebook_task"
_ALLOWED_CAPABILITIES = frozenset({"reasoning:read"})
_MAX_OUTPUT_TOKENS = 2048


class NotebookTaskInputInvalid(ValueError):
    """A task payload is invalid or requests an unsupported side effect."""


class NotebookReasoningTaskHandler:
    """Execute a single policy-gated reasoning stage for one notebook task."""

    def __init__(
        self,
        *,
        store: PostgresWorkflowStore,
        cipher: TaskPayloadCipher,
    ) -> None:
        if store is None or cipher is None:
            raise ValueError("notebook_worker_dependencies_required")
        self._store = store
        self._cipher = cipher

    async def _payload(self, task: WorkflowTask) -> TaskSubmission:
        encrypted = await self._store.get_encrypted_payload(
            task_id=task.task_id,
            tenant_id=task.tenant_id,
        )
        if encrypted is None:
            raise NotebookTaskInputInvalid("notebook_task_encrypted_input_missing")
        key_id, ciphertext, digest = encrypted
        try:
            payload = self._cipher.decrypt(
                ciphertext,
                expected_sha256=digest,
                key_id=key_id,
            )
            submission = TaskSubmission.model_validate(payload)
        except Exception as exc:
            raise NotebookTaskInputInvalid("notebook_task_payload_integrity_or_schema_invalid") from exc

        if submission.project_id != task.project_id:
            raise NotebookTaskInputInvalid("notebook_task_project_scope_mismatch")
        if set(submission.requested_capabilities) != _ALLOWED_CAPABILITIES:
            raise NotebookTaskInputInvalid("notebook_task_capability_not_allowed")
        if submission.artifacts:
            raise NotebookTaskInputInvalid("notebook_task_artifact_fetch_not_enabled")
        return submission

    @staticmethod
    def _requirements(submission: TaskSubmission) -> RoutingRequirements:
        estimated_input_tokens = max(
            1,
            ceil((len(submission.intent) + len(submission.context)) / 4),
        )
        regions = {
            item.strip()
            for item in settings.reasoning_permitted_data_regions.split(",")
            if item.strip()
        }
        if not regions:
            raise NoEligibleModelRoute("No permitted reasoning data region is configured")
        return RoutingRequirements(
            risk_tier=RiskTier.HIGH,
            profile=ReasoningProfile.DEEP,
            required_capabilities={"text"},
            permitted_data_regions=regions,
            estimated_input_tokens=estimated_input_tokens,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            max_estimated_cost=settings.reasoning_max_estimated_cost,
        )

    async def _executor(
        self, submission: TaskSubmission
    ) -> tuple[PolicyRoutedTextExecutor, RoutingRequirements, str]:
        routes = await load_approved_text_routes()
        requirements = self._requirements(submission)
        decision = select_model_routes(routes, requirements)
        if decision.independent_evaluator is None:
            raise NoEligibleModelRoute("High-risk Notebook reasoning requires an independent evaluator")
        from app.providers.router import TextModelRouter

        executor = PolicyRoutedTextExecutor(
            router=TextModelRouter.from_settings(),
            routes=routes,
        )
        plan = {
            "task_type": _NOTEBOOK_TASK_TYPE,
            "project_id": submission.project_id,
            "capabilities": sorted(_ALLOWED_CAPABILITIES),
            "risk_tier": RiskTier.HIGH.value,
            "profile": ReasoningProfile.DEEP.value,
            "primary_route_id": decision.primary.route_id,
            "fallback_route_id": decision.fallback.route_id if decision.fallback else None,
            "evaluator_route_id": decision.independent_evaluator.route_id,
        }
        plan_digest = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return executor, requirements, plan_digest

    @staticmethod
    def _result_payload(
        *,
        task: WorkflowTask,
        submission: TaskSubmission,
        policy_result: Any,
    ) -> dict[str, Any]:
        evaluator_route = policy_result.decision.independent_evaluator
        evaluation = policy_result.independent_evaluation
        if evaluator_route is None or evaluation is None:
            raise ExternalOutcomeUnknown(
                "independent_evaluator_result_missing_after_model_execution"
            )
        candidate = policy_result.completion.final_content
        critique = evaluation.final_content
        if (
            not isinstance(candidate, str)
            or not candidate.strip()
            or len(candidate.encode("utf-8")) > 48 * 1024
            or not isinstance(critique, str)
            or not critique.strip()
            or len(critique.encode("utf-8")) > 48 * 1024
        ):
            raise ExternalOutcomeUnknown("reasoning_result_invalid_after_model_execution")
        execution_route = policy_result.execution_route
        return {
            "contract_version": "1.0.0",
            "task_id": str(task.task_id),
            "project_id": submission.project_id,
            "workspace_id": str(submission.workspace_id),
            "request_id": str(uuid4()),
            "policy_version": "reasoning-policy-v1",
            "risk_tier": RiskTier.HIGH.value,
            "profile": ReasoningProfile.DEEP.value,
            "candidate_answer": candidate,
            "independent_review": critique,
            "selected_route": {
                "route_id": execution_route.route_id,
                "provider": execution_route.provider,
                "model_id": execution_route.model_id,
                "model_revision": execution_route.model_revision,
            },
            "evaluator_route": {
                "route_id": evaluator_route.route_id,
                "provider": evaluator_route.provider,
                "model_id": evaluator_route.model_id,
                "model_revision": evaluator_route.model_revision,
            },
            "fallback_used": bool(policy_result.fallback_used),
            "verification_status": "needs_human_review",
            "human_review_required": True,
            "tool_execution_performed": False,
            "evidence_grounding": "not_performed",
            "limitations": [
                "This is an AI-generated candidate with an independent model critique.",
                "No source-grounding retrieval or human approval was performed.",
                "The result does not authorize code execution, MCP tools, or external actions.",
            ],
        }

    @staticmethod
    def _validate_result(task: WorkflowTask, value: dict[str, Any]) -> None:
        if (
            value.get("task_id") != str(task.task_id)
            or value.get("project_id") != task.project_id
            or value.get("verification_status") != "needs_human_review"
            or value.get("human_review_required") is not True
            or value.get("tool_execution_performed") is not False
            or not isinstance(value.get("candidate_answer"), str)
            or not isinstance(value.get("independent_review"), str)
            or not value["candidate_answer"].strip()
            or not value["independent_review"].strip()
        ):
            raise ValueError("notebook_task_result_contract_invalid")

    async def handle(self, task: WorkflowTask) -> WorkerOutcome:
        if task.task_type != _NOTEBOOK_TASK_TYPE:
            return WorkerOutcome(
                next_state=TaskState.BLOCKED,
                reason_code="unsupported_notebook_task_type",
                error_code="unsupported_task_type",
            )
        if task.state is TaskState.RECEIVED:
            return WorkerOutcome(
                next_state=TaskState.OBSERVING,
                reason_code="notebook_task_received",
            )
        if task.state is TaskState.OBSERVING:
            try:
                await self._payload(task)
            except NotebookTaskInputInvalid:
                return WorkerOutcome(
                    next_state=TaskState.BLOCKED,
                    reason_code="notebook_input_validation_failed",
                    error_code="notebook_input_invalid",
                )
            return WorkerOutcome(
                next_state=TaskState.PLANNING,
                reason_code="notebook_input_validated",
            )
        if task.state is TaskState.PLANNING:
            try:
                submission = await self._payload(task)
                _executor, _requirements, plan_digest = await self._executor(submission)
            except (NotebookTaskInputInvalid, ReasoningRouteCatalogError, ReasoningRouteConfigurationError, NoEligibleModelRoute):
                return WorkerOutcome(
                    next_state=TaskState.BLOCKED,
                    reason_code="notebook_reasoning_preflight_failed",
                    error_code="reasoning_route_unavailable",
                )
            return WorkerOutcome(
                next_state=TaskState.EXECUTING,
                reason_code="notebook_reasoning_plan_ready",
                plan_digest=plan_digest,
            )
        if task.state is TaskState.EXECUTING:
            existing = await self._store.get_encrypted_result(
                tenant_id=task.tenant_id,
                task_id=task.task_id,
            )
            if existing is not None:
                key_id, ciphertext, digest = existing
                try:
                    value = self._cipher.decrypt(
                        ciphertext, expected_sha256=digest, key_id=key_id
                    )
                    self._validate_result(task, value)
                except Exception as exc:
                    raise ExternalOutcomeUnknown("persisted_notebook_result_integrity_failure") from exc
                return WorkerOutcome(
                    next_state=TaskState.VERIFYING,
                    reason_code="persisted_notebook_result_recovered",
                    decision_digest=digest,
                    metadata={
                        "evidence_digest": digest,
                        "verification_status": "needs_human_review",
                    },
                )

            try:
                submission = await self._payload(task)
                executor, requirements, _plan_digest = await self._executor(submission)
            except (NotebookTaskInputInvalid, ReasoningRouteCatalogError, ReasoningRouteConfigurationError, NoEligibleModelRoute):
                return WorkerOutcome(
                    next_state=TaskState.BLOCKED,
                    reason_code="notebook_reasoning_preflight_failed",
                    error_code="reasoning_route_unavailable",
                )

            request = AICompletionRequest(
                project_id=submission.project_id,
                domain=ProjectDomain.WORKFLOW,
                objective=submission.intent,
                context=submission.context,
                output_format="Markdown with clear headings and explicit uncertainty",
                quality_mode="single",
                temperature=0.2,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
            )
            try:
                policy_result = await executor.execute(
                    request=request,
                    requirements=requirements,
                )
                value = self._result_payload(
                    task=task,
                    submission=submission,
                    policy_result=policy_result,
                )
                encrypted, digest = self._cipher.encrypt(value)
                await self._store.put_encrypted_result(
                    tenant_id=task.tenant_id,
                    actor_id=task.actor_id,
                    project_id=task.project_id or "",
                    task_id=task.task_id,
                    key_id=self._cipher.key_id,
                    ciphertext=encrypted,
                    payload_sha256=digest,
                )
            except ExternalOutcomeUnknown:
                raise
            except Exception as exc:
                # A provider may have completed even when the response, evaluator,
                # persistence or network path fails. Never replay automatically.
                raise ExternalOutcomeUnknown(
                    "notebook_reasoning_external_outcome_requires_reconciliation"
                ) from exc
            return WorkerOutcome(
                next_state=TaskState.VERIFYING,
                reason_code="notebook_reasoning_result_persisted",
                decision_digest=digest,
                metadata={
                    "evidence_digest": digest,
                    "verification_status": "needs_human_review",
                },
            )
        if task.state is TaskState.VERIFYING:
            existing = await self._store.get_encrypted_result(
                tenant_id=task.tenant_id,
                task_id=task.task_id,
            )
            if existing is None:
                return WorkerOutcome(
                    next_state=TaskState.BLOCKED,
                    reason_code="notebook_result_missing_at_verification",
                    error_code="notebook_result_missing",
                )
            key_id, ciphertext, digest = existing
            try:
                value = self._cipher.decrypt(
                    ciphertext, expected_sha256=digest, key_id=key_id
                )
                self._validate_result(task, value)
            except Exception:
                return WorkerOutcome(
                    next_state=TaskState.BLOCKED,
                    reason_code="notebook_result_integrity_failed",
                    error_code="notebook_result_integrity_failure",
                )
            return WorkerOutcome(
                next_state=TaskState.SUCCEEDED,
                reason_code="notebook_reasoning_result_verified",
                decision_digest=digest,
                metadata={
                    "evidence_digest": digest,
                    "verification_status": "needs_human_review",
                },
            )
        return WorkerOutcome(
            next_state=TaskState.BLOCKED,
            reason_code="notebook_task_state_not_supported",
            error_code="notebook_task_state_unsupported",
        )


async def reconcile_outcome_unknown_once(
    *,
    store: PostgresWorkflowStore,
    cipher: TaskPayloadCipher,
    tenant_id: str,
    limit: int = 50,
) -> int:
    """Recover only quarantined tasks with an already persisted, valid result."""
    recovered = 0
    tasks = await store.list_outcome_unknown(tenant_id=tenant_id, limit=limit)
    for task in tasks:
        existing = await store.get_encrypted_result(
            tenant_id=tenant_id,
            task_id=task.task_id,
        )
        if existing is None:
            continue
        key_id, ciphertext, digest = existing
        try:
            value = cipher.decrypt(
                ciphertext, expected_sha256=digest, key_id=key_id
            )
            NotebookReasoningTaskHandler._validate_result(task, value)
            await store.transition(
                task_id=task.task_id,
                tenant_id=tenant_id,
                expected_version=task.version,
                target=TaskState.VERIFYING,
                actor_id="system:notebook-result-reconciler",
                reason_code="persisted_result_reconciled",
                require_lease=False,
                reconciliation_verified=True,
                metadata={
                    "evidence_digest": digest,
                    "verification_status": "needs_human_review",
                },
                decision_digest=digest,
            )
        except Exception:
            # Preserve quarantine on stale state, corrupt data or failed writes.
            continue
        recovered += 1
    return recovered
