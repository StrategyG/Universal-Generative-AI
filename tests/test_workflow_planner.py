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


def test_plan_orders_dependencies_and_applies_server_policy():
    plan = build_workflow_plan(request([
        {"step_id": "deploy", "title": "Deploy", "action": "deploy", "depends_on": ["test"], "side_effect": "none", "risk_score": 0},
        {"step_id": "test", "title": "Test", "action": "run_tests", "depends_on": ["build"]},
        {"step_id": "build", "title": "Build", "action": "generate_code", "risk_score": 5, "side_effect": "delete"},
    ]))
    assert [step.step_id for step in plan.ordered_steps] == ["build", "test", "deploy"]
    assert plan.approval_required_steps == ["deploy"]
    assert plan.ordered_steps[0].risk_score == 2
    assert plan.ordered_steps[0].side_effect.value == "workspace_write"
    assert plan.ordered_steps[0].agent_role == "Senior Software Engineer"
    assert "src/" in plan.ordered_steps[0].expected_artifacts
    assert len(plan.ordered_steps[0].acceptance_criteria) >= 3
    assert plan.execution_enabled is False
    assert plan.status == "planning_only"
    assert plan.quality_policy == "deliverable-contracts-v1"


def test_unknown_action_fails_closed_even_if_client_marks_it_safe():
    plan = build_workflow_plan(request([
        {"step_id": "custom", "title": "Custom", "action": "unreviewed_custom_action", "risk_score": 0, "side_effect": "none"},
    ]))
    step = plan.ordered_steps[0]
    assert step.risk_score == 5
    assert step.side_effect.value == "external_write"
    assert step.requires_human_approval is True
    assert step.policy_rule == "default.deny_unknown_action"
    assert step.agent_role.startswith("Unassigned")
    assert "unverified_action_report.json" in step.expected_artifacts


def test_high_risk_action_requires_approval_even_if_client_claims_safe():
    plan = build_workflow_plan(request([
        {"step_id": "release", "title": "Release", "action": "publish", "risk_score": 0, "side_effect": "none"},
    ], domain="film"))
    assert plan.approval_required_steps == ["release"]
    assert "rights_clearance/" in plan.ordered_steps[0].expected_artifacts


@pytest.mark.parametrize("steps, message", [
    ([{"step_id": "a", "title": "A", "action": "run_tests", "depends_on": ["missing"]}], "unknown dependencies"),
    ([{"step_id": "a", "title": "A", "action": "run_tests", "depends_on": ["b"]}, {"step_id": "b", "title": "B", "action": "run_tests", "depends_on": ["a"]}], "cycle"),
    ([{"step_id": "a", "title": "A", "action": "run_tests", "depends_on": ["a"]}], "itself"),
])
def test_invalid_graph_is_rejected(steps, message):
    with pytest.raises(ValueError, match=message):
        build_workflow_plan(request(steps))


def test_duplicate_step_ids_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        build_workflow_plan(request([
            {"step_id": "same", "title": "A", "action": "run_tests"},
            {"step_id": "same", "title": "B", "action": "run_tests"},
        ]))
