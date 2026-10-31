import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.model_registry_errors import (
    ModelApprovalRequiredError,
    ModelRegistryConflictError,
)
from app.services.postgres_gpu_queue import PostgresExternalGPUQueue
from app.workers.schemas import (
    ExternalJobCreate,
    ModelRegistryStatus,
    ModelVersionCreate,
    ModelVersionKey,
    WorkerPlatform,
    WorkerRegistration,
)


def _model_request(
    *,
    model_id: str | None = None,
    revision: str = "a" * 40,
    license_review_status: str = "pending",
    validation_status: str = "not_run",
    evaluation_results: dict | None = None,
) -> ModelVersionCreate:
    return ModelVersionCreate(
        model_id=model_id or f"org/model-{uuid4().hex}",
        revision=revision,
        model_name="Institutional Test Model",
        family="image_to_3d",
        source="huggingface",
        license_id="Apache-2.0",
        intended_use="CI integration testing only",
        input_schema={"type": "image"},
        output_schema={"type": "glb"},
        hardware_requirements={"min_gpu_vram_gb": 8},
        runtime_dependencies={"torch": "2.5.1"},
        license_review_status=license_review_status,
        validation_status=validation_status,
        evaluation_results=evaluation_results or {},
    )


def test_model_registry_requires_immutable_commit_revision():
    with pytest.raises(ValueError):
        _model_request(revision="main")


def test_model_registry_records_gates_schedules_and_disables_model_revision():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL not configured; PostgreSQL model registry test not run")

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
        model_id = f"ci/model-{uuid4().hex}"
        initial = _model_request(model_id=model_id)
        initial_key = ModelVersionKey(
            model_id=initial.model_id,
            revision=initial.revision,
        )
        try:
            pending = await queue.register_model_version(initial)
            assert pending.status is ModelRegistryStatus.PENDING_REVIEW

            with pytest.raises(ModelRegistryConflictError):
                await queue.register_model_version(initial)

            with pytest.raises(ModelApprovalRequiredError):
                await queue.assert_model_approved(model_id, initial.revision)

            assert await queue.approve_model_version(initial_key) is None

            reviewed_revision = "b" * 40
            reviewed = await queue.register_model_version(
                _model_request(
                    model_id=model_id,
                    revision=reviewed_revision,
                    license_review_status="approved",
                    validation_status="passed",
                    evaluation_results={
                        "status": "passed",
                        "dataset_version": "fixture-v1",
                        "evaluated_at": "2026-10-31T00:00:00Z",
                        "metrics": {"schema_validity": 1.0},
                    },
                )
            )
            assert reviewed.status is ModelRegistryStatus.PENDING_REVIEW

            reviewed_key = ModelVersionKey(
                model_id=model_id,
                revision=reviewed_revision,
            )
            approved = await queue.approve_model_version(reviewed_key)
            assert approved is not None
            assert approved.status is ModelRegistryStatus.APPROVED
            assert approved.approved_at is not None

            verified = await queue.assert_model_approved(model_id, reviewed_revision)
            assert verified.license_review_status == "approved"
            assert verified.validation_status == "passed"
            assert verified.evaluation_results["dataset_version"] == "fixture-v1"

            worker_id = f"ci-model-worker-{uuid4().hex}"
            issued = await queue.provision_worker(
                worker_id,
                WorkerPlatform.COLAB,
                3600,
            )
            registration = WorkerRegistration(
                runtime_version="Python 3.11.8",
                gpu_model="NVIDIA T4",
                gpu_vram_gb=16,
                available_gpu_memory_gb=12,
                cuda_version="12.4",
                frameworks=["torch==2.5.1"],
                supported_tasks=["image_to_3d"],
                available_memory_gb=16,
                capacity=1,
            )
            profile = await queue.register_worker(issued["token"], registration)
            assert profile is not None

            job = await queue.enqueue(
                ExternalJobCreate(
                    platform=WorkerPlatform.COLAB,
                    task="image_to_3d",
                    input_asset="asset://registry/source.png",
                    model_id=model_id,
                    model_revision=reviewed_revision,
                )
            )
            claimed = await queue.claim_for_worker(
                worker_id,
                enforce_model_registry=True,
            )
            assert claimed is not None
            assert claimed.job_id == job.job_id
            assert claimed.status.value == "running"

            disabled = await queue.disable_model_version(reviewed_key)
            assert disabled is not None
            assert disabled.status is ModelRegistryStatus.DISABLED

            with pytest.raises(ModelApprovalRequiredError):
                await queue.assert_model_approved(model_id, reviewed_revision)

            cancelled_job = await queue.get_external_job(job.job_id)
            assert cancelled_job is not None
            assert cancelled_job.status.value == "cancelled"
            assert await queue.disable_model_version(reviewed_key) is None
        finally:
            await queue.close()

    asyncio.run(scenario())
