from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.notebook_task_worker as notebook_worker
from app.notebook_task_worker import (
    NotebookReasoningTaskHandler,
    reconcile_outcome_unknown_once,
)
from ugai_workflow.input_vault import WorkflowInputNotFound
from ugai_workflow.state_machine import TaskState
from ugai_workflow.worker import ExternalOutcomeUnknown


class FakeInputs:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


class FakeResults:
    def __init__(self):
        self.rows = {}
        self.put_calls = []

    async def put(self, **kwargs):
        self.put_calls.append(kwargs)
        task_id = kwargs["task_id"]
        self.rows[task_id] = dict(kwargs["payload"])
        return "a" * 64

    async def get(self, *, task_id, **kwargs):
        if task_id not in self.rows:
            raise WorkflowInputNotFound("workflow_result_not_found")
        return dict(self.rows[task_id])


class FakeStore:
    def __init__(self, *, workspace_bound: bool = True):
        self.workspace_bound = workspace_bound
        self.transitions = []
        self.unknown_tasks = []

    async def workspace_is_bound(self, **kwargs):
        return self.workspace_bound

    async def list_outcome_unknown(self, **kwargs):
        return list(self.unknown_tasks)

    async def transition(self, **kwargs):
        self.transitions.append(kwargs)
        return SimpleNamespace(state=kwargs["target"])


class FakeRuntime:
    def __init__(self, payload, *, workspace_bound=True):
        self.inputs = FakeInputs(payload)
        self.results = FakeResults()
        self.store = FakeStore(workspace_bound=workspace_bound)


def make_task(state: TaskState):
    task_id = uuid4()
    workspace_id = str(uuid4())
    project_id = "project-1"
    return SimpleNamespace(
        task_id=task_id,
        tenant_id="tenant-1",
        actor_id="principal:" + "a" * 64,
        task_type="notebook_request",
        state=state,
        metadata={
            "context_ref": str(uuid4()),
            "project_id": project_id,
            "workspace_id": workspace_id,
        },
    )


def make_payload(task):
    return {
        "workspace_id": task.metadata["workspace_id"],
        "intent": "Explain the strategic options and their risks.",
        "requested_capabilities": ["reasoning.read"],
        "artifacts": [],
        "cell_revision": "cell-rev-1",
    }


def fake_execution():
    evaluator = SimpleNamespace(
        route_id="evaluator-route",
        provider="provider-b",
        model_id="model-b",
        model_revision="b" * 40,
    )
    primary = SimpleNamespace(
        route_id="primary-route",
        provider="provider-a",
        model_id="model-a",
        model_revision="a" * 40,
    )
    return SimpleNamespace(
        decision=SimpleNamespace(independent_evaluator=evaluator),
        completion=SimpleNamespace(final_content="A candidate answer."),
        independent_evaluation=SimpleNamespace(final_content="A critical independent review."),
        execution_route=primary,
        fallback_used=False,
    )


def patch_executor(monkeypatch, *, failure: Exception | None = None):
    calls = []

    class FakeExecutor:
        def __init__(self, *, router, routes):
            assert router is not None
            assert routes

        async def execute(self, *, request, requirements):
            calls.append((request, requirements))
            if failure is not None:
                raise failure
            return fake_execution()

    monkeypatch.setattr(
        notebook_worker,
        "load_approved_text_routes",
        _approved_routes,
    )
    monkeypatch.setattr(notebook_worker.TextModelRouter, "from_settings", lambda: object())
    monkeypatch.setattr(notebook_worker, "PolicyRoutedTextExecutor", FakeExecutor)
    return calls


async def _approved_routes():
    return [object()]


@pytest.mark.asyncio
async def test_notebook_worker_persists_result_then_verifies_before_success(monkeypatch):
    calls = patch_executor(monkeypatch)
    task = make_task(TaskState.EXECUTING)
    runtime = FakeRuntime(make_payload(task))
    handler = NotebookReasoningTaskHandler(runtime=runtime)

    outcome = await handler.handle(task)
    assert outcome.next_state is TaskState.VERIFYING
    assert len(calls) == 1
    assert len(runtime.results.put_calls) == 1

    result = runtime.results.rows[task.task_id]
    assert result["human_review_required"] is True
    assert result["verification_status"] == "needs_human_review"
    assert result["tool_execution_performed"] is False
    assert result["evidence_grounding"] == "not_performed"

    task.state = TaskState.VERIFYING
    verified = await handler.handle(task)
    assert verified.next_state is TaskState.SUCCEEDED
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_notebook_worker_reuses_persisted_result_without_calling_provider(monkeypatch):
    calls = patch_executor(monkeypatch)
    task = make_task(TaskState.EXECUTING)
    runtime = FakeRuntime(make_payload(task))
    runtime.results.rows[task.task_id] = {
        "schema_version": "1",
        "task_id": str(task.task_id),
        "project_id": task.metadata["project_id"],
        "workspace_id": task.metadata["workspace_id"],
        "candidate_answer": "Previously stored answer.",
        "independent_review": "Previously stored review.",
        "selected_route": {"route_id": "primary"},
        "evaluator_route": {"route_id": "review"},
        "verification_status": "needs_human_review",
        "human_review_required": True,
        "tool_execution_performed": False,
        "evidence_grounding": "not_performed",
    }

    outcome = await NotebookReasoningTaskHandler(runtime=runtime).handle(task)

    assert outcome.next_state is TaskState.VERIFYING
    assert calls == []
    assert runtime.results.put_calls == []


@pytest.mark.asyncio
async def test_notebook_worker_blocks_when_workspace_binding_is_revoked(monkeypatch):
    calls = patch_executor(monkeypatch)
    task = make_task(TaskState.EXECUTING)
    runtime = FakeRuntime(make_payload(task), workspace_bound=False)

    outcome = await NotebookReasoningTaskHandler(runtime=runtime).handle(task)

    assert outcome.next_state is TaskState.BLOCKED
    assert outcome.error_code == "notebook_workspace_binding_revoked"
    assert runtime.inputs.calls == []
    assert calls == []


@pytest.mark.asyncio
async def test_notebook_worker_blocks_unresolved_artifacts_before_provider(monkeypatch):
    calls = patch_executor(monkeypatch)
    task = make_task(TaskState.EXECUTING)
    payload = make_payload(task)
    payload["artifacts"] = [{"uri": "client://unverified-artifact"}]
    runtime = FakeRuntime(payload)

    outcome = await NotebookReasoningTaskHandler(runtime=runtime).handle(task)

    assert outcome.next_state is TaskState.BLOCKED
    assert outcome.error_code == "notebook_artifact_resolver_not_configured"
    assert calls == []


@pytest.mark.asyncio
async def test_notebook_worker_quarantines_uncertain_provider_error(monkeypatch):
    patch_executor(monkeypatch, failure=TimeoutError("provider response timed out"))
    task = make_task(TaskState.EXECUTING)
    runtime = FakeRuntime(make_payload(task))

    with pytest.raises(ExternalOutcomeUnknown):
        await NotebookReasoningTaskHandler(runtime=runtime).handle(task)

    assert runtime.results.put_calls == []


@pytest.mark.asyncio
async def test_outcome_unknown_reconciler_requires_existing_valid_encrypted_result():
    task = make_task(TaskState.OUTCOME_UNKNOWN)
    runtime = FakeRuntime(make_payload(task))
    runtime.store.unknown_tasks = [task]

    assert await reconcile_outcome_unknown_once(runtime, tenant_id=task.tenant_id) == 0
    assert runtime.store.transitions == []

    runtime.results.rows[task.task_id] = {
        "schema_version": "1",
        "task_id": str(task.task_id),
        "project_id": task.metadata["project_id"],
        "workspace_id": task.metadata["workspace_id"],
        "candidate_answer": "Persisted answer.",
        "independent_review": "Persisted review.",
        "selected_route": {"route_id": "primary"},
        "evaluator_route": {"route_id": "review"},
        "verification_status": "needs_human_review",
        "human_review_required": True,
        "tool_execution_performed": False,
        "evidence_grounding": "not_performed",
    }

    assert await reconcile_outcome_unknown_once(runtime, tenant_id=task.tenant_id) == 1
    transition = runtime.store.transitions[0]
    assert transition["target"] is TaskState.VERIFYING
    assert transition["require_lease"] is False
    assert transition["reconciliation_verified"] is True
    assert len(transition["metadata"]["evidence_digest"]) == 64
