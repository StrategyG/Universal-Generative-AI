from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from ugai_workflow import (
    DecisionTaskInput,
    DecisionWorkflowTaskHandler,
    ExternalOutcomeUnknown,
    TaskState,
)
from ugai_workflow.postgres_store import canonical_json_digest


class FakeResolver:
    def __init__(self, value: DecisionTaskInput):
        self.value = value
        self.calls = []

    async def resolve(self, *, reference: str, tenant_id: str, actor_id: str):
        self.calls.append((reference, tenant_id, actor_id))
        return self.value


class FakeDecision:
    def to_dict(self):
        return {"status": "RECOMMENDATION_READY", "score": 0.91}


class FakeDecisionWorkflow:
    def __init__(self):
        self.calls = []

    async def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            decision=FakeDecision(),
            approval_reference="approval-ref-opaque-001",
            plan_digest="a" * 64,
        )


class FakeResultStore:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.saved = []

    async def save(self, **kwargs):
        if self.fail:
            raise OSError("result store response lost")
        self.saved.append(kwargs)


def make_task(state: TaskState):
    return SimpleNamespace(
        task_id=uuid4(),
        tenant_id="tenant-001",
        actor_id="trusted-actor",
        task_type="decision_evaluation",
        state=state,
        idempotency_key="decision-task-0001",
        metadata={"context_ref": "vault://tenant-001/request-0001"},
    )


def make_handler(*, fail_store: bool = False):
    input_value = DecisionTaskInput(
        question="Should the business enter the new market?",
        options=(),
        system_factors=("supplier concentration",),
        stakeholder_impacts=("employees", "customers"),
    )
    resolver = FakeResolver(input_value)
    workflow = FakeDecisionWorkflow()
    result_store = FakeResultStore(fail=fail_store)
    handler = DecisionWorkflowTaskHandler(
        workflow=workflow,
        input_resolver=resolver,
        result_store=result_store,
    )
    return handler, resolver, workflow, result_store


@pytest.mark.asyncio
async def test_decision_bridge_advances_state_machine_before_evaluation() -> None:
    handler, resolver, workflow, result_store = make_handler()

    observing = await handler.handle(make_task(TaskState.RECEIVED))
    planning = await handler.handle(make_task(TaskState.OBSERVING))

    assert observing.next_state is TaskState.OBSERVING
    assert planning.next_state is TaskState.PLANNING
    assert resolver.calls == []
    assert workflow.calls == []
    assert result_store.saved == []


@pytest.mark.asyncio
async def test_decision_bridge_reuses_existing_decision_workflow_and_persists_approval() -> None:
    handler, resolver, workflow, result_store = make_handler()
    task = make_task(TaskState.PLANNING)

    outcome = await handler.handle(task)
    outcome.validate()

    assert outcome.next_state is TaskState.AWAITING_APPROVAL
    assert outcome.approval_reference == "approval-ref-opaque-001"
    assert outcome.decision_digest == canonical_json_digest(FakeDecision().to_dict())
    assert outcome.plan_digest == "a" * 64
    assert resolver.calls == [
        ("vault://tenant-001/request-0001", "tenant-001", "trusted-actor")
    ]
    assert workflow.calls[0]["actor_id"] == "trusted-actor"
    assert workflow.calls[0]["question"] == "Should the business enter the new market?"
    assert len(workflow.calls[0]["idempotency_key"]) == 64
    assert result_store.saved[0]["tenant_id"] == task.tenant_id
    assert result_store.saved[0]["task_id"] == task.task_id
    assert result_store.saved[0]["decision_digest"] == outcome.decision_digest


@pytest.mark.asyncio
async def test_decision_bridge_blocks_when_protected_input_reference_is_missing() -> None:
    handler, resolver, workflow, result_store = make_handler()
    task = make_task(TaskState.PLANNING)
    task.metadata = {}

    outcome = await handler.handle(task)

    assert outcome.next_state is TaskState.BLOCKED
    assert outcome.error_code == "decision_input_reference_missing"
    assert resolver.calls == []
    assert workflow.calls == []
    assert result_store.saved == []


@pytest.mark.asyncio
async def test_decision_bridge_does_not_retry_uncertain_result_persistence() -> None:
    handler, _resolver, workflow, result_store = make_handler(fail_store=True)

    with pytest.raises(ExternalOutcomeUnknown):
        await handler.handle(make_task(TaskState.PLANNING))

    assert len(workflow.calls) == 1
    assert result_store.saved == []
