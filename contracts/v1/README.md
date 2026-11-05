# Cataran Platform Contracts v1

**Status:** Architecture-approved transitional source; release candidate under review, not yet published as a production contract.
**Version:** 1.0.0
**Canonical home:** `StrategyG/Universal-Generative-AI/contracts/v1`
**Decision:** [ADR-0003 — Canonical contract home and change control](../../docs/adr/0003-platform-contracts-home.md)

Runtime consumers must continue pinning immutable revisions and must not infer production compatibility from this directory alone. Adoption requires consumer CI, migration notes, review and a tagged release.

## Contract inventory

| Schema | Purpose |
|---|---|
| `identity-context` | Verified principal, issuer-scoped subject, tenant, project and namespaced roles |
| `task` | UGAI-owned task identity, lifecycle state and idempotency tuple |
| `task-event` | Append-only task event sequence and state transition evidence |
| `platform-event-envelope` | Shared cross-plane message envelope, trace context and secret-safe payload |
| `approval-receipt` | Human decision bound to an immutable stage digest |
| `tool-invocation` | IM19 gateway, connector revision, authorization and audit references |
| `evidence-record` | Artifact/source hash and producer provenance |
| `error-envelope` | Safe error and uncertain-outcome semantics |
| `a2a-dispatch` | Cross-service dispatch identity and idempotency |

## Normative ownership

- **UGAI:** authoritative task state, decision policy, orchestration and task-event publication.
- **IM19:** sole MCP gateway; connector/tool authorization, secret resolution, egress enforcement and tool invocation audit.
- **Notebook Studio:** client-side task submission and read-only projection of UGAI task state; never a second task authority.
- **Cloudbrowser:** worker execution against a lease-bound task; it does not own user identity or decision policy.
- **RAG_Cerdas:** source ingestion/retrieval and provenance production; it does not own platform task state.
- **Android Connector:** local adapter into IM19; it is not another MCP gateway.

## Identity rules

1. `issuer` plus opaque `subject` identify an external principal; `subject` alone is not globally unique.
2. Production issuers must be absolute HTTPS URIs. URL userinfo, query and fragment components are rejected.
3. Tenant and project context must be derived and verified server-side. Client-supplied tenant/project IDs are selectors only and must be authorized against the verified principal.
4. Never cast an OIDC subject to a Supabase UUID, infer identity from email, or accept JWT role claims as authoritative membership.
5. Role values are namespaced. Unknown namespaces/roles deny by default.
6. Mapping to Supabase `auth.users.id` is a separately provisioned identity link with provenance, lifecycle and revocation; no implicit linking is permitted.

## Task and idempotency rules

The idempotency identity is `(tenant_id, actor_id, idempotency_key)`. The request digest is SHA-256 over a documented canonical serialization of the semantic request (excluding transport-only headers and secrets). Same tuple + same digest returns the original task; same tuple + different digest returns a conflict. The server must persist task creation and outbox/event intent transactionally.

UGAI is the source of truth for task state. Notebook and workers hold projections/caches only. Task events are append-only and monotonically sequenced per task. Consumers deduplicate by `event_id` and reject sequence gaps until replay/reconciliation completes.

## State machine

The normal path follows UGAI's current state machine:

`received -> observing -> planning -> executing -> verifying -> succeeded`

Other allowed transitions include approval, clarification, blocked, failed, cancelled and outcome-unknown branches. Consumers must not invent alternate transitions.

Uncertain external effects use a dedicated non-claimable state:

- `executing -> outcome_unknown` when a side effect may have occurred but confirmation is missing.
- `outcome_unknown` cannot be claimed, retried or moved directly to success.
- Only a trusted, unleased reconciliation path may move `outcome_unknown -> verifying`, with a valid evidence digest and `reconciliation_verified=true`.
- Reconciliation verifies the existing external outcome first; it must not replay the side effect.

## Human approval rules

Approval is action-specific and bound to stage digest, task, tenant, policy version and expiry. Any change to the approved stage invalidates the receipt. Only an authenticated human principal may issue a human approval. A receipt is not transferable across tenants/tasks/actions. Expired, revoked or denied approvals never authorize execution. UI text alone is not approval evidence.

## IM19 tool rules

All MCP tools route through IM19. UGAI and workers call IM19's authenticated service boundary; they do not create direct MCP clients for arbitrary providers. Tool invocation records contain argument/result digests and references, not raw credentials or secret values. Mutating/destructive calls require policy authorization and a matching approval receipt. Egress controls are enforced outside application code as well as in the gateway.

## Evidence and audit rules

Evidence records preserve source/version/hash and producer version. Audit records are append-only. Secrets, access tokens, raw credentials and unredacted sensitive payloads must not be written to event or error envelopes. Every cross-plane request carries task and trace correlation IDs. Acknowledged delivery must be idempotent; uncertain external outcomes are reconciled before retry.

## Compatibility and change control

- Semantic versioning: patch = non-breaking clarification/optional additive constraints; minor = backward-compatible optional additions; major = breaking schema/semantics.
- Every consumer declares supported contract major/minor and records its version in release metadata.
- CI validates every Draft 2020-12 schema and positive/negative golden fixtures in the manifest.
- Breaking changes require a new major version, migration notes, consumer matrix, dual-read/dual-write plan where necessary, and rollback instructions.
- No runtime repo may copy a schema and silently diverge; consumers pin a version or immutable revision.
- The Architecture Owner controls changes to identity, task lifecycle, approval and gateway semantics. A named repository maintainer must own implementation and release automation; the role mapping must be recorded before the v1 tag is cut.

## Validation

Run:

```bash
python -m pip install jsonschema==4.23.0
python scripts/validate_platform_contracts.py
```

The validator checks all Draft 2020-12 schemas, positive fixtures and negative fixtures listed in the manifest. It does not prove runtime consumer conformance. Each consumer must add contract fixtures and integration tests before claiming compatibility.
