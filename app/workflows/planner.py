from app.workflows.schemas import (
    PlannedStep,
    SideEffect,
    WorkflowPlan,
    WorkflowPlanRequest,
)

_APPROVAL_SIDE_EFFECTS = {
    SideEffect.EXTERNAL_WRITE,
    SideEffect.DEPLOY,
    SideEffect.DELETE,
    SideEffect.PUBLISH,
}


def build_workflow_plan(request: WorkflowPlanRequest) -> WorkflowPlan:
    """Validate a workflow DAG and apply deterministic human-approval policy."""
    by_id = {step.step_id: step for step in request.steps}
    if len(by_id) != len(request.steps):
        raise ValueError("step_id values must be unique")

    for step in request.steps:
        if step.step_id in step.depends_on:
            raise ValueError(f"step '{step.step_id}' cannot depend on itself")
        unknown = sorted(set(step.depends_on) - by_id.keys())
        if unknown:
            raise ValueError(
                f"step '{step.step_id}' has unknown dependencies: {', '.join(unknown)}"
            )

    remaining = {step.step_id: list(step.depends_on) for step in request.steps}
    ordered_ids: list[str] = []
    while remaining:
        ready = [step.step_id for step in request.steps
                 if step.step_id in remaining and not remaining[step.step_id]]
        if not ready:
            raise ValueError("workflow dependencies contain a cycle")
        for step_id in ready:
            ordered_ids.append(step_id)
            remaining.pop(step_id)
        for dependencies in remaining.values():
            dependencies[:] = [item for item in dependencies if item not in ready]

    planned: list[PlannedStep] = []
    approval_ids: list[str] = []
    for step_id in ordered_ids:
        step = by_id[step_id]
        approval = step.risk_score >= 3 or step.side_effect in _APPROVAL_SIDE_EFFECTS
        if approval:
            approval_ids.append(step_id)
        planned.append(PlannedStep(
            step_id=step.step_id,
            title=step.title,
            action=step.action,
            depends_on=step.depends_on,
            side_effect=step.side_effect,
            risk_score=step.risk_score,
            requires_human_approval=approval,
        ))

    return WorkflowPlan(
        project_id=request.project_id,
        domain=request.domain,
        title=request.title,
        objective=request.objective,
        ordered_steps=planned,
        approval_required_steps=approval_ids,
        warnings=[
            "This endpoint validates and plans only; it does not execute agents, tools, code, or media jobs.",
            "No step may execute until a trusted executor, scoped permissions, and runtime evidence are configured.",
            "Human approval is mandatory for risk score 3-5 and external write, deploy, delete, or publish actions.",
        ],
    )
