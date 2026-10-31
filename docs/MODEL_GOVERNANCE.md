# Model Governance

## Policy

A model may not be selected for execution merely because a repository name is supplied in a job. Production execution must use a reviewed model registry entry and an immutable revision.

## Required registry record

Each approved model revision must retain:
- stable model ID, display name and model family;
- immutable repository revision/commit or artifact digest;
- publisher/source and retrieval date;
- license identifier, license text/reference and review decision;
- intended use, prohibited use, known limitations and safety notes;
- typed input/output contracts and supported task identifiers;
- supported framework/runtime versions and dependency lock;
- minimum CPU/RAM/GPU/VRAM/CUDA requirements;
- evaluation dataset/version, configuration, metrics and evidence;
- status: proposed, under_review, approved, deprecated, revoked;
- approval actor, timestamp, reason and rollback target.

## Required controls

1. **Allowlist:** execution accepts only model IDs and revisions explicitly reviewed by an operator.
2. **Immutable pinning:** mutable tags such as `main`, `latest`, or floating model branches are not production pins.
3. **License review:** record commercial-use permissions, redistribution constraints, attribution obligations and any usage restrictions.
4. **Provenance:** store source, revision/digest, runtime versions and model parameters with each job and artifact.
5. **Compatibility:** reject a job when the selected worker lacks the required framework, CUDA version, VRAM or task adapter.
6. **Evaluation:** record repeatable task-specific validity, quality, latency, failure and cost metrics.
7. **Rollback:** retain the last approved revision and the evidence needed to disable or revert a model.
8. **Human approval:** an authorized reviewer approves a model revision before production enablement.

## Current implementation status

**BLOCKED.** The repository currently has a model/provider abstraction and an optional Diffusers adapter with an environment-configured model ID and revision. It does not yet enforce a registry allowlist, license review, schema compatibility, evaluation gate, or approval history. A model revision field in a job is provenance metadata, not proof that the model was approved or executed.

Do not download arbitrary model repositories or train a foundation model from scratch without a separate approved plan, license review, infrastructure design and budget.
