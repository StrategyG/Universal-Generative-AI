"""PostgreSQL-backed external GPU queue.

asyncpg is imported lazily so local development can run without a database.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

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
                    """
                )
            )
        finally:
            if not migration_ready:
                await pool.close()
        if not migration_ready:
            raise RuntimeError(
                "Database migration is missing; apply "
                "migrations/0001_create_external_gpu_jobs.sql before startup"
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
            attempts=row["attempts"],
            worker_id=row["worker_id"],
            lease_expires_at=lease.timestamp() if lease is not None else None,
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
                model_id, model_revision, options, idempotency_key, request_hash
            )
            VALUES ($1, $2, $3, 'queued', $4, $5, $6, $7, $8::jsonb, $9, $10)
            ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
            DO UPDATE SET request_hash = external_gpu_jobs.request_hash
            RETURNING *
            """,
            str(uuid4()), request.platform.value, request.task, request.input_asset,
            request.prompt, request.model_id, request.model_revision,
            json.dumps(request.options), request.idempotency_key, request_hash,
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
                    updated_at = now()
                WHERE status = 'running'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= now()
                """,
                MAX_ATTEMPTS,
            )
            row = await connection.fetchrow(
                """
                SELECT *
                FROM external_gpu_jobs
                WHERE platform = $1 AND status = 'queued'
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
                error = $4, worker_id = NULL, lease_expires_at = NULL,
                updated_at = now()
            WHERE job_id = $1 AND worker_id = $2
              AND status = 'running' AND lease_expires_at > now()
            RETURNING *
            """,
            job_id, worker_id, MAX_ATTEMPTS, error[:1000],
        )
        return self._to_job(row) if row is not None else None

    async def get_external_job(self, job_id: str) -> ExternalJob | None:
        pool = self._require_pool()
        row = await pool.fetchrow(
            "SELECT * FROM external_gpu_jobs WHERE job_id = $1", job_id
        )
        return self._to_job(row) if row is not None else None
