"""Authenticated, tenant/project-scoped API for durable UGAI workflow tasks.

Task payloads are stored only in the encrypted workflow input vault. The task
row and append-only event ledger contain opaque references, digests and
allowlisted metadata only.
"""
from __future__ import annotations

from enum import StrEnum
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
from app.config import settings
from app.workflow_runtime import WorkflowRuntime
from ugai_workflow.input_vault import (
    WorkflowInputConflict,
    WorkflowInputError,
    WorkflowInputNotFound,
)
from ugai_workflow.postgres_store import (
    IdempotencyConflict,
    LeaseLost,
    StaleWorkflowVersion,
    TaskNotFound,
)
from ugai_workflow.state_machine import TaskState, TransitionDenied


router = APIRouter(prefix=settings.api_prefix, tags=["workflow-tasks"])


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_id: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    media_type: str = Field(min_length=1, max_length=128)


class TaskInputCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: str = Field(min_length=1, max_length=128)
    workspace_id: UUID
    notebook_id: UUID | None = None
    cell_revision: str | None = Field(default=None, max_length=128)
    intent: str = Field(min_length=1, max_length=4000)
    artifacts: tuple[ArtifactReference, ...] = Field(default=(), max_length=32)
    requested_capabilities: tuple[str, ...] = Field(default=(), max_length=32)


class TaskInputReceipt(BaseModel):
    input_ref: UUID
    input_digest: str
    project_id: str
    workspace_id: UUID
    expires_at: str


class TaskSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: str = Field(min_length=1, max_length=128)
    input_ref: UUID
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_type: str = Field(min_length=1, max_length=128)
    max_retries: int = Field(default=2, ge=0, le=2)


class TaskStateCode(StrEnum):
    ACCEPTED = "ACCEPTED"
    OBSERVING = "OBSERVING"
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    VALIDATION = "VALIDATION"
    APPROVAL = "APPROVAL"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskReceipt(BaseModel):
    task_id: UUID
    request_id: UUID
    state: TaskStateCode
    created_at: str | None = None


class TaskStatus(BaseModel):
    task_id: UUID
    request_id: UUID
    state: TaskStateCode
    task_version: int
    error_code: str | None = None


_STATE_PROJECTION = {
    TaskState.RECEIVED: TaskStateCode.ACCEPTED,
    TaskState.OBSERVING: TaskStateCode.OBSERVING,
    TaskState.PLANNING: TaskStateCode.PLANNED,
    TaskState.EXECUTING: TaskStateCode.RUNNING,
    TaskState.VERIFYING: TaskStateCode.VALIDATION,
    TaskState.AWAITING_APPROVAL: TaskStateCode.APPROVAL,
    TaskState.AWAITING_CLARIFICATION: TaskStateCode.WAITING,
    TaskState.BLOCKED: TaskStateCode.BLOCKED,
    TaskState.OUTCOME_UNKNOWN: TaskStateCode.OUTCOME_UNKNOWN,
    TaskState.FAILED: TaskStateCode.FAILED,
    TaskState.SUCCEEDED: TaskStateCode.COMPLETED,
    TaskState.CANCELLED: TaskStateCode.CANCELLED,
}


def _runtime(request: Request) -> WorkflowRuntime:
    runtime = getattr(request.app.state, "workflow_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "workflow_runtime_unavailable"},
        )
    return runtime


def _require_acceptance(runtime: WorkflowRuntime) -> None:
    if not runtime.task_acceptance_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "workflow_task_acceptance_disabled"},
        )


def _status(task) -> TaskStatus:
    correlation = task.metadata.get("correlation_id")
    try:
        request_id = UUID(correlation) if isinstance(correlation, str) else task.task_id
    except ValueError:
        request_id = task.task_id
    return TaskStatus(
        task_id=task.task_id,
        request_id=request_id,
        state=_STATE_PROJECTION[task.state],
        task_version=task.version,
        error_code=task.error_code,
    )


@router.post("/task-inputs", response_model=TaskInputReceipt, status_code=201)
async def create_task_input(
    payload: TaskInputCreateRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    principal: Principal = Depends(get_current_principal),
    runtime: WorkflowRuntime = Depends(_runtime),
):
    require_generation_role(principal)
    ensure_project_access(principal, payload.project_id)
    _require_acceptance(runtime)
    try:
        workspace_bound = await runtime.store.workspace_is_bound(
            tenant_id=principal.tenant_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "workspace_registry_unavailable"},
        ) from exc
    if not workspace_bound:
        raise HTTPException(
            status_code=403,
            detail={"code": "workspace_project_binding_required"},
        )

    protected_payload = payload.model_dump(mode="json", exclude={"project_id"})
    try:
        stored = await runtime.inputs.put(
            tenant_id=principal.tenant_id,
            actor_id=principal.actor_id,
            project_id=payload.project_id,
            workspace_id=payload.workspace_id,
            notebook_id=payload.notebook_id,
            idempotency_key=idempotency_key,
            payload=protected_payload,
        )
    except WorkflowInputConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "idempotency_conflict"}) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_task_input"}) from exc
    except WorkflowInputError as exc:
        raise HTTPException(status_code=503, detail={"code": "task_input_vault_unavailable"}) from exc

    return TaskInputReceipt(
        input_ref=stored.input_ref,
        input_digest=stored.input_digest,
        project_id=stored.project_id,
        workspace_id=stored.workspace_id,
        expires_at=stored.expires_at.isoformat(),
    )


@router.post("/tasks", response_model=TaskReceipt, status_code=202)
async def submit_task(
    payload: TaskSubmissionRequest,
    request_id: UUID = Header(alias="X-Request-ID"),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    principal: Principal = Depends(get_current_principal),
    runtime: WorkflowRuntime = Depends(_runtime),
):
    require_generation_role(principal)
    ensure_project_access(principal, payload.project_id)
    _require_acceptance(runtime)
    if payload.task_type not in runtime.enabled_task_types:
        raise HTTPException(
            status_code=422,
            detail={"code": "task_type_not_enabled"},
        )
    try:
        worker_available = await runtime.store.has_active_worker(
            tenant_id=principal.tenant_id,
            task_type=payload.task_type,
            max_age_seconds=60,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "worker_registry_unavailable"},
        ) from exc
    if not worker_available:
        raise HTTPException(
            status_code=503,
            detail={"code": "task_worker_unavailable"},
        )

    try:
        stored_input = await runtime.inputs.get_metadata(
            input_ref=payload.input_ref,
            tenant_id=principal.tenant_id,
            actor_id=principal.actor_id,
        )
    except WorkflowInputNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "task_input_not_found"}) from exc
    except WorkflowInputError as exc:
        raise HTTPException(status_code=503, detail={"code": "task_input_vault_unavailable"}) from exc

    if (
        stored_input.project_id != payload.project_id
        or stored_input.input_digest != payload.input_digest
        or not await runtime.store.workspace_is_bound(
            tenant_id=principal.tenant_id,
            workspace_id=stored_input.workspace_id,
            project_id=payload.project_id,
        )
    ):
        raise HTTPException(status_code=409, detail={"code": "task_input_scope_or_digest_mismatch"})

    try:
        task = await runtime.store.create_task(
            tenant_id=principal.tenant_id,
            actor_id=principal.actor_id,
            task_type=payload.task_type,
            idempotency_key=idempotency_key,
            input_digest=payload.input_digest,
            max_retries=payload.max_retries,
            metadata={
                "context_ref": str(payload.input_ref),
                "project_id": payload.project_id,
                "schema_version": "1.0",
                "correlation_id": str(request_id),
            },
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "idempotency_conflict"}) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_task_request"}) from exc
    return TaskReceipt(
        task_id=task.task_id,
        request_id=request_id,
        state=_STATE_PROJECTION[task.state],
        created_at=task.created_at.isoformat() if task.created_at else None,
    )


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(
    task_id: UUID,
    principal: Principal = Depends(get_current_principal),
    runtime: WorkflowRuntime = Depends(_runtime),
):
    require_job_read_role(principal)
    try:
        task = await runtime.store.get_task(task_id=task_id, tenant_id=principal.tenant_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found"}) from exc
    project_id = task.metadata.get("project_id")
    if not isinstance(project_id, str):
        raise HTTPException(status_code=404, detail={"code": "task_not_found"})
    try:
        ensure_project_access(principal, project_id)
    except HTTPException as exc:
        # Avoid revealing whether a task exists in another project.
        raise HTTPException(status_code=404, detail={"code": "task_not_found"}) from exc
    return _status(task)


@router.post("/tasks/{task_id}/cancel", response_model=TaskStatus)
async def cancel_task(
    task_id: UUID,
    principal: Principal = Depends(get_current_principal),
    runtime: WorkflowRuntime = Depends(_runtime),
):
    require_generation_role(principal)
    try:
        task = await runtime.store.get_task(task_id=task_id, tenant_id=principal.tenant_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found"}) from exc
    project_id = task.metadata.get("project_id")
    if not isinstance(project_id, str):
        raise HTTPException(status_code=404, detail={"code": "task_not_found"})
    try:
        ensure_project_access(principal, project_id)
    except HTTPException as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found"}) from exc

    # A project member may be allowed to view project metadata, but task
    # cancellation is an owner/admin operation. Do not let another project
    # collaborator cancel a task they did not submit.
    if task.actor_id != principal.actor_id and not principal.roles.intersection(
        {"tenant_admin", "platform_admin"}
    ):
        raise HTTPException(status_code=404, detail={"code": "task_not_found"})
    if task.state is TaskState.CANCELLED:
        return _status(task)
    try:
        cancelled = await runtime.store.transition(
            task_id=task.task_id,
            tenant_id=principal.tenant_id,
            expected_version=task.version,
            target=TaskState.CANCELLED,
            actor_id=principal.actor_id,
            reason_code="user_requested_cancel",
            require_lease=False,
        )
    except (LeaseLost, StaleWorkflowVersion) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "task_not_cancellable_while_worker_lease_or_state_changes"},
        ) from exc
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found"}) from exc
    except (TransitionDenied, ValueError) as exc:
        raise HTTPException(status_code=409, detail={"code": "task_state_not_cancellable"}) from exc
    return _status(cancelled)


@router.get("/tasks/{task_id}/result")
async def get_task_result(
    task_id: UUID,
    principal: Principal = Depends(get_current_principal),
    runtime: WorkflowRuntime = Depends(_runtime),
):
    require_job_read_role(principal)
    try:
        task = await runtime.store.get_task(task_id=task_id, tenant_id=principal.tenant_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found"}) from exc
    project_id = task.metadata.get("project_id")
    if not isinstance(project_id, str):
        raise HTTPException(status_code=404, detail={"code": "task_not_found"})
    try:
        ensure_project_access(principal, project_id)
    except HTTPException as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found"}) from exc
    if task.actor_id != principal.actor_id and not principal.roles.intersection(
        {"tenant_admin", "platform_admin"}
    ):
        raise HTTPException(status_code=404, detail={"code": "task_not_found"})
    if task.state is not TaskState.SUCCEEDED:
        raise HTTPException(
            status_code=409,
            detail={"code": "task_result_not_ready"},
        )
    try:
        result = await runtime.results.get(
            tenant_id=principal.tenant_id,
            actor_id=task.actor_id,
            project_id=project_id,
            task_id=task.task_id,
        )
    except WorkflowInputNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "task_result_not_found"}) from exc
    except WorkflowInputError as exc:
        raise HTTPException(status_code=503, detail={"code": "task_result_unavailable"}) from exc
    return {"task_id": str(task.task_id), "result": result}
