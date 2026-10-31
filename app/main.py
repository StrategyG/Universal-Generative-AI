import hmac

from fastapi import FastAPI, Header, HTTPException

from app.config import settings
from app.pipelines.planner import build_pipeline_plan
from app.pipelines.schemas import PipelinePlan, PipelineRequest
from app.schemas import GenerationRequest, JobResponse
from app.services.external_gpu_queue import (
    authenticate_worker,
    claim,
    claim_for_worker,
    close_queue,
    complete,
    enqueue,
    fail,
    get_external_job,
    heartbeat,
    heartbeat_worker,
    initialize_queue,
    queue_backend_name,
    provision_worker,
    register_worker,
    revoke_worker,
)
from app.services.jobs import get_job, submit_job
from app.services.queue_errors import IdempotencyConflictError
from app.workers.schemas import (
    ExternalJob,
    ExternalJobCreate,
    WorkerClaim,
    WorkerCompletion,
    WorkerFailure,
    WorkerHeartbeat,
    WorkerProfile,
    WorkerProvisionRequest,
    WorkerProvisionResponse,
    WorkerRegistration,
    WorkerRuntimeHeartbeat,
)

app = FastAPI(title=settings.app_name, version="0.4.0")


@app.on_event("startup")
async def startup_queue() -> None:
    await initialize_queue()


@app.on_event("shutdown")
async def shutdown_queue() -> None:
    await close_queue()


def require_worker_token(token: str | None) -> None:
    expected = settings.external_worker_token
    if not expected:
        raise HTTPException(status_code=503, detail="External GPU workers are disabled")
    if token is None or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credentials")


def require_admin_token(token: str | None) -> None:
    expected = settings.worker_admin_token
    if not expected:
        raise HTTPException(status_code=503, detail="Worker administration is disabled")
    if token is None or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid worker administration credentials")


async def authorize_worker(token: str | None) -> WorkerProfile | None:
    if not token:
        raise HTTPException(status_code=401, detail="Worker credentials are required")
    profile = await authenticate_worker(token)
    if profile is not None:
        return profile
    if settings.environment.lower() not in {"production", "prod"}:
        require_worker_token(token)
        return None
    raise HTTPException(status_code=401, detail="Worker credential is invalid, expired, or revoked")


def authorize_job_submission(worker_token: str | None, admin_token: str | None) -> None:
    if settings.environment.lower() in {"production", "prod"}:
        require_admin_token(admin_token)
    else:
        require_worker_token(worker_token)


@app.get("/health")
async def health():
    backend = queue_backend_name()
    return {
        "status": "ok",
        "environment": settings.environment,
        "external_gpu_workers_enabled": (
            backend == "postgresql" or bool(settings.external_worker_token)
        ),
        "worker_scoped_credentials_enabled": backend == "postgresql",
        "worker_administration_enabled": bool(settings.worker_admin_token),
        "queue_backend": backend,
        "queue_persistent": backend == "postgresql",
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
    x_worker_admin_token: str | None = Header(default=None),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=8, max_length=128
    ),
):
    authorize_job_submission(x_worker_token, x_worker_admin_token)
    if (
        idempotency_key
        and request.idempotency_key
        and idempotency_key != request.idempotency_key
    ):
        raise HTTPException(status_code=422, detail="Conflicting idempotency keys")
    if idempotency_key:
        request = request.model_copy(update={"idempotency_key": idempotency_key})
    try:
        return await enqueue(request)
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    f"{settings.api_prefix}/external-gpu/workers/provision",
    response_model=WorkerProvisionResponse,
)
async def provision_external_gpu_worker(
    request: WorkerProvisionRequest,
    x_worker_admin_token: str | None = Header(default=None),
):
    require_admin_token(x_worker_admin_token)
    try:
        return await provision_worker(request.worker_id, request.platform, request.ttl_seconds)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    f"{settings.api_prefix}/external-gpu/workers/register",
    response_model=WorkerProfile,
)
async def register_external_gpu_worker(
    request: WorkerRegistration,
    x_worker_token: str | None = Header(default=None),
):
    if not x_worker_token:
        raise HTTPException(status_code=401, detail="Worker credentials are required")
    profile = await register_worker(x_worker_token, request)
    if profile is None:
        raise HTTPException(status_code=401, detail="Worker credential is invalid, expired, or revoked")
    return profile


@app.post(
    f"{settings.api_prefix}/external-gpu/workers/heartbeat",
    response_model=WorkerProfile,
)
async def heartbeat_external_gpu_worker(
    request: WorkerRuntimeHeartbeat,
    x_worker_token: str | None = Header(default=None),
):
    profile = await authorize_worker(x_worker_token)
    if profile is None:
        raise HTTPException(status_code=409, detail="Legacy shared-token workers cannot publish runtime telemetry")
    updated = await heartbeat_worker(x_worker_token, request)
    if updated is None:
        raise HTTPException(status_code=401, detail="Worker credential is invalid, expired, or revoked")
    return updated


@app.delete(f"{settings.api_prefix}/external-gpu/workers/{{worker_id}}")
async def revoke_external_gpu_worker(
    worker_id: str,
    x_worker_admin_token: str | None = Header(default=None),
):
    require_admin_token(x_worker_admin_token)
    revoked = await revoke_worker(worker_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Worker not found or already revoked")
    return {"worker_id": worker_id, "status": "revoked"}


@app.post(f"{settings.api_prefix}/external-gpu/claim", response_model=ExternalJob | None)
async def claim_external_gpu_job(
    request: WorkerClaim,
    x_worker_token: str | None = Header(default=None),
):
    profile = await authorize_worker(x_worker_token)
    if profile is not None:
        if request.worker_id != profile.worker_id or request.platform != profile.platform:
            raise HTTPException(status_code=403, detail="Worker identity does not match its credential")
        return await claim_for_worker(profile.worker_id)
    return await claim(request.platform, request.worker_id)


@app.post(f"{settings.api_prefix}/external-gpu/jobs/{{job_id}}/heartbeat", response_model=ExternalJob)
async def heartbeat_external_gpu_job(
    job_id: str,
    request: WorkerHeartbeat,
    x_worker_token: str | None = Header(default=None),
):
    profile = await authorize_worker(x_worker_token)
    if profile is not None and request.worker_id != profile.worker_id:
        raise HTTPException(status_code=403, detail="Worker identity does not match its credential")
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
    profile = await authorize_worker(x_worker_token)
    if profile is not None and request.worker_id != profile.worker_id:
        raise HTTPException(status_code=403, detail="Worker identity does not match its credential")
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
    profile = await authorize_worker(x_worker_token)
    if profile is not None and request.worker_id != profile.worker_id:
        raise HTTPException(status_code=403, detail="Worker identity does not match its credential")
    job = await fail(job_id, request.worker_id, request.error)
    if job is None:
        raise HTTPException(status_code=409, detail="Job lease is not owned by this worker")
    return job


@app.get(f"{settings.api_prefix}/external-gpu/jobs/{{job_id}}", response_model=ExternalJob)
async def external_gpu_job_status(
    job_id: str,
    x_worker_token: str | None = Header(default=None),
):
    profile = await authorize_worker(x_worker_token)
    job = await get_external_job(job_id)
    if profile is not None and (job is None or job.worker_id != profile.worker_id):
        raise HTTPException(status_code=404, detail="External GPU job not found")
    if job is None:
        raise HTTPException(status_code=404, detail="External GPU job not found")
    return job
