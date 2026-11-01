from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_workflow_plan_endpoint_returns_controlled_plan():
    response = client.post("/api/v1/workflows/plan", json={
        "project_id": "local-project",
        "domain": "coding",
        "title": "Build cooperative system",
        "objective": "Generate, test, and prepare a cooperative management application",
        "steps": [
            {"step_id": "release", "title": "Release", "action": "deploy", "depends_on": ["test"], "side_effect": "deploy"},
            {"step_id": "test", "title": "Test", "action": "run_tests", "depends_on": ["code"]},
            {"step_id": "code", "title": "Generate code", "action": "generate_code", "side_effect": "workspace_write"},
        ],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["execution_enabled"] is False
    assert body["status"] == "planning_only"
    assert [step["step_id"] for step in body["ordered_steps"]] == ["code", "test", "release"]
    assert body["approval_required_steps"] == ["release"]


def test_workflow_plan_rejects_dependency_cycle():
    response = client.post("/api/v1/workflows/plan", json={
        "project_id": "local-project",
        "domain": "film",
        "title": "Produce short film",
        "objective": "Create a short film",
        "steps": [
            {"step_id": "script", "title": "Script", "action": "write_script", "depends_on": ["render"]},
            {"step_id": "render", "title": "Render", "action": "render_video", "depends_on": ["script"]},
        ],
    })
    assert response.status_code == 422
    assert "cycle" in response.json()["detail"]
