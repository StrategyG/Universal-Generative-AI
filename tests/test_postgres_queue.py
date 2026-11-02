import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import postgres_gpu_queue as postgres_queue
from app.services.postgres_gpu_queue import PostgresExternalGPUQueue
from app.services.queue_errors import IdempotencyConflictError
from app.workers.schemas import ExternalJobCreate, ExternalJobStatus, WorkerPlatform


def test_postgres_queue_requires_postgresql_dsn():
    with pytest.raises(ValueError, match="PostgreSQL scheme"):
        PostgresExternalGPUQueue("sqlite:///local.db")


def test_postgres_row_conversion_preserves_model_provenance():
    row = {
        "job_id": "unit-job-1",
        "platform": "colab",
        "task": "image_to_3d",
        "status": "succeeded",
        "input_asset": "asset://input.png",
        "prompt": "turn into a textured model",
        "model_id": "org/model",
        "model_revision": "0123456789abcdef",
        "options": '{"seed": 42}',
        "min_gpu_vram_gb": 0,
        "min_memory_gb": 0,
        "attempts": 1,
        "worker_id": None,
        "lease_expires_at": None,
        "next_attempt_at": None,
        "output_asset": "asset://output.glb",
        "result_metadata": '{"model_revision": "0123456789abcdef"}',
        "idempotency_key": None,
        "error": None,
    }

    job = PostgresExternalGPUQueue._to_job(row)

    assert job.status is ExternalJobStatus.SUCCEEDED
    assert job.options["seed"] == 42
    assert job.result_metadata["model_revision"] == "0123456789abcdef"


def test_postgres_queue_rejects_operations_before_initialization():
    queue = PostgresExternalGPUQueue("postgresql://localhost/test")

    with pytest.raises(RuntimeError, match="not initialized"):
        asyncio.run(queue.get_external_job("job-1"))


def test_postgres_queue_persists_jobs_and_recovers_expired_leases(monkeypatch):
    monkeypatch.setattr(postgres_queue, "RETRY_BASE_SECONDS", 0)
    monkeypatch.setattr(postgres_queue, "RETRY_MAX_SECONDS", 0)
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL not configured; PostgreSQL integration test not run")

    async def scenario():
        import asyncpg

        migration_dir = Path(__file__).parents[1] / "migrations"
        connection = await asyncpg.connect(database_url)
        try:
            for migration_path in sorted(migration_dir.glob("*.sql")):
                await connection.execute(migration_path.read_text(encoding="utf-8"))
            audit_table_exists = await connection.fetchval(
                "SELECT to_regclass('institutional_audit_ledger') IS NOT NULL"
            )
            assert audit_table_exists
            evidence_table_exists = await connection.fetchval(
                "SELECT to_regclass('institutional_evidence_claims') IS NOT NULL"
            )
            assert evidence_table_exists
            artifact_table_exists = await connection.fetchval(
                "SELECT to_regclass('institutional_artifacts') IS NOT NULL"
            )
            assert artifact_table_exists
        finally:
            await connection.close()

        first = PostgresExternalGPUQueue(database_url)
        await first.open()
        request = ExternalJobCreate(
            platform=WorkerPlatform.COLAB,
            task="image_to_3d",
            input_asset="asset://integration/input.png",
            model_id="test/model",
            model_revision="0123456789abcdef",
            idempotency_key=f"pg-it-{uuid4().hex}",
        )
        created = await first.enqueue(request)
        repeated = await first.enqueue(request)
        assert repeated.job_id == created.job_id
        mismatched = request.model_copy(update={"input_asset": "asset://integration/other.png"})
        with pytest.raises(IdempotencyConflictError):
            await first.enqueue(mismatched)
        await first.close()

        restarted = PostgresExternalGPUQueue(database_url)
        await restarted.open()
        try:
            recovered = await restarted.get_external_job(created.job_id)
            assert recovered is not None
            assert recovered.status is ExternalJobStatus.QUEUED

            claimed = await restarted.claim(WorkerPlatform.COLAB, "colab-it-worker")
            assert claimed is not None
            assert claimed.job_id == created.job_id
            assert claimed.attempts == 1

            pool_connection = await asyncpg.connect(database_url)
            try:
                await pool_connection.execute(
                    """
                    UPDATE external_gpu_jobs
                    SET lease_expires_at = now() - interval '1 second'
                    WHERE job_id = $1
                    """,
                    created.job_id,
                )
            finally:
                await pool_connection.close()

            reclaimed = await restarted.claim(WorkerPlatform.COLAB, "colab-it-worker-2")
            assert reclaimed is not None
            assert reclaimed.job_id == created.job_id
            assert reclaimed.attempts == 2
            assert reclaimed.status is ExternalJobStatus.RUNNING

            failed = await restarted.fail(
                created.job_id,
                "colab-it-worker-2",
                "test retry",
            )
            assert failed is not None
            assert failed.status is ExternalJobStatus.QUEUED
            assert failed.next_attempt_at is not None

            cancelled_request = request.model_copy(
                update={
                    "input_asset": "asset://integration/cancel.png",
                    "idempotency_key": f"pg-cancel-{uuid4().hex}",
                }
            )
            cancel_job = await restarted.enqueue(cancelled_request)
            cancelled = await restarted.cancel(cancel_job.job_id)
            assert cancelled is not None
            assert cancelled.status is ExternalJobStatus.CANCELLED
            assert await restarted.cancel(cancel_job.job_id) is None

            blocked_completion = await restarted.complete(
                created.job_id,
                "colab-it-worker-2",
                "asset://integration/late.glb",
            )
            assert blocked_completion is None
        finally:
            await restarted.close()

    asyncio.run(scenario())



def test_postgres_startup_fails_when_migration_is_missing(monkeypatch):
    class MissingMigrationPool:
        closed = False

        async def fetchval(self, query):
            assert "to_regclass" in query
            return False

        async def close(self):
            self.closed = True

    pool = MissingMigrationPool()
    async def create_pool(*args, **kwargs):
        return pool

    fake_asyncpg = SimpleNamespace(create_pool=create_pool)
    monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)
    queue = PostgresExternalGPUQueue("postgresql://localhost/test")

    with pytest.raises(RuntimeError, match="migrations are incomplete"):
        asyncio.run(queue.open())

    assert pool.closed is True
