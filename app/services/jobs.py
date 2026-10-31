from uuid import uuid4

from app.config import settings
from app.providers.registry import registry
from app.schemas import GenerationRequest, JobResponse, JobStatus
from app.services.external_gpu_queue import (
    get_persisted_generation_job,
    persist_generation_job,
    update_generation_job,
)

_jobs: dict[str, JobResponse] = {}


async def submit_job(request: GenerationRequest) -> JobResponse:
    provider = registry.for_task(settings.generation_backend, request.task)
    job_id = str(uuid4())
    running = JobResponse(
        job_id=job_id,
        task=request.task,
        status=JobStatus.RUNNING,
        message="Inference started",
    )
    _jobs[job_id] = running
    await persist_generation_job(running)
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
    except Exception as exc:  # noqa: BLE001 - record provider inference failures
        response = JobResponse(
            job_id=job_id,
            task=request.task,
            status=JobStatus.FAILED,
            message=str(exc)[:500],
        )
    _jobs[job_id] = response
    await update_generation_job(response)
    return response


async def get_job(job_id: str) -> JobResponse | None:
    persisted = await get_persisted_generation_job(job_id)
    if persisted is not None:
        return persisted
    return _jobs.get(job_id)
