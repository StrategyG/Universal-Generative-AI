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

def test_reject_empty_request():
    response = client.post("/api/v1/generate", json={"task": "text_to_image"})
    assert response.status_code == 422
