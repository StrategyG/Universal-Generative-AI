from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import Principal, get_current_principal
from app.workflow_tasks import _runtime, router
from ugai_workflow.input_vault import StoredWorkflowInput
from ugai_workflow.state_machine import TaskState


class FakeInputVault:
    def __init__(self) -> None:
        self.items: dict[UUID, StoredWorkflowInput] = {}
        self.payloads: dict[UUID, dict] = {}

    async def put(self, **kwargs) -> StoredWorkflowInput:
        input_ref = uuid4()
        record = StoredWorkflowInput(
            input_ref=input_ref,
            input_digest="a" * 64,
            project_id=kwargs["project_id"],
            workspace_id=kwargs["workspace_id"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        self.items[input_ref] = record
        self.payloads[input_ref] = dict(kwargs["payload"])
        return record

    async def get_metadata(self, *, input_ref: UUID, tenant_id: str, actor_id: str):
        if actor_id != "actor-1" or input_ref not in self.items:
            from ugai_workflow.input_vault import WorkflowInputNotFound
            raise WorkflowInputNotFound("workflow_input_not_found")
        return self.items[input_ref]


class FakeWorkflowStore:
    def __init__(self) -> None:
        self.tasks: dict[UUID, SimpleNamespace] = {}

    async def has_active_worker(self, *, tenant_id: str, task_type: str, max_age_seconds: int = 60):
        return True

    async def create_task(self, **kwargs):
        task_id = uuid4()
        task = SimpleNamespace(
            task_id=task_id,
            tenant_id=kwargs["tenant_id"],
            actor_id=kwargs["actor_id"],
            state=TaskState.RECEIVED,
            version=1,
            metadata=dict(kwargs["metadata"]),
            error_code=None,
            created_at=datetime.now(timezone.utc),
        )
        self.tasks[task_id] = task
        return task

    async def get_task(self, *, task_id: UUID, tenant_id: str):
        return self.tasks[task_id]

    async def transition(self, *, task_id: UUID, target: TaskState, **kwargs):
        task = self.tasks[task_id]
        task.state = target
        task.version += 1
        return task


class FakeResultVault:
    async def get(self, **kwargs):
        return {
            "task_id": str(kwargs["task_id"]),
            "verification_status": "needs_human_review",
            "human_review_required": True,
            "candidate_answer": "candidate",
        }


class FakeWorkflowRuntime:
    def __init__(self, *, enabled: bool = True, task_types: frozenset[str] = frozenset({"notebook_request"})):
        self.pool = object()
        self.inputs = FakeInputVault()
        self.store = FakeWorkflowStore()
        self.results = FakeResultVault()
        self.task_acceptance_enabled = enabled
        self.enabled_task_types = task_types


def _client(runtime: FakeWorkflowRuntime) -> TestClient:
    principal = Principal(
        subject="actor-1",
        tenant_id="tenant-1",
        roles=frozenset({"developer"}),
        project_ids=frozenset({"project-1"}),
        auth_mode="oidc",
        issuer="https://identity.example/",
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[_runtime] = lambda: runtime
    return TestClient(app)


def test_task_input_and_lifecycle_api_never_returns_raw_input() -> None:
    runtime = FakeWorkflowRuntime()
    with _client(runtime) as client:
        input_response = client.post(
            "/api/v1/task-inputs",
            headers={"Idempotency-Key": "input-request-0001"},
            json={
                "project_id": "project-1",
                "workspace_id": str(uuid4()),
                "notebook_id": str(uuid4()),
                "intent": "sensitive notebook task content",
                "requested_capabilities": ["reasoning.read"],
            },
        )
        assert input_response.status_code == 201
        input_body = input_response.json()
        assert input_body["input_digest"] == "a" * 64
        assert "sensitive notebook task content" not in input_response.text

        request_id = str(uuid4())
        submit_response = client.post(
            "/api/v1/tasks",
            headers={
                "X-Request-ID": request_id,
                "Idempotency-Key": "notebook-task-0001",
            },
            json={
                "project_id": "project-1",
                "input_ref": input_body["input_ref"],
                "input_digest": input_body["input_digest"],
                "task_type": "notebook_request",
            },
        )
        assert submit_response.status_code == 202
        receipt = submit_response.json()
        assert receipt["request_id"] == request_id
        assert receipt["state"] == "ACCEPTED"
        assert receipt["created_at"] is not None

        task_id = receipt["task_id"]
        status_response = client.get(f"/api/v1/tasks/{task_id}")
        assert status_response.status_code == 200
        assert status_response.json()["state"] == "ACCEPTED"

        cancel_response = client.post(f"/api/v1/tasks/{task_id}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["state"] == "CANCELLED"


def test_unknown_outcome_is_projected_without_server_error() -> None:
    runtime = FakeWorkflowRuntime()
    with _client(runtime) as client:
        response = client.post(
            "/api/v1/task-inputs",
            headers={"Idempotency-Key": "input-unknown-state-01"},
            json={
                "project_id": "project-1",
                "workspace_id": str(uuid4()),
                "intent": "uncertain external operation",
            },
        )
        assert response.status_code == 201
        body = response.json()
        submitted = client.post(
            "/api/v1/tasks",
            headers={
                "X-Request-ID": str(uuid4()),
                "Idempotency-Key": "notebook-unknown-state-01",
            },
            json={
                "project_id": "project-1",
                "input_ref": body["input_ref"],
                "input_digest": body["input_digest"],
                "task_type": "notebook_request",
            },
        )
        task_id = UUID(submitted.json()["task_id"])
        runtime.store.tasks[task_id].state = TaskState.OUTCOME_UNKNOWN

        status_response = client.get(f"/api/v1/tasks/{task_id}")

    assert status_response.status_code == 200
    assert status_response.json()["state"] == "OUTCOME_UNKNOWN"


def test_non_owner_cannot_cancel_another_users_task() -> None:
    runtime = FakeWorkflowRuntime()
    with _client(runtime) as client:
        input_response = client.post(
            "/api/v1/task-inputs",
            headers={"Idempotency-Key": "input-owner-check-01"},
            json={
                "project_id": "project-1",
                "workspace_id": str(uuid4()),
                "intent": "task owned by another user",
            },
        )
        input_body = input_response.json()
        submission = client.post(
            "/api/v1/tasks",
            headers={
                "X-Request-ID": str(uuid4()),
                "Idempotency-Key": "notebook-owner-check-01",
            },
            json={
                "project_id": "project-1",
                "input_ref": input_body["input_ref"],
                "input_digest": input_body["input_digest"],
                "task_type": "notebook_request",
            },
        )
        task_id = UUID(submission.json()["task_id"])
        runtime.store.tasks[task_id].actor_id = "different-owner"

        response = client.post(f"/api/v1/tasks/{task_id}/cancel")

    assert response.status_code == 404
    assert runtime.store.tasks[task_id].state is TaskState.RECEIVED


def test_task_submission_requires_fresh_registered_worker() -> None:
    runtime = FakeWorkflowRuntime()
    runtime.store.has_active_worker = lambda **kwargs: _async_false()
    with _client(runtime) as client:
        input_response = client.post(
            "/api/v1/task-inputs",
            headers={"Idempotency-Key": "input-no-worker-0001"},
            json={
                "project_id": "project-1",
                "workspace_id": str(uuid4()),
                "intent": "must not queue without worker",
            },
        )
        body = input_response.json()
        response = client.post(
            "/api/v1/tasks",
            headers={
                "X-Request-ID": str(uuid4()),
                "Idempotency-Key": "notebook-no-worker-0001",
            },
            json={
                "project_id": "project-1",
                "input_ref": body["input_ref"],
                "input_digest": body["input_digest"],
                "task_type": "notebook_request",
            },
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "task_worker_unavailable"
    assert runtime.store.tasks == {}


async def _async_false():
    return False


def test_task_api_is_fail_closed_when_acceptance_is_disabled() -> None:
    with _client(FakeWorkflowRuntime(enabled=False)) as client:
        response = client.post(
            "/api/v1/task-inputs",
            headers={"Idempotency-Key": "input-request-0002"},
            json={
                "project_id": "project-1",
                "workspace_id": str(uuid4()),
                "intent": "must not be accepted",
            },
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "workflow_task_acceptance_disabled"


def test_unregistered_task_type_is_rejected() -> None:
    runtime = FakeWorkflowRuntime(task_types=frozenset())
    with _client(runtime) as client:
        input_response = client.post(
            "/api/v1/task-inputs",
            headers={"Idempotency-Key": "input-request-0003"},
            json={
                "project_id": "project-1",
                "workspace_id": str(uuid4()),
                "intent": "authorized but not executable",
            },
        )
        assert input_response.status_code == 201
        body = input_response.json()
        response = client.post(
            "/api/v1/tasks",
            headers={
                "X-Request-ID": str(uuid4()),
                "Idempotency-Key": "notebook-task-0003",
            },
            json={
                "project_id": "project-1",
                "input_ref": body["input_ref"],
                "input_digest": body["input_digest"],
                "task_type": "notebook_request",
            },
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "task_type_not_enabled"
