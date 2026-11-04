# UGAI V3.0 — P0 Evidence Ledger

**Snapshot date:** 2026-11-04  
**Audit mode:** Read-only repository and Supabase inspection  
**Decision:** NO-GO for production release, database cutover, and unrestricted autonomous execution  
**Scope:** UGAI, IM19, AI Notebook Studio, and Supabase project `uktauwysjkseqrnbjwzy`

This ledger distinguishes verified observations from design claims and untested operations. It is a point-in-time snapshot, not a certification.

## 1. Evidence status vocabulary

- **VERIFIED** — directly inspected or executed in the named environment at the snapshot date.
- **PARTIALLY_VERIFIED** — some code or test evidence exists, but runtime or end-to-end acceptance is incomplete.
- **REPORTED_NOT_RECHECKED** — described in an existing PR/document but not independently reproduced during this audit.
- **NOT_TESTED** — no execution evidence was available.
- **BLOCKED** — a release gate explicitly prevents promotion.
- **NOT_APPLICABLE** — not relevant to the current release scope.

## 2. Repository and CI evidence

| Area | Evidence | Status | Limitation |
|---|---|---|---|
| UGAI default branch | `main` resolves to `dfc2456a7e5d4c27db448ea1b2ff5b5c9d0adede`; inspected tree contains README only | VERIFIED | Main is not the implementation baseline |
| UGAI candidate baseline | `upgrade/universal-model-platform-v1` resolves to `d650d0366674d9746c68a29464dd5fdacf21c1de` | VERIFIED | Candidate branch is not the default branch |
| UGAI reasoning | PR #19 head `d0e0bb1cfbcccf42be7e631c4b92dab455e45ec9`; workflow jobs for adapter/decision and Postgres workflow passed in inspected run | VERIFIED | Does not prove live provider inference or full three-plane E2E |
| UGAI durable workflow | PR #12 is open and draft; workflow code includes state machine, leases, fencing, retries, idempotency and worker contracts | PARTIALLY_VERIFIED | Requires runtime integration, failure-injection and external side-effect reconciliation tests |
| IM19 | `main` contains MCP gateway, security/policy, connector and test modules; one inspected Postgres transaction workflow passed | PARTIALLY_VERIFIED | Does not prove deployed configuration or UGAI-to-IM19 E2E |
| AI Notebook Studio | `main` contains application/API structure; inspected CI run failed at required bundled UI asset verification | VERIFIED | This is a release-blocking CI result for that inspected run; re-run after fixing assets |
| PR state | UGAI PR #12 and #19 are open Draft PRs | VERIFIED | Draft work is not an accepted release |
| VM / Drive DR | No provisioned VM, completed backup, or restore drill was evidenced in this audit | NOT_TESTED | Requires infrastructure access and an approved non-production drill |

### Branch governance decision

Do not treat the feature branch, a passing unit test, or an open Draft PR as the production baseline. Establish a release manifest containing the exact UGAI, IM19, Studio, database migration, and container/image digests. The manifest must be immutable for each release candidate.

## 3. Supabase RAG evidence

Project: `uktauwysjkseqrnbjwzy`  
Project status observed: `ACTIVE_HEALTHY`  
Database version observed: PostgreSQL 17.11.

### Inventory (exact SQL counts at snapshot)

| Object | Count |
|---|---:|
| Base tables in `rag` and `institutional_rag` | 25 |
| `rag.documents` | 383 |
| `rag.chunks` | 26,186 |
| `rag.chunks` with non-null embedding | 682 |
| `institutional_rag.source_documents` | 434 |
| `institutional_rag.document_chunks` | 1,109 |
| `institutional_rag.document_chunks` with non-null embedding | 0 |
| `institutional_rag.embedding_jobs` | 293 |
| Embedding jobs queued | 95 |
| Embedding jobs blocked | 198 |
| Embedding model approvals | 0 |
| Knowledge candidates | 669 |
| Knowledge candidates pending | 486 |
| Knowledge candidates needing more evidence | 183 |
| Published knowledge candidates | 0 |
| Active verified independent reviewers | 0 |
| Evaluation cases | 34 |
| Independently human-curated evaluation cases meeting the inspected filter | 0 |
| Evaluation results | 38 |
| Valid published evidence rows | 0 |
| Production release evidence rows | 0 |

Counts are raw database counts under the inspected table definitions. They do not imply quality, correctness, tenant isolation, or production readiness.

### Release gate

The Supabase release-readiness views returned:
- Technical gates passed: **2/9**.
- Operational gates passed: **0/4**.
- Release decision: **NO-GO**.

The immediate blockers include the absence of an approved/attested embedding model artifact, zero institutional document chunks with embeddings, zero approved model records, zero verified independent reviewers, zero published knowledge/evidence, and no qualifying independent human-curated evaluation cases.

The exact gate implementation is defined by the database views; re-query the views before every release decision. This ledger is not a substitute for that live query.

### Security interpretation

- Security Advisor reported 21 Institutional RAG tables with RLS enabled and no policy.
- Inspected schema/table privileges did not grant `anon` or `authenticated` direct schema usage/SELECT for the private RAG schemas.
- This combination is not, by itself, proof of public exposure. Keep the schemas private; verify owners, BYPASSRLS, grants, SECURITY DEFINER functions, API exposure, and actual runtime roles before changing policy.
- `service_role` is privileged and bypasses RLS. Treat its secret as a high-impact credential.
- The `institutional-rag-search` Edge Function had `verify_jwt=false`; the inspected handler performs a separate `x-rag-api-key` check and rejects missing/mismatched keys. This does not prove per-user or per-tenant authorization. Verify key rotation, rate limiting, tenant binding, logging redaction, and secret configuration before release.

No database schema, row, grant, RLS policy, migration, function, or secret was changed during this audit.

## 4. Cross-plane acceptance evidence

| Control | Current evidence | Status |
|---|---|---|
| Shared identity across UGAI, IM19, Studio | Contracts and code fragments exist; no complete live identity trace | NOT_TESTED |
| Tenant-scoped authorization end-to-end | Partial controls in code; no cross-tenant negative E2E evidence | NOT_TESTED |
| Approval bound to exact action payload/digest | Workflow/decision contracts exist | PARTIALLY_VERIFIED |
| Tool invocation through IM19 | Adapter and gateway code exist | PARTIALLY_VERIFIED |
| Studio job submission and result verification | API and integration artifacts exist | NOT_TESTED |
| One trace/correlation ID across all planes | No complete trace evidence | NOT_TESTED |
| Duplicate delivery and idempotent external effects | Store contracts exist; external side-effect replay not demonstrated | NOT_TESTED |
| Crash recovery and reconciliation | Unit-level mechanisms exist; operational drill absent | NOT_TESTED |
| PostgreSQL VM replication/DR | No verified VM replication session | NOT_TESTED |
| Google Drive encrypted backup/restore | No verified artifact plus restore drill | NOT_TESTED |

## 5. Mandatory evidence attached to every future claim

A status may be promoted only with:
1. Repository, branch, exact commit SHA, changed paths.
2. Exact workflow run URL/ID and successful job/step list.
3. Environment identifier (never secrets), deployed image digest and configuration version.
4. Test command, dataset version, test count, pass/fail count, and retained result artifact.
5. For database claims: exact migration ID, pre/post schema snapshot, row-count/reconciliation result, and rollback evidence.
6. For RAG claims: model artifact/version/digest, approval record, embedding coverage, independent review IDs, evaluation dataset version, and release-view output.
7. For DR claims: backup object digest, encryption/key reference, restore target, measured RPO/RTO, integrity check, and sign-off.

## 6. Explicit non-claims

This audit does not claim:
- production deployment is complete;
- all provider inference works;
- all three planes are integrated;
- the PostgreSQL VM exists or is synchronized;
- Google Drive backup or restore succeeded;
- the RAG corpus is fully published or independently evaluated;
- the platform is secure solely because RLS is enabled;
- the current score is an independently certified production-readiness score.


## 7. Exact release-gate output rechecked at 2026-11-04 05:31 UTC

The release views were queried again after creating this audit branch. They returned nine technical gates:

| Gate | Observed | Required | Result |
|---|---:|---|---|
| EMBEDDING_MODEL_ATTESTED | 0 | At least 1 approved artifact and real authenticated user identity | FAIL — P0 |
| STAGING_EMBEDDING_VALIDATED | 0 | At least 30 completed staging embeddings with verified model | FAIL — P0 |
| REVIEWER_IDENTITY_READY | 0 | At least 2 independent active real reviewers | FAIL — P0 |
| APPROVED_KNOWLEDGE_AVAILABLE | 0 | At least 1 formally approved and published cited excerpt | FAIL — P0 |
| INDEPENDENT_EVALUATION_SET | 0 | At least 50 independently authored labeled questions | FAIL — P0 |
| INDEPENDENT_EVALUATION_RUN | 0 | At least 50 complete scored cases with citations, relevance, and groundedness | FAIL — P0 |
| SOURCE_CATALOG_RECONCILED | 0 | At least 1 fully indexed document; full-corpus audit remains separate | FAIL — P1 |
| AI_TRIAGE_RECORDED | 528 | At least 502 distinct AI-reviewed candidates (advisory only) | PASS |
| HOLD_NOT_SILENTLY_INDEXED | 293/293 jobs aligned | All jobs match current AI review, excerpt provenance, and source SHA | PASS |

Release view: **NO_GO**. Technical gates: **2/9**. Operational gates: **0/4**. GO requires all technical gates and four unexpired operator-attested operational test results.

The 528 AI triage records are advisory only and do not substitute for human review or publication approval. The 293/293 alignment result is a positive provenance/hold control; it does not mean embeddings were completed or approved.

## 8. Security Advisor recheck

At 2026-11-04 05:31 UTC, Supabase Security Advisor returned 21 `rls_enabled_no_policy` findings, severity `INFO`, affecting Institutional RAG tables including source documents, document chunks, embedding jobs, reviewer registry, review votes, evaluation data, staging evidence, and release evidence.

The Advisor description identifies RLS enabled without policies. Interpret this together with the inspected private-schema usage and table grants; do not call it public exposure without evidence of an exposed path. Keep the schemas private and verify table owners, BYPASSRLS roles, function grants, API exposure, and runtime identities. Do not add permissive policies just to clear the informational findings.
