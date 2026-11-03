# Generation Quality Contracts

## Purpose

The workflow planner now emits a role, expected artifact list, and acceptance criteria for every registered action. This adds explicit deliverable contracts to coding, film, and operational workflow plans. The contracts are intended to reduce underspecified generation tasks and make downstream verification testable.

## How to use the contracts

For every planned step:

1. Assign the stated specialist role to the responsible agent or human.
2. Generate only the listed deliverables, retaining source and revision provenance.
3. Evaluate every acceptance criterion with a trusted tool or reviewer.
4. Store evidence against the exact artifact digest and source commit/revision.
5. Block dependent steps when required evidence is missing or a critical criterion fails.

Unknown actions receive no specialist assignment and only a deny-by-default contract. They remain risk 5, external-write, and require human approval.

## Coding deliverable contract

The coding sequence covers requirements traceability, solution architecture, data model, threat model, implementation, tests, security review, reproducible build, and human-controlled deployment. A generated code artifact is not accepted merely because the model returned syntactically plausible text. It must compile, pass relevant tests, satisfy security gates, and map back to approved requirements.

## Film deliverable contract

The film sequence covers screenplay and beat structure, character arcs, continuity, shot-level storyboard and timing, asset provenance, shot assembly, render metadata, editorial/technical QC, and rights clearance. A generated image or video is not accepted as a completed film deliverable without shot, timing, continuity, audio/video, and delivery validation.

## Workflow deliverable contract

Operational workflows require scoped intake, policy classification, approval for external writes, an action receipt, independent reconciliation, and an evidence-indexed report. An agent's assertion that an external action succeeded is not independent evidence.

## Important limitation

These contracts are deterministic planning metadata. They do not train or fine-tune foundation-model weights, call an LLM, run code, generate a screenplay, render video, or independently verify artifacts. The current API still returns planning-only workflow plans with execution disabled. Trusted evaluators, durable step execution, sandboxed coding, media adapters, artifact storage, and append-only audit remain separate implementation gates.
