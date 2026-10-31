import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.schemas import JobResponse, JobStatus, TaskType
from app.services.postgres_gpu_queue import PostgresExternalGPUQueue


def test_generation_job_row_conversion():
    row = {
        "job_id": "generation-unit-1",
        "task": "text_to_image",
        "status": "succeeded",
        "message": "Generated",
        "output_asset": "asset://generated/image.png",
    }
    job = PostgresExternalGPUQueue._to_generation_job(row)
    assert job.job_id == "generation-unit-1"
    assert job.task is TaskType.TEXT_TO_IMAGE
    assert job.status is JobStatus.SUCCEEDED
    assert job.output_asset == "asset://generated/image.png"


def test_generation_job_history_survives_queue_recreation():
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
        finally:
            await connection.close()

        job_id = str(uuid4())
        first = PostgresExternalGPUQueue(database_url)
        await first.open()
        try:
            running = JobResponse(
                job_id=job_id,
                task=TaskType.TEXT_TO_IMAGE,
                status=JobStatus.RUNNING,
                message="Inference started",
            )
            created = await first.create_generation_job(running)
            assert created.status is JobStatus.RUNNING
            completed = running.model_copy(
                update={
                    "status": JobStatus.SUCCEEDED,
                    "message": "Generation completed",
                    "output_asset": "asset://generated/result.png",
                }
            )
            await first.update_generation_job(completed)
        finally:
            await first.close()

        restarted = PostgresExternalGPUQueue(database_url)
        await restarted.open()
        try:
            recovered = await restarted.get_generation_job(job_id)
            assert recovered is not None
            assert recovered.status is JobStatus.SUCCEEDED
            assert recovered.output_asset == "asset://generated/result.png"
        finally:
            await restarted.close()

    asyncio.run(scenario())
