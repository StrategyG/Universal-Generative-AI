from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.notebook_task_worker import (
    NotebookReasoningTaskHandler,
    reconcile_outcome_unknown_once,
)
from app.task_api import TaskSubmission
from ugai_workflow.payload_cipher import TaskPayloadCipher
from ugai_workflow.state_machine import TaskState


class FakeWorkerStore:
    def __init__(self, *, payload=None, result=None, tasks=None):
        self.payload = payload
        self.result = result
        self.tasks = list(tasks or [])
        self.transitions = []
        self.puts = []

    async def get_encrypted_payload(self, **_kwargs):
        return self.payload

    async def get_encrypted_result(self, **_kwargs):
        return self.result

    async def put_encrypted_result(self, **kwargs):
        self.puts.append(kwargs)
        self.result = (
            kwargs["key_id"],
            kwargs["ciphertext"],
            kwargs["payload_sha256"],
        )
        return kwargs["payload_sha256"]

    async def list_outcome_unknown(self, **_kwargs):
        return self.tasks

    async def transition(self, **kwargs):
        self.transitions.append(kwargs)
        return SimpleNamespace(state=kwargs["target"])


def make_task(*, state=TaskState.OBSERVING):
    return SimpleNamespace(
        task_id=uuid4(),
        tenant_id="tenant-a",
        actor_id="user-a",
        project_id="project-a",
        task_type="notebook_task",
        state=state,
        version=4,
    )


def make_submission(*, capabilities=("reasoning:read",), artifacts=()):
    return TaskSubmission(
        project_id="project-a",
        workspace_id=uuid4(),
        notebook_id=uuid4(),
        cell_revision="revision-1",
        intent="Analyze this notebook request",
        context="Only the supplied context may be used.",
        artifacts=artifacts,
        requested_capabilities=capabilities,
    )


def make_cipher():
    return TaskPayloadCipher(Fernet.generate_key().decode("ascii"), key_id="test-v1")


@pytest.mark.asyncio
async def test_observing_stage_validates_encrypted_notebook_input():
    cipher = make_cipher()
    submission = make_submission()
    encrypted, digest = cipher.encrypt(submission.model_dump(mode="json"))
    store = FakeWorkerStore(payload=("test-v1", encrypted, digest))
    handler = NotebookReasoningTaskHandler(store=store, cipher=cipher)

    outcome = await handler.handle(make_task(state=TaskState.OBSERVING))

    assert outcome.next_state is TaskState.PLANNING
    assert outcome.reason_code == "notebook_input_validated"


@pytest.mark.asyncio
async def test_worker_blocks_unapproved_capabilities_before_model_invocation():
    cipher = make_cipher()
    submission = make_submission(capabilities=("reasoning:read", "mcp:write"))
    encrypted, digest = cipher.encrypt(submission.model_dump(mode="json"))
    store = FakeWorkerStore(payload=("test-v1", encrypted, digest))
    handler = NotebookReasoningTaskHandler(store=store, cipher=cipher)

    outcome = await handler.handle(make_task(state=TaskState.OBSERVING))

    assert outcome.next_state is TaskState.BLOCKED
    assert outcome.error_code == "notebook_input_invalid"
    assert store.puts == []


@pytest.mark.asyncio
async def test_worker_blocks_artifact_fetch_until_a_separate_policy_is_approved():
    cipher = make_cipher()
    submission = make_submission(
        artifacts=(
            {"artifact_id": "artifact-1", "sha256": "a" * 64, "media_type": "text/plain"},
        )
    )
    encrypted, digest = cipher.encrypt(submission.model_dump(mode="json"))
    store = FakeWorkerStore(payload=("test-v1", encrypted, digest))
    handler = NotebookReasoningTaskHandler(store=store, cipher=cipher)

    outcome = await handler.handle(make_task(state=TaskState.OBSERVING))

    assert outcome.next_state is TaskState.BLOCKED
    assert outcome.error_code == "notebook_input_invalid"


def test_result_contract_always_requires_human_review_and_no_tool_execution():
    task = make_task(state=TaskState.EXECUTING)
    submission = make_submission()
    route = SimpleNamespace(
        route_id="route-1",
        provider="provider-a",
        model_id="model-a",
        model_revision="a" * 40,
    )
    evaluation = SimpleNamespace(final_content="Independent critique")
    completion = SimpleNamespace(final_content="Candidate response")
    policy_result = SimpleNamespace(
        decision=SimpleNamespace(independent_evaluator=route),
        independent_evaluation=evaluation,
        execution_route=route,
        completion=completion,
        fallback_used=False,
    )

    result = NotebookReasoningTaskHandler._result_payload(
        task=task,
        submission=submission,
        policy_result=policy_result,
    )

    NotebookReasoningTaskHandler._validate_result(task, result)
    assert result["verification_status"] == "needs_human_review"
    assert result["human_review_required"] is True
    assert result["tool_execution_performed"] is False
    assert result["evidence_grounding"] == "not_performed"


@pytest.mark.asyncio
async def test_unknown_task_is_reconciled_only_when_an_immutable_result_exists():
    cipher = make_cipher()
    task = make_task(state=TaskState.OUTCOME_UNKNOWN)
    value = {
        "task_id": str(task.task_id),
        "project_id": task.project_id,
        "candidate_answer": "Candidate answer",
        "independent_review": "Independent critique",
        "verification_status": "needs_human_review",
        "human_review_required": True,
        "tool_execution_performed": False,
    }
    encrypted, digest = cipher.encrypt(value)
    store = FakeWorkerStore(
        result=("test-v1", encrypted, digest),
        tasks=[task],
    )

    recovered = await reconcile_outcome_unknown_once(
        store=store,
        cipher=cipher,
        tenant_id=task.tenant_id,
    )

    assert recovered == 1
    assert len(store.transitions) == 1
    call = store.transitions[0]
    assert call["target"] is TaskState.VERIFYING
    assert call["actor_id"] == "system:notebook-result-reconciler"
    assert call["reconciliation_verified"] is True
    assert call["metadata"]["evidence_digest"] == digest


@pytest.mark.asyncio
async def test_unknown_task_without_persisted_result_stays_quarantined():
    cipher = make_cipher()
    task = make_task(state=TaskState.OUTCOME_UNKNOWN)
    store = FakeWorkerStore(result=None, tasks=[task])

    recovered = await reconcile_outcome_unknown_once(
        store=store,
        cipher=cipher,
        tenant_id=task.tenant_id,
    )

    assert recovered == 0
    assert store.transitions == []
