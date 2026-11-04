# Cataran Platform Contracts v1 — proposal

**Status:** PROPOSED / NOT CANONICAL / NOT APPROVED FOR PRODUCTION  
**Version:** 1.0.0  
**Proposed home:** `StrategyG/Universal-Generative-AI/contracts/v1` as a transitional candidate only.  
**Architecture decision:** tracked by [UGAI issue #32](https://github.com/StrategyG/Universal-Generative-AI/issues/32).

This directory is a reviewable, machine-readable proposal. Runtime repositories must not independently treat it as an accepted contract until the Architecture Owner approves the canonical home, contract owner, compatibility policy and consumer migration plan.

## Contract inventory

| Schema | Purpose |
|---|---|
| `identity-context` | Verified principal, issuer-scoped subject, tenant, project and namespaced roles |
| `task` | UGAI-owned task identity, lifecycle state and idempotency tuple |
| `task-event` | Append-only event sequence and state transition evidence |
| `approval-receipt` | Human decision bound to an immutable stage digest |
| `tool-invocation` | IM19 gateway, connector revision, authorization and audit references |
| `evidence-record` | Artifact/source hash and producer provenance |
| `error-envelope` | Safe error and uncertain-outcome semantics |
| `a2a-dispatch` | Cross-service dispatch identity and idempotency |

## Normative ownership proposal

- **UGAI:** authoritative task state, decision policy, orchestration and task-event publication.
- **IM19:** sole MCP gateway; connector/tool authorization, secret resolution, egress enforcement and tool invocation audit.
- **Notebook Studio:** client-side task submission and read-only projection of UGAI task state; never a second task authority.
- **Cloudbrowser:** worker execution against a lease-bound task; it does not own user identity or decision policy.
- **RAG_Cerdas:** source ingestion/retrieval and provenance production; it does not own platform task state.
- **Android Connector:** local adapter into IM19; it is not another MCP gateway.

## Identity rules

1. `issuer` plus opaque `subject` identify an external principal; `subject` alone is not globally unique.
2. Tenant and project context must be derived and verified server-side. Client-supplied tenant/project IDs are selectors only and must be authorized against the verified principal.
3. Never cast an OIDC subject to a Supabase UUID, infer identity from email, or accept JWT role claims as authoritative membership.
4. Role values are namespaced. Unknown namespaces/roles deny by default.
5. Mapping to Supabase `auth.users.id` is a separately provisioned identity link with provenance, lifecycle and revocation; no implicit linking is permitted.

## Task and idempotency rules

The idempotency identity is `(tenant_id, actor_id, idempotency_key)`. The request digest is SHA-256 over a documented canonical serialization of the semantic request (excluding transport-only headers and secrets). Same tuple + same digest returns the original task; same tuple + different digest returns a conflict. The server must persist task creation and outbox/event intent transactionally.

UGAI is the source of truth for task state. Notebook and workers hold projections/caches only. Task events are append-only and monotonically sequenced per task. Consumers deduplicate by `event_id` and reject gaps until replay/reconciliation completes.

## State machine

Allowed normal path:

`queued -> running -> awaiting_approval -> running -> succeeded`

Allowed terminal paths:

- `queued|running|awaiting_approval -> failed|cancelled|blocked`
- `running -> outcome_unknown` when a side effect may have occurred but confirmation is missing.
- `outcome_unknown -> succeeded|failed|cancelled` only by an explicit reconciliation event that carries evidence; never retry an uncertain side effect blindly.

Additional transitions (for example direct `queued -> succeeded`) require explicit versioned policy and tests; consumers must not invent transitions.

## Human approval rules

Approval is action-specific and bound to `stage_digest`, task, tenant, policy version and expiry. Any change to the approved stage invalidates the receipt. Only an authenticated human principal may issue a human approval. A receipt is not transferable across tenants/tasks/actions. Expired, revoked or denied approvals never authorize execution. UI text alone is not approval evidence.

## IM19 tool rules

All MCP tools route through IM19. UGAI and workers call IM19's authenticated service boundary; they do not create direct MCP clients for arbitrary providers. Tool invocation records contain argument/result digests and references, not raw credentials or secret values. Mutating/destructive calls require policy authorization and a matching approval receipt. Egress controls are enforced outside application code as well as in the gateway.

## Evidence and audit rules

Evidence records preserve source/version/hash and producer version. Audit records are append-only. Secrets, access tokens, raw credentials and unredacted sensitive payloads must not be written to event or error envelopes. Every cross-plane request carries task and trace correlation IDs. Acknowledged delivery must be idempotent; uncertain external outcomes are reconciled before retry.

## Compatibility and change control

- Semantic versioning: patch = non-breaking clarification/optional additive constraints; minor = backward-compatible optional additions; major = breaking schema/semantics.
- Every consumer declares supported contract major/minor and records its version in release metadata.
- CI validates schemas and valid/invalid golden fixtures.
- Breaking changes require a new major version, migration notes, consumer matrix, dual-read/dual-write plan where necessary, and rollback instructions.
- No runtime repo may copy a schema and silently diverge; consumers pin a version or immutable revision.
- This proposal remains non-canonical until issue #32 records Architecture Owner approval and the approved owner.

## Validation

Run:

```bash
python -m pip install jsonschema==4.23.0
python scripts/validate_platform_contracts.py
```

The validator checks every Draft 2020-12 schema, every positive fixture and every negative fixture in the manifest. It does not prove runtime consumer conformance. Each consumer must add contract fixtures and integration tests before claiming compatibility.
