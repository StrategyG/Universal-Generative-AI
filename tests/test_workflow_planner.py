import pytest

from app.workflows.planner import build_workflow_plan
from app.workflows.schemas import WorkflowPlanRequest


def request(steps, domain="coding"):
    return WorkflowPlanRequest(
        project_id="project-1",
        domain=domain,
        title="Institutional project",
        objective="Build and validate a project",
        steps=steps,
    )


def test_plan_orders_dependencies_and_applies_approval_policy():
    plan = build_workflow_plan(request([
        {"step_id": "deploy", "title": "Deploy", "action": "deploy", "depends_on": ["test"], "side_effect": "deploy"},
        {"step_id": "test", "title": "Test", "action": "run_tests", "depends_on": ["build"]},
        {"step_id": "build", "title": "Build", "action": "generate_code", "risk_score": 1},
    ]))
    assert [step.step_id for step in plan.ordered_steps] == ["build", "test", "deploy"]
    assert plan.approval_required_steps == ["deploy"]
    assert plan.execution_enabled is False
    assert plan.status == "planning_only"


def test_high_risk_requires_approval_even_without_side_effect():
    plan = build_workflow_plan(request([
        {"step_id": "review", "title": "Review", "action": "review", "risk_score": 3},
    ], domain="film"))
    assert plan.approval_required_steps == ["review"]


@pytest.mark.parametrize("steps, message", [
    ([{"step_id": "a", "title": "A", "action": "x", "depends_on": ["missing"]}], "unknown dependencies"),
    ([{"step_id": "a", "title": "A", "action": "x", "depends_on": ["b"]}, {"step_id": "b", "title": "B", "action": "x", "depends_on": ["a"]}], "cycle"),
    ([{"step_id": "a", "title": "A", "action": "x", "depends_on": ["a"]}], "itself"),
])
def test_invalid_graph_is_rejected(steps, message):
    with pytest.raises(ValueError, match=message):
        build_workflow_plan(request(steps))


def test_duplicate_step_ids_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        build_workflow_plan(request([
            {"step_id": "same", "title": "A", "action": "x"},
            {"step_id": "same", "title": "B", "action": "y"},
        ]))
