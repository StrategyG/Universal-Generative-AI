from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet

from app.auth import Principal, get_current_principal
from app.main import app
from ugai_workflow.payload_cipher import TaskPayloadCipher
from ugai_workflow.postgres_store import IdempotencyConflict, StaleWorkflowVersion, TaskNotFound
from ugai_workflow.state_machine import TaskState, validate_transition


class MemoryWorkflowStore:
    """Small deterministic adapter for API contract tests; no production DB claims."""

    def __init__(self) -> None:
        self.tasks: dict[tuple[str, object], SimpleNamespace] = {}
        self.by_id: dict[object, tuple[str, object]] = {}
        self.payloads: dict[object, tuple[str, bytes, str]] = {}
        self.results: dict[object, tuple[str, bytes, str]] = {}
        self.healthy_worker = True
        self.transition_calls = 0

    async def create_task(self, **values):
        key = (values["tenant_id"], values["idempotency_key"])
        current = self.tasks.get(key)
        if current is not None:
            if (
                current.input_digest != values["input_digest"]
                or current.project_id != values["project_id"]
                or current.actor_id != values["actor_id"]
                or current.task_type != values["task_type"]
            ):
                raise IdempotencyConflict("idempotency_key_payload_mismatch")
            return current

        now = datetime.now(UTC)
        task = SimpleNamespace(
            task_id=values["task_id"],
            tenant_id=values["tenant_id"],
            actor_id=values["actor_id"],
            task_type=values["task_type"],
            state=TaskState.RECEIVED,
            version=0,
            retry_count=0,
            max_retries=values["max_retries"],
            retryable=False,
            idempotency_key=values["idempotency_key"],
            input_digest=values["input_digest"],
            priority=values["priority"],
            available_at=now,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            approval_reference=None,
            decision_digest=None,
            plan_digest=None,
            error_code=None,
            metadata=values["metadata"],
            project_id=values["project_id"],
            correlation_id=values["correlation_id"],
            created_at=now,
            updated_at=now,
        )
        self.tasks[key] = task
        self.by_id[task.task_id] = key
        self.payloads[task.task_id] = (
            values["payload_key_id"],
            values["encrypted_payload"],
            values["payload_sha256"],
        )
        return task

    async def get_task(self, *, task_id, tenant_id):
        key = self.by_id.get(task_id)
        if key is None or key[0] != tenant_id:
            raise TaskNotFound(str(task_id))
        return self.tasks[key]

    async def has_healthy_worker(self, **_kwargs):
        return self.healthy_worker

    async def get_encrypted_result(self, *, tenant_id, task_id):
        key = self.by_id.get(task_id)
        if key is None or key[0] != tenant_id:
            return None
        return self.results.get(task_id)

    async def transition(
        self, *, task_id, tenant_id, expected_version, target, actor_id,
        reason_code, require_lease=True, **_kwargs
    ):
        task = await self.get_task(task_id=task_id, tenant_id=tenant_id)
        if task.version != expected_version:
            raise StaleWorkflowVersion("stale")
        validate_transition(task.state, target)
        if require_lease:
            raise AssertionError("API cancellation must not impersonate a worker lease")
        self.transition_calls += 1
        task.state = target
        task.version += 1
        task.updated_at = datetime.now(UTC)
        task.retryable = False
        task.error_code = None
        return task


@pytest.fixture
def runtime():
    old_store = getattr(app.state, "workflow_task_store", None)
    old_cipher = getattr(app.state, "workflow_task_payload_cipher", None)
    store = MemoryWorkflowStore()
    cipher = TaskPayloadCipher(Fernet.generate_key().decode("ascii"), key_id="test-v1")
    app.state.workflow_task_store = store
    app.state.workflow_task_payload_cipher = cipher
    try:
        yield store, cipher
    finally:
        app.state.workflow_task_store = old_store
        app.state.workflow_task_payload_cipher = old_cipher
        app.dependency_overrides.clear()


def payload(*, intent: str = "Summarize this notebook") -> dict:
    return {
        "project_id": "project-a",
        "workspace_id": str(uuid4()),
        "notebook_id": str(uuid4()),
        "cell_revision": "rev-1",
        "intent": intent,
        "artifacts": [],
        "requested_capabilities": ["reasoning:read"],
    }


def principal(*, tenant: str = "tenant-a", roles: set[str] | None = None) -> Principal:
    return Principal(
        subject="user-a",
        tenant_id=tenant,
        roles=frozenset(roles or {"developer"}),
        project_ids=frozenset({"project-a"}),
        auth_mode="oidc",
    )


def test_submit_task_persists_only_encrypted_payload_and_returns_contract_state(runtime):
    store, cipher = runtime
    request_id = uuid4()
    client = TestClient(app)

    response = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-0001", "X-Request-ID": str(request_id)},
        json=payload(intent="Private notebook prompt that must not be stored as plaintext"),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "queued"
    assert body["request_id"] == str(request_id)
    assert body["contract_version"] == "1.0.0"
    task_id = body["task_id"]
    key_id, ciphertext, digest = store.payloads[__import__("uuid").UUID(task_id)]
    assert key_id == "test-v1"
    assert b"Private notebook prompt" not in ciphertext
    decrypted = cipher.decrypt(ciphertext, expected_sha256=digest)
    assert decrypted["intent"].startswith("Private notebook prompt")
    assert store.tasks[("local-development", "notebook-task-0001")].metadata["context_ref"].endswith(task_id)


def test_idempotent_replay_returns_same_task_and_changed_payload_conflicts(runtime):
    store, _cipher = runtime
    client = TestClient(app)
    headers = {"Idempotency-Key": "notebook-task-0002"}

    request_body = payload()
    first = client.post("/api/v1/tasks", headers=headers, json=request_body)
    replay = client.post("/api/v1/tasks", headers=headers, json=request_body)
    changed_body = {**request_body, "intent": "A different request must not reuse the old task"}
    changed = client.post("/api/v1/tasks", headers=headers, json=changed_body)

    assert first.status_code == 202
    assert replay.status_code == 202
    assert first.json()["task_id"] == replay.json()["task_id"]
    assert changed.status_code == 409
    assert len(store.tasks) == 1
    assert len(store.payloads) == 1


def test_client_cannot_spoof_tenant_actor_or_role(runtime):
    client = TestClient(app)
    body = {**payload(), "tenant_id": "tenant-victim", "actor_id": "platform-admin", "role": "owner"}
    response = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-0003"},
        json=body,
    )
    assert response.status_code == 422


def test_task_status_is_tenant_scoped_and_does_not_disclose_other_tenant(runtime):
    _store, _cipher = runtime
    client = TestClient(app)
    created = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-0004"},
        json=payload(),
    )
    assert created.status_code == 202
    task_id = created.json()["task_id"]

    app.dependency_overrides[get_current_principal] = lambda: principal(
        tenant="tenant-b", roles={"read_only"}
    )
    try:
        response = client.get(f"/api/v1/tasks/{task_id}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


def test_task_cancellation_is_idempotent_for_queued_tasks(runtime):
    store, _cipher = runtime
    client = TestClient(app)
    created = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-0005"},
        json=payload(),
    )
    task_id = created.json()["task_id"]

    cancelled = client.post(f"/api/v1/tasks/{task_id}/cancel")
    repeated = client.post(f"/api/v1/tasks/{task_id}/cancel")

    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert repeated.status_code == 200
    assert repeated.json()["state"] == "cancelled"
    assert store.transition_calls == 1


def test_task_cancellation_denied_for_running_stage_until_worker_cooperation(runtime):
    store, _cipher = runtime
    client = TestClient(app)
    created = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-0006"},
        json=payload(),
    )
    task_id = __import__("uuid").UUID(created.json()["task_id"])
    task = store.tasks[("local-development", "notebook-task-0006")]
    task.state = TaskState.EXECUTING

    response = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "task_stage_requires_cooperative_cancellation"
    assert store.transition_calls == 0


def test_read_only_member_can_read_but_cannot_cancel_task(runtime):
    _store, _cipher = runtime
    client = TestClient(app)
    created = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-0007"},
        json=payload(),
    )
    task_id = created.json()["task_id"]
    app.dependency_overrides[get_current_principal] = lambda: principal(tenant="local-development", roles={"read_only"})
    try:
        read = client.get(f"/api/v1/tasks/{task_id}")
        cancel = client.post(f"/api/v1/tasks/{task_id}/cancel")
    finally:
        app.dependency_overrides.clear()
    assert read.status_code == 200
    assert cancel.status_code == 403


def test_unknown_external_outcome_is_visible_and_cannot_be_cancelled(runtime):
    store, _cipher = runtime
    client = TestClient(app)
    created = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-0008"},
        json=payload(),
    )
    task_id = __import__("uuid").UUID(created.json()["task_id"])
    task = store.tasks[("local-development", "notebook-task-0008")]
    task.state = TaskState.OUTCOME_UNKNOWN
    task.error_code = "outcome_unknown"

    status_response = client.get(f"/api/v1/tasks/{task_id}")
    cancel_response = client.post(f"/api/v1/tasks/{task_id}/cancel")

    assert status_response.status_code == 200
    assert status_response.json()["state"] == "outcome_unknown"
    assert cancel_response.status_code == 409
    assert cancel_response.json()["detail"]["code"] == "task_outcome_requires_reconciliation"


def test_submit_task_fails_closed_when_dedicated_worker_is_unhealthy(runtime):
    store, _cipher = runtime
    store.healthy_worker = False
    client = TestClient(app)
    response = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-0009"},
        json=payload(),
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "notebook_worker_unavailable"
    assert store.tasks == {}


def test_task_result_is_decrypted_only_after_success_and_keeps_human_review_required(runtime):
    store, cipher = runtime
    client = TestClient(app)
    created = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-0010"},
        json=payload(),
    )
    assert created.status_code == 202
    task_id = __import__("uuid").UUID(created.json()["task_id"])
    key = store.by_id[task_id]
    task = store.tasks[key]
    result = {
        "task_id": str(task_id),
        "project_id": "project-a",
        "candidate_answer": "A candidate answer",
        "independent_review": "A separate critique",
        "verification_status": "needs_human_review",
        "human_review_required": True,
        "tool_execution_performed": False,
    }
    encrypted, digest = cipher.encrypt(result)
    store.results[task_id] = (cipher.key_id, encrypted, digest)

    not_ready = client.get(f"/api/v1/tasks/{task_id}/result")
    assert not_ready.status_code == 409
    task.state = TaskState.SUCCEEDED
    ready = client.get(f"/api/v1/tasks/{task_id}/result")
    assert ready.status_code == 200, ready.text
    assert ready.json()["result_sha256"] == digest
    assert ready.json()["result"]["candidate_answer"] == "A candidate answer"
    assert ready.json()["verification_status"] == "needs_human_review"
    assert ready.json()["human_review_required"] is True


def test_task_result_does_not_cross_project_scope(runtime):
    store, cipher = runtime
    client = TestClient(app)
    created = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-0011"},
        json=payload(),
    )
    task_id = __import__("uuid").UUID(created.json()["task_id"])
    key = store.by_id[task_id]
    task = store.tasks[key]
    task.state = TaskState.SUCCEEDED
    result = {
        "task_id": str(task_id),
        "project_id": "project-a",
        "candidate_answer": "answer",
        "independent_review": "review",
        "verification_status": "needs_human_review",
        "human_review_required": True,
        "tool_execution_performed": False,
    }
    encrypted, digest = cipher.encrypt(result)
    store.results[task_id] = (cipher.key_id, encrypted, digest)
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        subject="user-a", tenant_id="tenant-a", roles=frozenset({"read_only"}),
        project_ids=frozenset({"different-project"}), auth_mode="oidc",
    )
    try:
        response = client.get(f"/api/v1/tasks/{task_id}/result")
    finally:
        app.dependency_overrides.clear()
    # Cross-project resources are concealed as not found, avoiding existence leaks.
    assert response.status_code == 404
