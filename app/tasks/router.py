"""Authenticated REST surface for UGAI durable notebook tasks."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.auth import (
    Principal,
    ensure_workspace_access,
    get_current_principal,
    require_generation_role,
    require_job_read_role,
    require_scope,
)
from app.config import settings
from app.tasks.schemas import TaskReceipt, TaskStatus, TaskSubmission
from app.tasks.service import TaskCancellationConflict, UGAITaskService
from ugai_workflow.postgres_store import IdempotencyConflict, TaskNotFound
from ugai_workflow.state_machine import TaskState

logger = logging.getLogger(__name__)
router = APIRouter(prefix=settings.api_prefix, tags=["tasks"])


def get_task_service(request: Request) -> UGAITaskService:
    service = getattr(request.app.state, "task_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "TASK_SERVICE_DISABLED", "retryable": True},
        )
    return service


def _assert_task_owner(task, principal: Principal) -> None:
    if task.actor_id != principal.actor_id and not principal.is_tenant_admin:
        # Do not disclose whether a task ID belongs to another subject.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


def _assert_workspace_access(task, principal: Principal) -> None:
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    workspace_id = metadata.get("workspace_id")
    ensure_workspace_access(principal, workspace_id)


def _task_status(task, request_id: UUID) -> TaskStatus:
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    result_reference = metadata.get("result_reference")
    if not isinstance(result_reference, str):
        result_reference = None
    return TaskStatus(
        task_id=task.task_id,
        request_id=request_id,
        state=task.state.value,
        result_reference=result_reference,
        error_code=task.error_code,
    )


@router.post("/tasks", response_model=TaskReceipt, status_code=status.HTTP_202_ACCEPTED)
async def submit_task(
    submission: TaskSubmission,
    request_id: UUID = Header(alias="X-Request-ID"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    principal: Principal = Depends(get_current_principal),
    service: UGAITaskService = Depends(get_task_service),
) -> TaskReceipt:
    require_generation_role(principal)
    require_scope(principal, "ugai:tasks:write")
    ensure_workspace_access(principal, str(submission.workspace_id))
    try:
        task = await service.submit(
            submission,
            tenant_id=principal.tenant_id,
            actor_id=principal.actor_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "IDEMPOTENCY_KEY_REUSED", "retryable": False},
        ) from exc
    except Exception as exc:  # database/provider errors are not returned to clients
        logger.exception("UGAI task submission failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "TASK_SUBMISSION_UNAVAILABLE", "retryable": True},
        ) from exc
    return TaskReceipt(
        task_id=task.task_id,
        request_id=request_id,
        state=task.state.value,
        created_at=task.created_at.isoformat(),
    )


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(
    task_id: UUID,
    request_id: UUID = Header(alias="X-Request-ID"),
    principal: Principal = Depends(get_current_principal),
    service: UGAITaskService = Depends(get_task_service),
) -> TaskStatus:
    require_job_read_role(principal)
    require_scope(principal, "ugai:tasks:read")
    try:
        task = await service.status(task_id=task_id, tenant_id=principal.tenant_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    except Exception as exc:
        logger.exception("UGAI task status lookup failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "TASK_STATUS_UNAVAILABLE", "retryable": True},
        ) from exc
    _assert_task_owner(task, principal)
    _assert_workspace_access(task, principal)
    return _task_status(task, request_id)


@router.post("/tasks/{task_id}/cancel", response_model=TaskStatus)
async def cancel_task(
    task_id: UUID,
    request_id: UUID = Header(alias="X-Request-ID"),
    principal: Principal = Depends(get_current_principal),
    service: UGAITaskService = Depends(get_task_service),
) -> TaskStatus:
    require_generation_role(principal)
    require_scope(principal, "ugai:tasks:cancel")
    try:
        current = await service.status(task_id=task_id, tenant_id=principal.tenant_id)
        _assert_task_owner(current, principal)
        _assert_workspace_access(current, principal)
        task = await service.cancel(
            task_id=task_id,
            tenant_id=principal.tenant_id,
            actor_id=principal.actor_id,
        )
    except TaskNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    except TaskCancellationConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "TASK_CANCELLATION_CONFLICT", "retryable": False},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("UGAI task cancellation failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "TASK_CANCELLATION_UNAVAILABLE", "retryable": True},
        ) from exc
    return _task_status(task, request_id)

@router.get("/tasks/{task_id}/result")
async def get_task_result(
    task_id: UUID,
    request_id: UUID = Header(alias="X-Request-ID"),
    principal: Principal = Depends(get_current_principal),
    service: UGAITaskService = Depends(get_task_service),
) -> dict:
    require_job_read_role(principal)
    require_scope(principal, "ugai:tasks:read")
    try:
        task = await service.status(task_id=task_id, tenant_id=principal.tenant_id)
        _assert_task_owner(task, principal)
        _assert_workspace_access(task, principal)
        if task.state is not TaskState.SUCCEEDED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "TASK_RESULT_NOT_READY", "retryable": True},
            )
        result = await service.load_result(
            task_id=task_id,
            tenant_id=principal.tenant_id,
            actor_id=principal.actor_id,
        )
    except TaskNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task result not found") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("UGAI task result lookup failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "TASK_RESULT_UNAVAILABLE", "retryable": True},
        ) from exc
    return {
        "task_id": str(task_id),
        "request_id": str(request_id),
        "result": result,
    }

