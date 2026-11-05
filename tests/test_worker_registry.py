import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.postgres_gpu_queue import PostgresExternalGPUQueue
from app.workers.schemas import (
    ExternalJobCreate,
    WorkerPlatform,
    WorkerRegistration,
    WorkerRuntimeHeartbeat,
)


def test_worker_registration_requires_explicit_task_capabilities():
    with pytest.raises(ValueError):
        WorkerRegistration(runtime_version="Python 3.11")


def test_worker_registration_rejects_invalid_capacity():
    with pytest.raises(ValueError):
        WorkerRegistration(
            runtime_version="Python 3.11",
            supported_tasks=["image_to_3d"],
            capacity=0,
        )


def test_postgres_worker_credentials_revoke_and_schedule_by_capability():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL not configured; PostgreSQL worker test not run")

    async def scenario():
        import asyncpg

        migration_dir = Path(__file__).parents[1] / "migrations"
        connection = await asyncpg.connect(database_url)
        try:
            for migration_path in sorted(migration_dir.glob("*.sql")):
                await connection.execute(migration_path.read_text(encoding="utf-8"))
        finally:
            await connection.close()

        queue = PostgresExternalGPUQueue(database_url)
        await queue.open()
        worker_id = f"ci-worker-{uuid4().hex}"
        test_task = f"worker_registry_test_{uuid4().hex}"
        try:
            issued = await queue.provision_worker(
                worker_id,
                WorkerPlatform.COLAB,
                3600,
            )
            token = issued["token"]
            assert len(token) >= 40

            registration = WorkerRegistration(
                runtime_version="Python 3.11.8",
                gpu_model="NVIDIA T4",
                gpu_vram_gb=16,
                available_gpu_memory_gb=8,
                cuda_version="12.4",
                frameworks=["torch==2.5.1"],
                supported_tasks=[test_task],
                available_memory_gb=4,
                capacity=1,
            )
            profile = await queue.register_worker(token, registration)
            assert profile is not None
            assert profile.worker_id == worker_id
            assert profile.gpu_model == "NVIDIA T4"
            assert profile.supported_tasks == [test_task]

            authenticated = await queue.authenticate_worker(token)
            assert authenticated is not None
            assert authenticated.worker_id == worker_id
            stored_hash = await queue._require_pool().fetchval(
                "SELECT token_hash FROM external_gpu_workers WHERE worker_id = $1",
                worker_id,
            )
            assert stored_hash.strip() != token
            assert len(stored_hash.strip()) == 64

            refreshed = await queue.heartbeat_worker(
                token,
                WorkerRuntimeHeartbeat(
                    available_gpu_memory_gb=7,
                    available_memory_gb=3,
                ),
            )
            assert refreshed is not None
            assert refreshed.available_gpu_memory_gb == 7

            too_large = await queue.enqueue(
                ExternalJobCreate(
                    platform=WorkerPlatform.COLAB,
                    task=test_task,
                    input_asset="asset://test/too-large.png",
                    model_id="test/model",
                    model_revision="revision-1",
                    min_gpu_vram_gb=12,
                    min_memory_gb=2,
                )
            )
            compatible = await queue.enqueue(
                ExternalJobCreate(
                    platform=WorkerPlatform.COLAB,
                    task=test_task,
                    input_asset="asset://test/compatible.png",
                    model_id="test/model",
                    model_revision="revision-1",
                    min_gpu_vram_gb=6,
                    min_memory_gb=2,
                )
            )

            claimed = await queue.claim_for_worker(worker_id)
            assert claimed is not None
            assert claimed.job_id == compatible.job_id
            assert claimed.min_gpu_vram_gb == 6

            blocked_by_capacity = await queue.claim_for_worker(worker_id)
            assert blocked_by_capacity is None

            await queue.complete(
                compatible.job_id,
                worker_id,
                "asset://test/compatible.glb",
            )
            assert await queue.revoke_worker(worker_id) is True
            assert await queue.authenticate_worker(token) is None
            assert await queue.claim_for_worker(worker_id) is None

            still_queued = await queue.get_external_job(too_large.job_id)
            assert still_queued is not None
            assert still_queued.status.value == "queued"
        finally:
            await queue.close()

    asyncio.run(scenario())
