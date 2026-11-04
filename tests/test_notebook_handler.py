from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.tasks.notebook_handler import NotebookReasoningTaskHandler
from ugai_workflow.postgres_store import TaskNotFound
from ugai_workflow.state_machine import TaskState


class FakeTaskService:
    def __init__(self, payload=None, result=None) -> None:
        self.payload = payload or {}
        self.result = result
        self.saved_result = None

    async def load_result(self, **_kwargs):
        if self.result is None:
            raise TaskNotFound("missing")
        return self.result

    async def load_payload(self, **_kwargs):
        return self.payload

    async def save_result(self, **_kwargs):
        self.saved_result = _kwargs["result"]
        self.result = self.saved_result


def _task(state: TaskState, *, workspace_id: str | None = None):
    return SimpleNamespace(
        task_id=uuid4(),
        task_type="notebook.request",
        state=state,
        tenant_id="tenant-1",
        actor_id="actor-1",
        metadata={"workspace_id": workspace_id or str(uuid4())},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (TaskState.RECEIVED, TaskState.OBSERVING),
        (TaskState.OBSERVING, TaskState.PLANNING),
        (TaskState.PLANNING, TaskState.EXECUTING),
    ],
)
async def test_notebook_task_advances_only_through_durable_policy_states(
    current: TaskState, expected: TaskState
) -> None:
    handler = NotebookReasoningTaskHandler(task_service=FakeTaskService())
    outcome = await handler.handle(_task(current))
    assert outcome.next_state is expected


@pytest.mark.asyncio
async def test_notebook_task_blocks_unimplemented_tool_capability() -> None:
    service = FakeTaskService(
        payload={
            "intent": "Search the internet",
            "context": "",
            "workspace_id": str(uuid4()),
            "requested_capabilities": ["browser"],
        }
    )
    handler = NotebookReasoningTaskHandler(task_service=service)
    outcome = await handler.handle(_task(TaskState.EXECUTING))
    assert outcome.next_state is TaskState.BLOCKED
    assert outcome.error_code == "notebook_capability_not_configured"
    assert service.saved_result is None


@pytest.mark.asyncio
async def test_notebook_task_blocks_artifacts_until_trusted_resolver_exists() -> None:
    service = FakeTaskService(
        payload={
            "intent": "Summarize this file",
            "context": "",
            "workspace_id": str(uuid4()),
            "artifacts": [
                {
                    "artifact_id": "file-1",
                    "sha256": "a" * 64,
                    "media_type": "text/plain",
                }
            ],
        }
    )
    handler = NotebookReasoningTaskHandler(task_service=service)
    outcome = await handler.handle(_task(TaskState.EXECUTING))
    assert outcome.next_state is TaskState.BLOCKED
    assert outcome.error_code == "notebook_artifact_resolver_not_configured"


@pytest.mark.asyncio
async def test_notebook_task_verifies_result_before_success() -> None:
    task = _task(TaskState.VERIFYING)
    service = FakeTaskService(
        result={
            "task_id": str(task.task_id),
            "workspace_id": task.metadata["workspace_id"],
            "candidate_answer": "Candidate",
            "independent_review": "Review",
            "selected_route": {"route_id": "primary"},
            "evaluator_route": {"route_id": "evaluator"},
            "verification_status": "needs_human_review",
            "human_review_required": True,
        }
    )
    handler = NotebookReasoningTaskHandler(task_service=service)
    outcome = await handler.handle(task)
    assert outcome.next_state is TaskState.SUCCEEDED
    assert outcome.reason_code == "notebook_reasoning_result_verified"


@pytest.mark.asyncio
async def test_notebook_task_does_not_succeed_without_persisted_result() -> None:
    task = _task(TaskState.VERIFYING)
    handler = NotebookReasoningTaskHandler(task_service=FakeTaskService())
    outcome = await handler.handle(task)
    assert outcome.next_state is TaskState.BLOCKED
    assert outcome.error_code == "notebook_result_missing"
