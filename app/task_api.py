"""Authenticated durable task API for AI Notebook Studio.

The browser never supplies tenant or actor authority. Both values are derived
from the verified UGAI principal, and notebook input is encrypted before the
task row and append-only event are committed by the PostgreSQL workflow store.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import (
    Principal,
    ensure_project_access,
    get_current_principal,
    require_generation_role,
    require_job_read_role,
)
from ugai_workflow.payload_cipher import TaskPayloadCipher
from ugai_workflow.postgres_store import (
    IdempotencyConflict,
    PostgresWorkflowStore,
    StaleWorkflowVersion,
    TaskNotFound,
)
from ugai_workflow.state_machine import TaskState, TransitionDenied

router = APIRouter(prefix="/api/v1/tasks", tags=["durable-tasks"])


class PublicTaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    BLOCKED = "blocked"
    OUTCOME_UNKNOWN = "outcome_unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_INTERNAL_TO_PUBLIC = {
    TaskState.RECEIVED: PublicTaskState.QUEUED,
    TaskState.OBSERVING: PublicTaskState.RUNNING,
    TaskState.PLANNING: PublicTaskState.RUNNING,
    TaskState.EXECUTING: PublicTaskState.RUNNING,
    TaskState.VERIFYING: PublicTaskState.RUNNING,
    TaskState.AWAITING_APPROVAL: PublicTaskState.AWAITING_APPROVAL,
    TaskState.AWAITING_CLARIFICATION: PublicTaskState.AWAITING_CLARIFICATION,
    TaskState.BLOCKED: PublicTaskState.BLOCKED,
    TaskState.OUTCOME_UNKNOWN: PublicTaskState.OUTCOME_UNKNOWN,
    TaskState.SUCCEEDED: PublicTaskState.SUCCEEDED,
    TaskState.FAILED: PublicTaskState.FAILED,
    TaskState.CANCELLED: PublicTaskState.CANCELLED,
}
_CANCELABLE_STATES = frozenset({
    TaskState.RECEIVED,
    TaskState.AWAITING_APPROVAL,
    TaskState.AWAITING_CLARIFICATION,
    TaskState.BLOCKED,
    TaskState.FAILED,
})


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    media_type: str = Field(min_length=1, max_length=128)


class TaskSubmission(BaseModel):
    """User task payload; tenant/actor/role fields are intentionally forbidden."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    project_id: str = Field(min_length=1, max_length=128)
    workspace_id: UUID
    notebook_id: UUID | None = None
    cell_revision: str | None = Field(default=None, max_length=128)
    intent: str = Field(min_length=1, max_length=12_000)
    context: str = Field(default="", max_length=20_000)
    artifacts: tuple[ArtifactReference, ...] = Field(default=(), max_length=32)
    requested_capabilities: tuple[str, ...] = Field(default=(), max_length=32)


class TaskStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = "1.0.0"
    task_id: UUID
    request_id: UUID
    correlation_id: UUID
    project_id: str
    state: PublicTaskState
    version: int
    retry_count: int
    retryable: bool
    error_code: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = "1.0.0"
    task_id: UUID
    project_id: str
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_status: str = "needs_human_review"
    human_review_required: bool = True
    result: dict[str, Any]


def _runtime(request: Request) -> tuple[PostgresWorkflowStore, TaskPayloadCipher]:
    store = getattr(request.app.state, "workflow_task_store", None)
    cipher = getattr(request.app.state, "workflow_task_payload_cipher", None)
    if store is None or cipher is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "workflow_task_runtime_unavailable"},
        )
    return store, cipher


def _public_state(task: Any) -> PublicTaskState:
    return _INTERNAL_TO_PUBLIC[TaskState(task.state)]


def _status(task: Any, request_id: UUID) -> TaskStatusResponse:
    metadata = task.metadata or {}
    correlation_id = task.correlation_id
    if correlation_id is None:
        raw = metadata.get("correlation_id")
        try:
            correlation_id = UUID(raw)
        except (TypeError, ValueError):
            correlation_id = request_id
    return TaskStatusResponse(
        task_id=task.task_id,
        request_id=request_id,
        correlation_id=correlation_id,
        project_id=task.project_id or "",
        state=_public_state(task),
        version=task.version,
        retry_count=task.retry_count,
        retryable=task.retryable,
        error_code=task.error_code,
        created_at=getattr(task, "created_at", None),
        updated_at=getattr(task, "updated_at", None),
    )


def _authorize_task_project(principal: Principal, task: Any) -> None:
    if not isinstance(task.project_id, str) or not task.project_id:
        raise HTTPException(status_code=4304, detail="Task not found")
    ensure_project_access(principal, task.project_id)


@router.post("", response_model=TaskStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_task(
    request: TaskSubmission,
    http_request: Request,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=8, max_length=128
    ),
    request_id: UUID = Header(default_factory=uuid.uuid4, alias="X-Request-ID"),
    correlation_id: UUID | None = Header(default=None, alias="X-Correlation-ID"),
):
    require_generation_role(principal)
    ensure_project_access(principal, request.project_id)
    store, cipher = _runtime(http_request)
    try:
        worker_ready = await store.has_healthy_worker(
            tenant_id=principal.tenant_id,
            task_type="notebook_task",
            max_age_seconds=60,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed when registry is unavailable
        raise HTTPException(
            status_code=503,
            detail={"code": "notebook_worker_registry_unavailable"},
        ) from exc
    if not worker_ready:
        raise HTTPException(
            status_code=503,
            detail={"code": "notebook_worker_unavailable"},
        )

    payload = request.model_dump(mode="json")
    encrypted_payload, payload_digest = cipher.encrypt(payload)
    task_id = uuid.uuid4()
    correlation_id = correlation_id or request_id
    context_ref = f"ugai-task-input://{task_id}"
    metadata = {
        "context_ref": context_ref,
        "correlation_id": str(correlation_id),
        "schema_version": "1.0.0",
    }

    try:
        task = await store.create_task(
            tenant_id=principal.tenant_id,
            actor_id=principal.subject,
            task_type="notebook_task",
            idempotency_key=idempotency_key,
            input_digest=payload_digest,
            priority=0,
            max_retries=2,
            metadata=metadata,
            task_id=task_id,
            project_id=request.project_id,
            correlation_id=correlation_id,
            encrypted_payload=encrypted_payload,
            payload_key_id=cipher.key_id,
            payload_sha256=payload_digest,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "idempotency_payload_conflict"}) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "task_payload_invalid"}) from exc
    except Exception as exc:  # noqa: BLE001 - database details are not public API data
        raise HTTPException(
            status_code=503,
            detail={"code": "workflow_task_persistence_unavailable"},
        ) from exc
    return _status(task, request_id)


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: UUID,
    http_request: Request,
    principal: Principal = Depends(get_current_principal),
    request_id: UUID = Header(default_factory=uuid.uuid4, alias="X-Request-ID"),
):
    require_job_read_role(principal)
    store, _cipher = _runtime(http_request)
    try:
        task = await store.get_task(task_id=task_id, tenant_id=principal.tenant_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail={"code": "workflow_task_read_unavailable"}) from exc
    _authorize_task_project(principal, task)
    return _status(task, request_id)


@router.get("/{task_id}/result", response_model=TaskResultResponse)
async def get_task_result(
    task_id: UUID,
    http_request: Request,
    principal: Principal = Depends(get_current_principal),
):
    """Return a verified encrypted result only to an authorized project member."""
    require_job_read_role(principal)
    store, cipher = _runtime(http_request)
    try:
        task = await store.get_task(task_id=task_id, tenant_id=principal.tenant_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "workflow_task_read_unavailable"},
        ) from exc
    _authorize_task_project(principal, task)
    if task.state is not TaskState.SUCCEEDED:
        raise HTTPException(
            status_code=409,
            detail={"code": "notebook_task_result_not_ready", "state": _public_state(task).value},
        )
    try:
        encrypted = await store.get_encrypted_result(
            tenant_id=principal.tenant_id,
            task_id=task_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "notebook_task_result_read_unavailable"},
        ) from exc
    if encrypted is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "notebook_task_result_missing"},
        )
    key_id, ciphertext, digest = encrypted
    try:
        result = cipher.decrypt(
            ciphertext,
            expected_sha256=digest,
            key_id=key_id,
        )
    except Exception as exc:  # noqa: BLE001 - do not disclose ciphertext or key details
        raise HTTPException(
            status_code=503,
            detail={"code": "notebook_task_result_integrity_failure"},
        ) from exc
    if (
        result.get("task_id") != str(task_id)
        or result.get("project_id") != task.project_id
        or result.get("verification_status") != "needs_human_review"
        or result.get("human_review_required") is not True
        or result.get("tool_execution_performed") is not False
    ):
        raise HTTPException(
            status_code=503,
            detail={"code": "notebook_task_result_contract_invalid"},
        )
    return TaskResultResponse(
        task_id=task_id,
        project_id=task.project_id,
        result_sha256=digest,
        verification_status="needs_human_review",
        human_review_required=True,
        result=result,
    )


@router.post("/{task_id}/cancel", response_model=TaskStatusResponse)
async def cancel_task(
    task_id: UUID,
    http_request: Request,
    principal: Principal = Depends(get_current_principal),
    request_id: UUID = Header(default_factory=uuid.uuid4, alias="X-Request-ID"),
):
    require_generation_role(principal)
    store, _cipher = _runtime(http_request)
    try:
        task = await store.get_task(task_id=task_id, tenant_id=principal.tenant_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail={"code": "workflow_task_read_unavailable"}) from exc
    _authorize_task_project(principal, task)

    if task.state is TaskState.CANCELLED:
        return _status(task, request_id)
    if task.state in {TaskState.SUCCEEDED}:
        raise HTTPException(status_code=409, detail={"code": "task_already_terminal"})
    if task.state is TaskState.OUTCOME_UNKNOWN:
        raise HTTPException(status_code=409, detail={"code": "task_outcome_requires_reconciliation"})
    if task.state not in _CANCELABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail={"code": "task_stage_requires_cooperative_cancellation"},
        )

    try:
        cancelled = await store.transition(
            task_id=task.task_id,
            tenant_id=principal.tenant_id,
            expected_version=task.version,
            target=TaskState.CANCELLED,
            actor_id=principal.subject,
            reason_code="user_cancelled",
            require_lease=False,
        )
    except StaleWorkflowVersion as exc:
        raise HTTPException(status_code=409, detail={"code": "task_state_changed_retry_read"}) from exc
    except (TransitionDenied, ValueError) as exc:
        raise HTTPException(status_code=409, detail={"code": "task_cancellation_not_allowed"}) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail={"code": "workflow_task_cancel_unavailable"}) from exc
    return _status(cancelled, request_id)
