"""PostgreSQL-backed external GPU queue.

asyncpg is imported lazily so local development can run without a database.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any
from uuid import uuid4

from app.schemas import JobResponse, JobStatus, TaskType
from app.services.queue_errors import IdempotencyConflictError
from app.services.queue_utils import (
    RETRY_BASE_SECONDS,
    RETRY_MAX_SECONDS,
    request_fingerprint,
)
from app.workers.schemas import (
    ExternalJob,
    ExternalJobCreate,
    ExternalJobStatus,
    WorkerPlatform,
    WorkerProfile,
    WorkerRegistration,
)

LEASE_SECONDS = 900
MAX_ATTEMPTS = 3


class PostgresExternalGPUQueue:
    def __init__(self, database_url: str) -> None:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must use the PostgreSQL scheme")
        self.database_url = database_url
        self._pool: Any = None

    async def open(self) -> None:
        if self._pool is not None:
            return
        try:
            import asyncpg
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL queue requires asyncpg; install with "
                "pip install -e '.[postgres]'"
            ) from exc
        pool = await asyncpg.create_pool(
            self.database_url, min_size=1, max_size=10, command_timeout=30
        )
        migration_ready = False
        try:
            migration_ready = bool(
                await pool.fetchval(
                    """
                    SELECT to_regclass('external_gpu_jobs') IS NOT NULL
                       AND EXISTS (
                           SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'external_gpu_jobs'
                             AND column_name = 'idempotency_key'
                       )
                       AND to_regclass('external_gpu_workers') IS NOT NULL
                       AND EXISTS (
                           SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'external_gpu_jobs'
                             AND column_name = 'min_gpu_vram_gb'
                       )
                       AND EXISTS (
                           SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'external_gpu_jobs'
                             AND column_name = 'next_attempt_at'
                       )
                       AND to_regclass('generation_jobs') IS NOT NULL
                    """
                )
            )
        finally:
            if not migration_ready:
                await pool.close()
        if not migration_ready:
            raise RuntimeError(
                "Database migrations are incomplete; apply all ordered SQL files "
                "in migrations/ before startup"
            )
        self._pool = pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _require_pool(self) -> Any:
        if self._pool is None:
            raise RuntimeError("PostgreSQL queue is not initialized")
        return self._pool

    @staticmethod
    def _decode_json(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            return json.loads(value)
        return dict(value or {})

    @classmethod
    def _to_job(cls, row: Any) -> ExternalJob:
        lease = row["lease_expires_at"]
        next_attempt = row["next_attempt_at"]
        return ExternalJob(
            job_id=row["job_id"],
            platform=WorkerPlatform(row["platform"]),
            task=row["task"],
            status=ExternalJobStatus(row["status"]),
            input_asset=row["input_asset"],
            prompt=row["prompt"],
            model_id=row["model_id"],
            model_revision=row["model_revision"],
            options=cls._decode_json(row["options"]),
            min_gpu_vram_gb=float(row["min_gpu_vram_gb"]),
            min_memory_gb=float(row["min_memory_gb"]),
            attempts=row["attempts"],
            worker_id=row["worker_id"],
            lease_expires_at=lease.timestamp() if lease is not None else None,
            next_attempt_at=(next_attempt.timestamp() if next_attempt is not None else None),
            output_asset=row["output_asset"],
            result_metadata=cls._decode_json(row["result_metadata"]),
            idempotency_key=row["idempotency_key"],
            error=row["error"],
        )

    async def enqueue(self, request: ExternalJobCreate) -> ExternalJob:
        pool = self._require_pool()
        request_hash = request_fingerprint(request)
        row = await pool.fetchrow(
            """
            INSERT INTO external_gpu_jobs (
                job_id, platform, task, status, input_asset, prompt,
                model_id, model_revision, options, min_gpu_vram_gb, min_memory_gb,
                idempotency_key, request_hash
            )
            VALUES ($1, $2, $3, 'queued', $4, $5, $6, $7, $8::jsonb, $9, $10, $11, $12)
            ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
            DO UPDATE SET request_hash = external_gpu_jobs.request_hash
            RETURNING *
            """,
            str(uuid4()), request.platform.value, request.task, request.input_asset,
            request.prompt, request.model_id, request.model_revision,
            json.dumps(request.options), request.min_gpu_vram_gb, request.min_memory_gb,
            request.idempotency_key, request_hash,
        )
        if request.idempotency_key and row["request_hash"] != request_hash:
            raise IdempotencyConflictError(
                "Idempotency-Key was already used with a different request"
            )
        return self._to_job(row)

    async def claim(self, platform: WorkerPlatform, worker_id: str) -> ExternalJob | None:
        pool = self._require_pool()
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                """
                UPDATE external_gpu_jobs
                SET
                    status = CASE WHEN attempts >= $1 THEN 'dead_letter' ELSE 'queued' END,
                    error = CASE
                        WHEN attempts >= $1
                            THEN 'Worker lease expired; retry limit reached'
                        ELSE error
                    END,
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    next_attempt_at = CASE
                        WHEN attempts >= $1 THEN now()
                        ELSE now() + (
                            LEAST(
                                $2 * POWER(2::double precision, GREATEST(attempts - 1, 0)),
                                $3
                            ) * interval '1 second'
                        )
                    END,
                    updated_at = now()
                WHERE status = 'running'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= now()
                """,
                MAX_ATTEMPTS,
                RETRY_BASE_SECONDS,
                RETRY_MAX_SECONDS,
            )
            row = await connection.fetchrow(
                """
                SELECT *
                FROM external_gpu_jobs
                WHERE platform = $1 AND status = 'queued'
                  AND next_attempt_at <= now()
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                platform.value,
            )
            if row is None:
                return None
            claimed = await connection.fetchrow(
                """
                UPDATE external_gpu_jobs
                SET
                    status = 'running',
                    worker_id = $2,
                    attempts = attempts + 1,
                    lease_expires_at = now() + ($3 * interval '1 second'),
                    updated_at = now()
                WHERE job_id = $1
                RETURNING *
                """,
                row["job_id"], worker_id, LEASE_SECONDS,
            )
        return self._to_job(claimed)

    async def heartbeat(self, job_id: str, worker_id: str) -> ExternalJob | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            UPDATE external_gpu_jobs
            SET lease_expires_at = now() + ($3 * interval '1 second'),
                updated_at = now()
            WHERE job_id = $1 AND worker_id = $2
              AND status = 'running' AND lease_expires_at > now()
            RETURNING *
            """,
            job_id, worker_id, LEASE_SECONDS,
        )
        return self._to_job(row) if row is not None else None

    async def complete(
        self,
        job_id: str,
        worker_id: str,
        output_asset: str,
        metadata: dict[str, str | int | float | bool] | None = None,
    ) -> ExternalJob | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            UPDATE external_gpu_jobs
            SET status = 'succeeded', output_asset = $3,
                result_metadata = $4::jsonb, worker_id = NULL,
                lease_expires_at = NULL, updated_at = now()
            WHERE job_id = $1 AND worker_id = $2
              AND status = 'running' AND lease_expires_at > now()
            RETURNING *
            """,
            job_id, worker_id, output_asset, json.dumps(metadata or {}),
        )
        return self._to_job(row) if row is not None else None

    async def fail(self, job_id: str, worker_id: str, error: str) -> ExternalJob | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            UPDATE external_gpu_jobs
            SET status = CASE WHEN attempts < $3 THEN 'queued' ELSE 'dead_letter' END,
                error = $4,
                worker_id = NULL,
                lease_expires_at = NULL,
                next_attempt_at = CASE
                    WHEN attempts < $3 THEN now() + (
                        LEAST(
                            $5 * POWER(2::double precision, GREATEST(attempts - 1, 0)),
                            $6
                        ) * interval '1 second'
                    )
                    ELSE now()
                END,
                updated_at = now()
            WHERE job_id = $1 AND worker_id = $2
              AND status = 'running' AND lease_expires_at > now()
            RETURNING *
            """,
            job_id, worker_id, MAX_ATTEMPTS, error[:1000],
            RETRY_BASE_SECONDS, RETRY_MAX_SECONDS,
        )
        return self._to_job(row) if row is not None else None

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @classmethod
    def _to_worker_profile(cls, row: Any) -> WorkerProfile:
        def decode_list(value: Any) -> list[str]:
            if isinstance(value, str):
                return json.loads(value)
            return list(value or [])

        return WorkerProfile(
            worker_id=row["worker_id"],
            platform=WorkerPlatform(row["platform"]),
            status=row["status"],
            runtime_version=row["runtime_version"],
            gpu_model=row["gpu_model"],
            gpu_vram_gb=float(row["gpu_vram_gb"]),
            available_gpu_memory_gb=float(row["available_gpu_memory_gb"]),
            cuda_version=row["cuda_version"],
            frameworks=decode_list(row["frameworks"]),
            supported_tasks=decode_list(row["supported_tasks"]),
            available_memory_gb=float(row["available_memory_gb"]),
            capacity=row["capacity"],
            token_expires_at=row["token_expires_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
        )

    async def provision_worker(
        self, worker_id: str, platform: WorkerPlatform, ttl_seconds: int
    ) -> dict[str, Any]:
        pool = self._require_pool()
        token = secrets.token_urlsafe(32)
        token_hash = self._token_hash(token)
        row = await pool.fetchrow(
            """
            INSERT INTO external_gpu_workers (
                worker_id, platform, token_hash, token_expires_at, status,
                runtime_version, gpu_model, gpu_vram_gb, available_gpu_memory_gb,
                cuda_version, frameworks, supported_tasks, available_memory_gb,
                capacity, revoked_at, last_heartbeat_at
            )
            VALUES (
                $1, $2, $3, now() + ($4 * interval '1 second'), 'provisioned',
                NULL, NULL, 0, 0, NULL, '[]'::jsonb, '[]'::jsonb, 0, 1, NULL, NULL
            )
            ON CONFLICT (worker_id) DO UPDATE SET
                platform = EXCLUDED.platform,
                token_hash = EXCLUDED.token_hash,
                token_expires_at = EXCLUDED.token_expires_at,
                status = 'provisioned',
                runtime_version = NULL,
                gpu_model = NULL,
                gpu_vram_gb = 0,
                available_gpu_memory_gb = 0,
                cuda_version = NULL,
                frameworks = '[]'::jsonb,
                supported_tasks = '[]'::jsonb,
                available_memory_gb = 0,
                capacity = 1,
                revoked_at = NULL,
                last_heartbeat_at = NULL,
                updated_at = now()
            RETURNING worker_id, token_expires_at
            """,
            worker_id, platform.value, token_hash, ttl_seconds,
        )
        return {"worker_id": row["worker_id"], "token": token,
                "token_expires_at": row["token_expires_at"]}

    async def register_worker(
        self, token: str, registration: WorkerRegistration
    ) -> WorkerProfile | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            UPDATE external_gpu_workers
            SET status = 'active',
                runtime_version = $2,
                gpu_model = $3,
                gpu_vram_gb = $4,
                available_gpu_memory_gb = $5,
                cuda_version = $6,
                frameworks = $7::jsonb,
                supported_tasks = $8::jsonb,
                available_memory_gb = $9,
                capacity = $10,
                last_heartbeat_at = now(),
                updated_at = now()
            WHERE token_hash = $1
              AND status IN ('provisioned', 'active')
              AND revoked_at IS NULL
              AND token_expires_at > now()
            RETURNING *
            """,
            self._token_hash(token),
            registration.runtime_version,
            registration.gpu_model,
            registration.gpu_vram_gb,
            registration.available_gpu_memory_gb,
            registration.cuda_version,
            json.dumps(registration.frameworks),
            json.dumps(registration.supported_tasks),
            registration.available_memory_gb,
            registration.capacity,
        )
        return self._to_worker_profile(row) if row is not None else None

    async def authenticate_worker(self, token: str) -> WorkerProfile | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            SELECT * FROM external_gpu_workers
            WHERE token_hash = $1 AND status = 'active'
              AND revoked_at IS NULL AND token_expires_at > now()
            """,
            self._token_hash(token),
        )
        return self._to_worker_profile(row) if row is not None else None

    async def heartbeat_worker(
        self, token: str, telemetry: Any
    ) -> WorkerProfile | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            UPDATE external_gpu_workers
            SET available_gpu_memory_gb = $2,
                available_memory_gb = $3,
                last_heartbeat_at = now(),
                updated_at = now()
            WHERE token_hash = $1 AND status = 'active'
              AND revoked_at IS NULL AND token_expires_at > now()
            RETURNING *
            """,
            self._token_hash(token),
            telemetry.available_gpu_memory_gb,
            telemetry.available_memory_gb,
        )
        return self._to_worker_profile(row) if row is not None else None

    async def revoke_worker(self, worker_id: str) -> bool:
        pool = self._require_pool()
        result = await pool.execute(
            """
            UPDATE external_gpu_workers
            SET status = 'revoked', revoked_at = now(), updated_at = now()
            WHERE worker_id = $1 AND status <> 'revoked'
            """,
            worker_id,
        )
        return result.endswith(" 1")

    async def claim_for_worker(self, worker_id: str) -> ExternalJob | None:
        pool = self._require_pool()
        async with pool.acquire() as connection, connection.transaction():
            worker = await connection.fetchrow(
                """
                SELECT * FROM external_gpu_workers
                WHERE worker_id = $1 AND status = 'active'
                  AND revoked_at IS NULL AND token_expires_at > now()
                FOR UPDATE
                """,
                worker_id,
            )
            if worker is None:
                return None

            await connection.execute(
                """
                UPDATE external_gpu_jobs
                SET
                    status = CASE WHEN attempts >= $1 THEN 'dead_letter' ELSE 'queued' END,
                    error = CASE
                        WHEN attempts >= $1
                            THEN 'Worker lease expired; retry limit reached'
                        ELSE error
                    END,
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    next_attempt_at = CASE
                        WHEN attempts >= $1 THEN now()
                        ELSE now() + (
                            LEAST(
                                $2 * POWER(2::double precision, GREATEST(attempts - 1, 0)),
                                $3
                            ) * interval '1 second'
                        )
                    END,
                    updated_at = now()
                WHERE status = 'running'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= now()
                """,
                MAX_ATTEMPTS,
                RETRY_BASE_SECONDS,
                RETRY_MAX_SECONDS,
            )

            active_count = await connection.fetchval(
                """
                SELECT count(*) FROM external_gpu_jobs
                WHERE worker_id = $1 AND status = 'running'
                """,
                worker_id,
            )
            if active_count >= worker["capacity"]:
                return None

            tasks = worker["supported_tasks"]
            if isinstance(tasks, str):
                tasks = json.loads(tasks)
            if not tasks:
                return None

            row = await connection.fetchrow(
                """
                SELECT * FROM external_gpu_jobs
                WHERE platform = $1 AND status = 'queued'
                  AND next_attempt_at <= now()
                  AND task = ANY($2::text[])
                  AND min_gpu_vram_gb <= $3
                  AND min_gpu_vram_gb <= $4
                  AND min_memory_gb <= $5
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                worker["platform"], tasks, worker["gpu_vram_gb"],
                worker["available_gpu_memory_gb"], worker["available_memory_gb"],
            )
            if row is None:
                return None
            claimed = await connection.fetchrow(
                """
                UPDATE external_gpu_jobs
                SET
                    status = 'running',
                    worker_id = $2,
                    attempts = attempts + 1,
                    lease_expires_at = now() + ($3 * interval '1 second'),
                    updated_at = now()
                WHERE job_id = $1
                RETURNING *
                """,
                row["job_id"], worker_id, LEASE_SECONDS,
            )
        return self._to_job(claimed)

    async def cancel(self, job_id: str) -> ExternalJob | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            UPDATE external_gpu_jobs
            SET status = 'cancelled',
                worker_id = NULL,
                lease_expires_at = NULL,
                updated_at = now()
            WHERE job_id = $1 AND status IN ('queued', 'running')
            RETURNING *
            """,
            job_id,
        )
        return self._to_job(row) if row is not None else None


    async def create_generation_job(self, job: JobResponse) -> JobResponse:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO generation_jobs (job_id, task, status, message, output_asset)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            job.job_id, job.task.value, job.status.value, job.message, job.output_asset,
        )
        return self._to_generation_job(row)

    async def update_generation_job(self, job: JobResponse) -> JobResponse:
        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            UPDATE generation_jobs
            SET status = $2, message = $3, output_asset = $4, updated_at = now()
            WHERE job_id = $1
            RETURNING *
            """,
            job.job_id, job.status.value, job.message, job.output_asset,
        )
        return self._to_generation_job(row) if row is not None else job

    async def get_generation_job(self, job_id: str) -> JobResponse | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            "SELECT * FROM generation_jobs WHERE job_id = $1", job_id
        )
        return self._to_generation_job(row) if row is not None else None

    @staticmethod
    def _to_generation_job(row: Any) -> JobResponse:
        return JobResponse(
            job_id=row["job_id"],
            task=TaskType(row["task"]),
            status=JobStatus(row["status"]),
            message=row["message"],
            output_asset=row["output_asset"],
        )

    async def get_external_job(self, job_id: str) -> ExternalJob | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            "SELECT * FROM external_gpu_jobs WHERE job_id = $1", job_id
        )
        return self._to_job(row) if row is not None else None
