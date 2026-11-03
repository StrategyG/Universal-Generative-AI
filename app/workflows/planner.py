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
    "intake_request": (1, SideEffect.NONE, "workflow.intake_request"),
    "classify_request": (1, SideEffect.NONE, "workflow.classify_request"),
    "reconcile_result": (1, SideEffect.NONE, "workflow.reconcile_result"),
    "generate_report": (1, SideEffect.NONE, "workflow.generate_report"),
}

# These are generation contracts, not claims that an agent or provider has executed.
# Every generated artifact must be checked against its acceptance criteria by a trusted
# evaluator before it can be treated as verified.
_ACTION_CONTRACTS: dict[str, tuple[str, list[str], list[str]]] = {
    "requirements_analysis": (
        "Product Manager / Business Analyst",
        ["requirements_spec.md", "acceptance_matrix.json"],
        [
            "Functional requirements have unique IDs and are testable.",
            "Non-functional requirements cover security, performance, accessibility, and reliability.",
            "Assumptions, exclusions, dependencies, and unresolved questions are explicit.",
            "Every requirement maps to at least one acceptance test.",
        ],
    ),
    "architecture_design": (
        "Principal Solution Architect",
        ["architecture.md", "adr/", "data_model.md", "threat_model.md"],
        [
            "Architecture identifies components, boundaries, interfaces, and data flows.",
            "Technology choices include rationale and documented trade-offs.",
            "Data model, tenancy boundaries, authorization, and failure modes are specified.",
            "Threat model covers trust boundaries, secrets, abuse cases, and mitigations.",
            "Deployment topology, observability, backup, and recovery are addressed.",
        ],
    ),
    "generate_code": (
        "Senior Software Engineer",
        ["src/", "tests/", "README.md"],
        [
            "Implementation follows approved architecture and repository conventions.",
            "No placeholder, stub, or mocked behavior is represented as production functionality.",
            "Inputs are validated and errors are explicit and safe.",
            "Tests cover normal, boundary, failure, and authorization cases.",
        ],
    ),
    "edit_code": (
        "Senior Software Engineer / Code Reviewer",
        ["changed_files/", "change_summary.md", "tests/"],
        [
            "Changes are limited to the approved scope.",
            "Existing public contracts remain compatible or are versioned.",
            "Regression tests cover the reported defect.",
            "Diff contains no secrets, unrelated formatting churn, or generated debris.",
        ],
    ),
    "run_tests": (
        "QA Automation Engineer",
        ["test_report.json", "coverage_report"],
        [
            "Unit, integration, and contract tests execute against the target commit.",
            "Failures and skipped tests are reported without being relabeled as passes.",
            "Critical paths and authorization boundaries have explicit coverage.",
            "Test evidence identifies commit, environment, and command.",
        ],
    ),
    "security_review": (
        "Application Security Engineer",
        ["security_report.md", "dependency_audit.json"],
        [
            "Authentication, authorization, tenant isolation, and input validation are reviewed.",
            "Secrets, injection, SSRF, unsafe deserialization, and supply-chain risks are assessed.",
            "Critical and high findings are fixed or formally blocked from release.",
            "Evidence is tied to the exact candidate commit.",
        ],
    ),
    "build_project": (
        "Build / Release Engineer",
        ["build_manifest.json", "dist/"],
        [
            "Build is reproducible from a clean environment.",
            "Artifacts have checksums and declared versions.",
            "Dependency and license manifests are retained.",
            "Build output passes smoke tests.",
        ],
    ),
    "deploy": (
        "Release Manager (human approval required)",
        ["release_record.json", "rollback_plan.md"],
        [
            "Deployment has explicit human approval and a verified target environment.",
            "Health checks and smoke tests pass after deployment.",
            "Rollback trigger, owner, and procedure are documented.",
            "Release provenance identifies source commit and artifact digest.",
        ],
    ),
    "write_script": (
        "Screenwriter / Story Editor",
        ["screenplay.fountain", "beat_sheet.md", "character_arcs.md"],
        [
            "Premise, protagonist goal, obstacle, stakes, and resolution are explicit.",
            "Scenes have causal transitions and advance character or plot.",
            "Dialogue is performable and distinct by character.",
            "Runtime target and audience constraints are respected.",
        ],
    ),
    "continuity_review": (
        "Script Supervisor / Story Editor",
        ["continuity_report.md", "story_issues.json"],
        [
            "Character motivations and emotional state remain consistent.",
            "Timeline, geography, props, costumes, and cause-effect continuity are checked.",
            "Unresolved story contradictions are listed with severity.",
            "Every critical issue has a proposed correction.",
        ],
    ),
    "create_storyboard": (
        "Director / Storyboard Artist",
        ["shot_list.csv", "storyboard/", "animatic_timing.json"],
        [
            "Every scene maps to shots with framing, action, camera, and duration.",
            "Screen direction, eyelines, staging, and visual continuity are specified.",
            "Shot durations add up to the approved runtime target.",
            "Critical emotional beats are legible without relying only on dialogue.",
        ],
    ),
    "generate_asset": (
        "Production Designer / Asset Supervisor",
        ["asset_manifest.json", "assets/"],
        [
            "Assets match approved character and world design references.",
            "Scale, naming, format, resolution, and rig compatibility are validated.",
            "Source model, prompt, seed, license, and revision are recorded where available.",
            "No unapproved character or style drift is introduced.",
        ],
    ),
    "assemble_shot": (
        "Layout Artist / Animation Director",
        ["shot_project/", "shot_manifest.json"],
        [
            "Shot references the approved assets and storyboard revision.",
            "Camera, blocking, timing, and transforms are reproducible.",
            "Missing assets and unsupported operations fail explicitly.",
            "Shot can be opened by the declared downstream toolchain.",
        ],
    ),
    "render_video": (
        "Lighting / Render Supervisor",
        ["render_manifest.json", "preview.mp4"],
        [
            "Resolution, frame rate, color space, and duration match the specification.",
            "Render completes without missing frames, black frames, or corrupt media.",
            "Audio/video synchronization and codec metadata are validated.",
            "Render settings and source revisions are recorded.",
        ],
    ),
    "quality_review": (
        "Editorial / Technical QC Supervisor",
        ["editorial_qc.md", "technical_qc.json"],
        [
            "Narrative clarity, pacing, continuity, and audience suitability are reviewed.",
            "Frame integrity, audio peaks, synchronization, and encoding are checked.",
            "All critical defects are resolved or publication is blocked.",
            "QC evidence identifies the exact rendered artifact digest.",
        ],
    ),
    "publish": (
        "Producer / Rights Manager (human approval required)",
        ["publication_record.json", "rights_clearance/"],
        [
            "Human approval is recorded for the exact final master.",
            "Music, voice, likeness, stock, and generated asset rights are cleared.",
            "Metadata, captions, accessibility, and delivery specifications are complete.",
            "Published artifact digest matches the approved master.",
        ],
    ),
    "intake_request": (
        "Service Intake Analyst",
        ["intake_record.json"],
        ["Requester, objective, scope, deadline, and project are captured."],
    ),
    "classify_request": (
        "Operations Analyst",
        ["classification.json", "policy_match.json"],
        ["Request type, sensitivity, risk, owner, and required permissions are classified."],
    ),
    "external_write": (
        "Authorized Operations Agent (human approval required)",
        ["action_receipt.json"],
        ["Exact target, payload, authorization, and idempotency key are recorded."],
    ),
    "reconcile_result": (
        "Control / Reconciliation Analyst",
        ["reconciliation_report.json"],
        ["Requested action is compared with independently retrieved resulting state."],
    ),
    "generate_report": (
        "Institutional Reporting Analyst",
        ["execution_report.md", "evidence_index.json"],
        ["Report distinguishes verified facts, unverified claims, failures, and omissions."],
    ),
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
    """Validate a workflow DAG and derive server-owned risk and quality contracts."""
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
        contract = _ACTION_CONTRACTS.get(step.action.strip().lower())
        if contract is None:
            agent_role = "Unassigned — action requires policy review"
            expected_artifacts = ["unverified_action_report.json"]
            acceptance_criteria = [
                "Action is not executable until its policy, owner, and evaluator are registered.",
                "Output must be independently verified before downstream use.",
            ]
        else:
            agent_role, expected_artifacts, acceptance_criteria = contract
        planned.append(PlannedStep(
            step_id=step.step_id,
            title=step.title,
            action=step.action,
            depends_on=step.depends_on,
            side_effect=side_effect,
            risk_score=risk_score,
            policy_rule=policy_rule,
            requires_human_approval=approval,
            agent_role=agent_role,
            expected_artifacts=expected_artifacts,
            acceptance_criteria=acceptance_criteria,
        ))

    domain_notes = {
        ProjectDomain.CODING: "Coding plans require isolated workspaces, reproducible builds, tests, security review, and human release approval.",
        ProjectDomain.FILM: "Film plans require screenplay and continuity review, shot-level contracts, asset provenance, render QC, rights review, and human publication approval.",
        ProjectDomain.WORKFLOW: "Workflow plans require scoped tool permissions, human approval for external writes, and independent reconciliation evidence.",
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
            "Role, artifact, and acceptance contracts define expected work; they are not proof of completed or verified work.",
            "Risk and side-effect classifications are derived from server policy; client hints are ignored.",
            "Unknown actions fail closed as risk 5 and require human approval.",
            domain_notes[request.domain],
            "Execution remains disabled until trusted executors, scoped permissions, durable state, artifact verification, and audit evidence are implemented.",
        ],
    )
