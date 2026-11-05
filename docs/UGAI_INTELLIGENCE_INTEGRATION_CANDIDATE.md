# UGAI Intelligence Integration Candidate V1

**Status:** Draft integration candidate — not production-ready  
**Parent branch:** `feature/hybrid-reasoning-architecture-v1`  
**Purpose:** Exercise the UGAI model platform, reasoning contracts, decision engine, IM19 adapter and durable workflow in one isolated candidate without changing `main`.

## Included packages

- `app/`: existing FastAPI application, provider adapters, model router and model registry.
- `app/reasoning/`: versioned reasoning artifacts, evidence/claim reference validation, model-role routing, calibrated-confidence provenance, registry-backed route catalog loading, exact-provider execution, and an authenticated read-only reasoning endpoint.
- `src/ugai_decision/`: AEPH/decision workflow, evidence models, MCP evidence source, Supabase and PostgreSQL audit adapters.
- `src/ugai_mcp/`: bounded remote IM19 Streamable HTTP client, identity/resource scoping, allowlisted tool policy and audit.
- `src/ugai_workflow/`: task state machine, PostgreSQL store, worker leases, retry scheduler and decision-workflow bridge.
- `src/ugai_replication/`: framework-neutral outbox replication contracts.
- `ops/knowledge_replication/`, `postgres/migrations/`, and `supabase/migrations/`: non-applied SQL and deployment/backup artifacts.

## Integration rules

1. UGAI owns reasoning, decision policy and task orchestration.
2. IM19 remains the only central MCP gateway. This repository contains only the client adapter.
3. Model output is untrusted data; it cannot authorize tools, change task state, approve a decision or bypass tenant policy.
4. The decision bridge reuses `DecisionWorkflow`; it does not create a second decision engine.
5. Workflow state is persisted through the durable workflow store. Side-effect uncertainty is blocked for reconciliation rather than retried blindly.
6. Supabase remains active and authoritative. PostgreSQL VM is a replication/DR target until separately verified. Google Drive remains encrypted backup/archive.
7. SQL migrations in this candidate are files only. No database has been changed by this PR.

## Validation enabled by this candidate

- Main CI installs the API, MCP, PostgreSQL and worker extras; lint/test covers `app`, `src` and `tests`.
- IM19/decision adapter CI covers connector, decision, workflow, audit and replication contracts.
- Dedicated PostgreSQL workflow tests tenant RLS, idempotency, concurrent claims, lease fencing and retry behavior against a disposable PostgreSQL service.
- Reasoning tests check strict schemas, model route policy, evidence-reference integrity and calibration provenance.

## Explicitly incomplete

- The reasoning policy router is not yet wired into the existing provider inference router/model registry.
- The endpoint is an initial policy-routed completion + critique, not the complete Observe/Analyze/Retrieve/Evaluate/Challenge/Synthesize/Decide/Verify orchestration. Authorized RAG_Cerdas retrieval is not yet connected; the response explicitly reports evidence grounding as not performed.
- The route catalog's capability, region, quality and price attributes are operator-maintained and still require controlled administration, freshness checks and monitoring. No live IM19, RAG_Cerdas, Notebook Studio or Cloudbrowser staging E2E has been demonstrated.
- No production tenant identity/secret resolver injection, production provider operation, RAG gold-set benchmark, calibrated confidence dataset, route-catalog caching/rotation, PostgreSQL VM provisioning, Google Drive backup/restore, load test or deployment has been verified.
- The Notebook Studio execution API and user-side isolated runtime remain owned by that repository and are not provided by this candidate.

## Merge/release gate

Keep this PR Draft until all workflows pass on the same head SHA, the Architecture Owner approves the branch convergence strategy, runtime and security integration tests pass, and the external service boundaries are tested in staging. A green unit-test run alone is not production certification.
