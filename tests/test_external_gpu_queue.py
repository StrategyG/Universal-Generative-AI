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
