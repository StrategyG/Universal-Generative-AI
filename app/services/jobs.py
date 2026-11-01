import logging
from uuid import uuid4

from app.auth import Principal
from app.config import settings
from app.providers.registry import registry
from app.schemas import GenerationRequest, JobResponse, JobStatus
from app.services.external_gpu_queue import (
    get_persisted_generation_job,
    persist_generation_job,
    update_generation_job,
)

logger = logging.getLogger(__name__)

_jobs: dict[str, JobResponse] = {}
_job_scopes: dict[str, tuple[str, str, str | None]] = {}


async def submit_job(request: GenerationRequest, principal: Principal) -> JobResponse:
    provider = registry.for_task(settings.generation_backend, request.task)
    job_id = str(uuid4())
    running = JobResponse(
        job_id=job_id,
        task=request.task,
        status=JobStatus.RUNNING,
        message="Inference started",
    )
    _jobs[job_id] = running
    _job_scopes[job_id] = (principal.tenant_id, principal.subject, request.project_id)
    await persist_generation_job(
        running,
        owner_subject=principal.subject,
        tenant_id=principal.tenant_id,
        project_id=request.project_id,
    )
    try:
        result = await provider.generate(
            request.task, request.prompt, request.input_asset, request.options
        )
        response = JobResponse(
            job_id=job_id,
            task=request.task,
            status=JobStatus.SUCCEEDED,
            message=(
                "Simulated result"
                if result.metadata.get("simulated")
                else "Generation completed"
            ),
            output_asset=result.output_asset,
        )
    except Exception as exc:  # noqa: BLE001 - provider details must not reach API clients
        logger.error(
            "Generation provider failed; job_id=%s task=%s error_type=%s",
            job_id,
            request.task.value,
            type(exc).__name__,
        )
        response = JobResponse(
            job_id=job_id,
            task=request.task,
            status=JobStatus.FAILED,
            message="Generation failed",
        )
    _jobs[job_id] = response
    await update_generation_job(response)
    return response


async def get_job(job_id: str, principal: Principal) -> JobResponse | None:
    persisted = await get_persisted_generation_job(
        job_id,
        tenant_id=principal.tenant_id,
        owner_subject=principal.subject,
        project_ids=sorted(principal.project_ids - {"*"}),
        tenant_admin=principal.is_tenant_admin,
    )
    if persisted is not None:
        return persisted

    job = _jobs.get(job_id)
    scope = _job_scopes.get(job_id)
    if job is None or scope is None:
        return None

    tenant_id, owner_subject, project_id = scope
    if tenant_id != principal.tenant_id:
        return None
    if (
        principal.auth_mode == "disabled"
        or principal.is_tenant_admin
        or owner_subject == principal.subject
        or (project_id is not None and project_id in principal.project_ids)
        or "*" in principal.project_ids
    ):
        return job
    return None
