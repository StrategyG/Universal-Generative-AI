# Institutional Workflow Control Plane

## Purpose

The shared workflow contract supports three project domains: software engineering (coding), film/media production (film), and general operations (workflow). A domain describes the work; it does not grant execution authority.

## Control model

1. A caller submits a project-scoped objective and typed workflow steps.
2. The planner validates unique identifiers, dependency references, and acyclic DAG structure.
3. A server-owned action policy derives risk and side-effect classification. Client-provided risk and side-effect hints never authorize or downgrade an action.
4. Known actions receive reviewed risk/side-effect classifications. Unknown actions default to risk 5, external-write semantics, and mandatory human approval.
5. The plan is returned in stable topological order with an explicit not_configured execution state.
6. Execution is disabled until a trusted executor, tenant/project-scoped tool permissions, durable job state, artifact trust, and audit events are implemented and verified.

## Domain mapping

- Coding: requirements, architecture, implementation, tests, security review, build, deployment.
- Film: concept, script, continuity/bible, storyboard, asset generation, shot assembly, audio, render, QC, publish.
- Workflow: intake, classify, plan, approve, execute, reconcile, report.

The server action registry currently includes a limited starter set. Domain descriptions are not evidence that every generator, model, or production tool is integrated.

## Risk policy

| Risk | Default treatment |
|---|---|
| 0-2 | May be considered for low-risk execution only after executor authorization and sandbox controls exist |
| 3-5 | Human approval required before execution |
| external_write / deploy / delete / publish | Human approval required regardless of numeric risk |
| unknown action | Fail closed: risk 5, external-write classification, human approval |
| workspace_write | Requires an isolated workspace and path policy; never implies arbitrary filesystem access |

Risk is currently derived from a server-owned static action registry. Before production, the policy must be versioned, reviewed, tied to executor capabilities, and covered by authorization tests. It must not accept an LLM-generated risk score as authority.

## Current limitations

This is a planning and validation control plane only. It does not persist plans, execute steps, call tools, run code, generate media, store artifacts, or provide approval endpoints. The API returns execution_enabled=false and each step as not_configured to prevent a plan from being mistaken for completed work.
