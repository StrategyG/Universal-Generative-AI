# UGAI Reasoning API and Route Catalog

**Status:** Initial authenticated policy-routed text service — production qualification pending.

## Endpoint

`POST /api/v1/reasoning/complete`

The endpoint uses the existing verified principal dependency and project-access check. The caller supplies a project and objective, but cannot supply or lower the risk tier. The first release profile is deliberately fixed server-side to:

- Risk tier: `high`
- Reasoning profile: `deep`
- Independent evaluator: mandatory
- Human review: always required
- Tool execution: not available from this endpoint
- Evidence grounding: not performed by this initial endpoint

The endpoint returns a candidate answer and a separate independent critique. It does not claim that a model evaluator is ground truth, does not mark the response verified, and does not authorize any action.

## Operator route catalog

Set `REASONING_ROUTE_CATALOG_JSON` in the server environment. It contains non-secret routing metadata only. Example structure:

```json
[
  {
    "route_id": "reasoning-primary",
    "role": "reasoning_primary",
    "provider": "openai-compatible-chat",
    "model_id": "approved-model-identifier",
    "model_revision": "0123456789abcdef0123456789abcdef01234567",
    "model_family": "approved-model-family",
    "capabilities": ["text"],
    "data_regions": ["ap-southeast-1"],
    "max_context_tokens": 64000,
    "quality_rank": 90,
    "estimated_input_cost_per_million": 1.0,
    "estimated_output_cost_per_million": 4.0
  },
  {
    "route_id": "reasoning-evaluator",
    "role": "independent_evaluator",
    "provider": "anthropic-messages",
    "model_id": "another-approved-model",
    "model_revision": "abcdef0123456789abcdef0123456789abcdef01",
    "model_family": "different-model-family",
    "capabilities": ["text"],
    "data_regions": ["ap-southeast-1"],
    "max_context_tokens": 64000,
    "quality_rank": 90,
    "estimated_input_cost_per_million": 3.0,
    "estimated_output_cost_per_million": 12.0
  }
]
```

The sample IDs are placeholders, not real approved models. Do not copy them into production.

For every route, the server:
1. Validates the strict route schema, immutable 40-character model revision, unique route ID and declared text capability.
2. Calls the canonical PostgreSQL model registry's `assert_model_approved(model_id, revision)`.
3. Requires exact model ID and revision, matching model family, status `approved`, license review `approved`, and validation `passed`.
4. Sets the runtime `approved` and `enabled` flags itself only after registry success. The JSON cannot set these flags.
5. Compares the route metadata with the configured provider adapter before inference.

Additional settings:

- `REASONING_PERMITTED_DATA_REGIONS`: comma-separated allowed region identifiers. Default `ap-southeast-1`.
- `REASONING_MAX_ESTIMATED_COST`: maximum conservative estimated cost for primary + fallback + evaluator. Default `1.0`.

Provider API credentials must remain in the existing secret/environment injection mechanism and must never be placed in the route catalog.

## Limitations and remaining acceptance

- The catalog's capabilities, region, quality rank and price metadata are operator-maintained metadata; they must be reconciled with provider contracts and current pricing before activation.
- The endpoint performs a policy-routed candidate generation and independent critique, not the complete Observe/Analyze/Retrieve/Evaluate/Challenge/Synthesize/Decide/Verify workflow.
- It does not retrieve evidence from RAG_Cerdas. Caller context is untrusted input and does not count as source provenance.
- No benchmark-calibrated confidence is emitted.
- No live production provider or cross-repository staging call is implied by unit tests.
- High-impact outcomes still require human review; no tool invocation or side effect is exposed by this endpoint.
- Production qualification requires staging tests against the real registry, provider adapters, IM19 identity boundary and approved route metadata, plus latency/cost/security/load/rollback evidence.
