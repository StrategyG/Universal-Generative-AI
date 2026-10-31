from threading import Event

import pytest

from app.workers.client import ExternalGPUWorker


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload or {"status": "succeeded"}
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, heartbeat_event=None):
        self.headers = {}
        self.payload = None
        self.calls = []
        self.heartbeat_event = heartbeat_event

    def post(self, url, *, json, timeout):
        payload = {"url": url, "json": json, "timeout": timeout}
        self.payload = payload
        self.calls.append(payload)
        if url.endswith("/claim"):
            return FakeResponse({"job_id": "job-123"})
        if url.endswith("/heartbeat") and self.heartbeat_event is not None:
            self.heartbeat_event.set()
        return FakeResponse()

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


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


def test_worker_renews_lease_while_handler_runs(monkeypatch):
    heartbeat_event = Event()
    stop_event = Event()
    heartbeat_session = FakeSession(heartbeat_event)
    main_session = FakeSession()

    worker = ExternalGPUWorker(
        "colab",
        "colab-worker-01",
        api_url="https://api.example.test",
        token="test-token",
        heartbeat_interval=0.01,
    )
    worker.session.close()
    worker.session = main_session
    monkeypatch.setattr(
        "app.workers.client.requests.Session",
        lambda: heartbeat_session,
    )

    def handler(job):
        assert job["job_id"] == "job-123"
        assert heartbeat_event.wait(timeout=1)
        stop_event.set()
        return "s3://bucket/result.glb", {"model_revision": "pin"}

    worker.run_forever(handler, poll_seconds=1, stop_event=stop_event)

    assert any(call["url"].endswith("/claim") for call in main_session.calls)
    assert any(call["url"].endswith("/complete") for call in main_session.calls)
    assert any(call["url"].endswith("/heartbeat") for call in heartbeat_session.calls)
    worker.close()


def test_worker_rejects_non_tls_remote_api_url():
    with pytest.raises(ValueError, match="HTTPS"):
        ExternalGPUWorker(
            "kaggle",
            "kaggle-worker-01",
            api_url="http://api.example.test",
            token="test-token",
        )


def test_worker_rejects_localhost_prefix_spoofing():
    with pytest.raises(ValueError, match="HTTPS"):
        ExternalGPUWorker(
            "kaggle",
            "kaggle-worker-01",
            api_url="http://localhost.attacker.test",
            token="test-token",
        )
