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
            {"step_id": "release", "title": "Release", "action": "deploy", "depends_on": ["test"], "side_effect": "none", "risk_score": 0},
            {"step_id": "test", "title": "Test", "action": "run_tests", "depends_on": ["code"]},
            {"step_id": "code", "title": "Generate code", "action": "generate_code", "side_effect": "workspace_write"},
        ],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["execution_enabled"] is False
    assert body["plan_id"]
    plan_id = body["plan_id"]
    saved = client.get(f"/api/v1/workflows/plans/{plan_id}")
    assert saved.status_code == 200
    assert saved.json()["plan_id"] == body["plan_id"]
    assert body["status"] == "planning_only"
    assert [step["step_id"] for step in body["ordered_steps"]] == ["code", "test", "release"]
    assert body["approval_required_steps"] == ["release"]
    assert body["ordered_steps"][0]["risk_score"] == 2
    assert body["ordered_steps"][2]["risk_score"] == 5


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


def test_workflow_plan_unknown_action_is_high_risk_by_default():
    response = client.post("/api/v1/workflows/plan", json={
        "project_id": "local-project",
        "domain": "workflow",
        "title": "Custom action",
        "objective": "Run a custom action",
        "steps": [
            {"step_id": "custom", "title": "Custom", "action": "unknown_action", "risk_score": 0, "side_effect": "none"},
        ],
    })
    assert response.status_code == 200
    step = response.json()["ordered_steps"][0]
    assert step["risk_score"] == 5
    assert step["requires_human_approval"] is True


def test_coding_template_has_reviewed_stages_and_release_gate():
    response = client.post("/api/v1/workflows/templates/coding", json={
        "project_id": "local-project",
        "title": "Build cooperative platform",
        "objective": "Build a cooperative management platform",
    })
    assert response.status_code == 200
    body = response.json()
    assert [step["step_id"] for step in body["ordered_steps"]] == [
        "requirements", "architecture", "implementation", "tests", "security", "build", "deploy"
    ]
    assert body["approval_required_steps"] == ["deploy"]
    assert body["execution_enabled"] is False


def test_film_template_requires_publish_approval():
    response = client.post("/api/v1/workflows/templates/film", json={
        "project_id": "local-project",
        "title": "Produce animated short",
        "objective": "Create a short animated film",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["ordered_steps"][-1]["action"] == "publish"
    assert body["approval_required_steps"] == ["publish"]


def test_general_workflow_template_gates_external_action():
    response = client.post("/api/v1/workflows/templates/workflow", json={
        "project_id": "local-project",
        "title": "Process service request",
        "objective": "Process and reconcile a service request",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["approval_required_steps"] == ["execute"]
