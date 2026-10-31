from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_generation_mock_is_explicit():
    response = client.post("/api/v1/generate", json={
        "task": "text_to_image", "prompt": "a red cube"
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["output_asset"] is None
    assert body["message"] == "Simulated result"

def test_pipeline_plan_endpoint_is_planning_only():
    response = client.post("/api/v1/pipelines/plan", json={
        "workflow": "image_to_video",
        "input_asset": "asset://uploads/character.png"
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert len(body["steps"]) == 5
    assert body["steps"][0]["execution"] == "not_implemented"
    assert "no model inference" in body["warnings"][0].lower()


def test_pipeline_plan_rejects_wrong_input_type():
    response = client.post("/api/v1/pipelines/plan", json={
        "workflow": "glb_to_video",
        "input_asset": "asset://uploads/character.png"
    })
    assert response.status_code == 422


def test_reject_empty_request():
    response = client.post("/api/v1/generate", json={"task": "text_to_image"})
    assert response.status_code == 422


def test_external_gpu_routes_require_worker_token(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "external_worker_token", "test-secret")
    response = client.post("/api/v1/external-gpu/claim", json={
        "platform": "colab", "worker_id": "colab-worker-test"
    })
    assert response.status_code == 401


def test_external_gpu_worker_claim_and_complete(monkeypatch):
    from app.config import settings
    from app.services import external_gpu_queue
    monkeypatch.setattr(settings, "external_worker_token", "test-secret")
    external_gpu_queue._jobs.clear()
    headers = {"X-Worker-Token": "test-secret"}
    created = client.post("/api/v1/external-gpu/jobs", headers=headers, json={
        "platform": "kaggle",
        "task": "image_to_3d",
        "input_asset": "s3://private-bucket/input.png",
        "model_id": "org/model",
        "model_revision": "0123456789abcdef"
    })
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    claimed = client.post("/api/v1/external-gpu/claim", headers=headers, json={
        "platform": "kaggle", "worker_id": "kaggle-worker-test"
    })
    assert claimed.status_code == 200
    assert claimed.json()["job_id"] == job_id
    completed = client.post(f"/api/v1/external-gpu/jobs/{job_id}/complete",
        headers=headers, json={
            "worker_id": "kaggle-worker-test",
            "output_asset": "s3://private-bucket/output.glb",
            "metadata": {"model_revision": "0123456789abcdef"}
        })
    assert completed.status_code == 200
    assert completed.json()["status"] == "succeeded"
    assert completed.json()["result_metadata"]["model_revision"] == "0123456789abcdef"



def test_external_gpu_job_idempotency(monkeypatch):
    from app.config import settings
    from app.services import external_gpu_queue

    monkeypatch.setattr(settings, "external_worker_token", "test-secret")
    external_gpu_queue._jobs.clear()
    external_gpu_queue._memory_idempotency.clear()
    headers = {
        "X-Worker-Token": "test-secret",
        "Idempotency-Key": "external-job-idempotency-01",
    }
    payload = {
        "platform": "kaggle",
        "task": "image_to_3d",
        "input_asset": "asset://uploads/source.png",
        "model_id": "org/model",
        "model_revision": "0123456789abcdef",
    }

    first = client.post("/api/v1/external-gpu/jobs", headers=headers, json=payload)
    repeated = client.post("/api/v1/external-gpu/jobs", headers=headers, json=payload)
    assert first.status_code == 200
    assert repeated.status_code == 200
    assert first.json()["job_id"] == repeated.json()["job_id"]

    changed_payload = {**payload, "input_asset": "asset://uploads/other.png"}
    conflict = client.post(
        "/api/v1/external-gpu/jobs",
        headers=headers,
        json=changed_payload,
    )
    assert conflict.status_code == 409
