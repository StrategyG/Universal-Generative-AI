from fastapi import FastAPI, HTTPException

from app.config import settings
from app.pipelines.planner import build_pipeline_plan
from app.pipelines.schemas import PipelineRequest, PipelinePlan
from app.schemas import GenerationRequest, JobResponse
from app.services.jobs import get_job, submit_job

app = FastAPI(title=settings.app_name, version="0.2.0")


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}


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
