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
    # Create the task under the same verified tenant used by the cross-project
    # assertion; otherwise tenant isolation masks the project authorization path.
    app.dependency_overrides[get_current_principal] = lambda: principal()
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
    assert response.status_code == 403


def _create_task(client, key: str):
    response = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": key},
        json=payload(),
    )
    assert response.status_code == 202, response.text
    return __import__("uuid").UUID(response.json()["task_id"])


def test_task_submission_maps_store_validation_and_persistence_errors(runtime, monkeypatch):
    store, _cipher = runtime
    client = TestClient(app)

    async def invalid_create(**_kwargs):
        raise ValueError("private persistence detail")

    monkeypatch.setattr(store, "create_task", invalid_create)
    invalid = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-101"},
        json=payload(),
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "task_payload_invalid"

    async def unavailable_create(**_kwargs):
        raise RuntimeError("database credentials must not leak")

    monkeypatch.setattr(store, "create_task", unavailable_create)
    unavailable = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-102"},
        json=payload(),
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "workflow_task_persistence_unavailable"
    assert "database credentials" not in unavailable.text


def test_task_submission_maps_worker_registry_unavailability(runtime, monkeypatch):
    store, _cipher = runtime
    client = TestClient(app)

    async def registry_unavailable(**_kwargs):
        raise RuntimeError("private worker registry detail")

    monkeypatch.setattr(store, "has_healthy_worker", registry_unavailable)
    response = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": "notebook-task-103"},
        json=payload(),
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "notebook_worker_registry_unavailable"
    assert "private worker registry detail" not in response.text


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/v1/tasks", payload()),
        ("GET", "/api/v1/tasks/00000000-0000-0000-0000-000000000001", None),
        ("GET", "/api/v1/tasks/00000000-0000-0000-0000-000000000001/result", None),
        ("POST", "/api/v1/tasks/00000000-0000-0000-0000-000000000001/cancel", None),
    ],
)
def test_all_task_routes_fail_closed_when_runtime_is_missing(runtime, method, path, body):
    app.state.workflow_task_store = None
    client = TestClient(app)
    response = client.request(
        method,
        path,
        headers={"Idempotency-Key": "notebook-task-104"} if method == "POST" and path.endswith("/tasks") else {},
        json=body,
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "workflow_task_runtime_unavailable"


def test_task_status_maps_missing_rows_database_errors_and_missing_project_scope(runtime, monkeypatch):
    store, _cipher = runtime
    client = TestClient(app)
    task_id = _create_task(client, "notebook-task-105")

    async def missing(**_kwargs):
        raise TaskNotFound("private task id")

    monkeypatch.setattr(store, "get_task", missing)
    not_found = client.get(f"/api/v1/tasks/{task_id}")
    assert not_found.status_code == 404
    assert not_found.json()["detail"] == "Task not found"

    async def unavailable(**_kwargs):
        raise RuntimeError("private database detail")

    monkeypatch.setattr(store, "get_task", unavailable)
    failed_read = client.get(f"/api/v1/tasks/{task_id}")
    assert failed_read.status_code == 503
    assert failed_read.json()["detail"]["code"] == "workflow_task_read_unavailable"

    monkeypatch.undo()
    task = store.tasks[store.by_id[task_id]]
    task.project_id = None
    missing_project = client.get(f"/api/v1/tasks/{task_id}")
    assert missing_project.status_code == 404


def test_status_correlation_id_fallback_and_invalid_state_are_explicit():
    from app.task_api import _public_state, _status

    request_id = uuid4()
    value = SimpleNamespace(
        task_id=uuid4(),
        metadata={"correlation_id": "not-a-uuid"},
        correlation_id=None,
        project_id="project-a",
        state=TaskState.RECEIVED,
        version=1,
        retry_count=0,
        retryable=False,
        error_code=None,
        created_at=None,
        updated_at=None,
    )
    assert _status(value, request_id).correlation_id == request_id

    valid_correlation = uuid4()
    value.metadata = {"correlation_id": str(valid_correlation)}
    assert _status(value, request_id).correlation_id == valid_correlation

    value.state = "not-a-state"
    with pytest.raises(ValueError):
        _public_state(value)


def test_task_result_maps_store_read_missing_cipher_and_contract_errors(runtime, monkeypatch):
    store, cipher = runtime
    client = TestClient(app)
    task_id = _create_task(client, "notebook-task-106")
    task = store.tasks[store.by_id[task_id]]
    task.state = TaskState.SUCCEEDED

    async def unavailable_result(**_kwargs):
        raise RuntimeError("private result store detail")

    monkeypatch.setattr(store, "get_encrypted_result", unavailable_result)
    unavailable = client.get(f"/api/v1/tasks/{task_id}/result")
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "notebook_task_result_read_unavailable"

    async def missing_result(**_kwargs):
        return None

    monkeypatch.setattr(store, "get_encrypted_result", missing_result)
    missing = client.get(f"/api/v1/tasks/{task_id}/result")
    assert missing.status_code == 503
    assert missing.json()["detail"]["code"] == "notebook_task_result_missing"

    async def invalid_result(**_kwargs):
        return (cipher.key_id, b"tampered", "a" * 64)

    monkeypatch.setattr(store, "get_encrypted_result", invalid_result)
    integrity = client.get(f"/api/v1/tasks/{task_id}/result")
    assert integrity.status_code == 503
    assert integrity.json()["detail"]["code"] == "notebook_task_result_integrity_failure"

    valid_but_wrong_contract, digest = cipher.encrypt(
        {
            "task_id": str(task_id),
            "project_id": "project-a",
            "verification_status": "verified",
            "human_review_required": False,
            "tool_execution_performed": True,
        }
    )

    async def wrong_contract(**_kwargs):
        return (cipher.key_id, valid_but_wrong_contract, digest)

    monkeypatch.setattr(store, "get_encrypted_result", wrong_contract)
    contract = client.get(f"/api/v1/tasks/{task_id}/result")
    assert contract.status_code == 503
    assert contract.json()["detail"]["code"] == "notebook_task_result_contract_invalid"


def test_task_result_maps_missing_task_and_database_errors(runtime, monkeypatch):
    store, _cipher = runtime
    client = TestClient(app)
    task_id = _create_task(client, "notebook-task-107")

    async def missing(**_kwargs):
        raise TaskNotFound("not found")

    monkeypatch.setattr(store, "get_task", missing)
    response = client.get(f"/api/v1/tasks/{task_id}/result")
    assert response.status_code == 404

    async def unavailable(**_kwargs):
        raise RuntimeError("private database error")

    monkeypatch.setattr(store, "get_task", unavailable)
    response = client.get(f"/api/v1/tasks/{task_id}/result")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "workflow_task_read_unavailable"


@pytest.mark.parametrize(
    ("state", "status_code", "error_code"),
    [
        (TaskState.SUCCEEDED, 409, "task_already_terminal"),
        (TaskState.OUTCOME_UNKNOWN, 409, "task_outcome_requires_reconciliation"),
        (TaskState.EXECUTING, 409, "task_stage_requires_cooperative_cancellation"),
    ],
)
def test_task_cancellation_rejects_terminal_unknown_and_inflight_states(
    runtime, state, status_code, error_code
):
    store, _cipher = runtime
    client = TestClient(app)
    task_id = _create_task(client, f"notebook-task-{state.value[:12]}")
    store.tasks[store.by_id[task_id]].state = state
    response = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == error_code


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (StaleWorkflowVersion("stale"), 409, "task_state_changed_retry_read"),
        (TransitionDenied("not allowed"), 409, "task_cancellation_not_allowed"),
        (ValueError("invalid transition"), 409, "task_cancellation_not_allowed"),
        (RuntimeError("database unavailable"), 503, "workflow_task_cancel_unavailable"),
    ],
)
def test_task_cancellation_maps_transition_conflicts_and_storage_failures(
    runtime, monkeypatch, error, status_code, error_code
):
    store, _cipher = runtime
    client = TestClient(app)
    task_id = _create_task(client, "notebook-task-108")

    async def fail_transition(**_kwargs):
        raise error

    monkeypatch.setattr(store, "transition", fail_transition)
    response = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == error_code


def test_failed_task_can_be_cancelled_before_retry_is_claimed(runtime):
    store, _cipher = runtime
    client = TestClient(app)
    task_id = _create_task(client, "notebook-task-109")
    store.tasks[store.by_id[task_id]].state = TaskState.FAILED
    response = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert response.status_code == 200
    assert response.json()["state"] == "cancelled"
