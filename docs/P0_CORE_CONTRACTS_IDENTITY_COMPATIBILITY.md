# CAT-ENG-001 — Core Contracts & Identity Compatibility

**Status:** implementation candidate; not approved for runtime production adoption  
**Scope:** contract/identity compatibility evidence across UGAI, IM19 and Notebook Studio  
**Safety:** no production migration, deployment, secret change, or merge is performed by this change.

## Architecture authority

The Architecture Owner recorded the canonical-home decision in UGAI issue #32: the single transitional contract source is `StrategyG/Universal-Generative-AI/contracts/v1/`; no separate eighth repository is to be created. UGAI PR #34 carries the current schema proposal and ADR-0003. The package remains a candidate until its review, exact-SHA CI, consumer conformance and release/version pin are accepted.

Normative ownership:
- UGAI owns task lifecycle, reasoning decisions and orchestration.
- IM19 is the sole MCP gateway.
- Notebook Studio authenticates the user and presents a projection of UGAI task state; it is not a second task authority.
- A worker may execute only a lease-bound task and does not own user identity or policy.

## Identity compatibility rule

The authenticated external principal is identified by the exact pair `(issuer, subject)`, where both values come from a signature-, audience- and issuer-verified OIDC token. `subject` is opaque and is not globally unique on its own.

Tenant and project context must be resolved and authorized by trusted server-side policy. Supabase Auth `auth.users.id` is a separate identifier: no UUID cast, email-based linking, or automatic role translation is permitted. Any mapping to a Supabase user must be explicit, audited, revocable and separately provisioned.

This change makes UGAI's in-memory OIDC Principal preserve the exact verified `iss` claim and rejects missing or mismatched issuer values. Local development authentication retains a null issuer and is not valid as a production identity.

## Consumer matrix — observed repository state

| Plane | Identity/task responsibility | Evidence observed | Remaining gate |
|---|---|---|---|
| UGAI | Verifies OIDC; authoritative task state | This branch adds issuer to Principal and negative tests. Main task API maps internal states to public states. | Persist issuer provenance in task/audit actor identity where required; run exact-branch CI and consumer E2E. |
| Notebook Studio | Verify user; resolve active tenant membership; task projection | Draft PR #20 adds `(tenant_id, issuer, subject)` membership and a fail-closed legacy-row policy. Draft PR #19 maps UGAI workflow states to display-only states. | Merge/reconcile identity and task PRs; include `outcome_unknown` in display mapping; prove workspace/project authorization and UGAI service-token delegation. |
| IM19 | Verify its resource-server token and enforce MCP/tool policy | Main gateway architecture documents issuer, resource audience and verified subject checks. Draft PR #39 pins an event-envelope snapshot. | Prove tenant resolver and connector authorization against the canonical full identity/task package; keep IM19 the only MCP gateway. |

The consumer PRs listed above are evidence of work in progress, not merged or deployed integration. Their local event-envelope snapshots do not establish full platform contract conformance.

## Task lifecycle compatibility

UGAI is authoritative for task state. Notebook may map canonical UGAI states into display-only labels, but must not persist a second workflow lifecycle or invent terminal states.

The canonical task contract includes explicit blocked, failed, cancelled and `outcome_unknown` semantics. In particular, an uncertain external side effect must not be blindly retried or reported as successful; it requires trusted reconciliation evidence.

Known gap: Notebook Studio's current draft state mapping must explicitly represent `outcome_unknown` before the consumer compatibility gate can pass.

## Database and migration safety

- The Notebook API membership table and Supabase Auth membership table are distinct schemas and must not be treated as interchangeable.
- Notebook PR #20's proposed issuer column is nullable for legacy rows; rows without a verified issuer must fail closed.
- No existing issuer is inferred from email, subject, role claims or UUID shape.
- No production database has been modified by this work.
- Any migration requires a staging clone, verified identity-provider mapping, fresh backup, restore test, explicit operator approval and a tested rollback. Legacy rows must remain non-authorizing until provenance is verified.

## Acceptance evidence required before closure

1. Contract PR #34 reviewed and its schema/fixtures CI green on the exact head SHA.
2. UGAI, IM19 and Notebook pin the same immutable contract source revision and validate their consumer-facing identity/task shapes.
3. Issuer-scoped membership tests prove that identical subjects from different issuers cannot share membership.
4. Tenant and project isolation tests pass; untrusted client tenant/actor fields are rejected or ignored.
5. Notebook task display mapping covers every canonical UGAI state, including `outcome_unknown`.
6. IM19 remains the only MCP gateway and validates tenant/tool policy from verified context.
7. Compatibility, integration and security checks pass on exact PR SHAs; migration and rollback plans are reviewed before any staging or production data change.

## Explicit non-claims

This document and the associated branch do not claim a released contract package, complete cross-repository runtime conformance, successful staging E2E, production readiness, migration execution or deployment.
