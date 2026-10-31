import hmac

from fastapi import FastAPI, Header, HTTPException

from app.config import settings
from app.pipelines.planner import build_pipeline_plan
from app.pipelines.schemas import PipelinePlan, PipelineRequest
from app.schemas import GenerationRequest, JobResponse
from app.services.external_gpu_queue import (
    claim,
    complete,
    enqueue,
    fail,
    get_external_job,
    heartbeat,
)
from app.services.jobs import get_job, submit_job
from app.workers.schemas import (
    ExternalJob,
    ExternalJobCreate,
    WorkerClaim,
    WorkerCompletion,
    WorkerFailure,
    WorkerHeartbeat,
)

app = FastAPI(title=settings.app_name, version="0.3.0")


def require_worker_token(token: str | None) -> None:
    expected = settings.external_worker_token
    if not expected:
        raise HTTPException(status_code=503, detail="External GPU workers are disabled")
    if token is None or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credentials")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "environment": settings.environment,
        "external_gpu_workers_enabled": bool(settings.external_worker_token),
    }


@app.post(f"{settings.api_prefix}/generate", response_model=JobResponse)
async def generate(request: GenerationRequest):
    if not request.prompt and not request.input_asset:
        raise HTTPException(status_code=422, detail="prompt or input_asset is required")
    try:
        return await submit_job(request)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}", response_model=JobResponse)
async def job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post(f"{settings.api_prefix}/pipelines/plan", response_model=PipelinePlan)
async def plan_pipeline(request: PipelineRequest):
    """Validate a workflow request and return a dependency/resource plan; never executes it."""
    try:
        return build_pipeline_plan(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/external-gpu/jobs", response_model=ExternalJob)
async def create_external_gpu_job(
    request: ExternalJobCreate,
    x_worker_token: str | None = Header(default=None),
):
    require_worker_token(x_worker_token)
    return await enqueue(request)


@app.post(f"{settings.api_prefix}/external-gpu/claim", response_model=ExternalJob | None)
async def claim_external_gpu_job(
    request: WorkerClaim,
    x_worker_token: str | None = Header(default=None),
):
    require_worker_token(x_worker_token)
    return await claim(request.platform, request.worker_id)


@app.post(f"{settings.api_prefix}/external-gpu/jobs/{{job_id}}/heartbeat", response_model=ExternalJob)
async def heartbeat_external_gpu_job(
    job_id: str,
    request: WorkerHeartbeat,
    x_worker_token: str | None = Header(default=None),
):
    require_worker_token(x_worker_token)
    job = await heartbeat(job_id, request.worker_id)
    if job is None:
        raise HTTPException(status_code=409, detail="Job lease is not owned by this worker")
    return job


@app.post(f"{settings.api_prefix}/external-gpu/jobs/{{job_id}}/complete", response_model=ExternalJob)
async def complete_external_gpu_job(
    job_id: str,
    request: WorkerCompletion,
    x_worker_token: str | None = Header(default=None),
):
    require_worker_token(x_worker_token)
    job = await complete(job_id, request.worker_id, request.output_asset, request.metadata)
    if job is None:
        raise HTTPException(status_code=409, detail="Job lease is not owned by this worker")
    return job


@app.post(f"{settings.api_prefix}/external-gpu/jobs/{{job_id}}/fail", response_model=ExternalJob)
async def fail_external_gpu_job(
    job_id: str,
    request: WorkerFailure,
    x_worker_token: str | None = Header(default=None),
):
    require_worker_token(x_worker_token)
    job = await fail(job_id, request.worker_id, request.error)
    if job is None:
        raise HTTPException(status_code=409, detail="Job lease is not owned by this worker")
    return job


@app.get(f"{settings.api_prefix}/external-gpu/jobs/{{job_id}}", response_model=ExternalJob)
async def external_gpu_job_status(
    job_id: str,
    x_worker_token: str | None = Header(default=None),
):
    require_worker_token(x_worker_token)
    job = await get_external_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="External GPU job not found")
    return job
