"""Bridge the existing DecisionWorkflow into the durable task lifecycle.

The resolver and result store are application-owned ports. They must enforce
tenant/actor scope, idempotent writes and encrypted storage for decision details.
No raw decision input or model reasoning is copied into the workflow task row.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ugai_decision.models import StrategicOption
from ugai_decision.workflow import DecisionWorkflow, DecisionWorkflowResult

from .postgres_store import WorkflowTask, canonical_json_digest
from .state_machine import TaskState
from .worker import ExternalOutcomeUnknown, WorkerOutcome


@dataclass(frozen=True, slots=True)
class DecisionTaskInput:
    question: str
    options: tuple[StrategicOption, ...]
    system_factors: tuple[str, ...] = ()
    stakeholder_impacts: tuple[str, ...] = ()
    time_horizons: tuple[str, ...] = ("short_term", "long_term")
    assumptions: tuple[str, ...] = ()
    risk_tolerance: str = "balanced"
    evidence_threshold: float = 0.50
    reserve_floor: float = 0.15
    hedge_target: float = 0.20
    max_bet_allocation: float = 0.25
    risk_budget: float = 0.25

    def validate(self) -> None:
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("decision_question_required")
        if not isinstance(self.options, tuple) or not all(
            isinstance(option, StrategicOption) for option in self.options
        ):
            raise TypeError("decision_options_must_be_strategic_options")
        for name, values in (
            ("system_factors", self.system_factors),
            ("stakeholder_impacts", self.stakeholder_impacts),
            ("time_horizons", self.time_horizons),
            ("assumptions", self.assumptions),
        ):
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"decision_{name}_invalid")
        if self.risk_tolerance not in {"defensive", "balanced", "opportunity_seeking"}:
            raise ValueError("decision_risk_tolerance_invalid")

    def to_workflow_kwargs(self) -> dict[str, object]:
        self.validate()
        return {
            "question": self.question,
            "options": self.options,
            "system_factors": self.system_factors,
            "stakeholder_impacts": self.stakeholder_impacts,
            "time_horizons": self.time_horizons,
            "assumptions": self.assumptions,
            "risk_tolerance": self.risk_tolerance,
            "evidence_threshold": self.evidence_threshold,
            "reserve_floor": self.reserve_floor,
            "hedge_target": self.hedge_target,
            "max_bet_allocation": self.max_bet_allocation,
            "risk_budget": self.risk_budget,
        }


class DecisionInputResolver(Protocol):
    async def resolve(
        self, *, reference: str, tenant_id: str, actor_id: str
    ) -> DecisionTaskInput:
        """Resolve a protected input reference under tenant and actor authorization."""


class DecisionResultStore(Protocol):
    async def save(
        self,
        *,
        tenant_id: str,
        task_id: UUID,
        actor_id: str,
        idempotency_key: str,
        decision_digest: str,
        result: DecisionWorkflowResult,
    ) -> None:
        """Atomically persist an encrypted, immutable decision result idempotently."""


class DecisionWorkflowTaskHandler:
    """Advance one durable decision task using the single existing decision engine.

    The task moves RECEIVED -> OBSERVING -> PLANNING before evaluation. The
    existing DecisionWorkflow remains responsible for evidence, evaluation,
    approval request creation and audit. Only the resulting digests and opaque
    approval reference are written to the durable task row.
    """

    def __init__(
        self,
        *,
        workflow: DecisionWorkflow,
        input_resolver: DecisionInputResolver,
        result_store: DecisionResultStore,
        task_type: str = "decision_evaluation",
    ) -> None:
        if workflow is None or input_resolver is None or result_store is None:
            raise ValueError("decision_workflow_dependencies_required")
        if not isinstance(task_type, str) or not task_type.strip() or len(task_type) > 128:
            raise ValueError("decision_task_type_invalid")
        self._workflow = workflow
        self._resolver = input_resolver
        self._results = result_store
        self._task_type = task_type

    async def handle(self, task: WorkflowTask) -> WorkerOutcome:
        if task.task_type != self._task_type:
            raise ValueError("decision_task_type_mismatch")
        if task.state is TaskState.RECEIVED:
            return WorkerOutcome(
                next_state=TaskState.OBSERVING,
                reason_code="decision_input_observed",
            )
        if task.state is TaskState.OBSERVING:
            return WorkerOutcome(
                next_state=TaskState.PLANNING,
                reason_code="decision_planning_started",
            )
        if task.state is not TaskState.PLANNING:
            return WorkerOutcome(
                next_state=TaskState.BLOCKED,
                reason_code="decision_stage_not_supported",
                error_code="decision_stage_not_supported",
            )

        reference = task.metadata.get("context_ref")
        if not isinstance(reference, str) or not reference.strip():
            return WorkerOutcome(
                next_state=TaskState.BLOCKED,
                reason_code="decision_input_reference_missing",
                error_code="decision_input_reference_missing",
            )

        decision_input = await self._resolver.resolve(
            reference=reference,
            tenant_id=task.tenant_id,
            actor_id=task.actor_id,
        )
        if not isinstance(decision_input, DecisionTaskInput):
            raise TypeError("decision_input_resolver_returned_invalid_type")

        # Scope the stable key by tenant; only its digest crosses into the
        # decision gateway, avoiding raw tenant identifiers in downstream keys.
        stable_idempotency_key = hashlib.sha256(
            f"{task.tenant_id}:{task.idempotency_key}".encode()
        ).hexdigest()
        result = await self._workflow.evaluate(
            **decision_input.to_workflow_kwargs(),
            actor_id=task.actor_id,
            idempotency_key=stable_idempotency_key,
        )
        decision_digest = canonical_json_digest(result.decision.to_dict())

        try:
            await self._results.save(
                tenant_id=task.tenant_id,
                task_id=task.task_id,
                actor_id=task.actor_id,
                idempotency_key=task.idempotency_key,
                decision_digest=decision_digest,
                result=result,
            )
        except Exception as exc:
            # Approval creation may already have committed. Do not let the
            # generic worker retry this external side effect blindly.
            raise ExternalOutcomeUnknown(
                "Decision result persistence is uncertain; reconcile by task idempotency key"
            ) from exc

        return WorkerOutcome(
            next_state=TaskState.AWAITING_APPROVAL,
            reason_code="decision_approval_requested",
            approval_reference=result.approval_reference,
            decision_digest=decision_digest,
            plan_digest=result.plan_digest,
        )
