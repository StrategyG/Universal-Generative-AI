# Validation and Production Release Gates

**Snapshot date:** 2026-11-03.  
**Current release decision:** NO_GO (live Supabase view).  
This document distinguishes measured status from target acceptance criteria.

## 1. Verified current status

The live institutional_rag.production_release_decision_v1 view reports:
- technical: 2/9 passed;
- operational: 0/4 passed;
- decision: NO_GO.

The institutional_rag.production_readiness_v1 view reports:

| Gate | Observed | Requirement | Result |
|---|---:|---|---|
| EMBEDDING_MODEL_ATTESTED | 0 | >=1 approved artifact and real auth user identity | Blocked P0 |
| STAGING_EMBEDDING_VALIDATED | 0 | >=30 verified completed embeddings | Blocked P0 |
| REVIEWER_IDENTITY_READY | 0 | >=2 independent active real reviewers | Blocked P0 |
| APPROVED_KNOWLEDGE_AVAILABLE | 0 | >=1 formally approved/published cited excerpt | Blocked P0 |
| INDEPENDENT_EVALUATION_SET | 0 | >=50 independently authored labelled questions | Blocked P0 |
| INDEPENDENT_EVALUATION_RUN | 0 | >=50 complete scored cases with citations, relevance and groundedness | Blocked P0 |
| SOURCE_CATALOG_RECONCILED | 0 | >=1 document fully indexed; full corpus separately audited | Blocked P1 |
| AI_TRIAGE_RECORDED | 528 | >=502 distinct AI-reviewed candidates; advisory only | Passed P1 |
| HOLD_NOT_SILENTLY_INDEXED | 293/293 | All jobs align to latest review, excerpt provenance, and source SHA | Passed P0 |

Additional observations:
- source_documents currently contains 432 discovered and 2 chunked rows.
- Current evaluation inventory is 34 active cases and 38 result rows; it does not satisfy the independent 50-case release gate.
- Zero approved/published cited excerpts means approved retrieval availability is not demonstrated.
- Four operational tests remain unattested or not passed.

This is a snapshot. Query live views before every release decision.

## 2. Release policy

A release is GO only when:
1. Every P0 technical gate passes.
2. Every P1 gate required by target release scope passes or has a documented approved exception.
3. All four operational evidence records are present, independently attested, unexpired, and tied to candidate release.
4. Security, privacy, recovery, and cost controls pass.
5. Release manager records an auditable decision.

Missing, expired, unverifiable, or contradictory evidence results in NO_GO. Model-generated reports are not operational attestations.

## 3. Application CI gates (target)

### Pull request
- clean dependency installation;
- formatting and lint;
- static type checking;
- unit tests;
- OpenAPI/JSON Schema validation;
- secret scanning;
- dependency vulnerability scan;
- container build;
- migration lint (destructive SQL requires reviewed migration);
- contract tests against mocked Supabase and model providers.

### Main/release candidate
- integration tests against isolated Supabase branch/project;
- RLS and grant negative tests using anon/authenticated/service roles;
- Edge Function authentication and body-limit tests;
- workflow replay/idempotency tests;
- retrieval benchmark and citation integrity suite;
- load and soak tests;
- backup restore and rollback rehearsal;
- signed release metadata and operator sign-off.

## 4. Functional acceptance matrix

| Test ID | Scenario | Expected result |
|---|---|---|
| F-001 | Valid question with approved evidence | Answer includes only resolved citations |
| F-002 | No eligible evidence | Explicit no-evidence; no invented citation |
| F-003 | Only private staging evidence exists | No normal user citation; provisional label only in authorized research mode |
| F-004 | Source hash changes | Citation invalidated pending re-index/review |
| F-005 | Two sources contradict | Both retained and conflict explained |
| F-006 | Short exact entity query | Exact phrase/entity retrieval tested |
| F-007 | Indonesian/English query pair | Both language paths evaluated |
| F-008 | Negation or exception | Retrieval does not invert meaning |
| F-009 | Large multi-hop task | Bounded plan and step count |
| F-010 | Planner proposes unknown tool | Rejected before execution |
| F-011 | Tool timeout | Bounded retry or graceful failure |
| F-012 | User cancels | No new steps; cancellable operations signalled |
| F-013 | Duplicate idempotency key | No duplicate side effect |
| F-014 | Provider outage | Compatible fallback or explicit unavailable |
| F-015 | Provider fallback violates privacy | Fallback denied |
| F-016 | Prompt injection in PDF | Retrieved text treated as data; no tool escalation |
| F-017 | Oversized upload/archive | Rejected before unbounded resource use |
| F-018 | Cross-tenant retrieval | Zero unauthorized records |
| F-019 | Expired approval | Citation no longer eligible |
| F-020 | Budget exhausted | Workflow stops with stable error code |

## 5. Security acceptance

- Zero unresolved critical/high findings at release.
- Authentication and authorization tested independently; CORS is not access control.
- Service-role and provider keys never appear in browser, logs, notebook, prompts, or repository.
- Private schemas/RPCs inaccessible to anon/authenticated roles unless explicit reviewed grants exist.
- Edge Function rate limit, concurrency and request byte cap verified.
- Prompt-injection, SSRF, upload/archive traversal, data-exfiltration, and cross-tenant tests pass.
- RLS advisor findings reviewed per object. RLS enabled/no-policy is not automatically remediated by broad policies.

## 6. Retrieval thresholds (proposed starting targets)

Targets require independent labels and calibration. Initial candidate thresholds:
- Recall@10 >= 0.90 on release benchmark;
- citation precision >= 0.98;
- citation locator accuracy = 1.00 for page-cited PDF evidence;
- unsupported factual claim rate <= 0.01;
- no staging evidence in standard production responses;
- abstention on no-evidence cases >= 0.95 precision.

These are proposed targets, not measured results. Report per-domain and per-language metrics, confidence intervals, and failure examples.

## 7. Operational evidence (four records)

The live release rule requires four unexpired operator-attested operational test results. Before recording the four items, inspect current gate definitions and map each record to its exact gate and external test run. Do not invent gate names or insert synthetic attestations.

Each record should include release SHA, environment, test suite/version, result, measured time, expiry, external run reference, attestor auth user, evidence URI/hash, and remediation link for failures.

## 8. Release decision report

Every candidate release produces:
- commit and container image digest;
- migration versions;
- Edge Function versions;
- test run identifiers;
- readiness gate results;
- security and performance advisor snapshots;
- retrieval quality report;
- operational test attestations;
- known limitations;
- rollback target and operator.

The live release decision view remains authoritative. This project is currently NO_GO.
