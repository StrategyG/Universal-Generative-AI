import asyncio

from app.services import external_gpu_queue as queue
from app.workers.schemas import ExternalJobCreate, WorkerPlatform


def test_external_worker_claim_and_complete():
    async def scenario():
        queue._jobs.clear()
        job = await queue.enqueue(ExternalJobCreate(
            platform=WorkerPlatform.COLAB,
            task="image_to_3d",
            input_asset="s3://private-bucket/input.png",
            model_id="example/model",
            model_revision="0123456789abcdef",
        ))
        claimed = await queue.claim(WorkerPlatform.COLAB, "colab-worker-01")
        assert claimed.job_id == job.job_id
        assert claimed.status.value == "running"
        completed = await queue.complete(job.job_id, "colab-worker-01", "s3://private-bucket/output.glb")
        assert completed.status.value == "succeeded"
        assert completed.output_asset.endswith(".glb")

    asyncio.run(scenario())


def test_worker_cannot_complete_another_workers_job():
    async def scenario():
        queue._jobs.clear()
        job = await queue.enqueue(ExternalJobCreate(
            platform=WorkerPlatform.KAGGLE,
            task="image_to_3d",
            input_asset="s3://private-bucket/input.png",
            model_id="example/model",
            model_revision="0123456789abcdef",
        ))
        await queue.claim(WorkerPlatform.KAGGLE, "kaggle-worker-01")
        result = await queue.complete(job.job_id, "attacker-worker", "s3://private-bucket/fake.glb")
        assert result is None

    asyncio.run(scenario())



def test_external_gpu_job_cancellation_rejects_late_completion():
    async def scenario():
        queue._jobs.clear()
        request = ExternalJobCreate(
            platform=WorkerPlatform.COLAB,
            task="image_to_3d",
            input_asset="asset://cancel/input.png",
            model_id="test/model",
            model_revision="revision-1",
        )
        job = await queue.enqueue(request)
        claimed = await queue.claim(WorkerPlatform.COLAB, "colab-worker-cancel")
        assert claimed is not None

        cancelled = await queue.cancel_external_job(job.job_id)
        assert cancelled is not None
        assert cancelled.status.value == "cancelled"
        assert cancelled.worker_id is None
        assert cancelled.lease_expires_at is None

        late_completion = await queue.complete(
            job.job_id,
            "colab-worker-cancel",
            "asset://cancel/output.glb",
        )
        assert late_completion is None
        assert await queue.cancel_external_job(job.job_id) is None

    asyncio.run(scenario())


def test_external_gpu_failure_uses_retry_backoff(monkeypatch):
    async def scenario():
        queue._jobs.clear()
        request = ExternalJobCreate(
            platform=WorkerPlatform.KAGGLE,
            task="image_to_3d",
            input_asset="asset://retry/input.png",
            model_id="test/model",
            model_revision="revision-1",
        )
        job = await queue.enqueue(request)
        claimed = await queue.claim(WorkerPlatform.KAGGLE, "kaggle-worker-retry")
        assert claimed is not None

        failed = await queue.fail(job.job_id, "kaggle-worker-retry", "simulated failure")
        assert failed is not None
        assert failed.status.value == "queued"
        assert failed.next_attempt_at is not None
        assert failed.next_attempt_at > claimed.lease_expires_at - 900

        cancelled = await queue.cancel_external_job(job.job_id)
        assert cancelled is not None
        assert cancelled.status.value == "cancelled"

    asyncio.run(scenario())
