from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.auth import Principal
from app.tasks.router import _assert_task_owner
from app.tasks.payloads import (
    EncryptedTaskPayload,
    TaskPayloadCipher,
    TaskPayloadIntegrityError,
)
from app.tasks.schemas import TaskSubmission
from app.tasks.service import TaskCancellationConflict, UGAITaskService
from ugai_workflow.state_machine import TaskState


def _submission() -> TaskSubmission:
    return TaskSubmission(
        intent="Explain the failing notebook cell",
        workspace_id=uuid4(),
        notebook_id=uuid4(),
        cell_revision="rev-17",
        requested_capabilities=("reasoning", "code_review"),
    )


def test_task_payload_encryption_is_authenticated_and_tenant_bound() -> None:
    cipher = TaskPayloadCipher(b"k" * 32, key_version="test-v1")
    task_id = uuid4()
    payload = {"intent": "private user content", "workspace_id": str(uuid4())}
    envelope = cipher.encrypt_json(payload, tenant_id="tenant-a", task_id=task_id)

    assert b"private user content" not in envelope.ciphertext
    assert cipher.decrypt_json(envelope, tenant_id="tenant-a", task_id=task_id) == payload

    with pytest.raises(TaskPayloadIntegrityError):
        cipher.decrypt_json(envelope, tenant_id="tenant-b", task_id=task_id)
    with pytest.raises(TaskPayloadIntegrityError):
        cipher.decrypt_json(envelope, tenant_id="tenant-a", task_id=uuid4())


def test_task_payload_cipher_rejects_invalid_key_material() -> None:
    with pytest.raises(ValueError, match="32_bytes"):
        TaskPayloadCipher(b"short", key_version="v1")
    with pytest.raises(ValueError, match="base64"):
        TaskPayloadCipher.from_base64("not valid base64!", key_version="v1")


def test_task_submission_rejects_client_supplied_identity() -> None:
    with pytest.raises(ValidationError):
        TaskSubmission.model_validate(
            {
                "intent": "Do work",
                "workspace_id": str(uuid4()),
                "tenant_id": "attacker-tenant",
                "actor_id": "attacker",
            }
        )


def test_task_submission_rejects_duplicate_capabilities() -> None:
    with pytest.raises(ValidationError, match="unique"):
        TaskSubmission(
            intent="Do work",
            workspace_id=uuid4(),
            requested_capabilities=("reasoning", "reasoning"),
        )


class CapturingStore:
    def __init__(self) -> None:
        self.calls = []
        self.task = None

    async def create_task(self, **kwargs):
        self.calls.append(kwargs)
        self.task = SimpleNamespace(
            task_id=kwargs["task_id"],
            state=TaskState.RECEIVED,
            created_at=datetime.now(timezone.utc),
            actor_id=kwargs["actor_id"],
            tenant_id=kwargs["tenant_id"],
            version=0,
            lease_token=None,
            metadata=kwargs["metadata"],
            error_code=None,
        )
        return self.task

    async def get_task(self, *, task_id, tenant_id):
        assert self.task.task_id == task_id
        assert self.task.tenant_id == tenant_id
        return self.task

    async def transition(self, **kwargs):
        assert kwargs["require_lease"] is False
        assert kwargs["require_no_lease"] is True
        self.task.state = kwargs["target"]
        self.task.version += 1
        return self.task


@pytest.mark.asyncio
async def test_task_service_encrypts_payload_and_keeps_idempotency_metadata_stable() -> None:
    store = CapturingStore()
    cipher = TaskPayloadCipher(b"z" * 32, key_version="test-v1")
    service = UGAITaskService(store, cipher)
    submission = _submission()
    tenant_id = f"tenant-{uuid4()}"
    actor_id = "verified-actor"
    idempotency_key = uuid4()

    first = await service.submit(
        submission,
        tenant_id=tenant_id,
        actor_id=actor_id,
        request_id=uuid4(),
        idempotency_key=idempotency_key,
    )
    second = await service.submit(
        submission,
        tenant_id=tenant_id,
        actor_id=actor_id,
        request_id=uuid4(),
        idempotency_key=idempotency_key,
    )

    assert first.task_id != second.task_id
    first_call, second_call = store.calls
    assert first_call["task_type"] == "notebook.request"
    assert first_call["input_digest"] == second_call["input_digest"]
    assert first_call["metadata"] == second_call["metadata"]
    assert "intent" not in first_call["metadata"]
    assert "tenant_id" not in first_call["metadata"]
    assert submission.intent.encode() not in first_call["encrypted_payload"]

    envelope = EncryptedTaskPayload(
        ciphertext=first_call["encrypted_payload"],
        nonce=first_call["payload_nonce"],
        key_version=first_call["payload_key_version"],
    )
    decrypted = cipher.decrypt_bytes(
        envelope, tenant_id=tenant_id, task_id=first_call["task_id"]
    )
    assert b"Explain the failing notebook cell" in decrypted


@pytest.mark.asyncio
async def test_task_service_refuses_cancel_when_worker_lease_exists() -> None:
    store = CapturingStore()
    store.task = SimpleNamespace(
        task_id=uuid4(),
        tenant_id="tenant-a",
        actor_id="actor-a",
        state=TaskState.RECEIVED,
        version=1,
        lease_token=uuid4(),
    )
    service = UGAITaskService(store, TaskPayloadCipher(b"q" * 32, key_version="v1"))

    with pytest.raises(TaskCancellationConflict, match="worker_lease"):
        await service.cancel(
            task_id=store.task.task_id,
            tenant_id="tenant-a",
            actor_id="actor-a",
        )


class RouteTaskService:
    def __init__(self) -> None:
        self.submission = None
        self.identity = None
        self.task_id = uuid4()

    async def submit(self, submission, **identity):
        self.submission = submission
        self.identity = identity
        return SimpleNamespace(
            task_id=self.task_id,
            state=TaskState.RECEIVED,
            created_at=datetime.now(timezone.utc),
        )

    async def status(self, *, task_id, tenant_id):
        return SimpleNamespace(
            task_id=task_id,
            tenant_id=tenant_id,
            actor_id="local-development",
            state=TaskState.RECEIVED,
            metadata={},
            error_code=None,
        )


def test_task_api_derives_actor_and_tenant_from_verified_principal() -> None:
    service = RouteTaskService()
    workspace_id = uuid4()
    request_id = uuid4()
    idempotency_key = uuid4()
    with TestClient(app) as client:
        app.state.task_service = service
        response = client.post(
            "/api/v1/tasks",
            headers={
                "X-Request-ID": str(request_id),
                "Idempotency-Key": str(idempotency_key),
            },
            json={
                "intent": "Summarize this notebook",
                "workspace_id": str(workspace_id),
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert body["request_id"] == str(request_id)
        assert body["state"] == "received"
        assert service.identity["tenant_id"] == "local-development"
        assert service.identity["actor_id"] == Principal(
            subject="local-development",
            tenant_id="local-development",
            roles=frozenset({"developer", "project_owner", "tenant_admin", "platform_admin"}),
            project_ids=frozenset({"*"}),
            auth_mode="disabled",
            issuer="urn:cataran:local-development",
        ).actor_id
        assert service.identity["actor_id"].startswith("principal:")
        assert service.identity["request_id"] == request_id
        assert service.identity["idempotency_key"] == idempotency_key

        spoofed = client.post(
            "/api/v1/tasks",
            headers={
                "X-Request-ID": str(uuid4()),
                "Idempotency-Key": str(uuid4()),
            },
            json={
                "intent": "Attempt to spoof identity",
                "workspace_id": str(workspace_id),
                "tenant_id": "attacker-tenant",
            },
        )
        assert spoofed.status_code == 422



def test_task_owner_is_scoped_to_verified_issuer_and_subject():
    issuer_a = Principal(
        subject="same-user",
        tenant_id="tenant-1",
        roles=frozenset({"developer"}),
        project_ids=frozenset(),
        auth_mode="oidc",
        issuer="https://identity-a.example.test/",
    )
    issuer_b = Principal(
        subject="same-user",
        tenant_id="tenant-1",
        roles=frozenset({"developer"}),
        project_ids=frozenset(),
        auth_mode="oidc",
        issuer="https://identity-b.example.test/",
    )
    task = SimpleNamespace(actor_id=issuer_a.actor_id)

    _assert_task_owner(task, issuer_a)
    with pytest.raises(Exception) as denied:
        _assert_task_owner(task, issuer_b)
    assert getattr(denied.value, "status_code", None) == 404
