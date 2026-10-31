import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.postgres_gpu_queue import PostgresExternalGPUQueue
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
        "attempts": 1,
        "worker_id": None,
        "lease_expires_at": None,
        "output_asset": "asset://output.glb",
        "result_metadata": '{"model_revision": "0123456789abcdef"}',
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


def test_postgres_queue_persists_jobs_and_recovers_expired_leases():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL not configured; PostgreSQL integration test not run")

    async def scenario():
        import asyncpg

        migration_path = Path(__file__).parents[1] / "migrations" / "0001_create_external_gpu_jobs.sql"
        connection = await asyncpg.connect(database_url)
        try:
            await connection.execute(migration_path.read_text(encoding="utf-8"))
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
        )
        created = await first.enqueue(request)
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
    fake_asyncpg = SimpleNamespace(
        create_pool=lambda *args, **kwargs: pool,
    )
    monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)
    queue = PostgresExternalGPUQueue("postgresql://localhost/test")

    with pytest.raises(RuntimeError, match="migration is missing"):
        asyncio.run(queue.open())

    assert pool.closed is True
