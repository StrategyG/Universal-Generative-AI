from app.workers.client import ExternalGPUWorker


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"status": "succeeded"}


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.payload = None

    def post(self, url, *, json, timeout):
        self.payload = {"url": url, "json": json, "timeout": timeout}
        return FakeResponse()

    def close(self):
        return None


def test_worker_complete_sends_optional_provenance():
    worker = ExternalGPUWorker(
        "colab",
        "colab-worker-01",
        api_url="https://api.example.test",
        token="test-token",
    )
    fake = FakeSession()
    worker.session.close()
    worker.session = fake

    result = worker.complete(
        "job-123",
        "s3://bucket/result.glb",
        {"model_revision": "immutable-revision", "seed": 42},
    )

    assert result["status"] == "succeeded"
    assert fake.payload["json"]["metadata"]["model_revision"] == "immutable-revision"
    assert fake.payload["json"]["metadata"]["seed"] == 42
