import asyncio
from time import time
from uuid import uuid4

from app.workers.schemas import (
    ExternalJob,
    ExternalJobCreate,
    ExternalJobStatus,
    WorkerPlatform,
)

LEASE_SECONDS = 900
MAX_ATTEMPTS = 3

_jobs: dict[str, ExternalJob] = {}
_lock = asyncio.Lock()


async def enqueue(request: ExternalJobCreate) -> ExternalJob:
    job = ExternalJob(
        job_id=str(uuid4()),
        platform=request.platform,
        task=request.task,
        status=ExternalJobStatus.QUEUED,
        input_asset=request.input_asset,
        prompt=request.prompt,
        model_id=request.model_id,
        model_revision=request.model_revision,
        options=request.options,
    )
    async with _lock:
        _jobs[job.job_id] = job
    return job


async def claim(platform: WorkerPlatform, worker_id: str) -> ExternalJob | None:
    now = time()
    async with _lock:
        # Expired leases are retried, with a bounded attempt count.
        for job_id, job in list(_jobs.items()):
            if job.status == ExternalJobStatus.RUNNING and job.lease_expires_at and job.lease_expires_at <= now:
                if job.attempts >= MAX_ATTEMPTS:
                    _jobs[job_id] = job.model_copy(update={
                        "status": ExternalJobStatus.FAILED,
                        "error": "Worker lease expired; retry limit reached",
                        "worker_id": None,
                        "lease_expires_at": None,
                    })
                else:
                    _jobs[job_id] = job.model_copy(update={
                        "status": ExternalJobStatus.QUEUED,
                        "worker_id": None,
                        "lease_expires_at": None,
                    })

        for job_id, job in _jobs.items():
            if job.platform == platform and job.status == ExternalJobStatus.QUEUED:
                claimed = job.model_copy(update={
                    "status": ExternalJobStatus.RUNNING,
                    "worker_id": worker_id,
                    "attempts": job.attempts + 1,
                    "lease_expires_at": now + LEASE_SECONDS,
                })
                _jobs[job_id] = claimed
                return claimed
    return None


async def heartbeat(job_id: str, worker_id: str) -> ExternalJob | None:
    async with _lock:
        job = _jobs.get(job_id)
        if not job or job.status != ExternalJobStatus.RUNNING or job.worker_id != worker_id:
            return None
        updated = job.model_copy(update={"lease_expires_at": time() + LEASE_SECONDS})
        _jobs[job_id] = updated
        return updated


async def complete(job_id: str, worker_id: str, output_asset: str, metadata: dict | None = None) -> ExternalJob | None:
    async with _lock:
        job = _jobs.get(job_id)
        if not job or job.status != ExternalJobStatus.RUNNING or job.worker_id != worker_id:
            return None
        updated = job.model_copy(update={
            "status": ExternalJobStatus.SUCCEEDED,
            "output_asset": output_asset,
            "worker_id": None,
            "lease_expires_at": None,
        })
        _jobs[job_id] = updated
        return updated


async def fail(job_id: str, worker_id: str, error: str) -> ExternalJob | None:
    async with _lock:
        job = _jobs.get(job_id)
        if not job or job.status != ExternalJobStatus.RUNNING or job.worker_id != worker_id:
            return None
        retry = job.attempts < MAX_ATTEMPTS
        updated = job.model_copy(update={
            "status": ExternalJobStatus.QUEUED if retry else ExternalJobStatus.FAILED,
            "error": error,
            "worker_id": None,
            "lease_expires_at": None,
        })
        _jobs[job_id] = updated
        return updated


async def get_external_job(job_id: str) -> ExternalJob | None:
    async with _lock:
        return _jobs.get(job_id)
