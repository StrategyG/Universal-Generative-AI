"""Business operations for encrypted, tenant-bound UGAI notebook tasks."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from app.tasks.payloads import TaskPayloadCipher
from app.tasks.schemas import TaskSubmission
from ugai_workflow.postgres_store import (
    IdempotencyConflict,
    LeaseLost,
    PostgresWorkflowStore,
    StaleWorkflowVersion,
    TaskNotFound,
)
from ugai_workflow.state_machine import TaskState, TransitionDenied


class TaskCancellationConflict(RuntimeError):
    """Task cannot be cancelled without interfering with an executing worker."""


class UGAITaskService:
    def __init__(self, store: PostgresWorkflowStore, cipher: TaskPayloadCipher) -> None:
        if store is None or cipher is None:
            raise ValueError("workflow_store_and_payload_cipher_required")
        self.store = store
        self.cipher = cipher

    async def submit(
        self,
        submission: TaskSubmission,
        *,
        tenant_id: str,
        actor_id: str,
        request_id: UUID,
        idempotency_key: UUID,
    ):
        payload = submission.model_dump(mode="json")
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        task_id = uuid4()
        envelope = self.cipher.encrypt_bytes(encoded, tenant_id=tenant_id, task_id=task_id)
        return await self.store.create_task(
            task_id=task_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            task_type="notebook.request",
            idempotency_key=str(idempotency_key),
            input_digest=digest,
            max_retries=2,
            metadata={
                "request_ref": str(request_id),
                "correlation_id": str(request_id),
                "schema_version": "1",
            },
            encrypted_payload=envelope.ciphertext,
            payload_nonce=envelope.nonce,
            payload_key_version=envelope.key_version,
        )

    async def status(self, *, task_id: UUID, tenant_id: str):
        return await self.store.get_task(task_id=task_id, tenant_id=tenant_id)

    async def cancel(
        self, *, task_id: UUID, tenant_id: str, actor_id: str
    ):
        current = await self.store.get_task(task_id=task_id, tenant_id=tenant_id)
        if current.state is TaskState.CANCELLED:
            return current
        if current.lease_token is not None:
            raise TaskCancellationConflict("task_has_worker_lease_reconcile_before_cancel")
        try:
            return await self.store.transition(
                task_id=task_id,
                tenant_id=tenant_id,
                expected_version=current.version,
                target=TaskState.CANCELLED,
                actor_id=actor_id,
                reason_code="user_cancelled",
                require_lease=False,
                require_no_lease=True,
            )
        except (LeaseLost, StaleWorkflowVersion, TransitionDenied) as exc:
            raise TaskCancellationConflict("task_cancellation_conflict") from exc
