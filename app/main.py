import collections.abc
import contextlib
import hmac
import json

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import (
    Principal,
    ensure_project_access,
    get_current_principal,
    require_generation_role,
    require_job_read_role,
    validate_auth_configuration,
)

from app.ai_schemas import AICompletionRequest, AICompletionResponse
from app.config import settings, validate_database_configuration
from app.observability import RequestObservabilityMiddleware, configure_logging
from app.providers.router import TextModelRouter
from app.reasoning.api import router as reasoning_router
from app.providers.text_errors import TextGenerationProviderError
from app.pipelines.planner import build_pipeline_plan
from app.pipelines.schemas import PipelinePlan, PipelineRequest
from app.schemas import GenerationRequest, JobResponse
from app.services.external_gpu_queue import (
    approve_model_version,
    assert_model_approved,
    authenticate_worker,
    cancel_external_job,
    claim,
    claim_for_worker,
    close_queue,
    complete,
    disable_model_version,
    enqueue,
    fail,
    get_external_job,
    get_persisted_workflow_plan,
    get_model_version,
    heartbeat,
    heartbeat_worker,
    initialize_queue,
    provision_worker,
    queue_backend_name,
    persist_workflow_plan,
    register_model_version,
    register_worker,
    revoke_worker,
)
from app.services.jobs import get_job, submit_job
from app.workflow_runtime import open_workflow_runtime
from app.workflow_tasks import router as workflow_tasks_router
from app.services.model_registry_errors import (
    ModelApprovalRequiredError,
    ModelRegistryConflictError,
)
from app.services.queue_errors import IdempotencyConflictError
from app.workflows.planner import build_workflow_plan
from app.workflows.templates import build_domain_template
from app.workflows.schemas import (
    ProjectDomain,
    WorkflowPlan,
    WorkflowPlanRequest,
    WorkflowTemplateRequest,
)
from app.workers.schemas import (
    ExternalJob,
    ExternalJobCreate,
    ModelVersion,
    ModelVersionCreate,
    ModelVersionKey,
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


@contextlib.asynccontextmanager
async def lifespan(application: FastAPI) -> collections.abc.AsyncIterator[None]:
    validate_auth_configuration()
    validate_database_configuration()
    await initialize_queue()
    workflow_runtime = None
    try:
        workflow_runtime = await open_workflow_runtime()
        application.state.workflow_runtime = workflow_runtime
        yield
    finally:
        if workflow_runtime is not None:
            await workflow_runtime.close()
        await close_queue()


configure_logging()
app = FastAPI(title=settings.app_name, version="0.5.0", lifespan=lifespan)
app.add_middleware(RequestObservabilityMiddleware)
app.include_router(reasoning_router)
app.include_router(workflow_tasks_router)


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
async def generate(
    request: GenerationRequest,
    principal: Principal = Depends(get_current_principal),
):
    require_generation_role(principal)
    ensure_project_access(principal, request.project_id)
    if not request.prompt and not request.input_asset:
        raise HTTPException(status_code=422, detail="prompt or input_asset is required")
    strict_model_registry = (
        settings.model_registry_enforcement
        or settings.environment.lower() in {"production", "prod"}
    )
    if strict_model_registry and settings.generation_backend != "mock":
        try:
            await assert_model_approved(
                settings.image_model_id,
                settings.image_model_revision,
            )
        except ModelApprovalRequiredError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        return await submit_job(request, principal)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc



async def _build_text_router() -> TextModelRouter:
    try:
        return TextModelRouter.from_settings()
    except TextGenerationProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": exc.code, "message": str(exc), "retryable": exc.retryable},
        ) from exc


async def _approve_configured_text_routes(router: TextModelRouter) -> None:
    strict_model_registry = (
        settings.model_registry_enforcement
        or settings.environment.lower() in {"production", "prod"}
    )
    if not strict_model_registry:
        return

    for provider in router.providers:
        model_id = getattr(provider, "model_id", "")
        model_revision = getattr(provider, "model_revision", "")
        if not model_id or not model_revision:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Every production text route requires its own registered immutable "
                    "model ID and revision"
                ),
            )
        try:
            await assert_model_approved(model_id, model_revision)
        except ModelApprovalRequiredError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="Text model registry is unavailable",
            ) from exc


def _provider_error_detail(exc: TextGenerationProviderError) -> dict:
    return {
        "code": exc.code,
        "message": str(exc),
        "retryable": exc.retryable,
    }


@app.post(
    f"{settings.api_prefix}/ai/complete",
    response_model=AICompletionResponse,
)
async def complete_ai_generation(
    request: AICompletionRequest,
    principal: Principal = Depends(get_current_principal),
):
    """Generate domain-specialist text using configured, policy-controlled routes."""
    require_generation_role(principal)
    ensure_project_access(principal, request.project_id)
    router = await _build_text_router()
    await _approve_configured_text_routes(router)
    try:
        result = await router.generate(request)
    except TextGenerationProviderError as exc:
        raise HTTPException(status_code=502, detail=_provider_error_detail(exc)) from exc
    return AICompletionResponse(**result)


@app.post(f"{settings.api_prefix}/ai/complete/stream")
async def stream_ai_completion(
    request: AICompletionRequest,
    principal: Principal = Depends(get_current_principal),
):
    """Stream text deltas as SSE; fallback is allowed only before the first token."""
    require_generation_role(principal)
    ensure_project_access(principal, request.project_id)
    if request.quality_mode.value != "single":
        raise HTTPException(
            status_code=422,
            detail="Streaming currently requires quality_mode=single",
        )
    router = await _build_text_router()
    await _approve_configured_text_routes(router)

    async def events():
        try:
            async for chunk in router.stream(request):
                payload = json.dumps({"content": chunk}, ensure_ascii=False)
                yield f"event: token\ndata: {payload}\n\n"
            yield "event: done\ndata: {}\n\n"
        except TextGenerationProviderError as exc:
            payload = json.dumps(_provider_error_detail(exc), ensure_ascii=False)
            yield f"event: error\ndata: {payload}\n\n"
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@app.get(f"{settings.api_prefix}/ai/models")
async def discover_ai_models(
    principal: Principal = Depends(get_current_principal),
):
    """Return configured model catalogs and whether each configured ID is listed."""
    require_generation_role(principal)
    router = await _build_text_router()
    return await router.discover_models()


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}", response_model=JobResponse)
async def job_status(
    job_id: str,
    principal: Principal = Depends(get_current_principal),
):
    require_job_read_role(principal)
    job = await get_job(job_id, principal)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post(f"{settings.api_prefix}/pipelines/plan", response_model=PipelinePlan)
async def plan_pipeline(
    request: PipelineRequest,
    principal: Principal = Depends(get_current_principal),
):
    """Validate a workflow request and return a dependency/resource plan; never executes it."""
    require_generation_role(principal)
    try:
        return build_pipeline_plan(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc



@app.post(
    f"{settings.api_prefix}/workflows/templates/{{domain}}",
    response_model=WorkflowPlan,
)
async def create_institutional_workflow_template(
    domain: ProjectDomain,
    request: WorkflowTemplateRequest,
    principal: Principal = Depends(get_current_principal),
):
    """Build a deterministic starter plan for a supported project domain."""
    require_generation_role(principal)
    ensure_project_access(principal, request.project_id)
    try:
        plan = build_domain_template(domain, request)
        return await persist_workflow_plan(
            plan,
            tenant_id=principal.tenant_id,
            owner_subject=principal.subject,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Workflow plan persistence is unavailable") from exc


@app.post(
    f"{settings.api_prefix}/workflows/plan",
    response_model=WorkflowPlan,
)
async def plan_institutional_workflow(
    request: WorkflowPlanRequest,
    principal: Principal = Depends(get_current_principal),
):
    """Validate a project-scoped workflow; this endpoint never executes steps."""
    require_generation_role(principal)
    ensure_project_access(principal, request.project_id)
    try:
        plan = build_workflow_plan(request)
        return await persist_workflow_plan(
            plan,
            tenant_id=principal.tenant_id,
            owner_subject=principal.subject,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Workflow plan persistence is unavailable") from exc


@app.get(
    f"{settings.api_prefix}/workflows/plans/{{plan_id}}",
    response_model=WorkflowPlan,
)
async def read_institutional_workflow_plan(
    plan_id: str,
    principal: Principal = Depends(get_current_principal),
):
    require_job_read_role(principal)
    try:
        plan = await get_persisted_workflow_plan(
            plan_id,
            tenant_id=principal.tenant_id,
            owner_subject=principal.subject,
            project_ids=sorted(principal.project_ids - {"*"}),
            tenant_admin=principal.is_tenant_admin,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Workflow plan storage is unavailable") from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Workflow plan not found")
    return plan


@app.post(
    f"{settings.api_prefix}/model-registry/versions",
    response_model=ModelVersion,
)
async def create_model_registry_version(
    request: ModelVersionCreate,
    x_worker_admin_token: str | None = Header(default=None),
):
    require_admin_token(x_worker_admin_token)
    try:
        return await register_model_version(request)
    except ModelRegistryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    f"{settings.api_prefix}/model-registry/versions/approve",
    response_model=ModelVersion,
)
async def approve_model_registry_version(
    request: ModelVersionKey,
    x_worker_admin_token: str | None = Header(default=None),
):
    require_admin_token(x_worker_admin_token)
    try:
        model = await approve_model_version(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if model is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Model revision is missing or lacks approved license, passed "
                "validation, and passed evaluation evidence"
            ),
        )
    return model


@app.post(
    f"{settings.api_prefix}/model-registry/versions/disable",
    response_model=ModelVersion,
)
async def disable_model_registry_version(
    request: ModelVersionKey,
    x_worker_admin_token: str | None = Header(default=None),
):
    require_admin_token(x_worker_admin_token)
    try:
        model = await disable_model_version(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if model is None:
        raise HTTPException(status_code=404, detail="Approved model revision not found")
    return model


@app.get(
    f"{settings.api_prefix}/model-registry/versions",
    response_model=ModelVersion,
)
async def read_model_registry_version(
    model_id: str,
    revision: str,
    x_worker_admin_token: str | None = Header(default=None),
):
    require_admin_token(x_worker_admin_token)
    try:
        key = ModelVersionKey(model_id=model_id, revision=revision)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        model = await get_model_version(key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if model is None:
        raise HTTPException(status_code=404, detail="Model revision not found")
    return model


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
    except ModelApprovalRequiredError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


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


@app.post(
    f"{settings.api_prefix}/external-gpu/jobs/{{job_id}}/cancel",
    response_model=ExternalJob,
)
async def cancel_external_gpu_job(
    job_id: str,
    x_worker_token: str | None = Header(default=None),
    x_worker_admin_token: str | None = Header(default=None),
):
    # There is no end-user RBAC yet; cancellation is restricted to the operator
    # credential in production and the development-only compatibility token locally.
    authorize_job_submission(x_worker_token, x_worker_admin_token)
    job = await cancel_external_job(job_id)
    if job is not None:
        return job
    existing = await get_external_job(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="External GPU job not found")
    raise HTTPException(
        status_code=409,
        detail=f"Job in terminal state '{existing.status.value}' cannot be cancelled",
    )


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
