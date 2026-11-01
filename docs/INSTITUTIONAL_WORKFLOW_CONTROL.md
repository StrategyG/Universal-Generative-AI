# Institutional Workflow Control Plane

## Purpose

The shared workflow contract supports three project domains: software engineering (coding), film/media production (film), and general operations (workflow). A domain describes the work; it does not grant execution authority.

## Control model

1. A caller submits a project-scoped objective and typed workflow steps.
2. The planner validates unique identifiers, dependency references, and acyclic DAG structure.
3. A deterministic policy classifies a step for human approval when risk is 3-5 or its side effect is external write, deploy, delete, or publish.
4. The plan is returned in stable topological order with an explicit not_configured execution state.
5. Execution is disabled until a trusted executor, tenant/project-scoped tool permissions, durable job state, artifact trust, and audit events are implemented and verified.

## Domain mapping

- Coding: requirements, architecture, implementation, tests, security review, build, deployment.
- Film: concept, script, continuity/bible, storyboard, asset generation, shot assembly, audio, render, QC, publish.
- Workflow: intake, classify, plan, approve, execute, reconcile, report.

These are reference task families, not claims that the corresponding generators or production tools are already integrated.

## Risk policy

| Risk | Default treatment |
|---|---|
| 0-2 | May be planned without human approval; execution still requires an enabled executor and scoped authorization |
| 3-5 | Human approval required before execution |
| external_write / deploy / delete / publish | Human approval required regardless of numeric risk |
| workspace_write | Not automatically approval-gated by this planner; executor must still enforce workspace sandbox and path policy |

Risk scores are caller-supplied inputs at this stage and are not independently inferred or verified. Production policy must calculate or validate risk server-side using action/tool metadata, not trust an agent-provided score.

## Current limitations

This is a planning and validation control plane only. It does not persist plans, execute steps, call tools, run code, generate media, store artifacts, or provide approval endpoints. The API returns execution_enabled=false and each step as not_configured to prevent a plan from being mistaken for completed work.
