from app.workflows.planner import build_workflow_plan
from app.workflows.schemas import (
    ProjectDomain,
    WorkflowPlan,
    WorkflowPlanRequest,
    WorkflowTemplateRequest,
)


_TEMPLATES: dict[ProjectDomain, list[dict[str, object]]] = {
    ProjectDomain.CODING: [
        {"step_id": "requirements", "title": "Requirements analysis", "action": "requirements_analysis"},
        {"step_id": "architecture", "title": "Architecture design", "action": "architecture_design", "depends_on": ["requirements"]},
        {"step_id": "implementation", "title": "Code generation and implementation", "action": "generate_code", "depends_on": ["architecture"]},
        {"step_id": "tests", "title": "Automated tests", "action": "run_tests", "depends_on": ["implementation"]},
        {"step_id": "security", "title": "Security review", "action": "security_review", "depends_on": ["tests"]},
        {"step_id": "build", "title": "Build and package", "action": "build_project", "depends_on": ["security"]},
        {"step_id": "deploy", "title": "Deployment approval and release", "action": "deploy", "depends_on": ["build"]},
    ],
    ProjectDomain.FILM: [
        {"step_id": "script", "title": "Script development", "action": "write_script"},
        {"step_id": "continuity", "title": "Story and continuity review", "action": "continuity_review", "depends_on": ["script"]},
        {"step_id": "storyboard", "title": "Storyboard and shot planning", "action": "create_storyboard", "depends_on": ["continuity"]},
        {"step_id": "assets", "title": "Asset generation", "action": "generate_asset", "depends_on": ["storyboard"]},
        {"step_id": "assembly", "title": "Shot assembly", "action": "assemble_shot", "depends_on": ["assets"]},
        {"step_id": "render", "title": "Video rendering", "action": "render_video", "depends_on": ["assembly"]},
        {"step_id": "quality", "title": "Editorial and technical QC", "action": "quality_review", "depends_on": ["render"]},
        {"step_id": "publish", "title": "Publication approval", "action": "publish", "depends_on": ["quality"]},
    ],
    ProjectDomain.WORKFLOW: [
        {"step_id": "intake", "title": "Request intake", "action": "intake_request"},
        {"step_id": "classify", "title": "Classification and routing", "action": "classify_request", "depends_on": ["intake"]},
        {"step_id": "execute", "title": "Controlled external action", "action": "external_write", "depends_on": ["classify"]},
        {"step_id": "reconcile", "title": "Result reconciliation", "action": "reconcile_result", "depends_on": ["execute"]},
        {"step_id": "report", "title": "Evidence and status report", "action": "generate_report", "depends_on": ["reconcile"]},
    ],
}


def build_domain_template(
    domain: ProjectDomain,
    request: WorkflowTemplateRequest,
) -> WorkflowPlan:
    """Return a deterministic starter DAG; it does not run any stage."""
    plan_request = WorkflowPlanRequest(
        project_id=request.project_id,
        domain=domain,
        title=request.title,
        objective=request.objective,
        steps=_TEMPLATES[domain],
    )
    return build_workflow_plan(plan_request)
