# Model Governance

## Policy

Production external-GPU jobs and non-mock `/api/v1/generate` inference must reference an approved model registry entry with an immutable 40-character hexadecimal commit revision. Mutable refs such as `main`, `latest`, or a floating branch are not production revisions.

## Registry record

The PostgreSQL registry records:
- stable model ID, model name and family;
- immutable revision/commit SHA;
- source identifier, license identifier and intended use;
- input and output schema metadata;
- hardware requirements and runtime dependency versions;
- license review status and validation status;
- evaluation dataset version, evaluation timestamp and metrics;
- lifecycle state (`pending_review`, `approved`, `disabled`, `rejected`) and timestamps.

The source field is metadata only; it is not a URL that the platform automatically fetches.

## Approval gate

A model revision starts in `pending_review`. Approval succeeds only when:
1. `license_review_status = approved`;
2. `validation_status = passed`;
3. `evaluation_results.status = passed`;
4. `evaluation_results.dataset_version` is present;
5. `evaluation_results.evaluated_at` is present;
6. `evaluation_results.metrics` is present.

The same predicate is checked during production job submission and registered-worker claim. In production, it also guards non-mock generation through `/api/v1/generate`. In development, `MODEL_REGISTRY_ENFORCEMENT=true` enables the stricter path.

Disabling an approved revision cancels unfinished external-GPU jobs pinned to that revision. A disabled revision cannot be re-enabled in place; register a new immutable revision and repeat review.

## API surface

Every registry administration route requires `X-Worker-Admin-Token`:

- `POST /api/v1/model-registry/versions` — register a revision as pending review.
- `GET /api/v1/model-registry/versions?model_id=...&revision=...` — inspect a revision.
- `POST /api/v1/model-registry/versions/approve` — approve if all required evidence fields pass.
- `POST /api/v1/model-registry/versions/disable` — disable a revision and cancel unfinished jobs.

## Evidence limits and remaining controls

The current API records evidence values supplied by an authorized operator. It does **not** independently determine legal license compatibility, rerun model validation, reproduce benchmark results, verify the model publisher, attest which weights an external notebook loaded, or provide an append-only reviewer identity/audit trail. The shared admin secret authorizes an action but does not identify the human reviewer.

The current registry is an approval control, not a certification or proof of supply-chain integrity. Independent license review, signed model manifests, runtime attestation, a sandboxed model downloader, repeatable evaluation runners and model rollback approval history remain outstanding.

Do not download arbitrary model repositories or train a foundation model from scratch without a separately approved plan, license review, infrastructure design and budget.
