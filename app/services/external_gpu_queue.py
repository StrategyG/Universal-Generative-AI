import asyncio
from time import time
from uuid import uuid4

from app.config import settings
from app.services.postgres_gpu_queue import PostgresExternalGPUQueue
from app.services.queue_errors import IdempotencyConflictError
from app.services.queue_utils import request_fingerprint
from app.workers.schemas import (
    ExternalJob,
    ExternalJobCreate,
    ExternalJobStatus,
    WorkerPlatform,
)

LEASE_SECONDS = 900
MAX_ATTEMPTS = 3

_jobs: dict[str, ExternalJob] = {}
_memory_idempotency: dict[str, tuple[str, str]] = {}
_lock = asyncio.Lock()


async def _memory_enqueue(request: ExternalJobCreate) -> ExternalJob:
    request_hash = request_fingerprint(request)
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
        idempotency_key=request.idempotency_key,
    )
    async with _lock:
        if request.idempotency_key:
            previous = _memory_idempotency.get(request.idempotency_key)
            if previous is not None:
                previous_job_id, previous_hash = previous
                existing = _jobs.get(previous_job_id)
                if existing is not None:
                    if previous_hash != request_hash:
                        raise IdempotencyConflictError(
                            "Idempotency-Key was already used with a different request"
                        )
                    return existing
                _memory_idempotency.pop(request.idempotency_key, None)
        _jobs[job.job_id] = job
        if request.idempotency_key:
            _memory_idempotency[request.idempotency_key] = (job.job_id, request_hash)
    return job


async def _memory_claim(platform: WorkerPlatform, worker_id: str) -> ExternalJob | None:
    now = time()
    async with _lock:
        for job_id, job in list(_jobs.items()):
            lease_expired = (
                job.status == ExternalJobStatus.RUNNING
                and job.lease_expires_at is not None
                and job.lease_expires_at <= now
            )
            if not lease_expired:
                continue
            if job.attempts >= MAX_ATTEMPTS:
                _jobs[job_id] = job.model_copy(
                    update={
                        "status": ExternalJobStatus.DEAD_LETTER,
                        "error": "Worker lease expired; retry limit reached",
                        "worker_id": None,
                        "lease_expires_at": None,
                    }
                )
            else:
                _jobs[job_id] = job.model_copy(
                    update={
                        "status": ExternalJobStatus.QUEUED,
                        "worker_id": None,
                        "lease_expires_at": None,
                    }
                )

        for job_id, job in _jobs.items():
            if job.platform != platform or job.status != ExternalJobStatus.QUEUED:
                continue
            claimed = job.model_copy(
                update={
                    "status": ExternalJobStatus.RUNNING,
                    "worker_id": worker_id,
                    "attempts": job.attempts + 1,
                    "lease_expires_at": now + LEASE_SECONDS,
                }
            )
            _jobs[job_id] = claimed
            return claimed
    return None


async def _memory_heartbeat(job_id: str, worker_id: str) -> ExternalJob | None:
    async with _lock:
        job = _jobs.get(job_id)
        if (
            job is None
            or job.status != ExternalJobStatus.RUNNING
            or job.worker_id != worker_id
        ):
            return None
        updated = job.model_copy(update={"lease_expires_at": time() + LEASE_SECONDS})
        _jobs[job_id] = updated
        return updated


async def _memory_complete(
    job_id: str,
    worker_id: str,
    output_asset: str,
    metadata: dict[str, str | int | float | bool] | None = None,
) -> ExternalJob | None:
    async with _lock:
        job = _jobs.get(job_id)
        if (
            job is None
            or job.status != ExternalJobStatus.RUNNING
            or job.worker_id != worker_id
        ):
            return None
        updated = job.model_copy(
            update={
                "status": ExternalJobStatus.SUCCEEDED,
                "output_asset": output_asset,
                "result_metadata": metadata or {},
                "worker_id": None,
                "lease_expires_at": None,
            }
        )
        _jobs[job_id] = updated
        return updated


async def _memory_fail(job_id: str, worker_id: str, error: str) -> ExternalJob | None:
    async with _lock:
        job = _jobs.get(job_id)
        if (
            job is None
            or job.status != ExternalJobStatus.RUNNING
            or job.worker_id != worker_id
        ):
            return None
        retry = job.attempts < MAX_ATTEMPTS
        updated = job.model_copy(
            update={
                "status": ExternalJobStatus.QUEUED if retry else ExternalJobStatus.DEAD_LETTER,
                "error": error,
                "worker_id": None,
                "lease_expires_at": None,
            }
        )
        _jobs[job_id] = updated
        return updated


async def _memory_get_external_job(job_id: str) -> ExternalJob | None:
    async with _lock:
        return _jobs.get(job_id)


_postgres_queue: PostgresExternalGPUQueue | None = None


async def initialize_queue() -> None:
    """Initialize PostgreSQL when configured; memory mode is development-only."""
    global _postgres_queue
    if not settings.database_url:
        if settings.environment.lower() in {"production", "prod"}:
            raise RuntimeError("DATABASE_URL is required in production; refusing volatile queue mode")
        return
    if _postgres_queue is not None:
        return
    backend = PostgresExternalGPUQueue(settings.database_url)
    await backend.open()
    _postgres_queue = backend


async def close_queue() -> None:
    global _postgres_queue
    if _postgres_queue is not None:
        await _postgres_queue.close()
        _postgres_queue = None


def queue_backend_name() -> str:
    return "postgresql" if _postgres_queue is not None else "memory"


async def enqueue(request: ExternalJobCreate) -> ExternalJob:
    if _postgres_queue is not None:
        return await _postgres_queue.enqueue(request)
    return await _memory_enqueue(request)


async def claim(platform: WorkerPlatform, worker_id: str) -> ExternalJob | None:
    if _postgres_queue is not None:
        return await _postgres_queue.claim(platform, worker_id)
    return await _memory_claim(platform, worker_id)


async def heartbeat(job_id: str, worker_id: str) -> ExternalJob | None:
    if _postgres_queue is not None:
        return await _postgres_queue.heartbeat(job_id, worker_id)
    return await _memory_heartbeat(job_id, worker_id)


async def complete(
    job_id: str,
    worker_id: str,
    output_asset: str,
    metadata: dict[str, str | int | float | bool] | None = None,
) -> ExternalJob | None:
    if _postgres_queue is not None:
        return await _postgres_queue.complete(job_id, worker_id, output_asset, metadata)
    return await _memory_complete(job_id, worker_id, output_asset, metadata)


async def fail(job_id: str, worker_id: str, error: str) -> ExternalJob | None:
    if _postgres_queue is not None:
        return await _postgres_queue.fail(job_id, worker_id, error)
    return await _memory_fail(job_id, worker_id, error)


async def get_external_job(job_id: str) -> ExternalJob | None:
    if _postgres_queue is not None:
        return await _postgres_queue.get_external_job(job_id)
    return await _memory_get_external_job(job_id)
