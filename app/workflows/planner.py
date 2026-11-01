from app.workflows.schemas import (
    PlannedStep,
    ProjectDomain,
    SideEffect,
    WorkflowPlan,
    WorkflowPlanRequest,
)

# Server-owned action policy. Client-supplied risk_score/side_effect are hints only.
# Unknown actions fail closed until explicitly reviewed and registered here.
_ACTION_POLICY: dict[str, tuple[int, SideEffect, str]] = {
    "requirements_analysis": (1, SideEffect.NONE, "coding.requirements_analysis"),
    "architecture_design": (1, SideEffect.NONE, "coding.architecture_design"),
    "generate_code": (2, SideEffect.WORKSPACE_WRITE, "coding.generate_code"),
    "edit_code": (2, SideEffect.WORKSPACE_WRITE, "coding.edit_code"),
    "run_tests": (1, SideEffect.NONE, "coding.run_tests"),
    "security_review": (2, SideEffect.NONE, "coding.security_review"),
    "build_project": (2, SideEffect.WORKSPACE_WRITE, "coding.build_project"),
    "install_dependencies": (3, SideEffect.WORKSPACE_WRITE, "coding.install_dependencies"),
    "deploy": (5, SideEffect.DEPLOY, "release.deploy"),
    "execute_shell": (5, SideEffect.EXTERNAL_WRITE, "sandbox.execute_shell"),
    "write_script": (1, SideEffect.NONE, "film.write_script"),
    "continuity_review": (1, SideEffect.NONE, "film.continuity_review"),
    "create_storyboard": (1, SideEffect.NONE, "film.create_storyboard"),
    "generate_asset": (2, SideEffect.WORKSPACE_WRITE, "film.generate_asset"),
    "assemble_shot": (2, SideEffect.WORKSPACE_WRITE, "film.assemble_shot"),
    "render_video": (2, SideEffect.WORKSPACE_WRITE, "film.render_video"),
    "quality_review": (1, SideEffect.NONE, "media.quality_review"),
    "publish": (5, SideEffect.PUBLISH, "media.publish"),
    "delete_asset": (5, SideEffect.DELETE, "artifact.delete"),
    "external_write": (5, SideEffect.EXTERNAL_WRITE, "workflow.external_write"),
}

_APPROVAL_SIDE_EFFECTS = {
    SideEffect.EXTERNAL_WRITE,
    SideEffect.DEPLOY,
    SideEffect.DELETE,
    SideEffect.PUBLISH,
}


def _policy_for(action: str) -> tuple[int, SideEffect, str]:
    normalized = action.strip().lower()
    return _ACTION_POLICY.get(
        normalized,
        (5, SideEffect.EXTERNAL_WRITE, "default.deny_unknown_action"),
    )


def build_workflow_plan(request: WorkflowPlanRequest) -> WorkflowPlan:
    """Validate a workflow DAG and derive approval policy on the server."""
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
        ready = [
            step.step_id for step in request.steps
            if step.step_id in remaining and not remaining[step.step_id]
        ]
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
        risk_score, side_effect, policy_rule = _policy_for(step.action)
        approval = risk_score >= 3 or side_effect in _APPROVAL_SIDE_EFFECTS
        if approval:
            approval_ids.append(step_id)
        planned.append(PlannedStep(
            step_id=step.step_id,
            title=step.title,
            action=step.action,
            depends_on=step.depends_on,
            side_effect=side_effect,
            risk_score=risk_score,
            policy_rule=policy_rule,
            requires_human_approval=approval,
        ))

    domain_notes = {
        ProjectDomain.CODING: "Coding plans require isolated workspaces and test gates before any code execution or release.",
        ProjectDomain.FILM: "Film plans require asset provenance, continuity checks, render validation, and rights review before publication.",
        ProjectDomain.WORKFLOW: "Workflow plans require scoped tool permissions and reconciliation evidence for external actions.",
    }
    return WorkflowPlan(
        project_id=request.project_id,
        domain=request.domain,
        title=request.title,
        objective=request.objective,
        ordered_steps=planned,
        approval_required_steps=approval_ids,
        warnings=[
            "Planning only: this endpoint does not execute agents, tools, code, or media jobs.",
            "Risk and side-effect classifications are derived from server policy; client hints are ignored.",
            "Unknown actions fail closed as risk 5 and require human approval.",
            domain_notes[request.domain],
            "Execution remains disabled until a trusted executor, scoped permissions, durable state, and audit evidence are verified.",
        ],
    )
