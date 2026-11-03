# Engineering Decomposition and Acceptance Traceability Matrix

**Document ID:** UGAI-EDATM-001  
**Version:** 1.0.0-draft  
**Status:** Engineering decomposition baseline; implementation certification pending  
**Assessment date:** 2026-11-03  
**Canonical specification:** [MASTER_ENGINEERING_SPECIFICATION.md](MASTER_ENGINEERING_SPECIFICATION.md)  
**Release gates:** [INSTITUTIONAL_PRODUCTION_GATES.md](INSTITUTIONAL_PRODUCTION_GATES.md)  
**Primary repository:** StrategyG/Universal-Generative-AI  
**Related repository:** StrategyG/ai-notebook-studio-v (separate release boundary)

> This matrix distinguishes observed repository facts, claims recorded in pull requests, target contracts, and missing evidence. A capability is not marked production-ready because a route, interface, mock, document, branch, or isolated test exists.

---

## 1. Purpose and authority

The Master Engineering Specification defines the target platform. This matrix converts that target into work packages that can be assigned, implemented, tested, reviewed, and certified.

The authority order is:

1. The exact release candidate commit and its source tree.
2. Reproducible test, benchmark, deployment, security, and operational evidence tied to that commit.
3. Reviewed pull requests and implementation documents.
4. Architecture specifications and ADRs.
5. Issue descriptions, plans, model-generated analysis, and informal status statements.

A lower item cannot override contradictory evidence from a higher item. A pull request description is an implementation claim until its code and evidence are independently checked.

### 1.1 Evidence status vocabulary

| Status | Meaning | Release interpretation |
|---|---|---|
| PASS | Required test or control passed on the exact candidate and evidence is retained | Eligible for gate review |
| PARTIAL | Some implementation exists, but the full acceptance contract is not met | NO-GO |
| FAIL | A required test ran and failed | NO-GO |
| BLOCKED | A prerequisite, integration, permission, environment, or capability is absent | NO-GO |
| NOT RUN | No qualifying test was executed | NO-GO |
| NOT VERIFIED | A claim or artifact exists but has not been independently validated | NO-GO |
| NOT APPLICABLE | The control is outside the approved scope with reviewer-approved rationale | Gate-specific |

Evidence must never be silently promoted from PARTIAL, BLOCKED, NOT RUN, or NOT VERIFIED to PASS.

---

## 2. Repository and pull-request topology

### 2.1 Repository boundary

| Boundary | Repository | Rule |
|---|---|---|
| Primary platform | StrategyG/Universal-Generative-AI | Canonical runtime, API, workflow, model, RAG and policy implementation |
| Related product | StrategyG/ai-notebook-studio-v | Separate product/release boundary; integration only through versioned contracts |
| Documentation candidate | Same primary repository | Documentation does not prove runtime capability |
| Production environment | Explicitly provisioned environment | Must be identified in release evidence; never inferred from a Git branch |

Do not copy private credentials, service-role keys, worker tokens, model weights, tenant data, or environment files between repositories.

### 2.2 Observed pull-request graph at assessment time

| PR | Head branch | Base branch | Head SHA | Observed purpose | Validation evidence | Integration decision |
|---|---|---|---|---|---|---|
| #1 | hardening/institutional-production-v1 | feature/multimodal-platform-v1 | 61d5d385435514432edcfe8cd5a2222da3e1923b | Hardening baseline, identity contract, workflow plan control and production gates | CI failed; supply-chain workflow succeeded | Draft; do not treat as main |
| #2 | upgrade/universal-model-platform-v1 | hardening/institutional-production-v1 | 46c0237736365ac1bca7d36c04c06deee1a71d0f | Multi-provider text model router, catalog, completion and streaming | CI succeeded; supply-chain workflow succeeded on this SHA | Draft; dependent on hardening base |
| #3 | feat/institutional-intelligence-hybrid | main | 50e75dcad541ac6fbcc3e2695d6361ca2933035a | Institutional RAG gateway and fail-closed evidence retrieval | Targeted runtime and contract validation workflows succeeded | Draft; base differs from hardening; reconcile before integration |
| #5 | docs/master-engineering-spec-v1 | hardening/institutional-production-v1 | e567b8a88e58dde42a706ca491f18bd271764e82 | Master engineering specification and production-gate documentation | PR merge-candidate CI failed at Ruff; supply-chain workflow succeeded | Draft; documentation-only candidate |

Pull-request URLs:

- #1: https://github.com/StrategyG/Universal-Generative-AI/pull/1
- #2: https://github.com/StrategyG/Universal-Generative-AI/pull/2
- #3: https://github.com/StrategyG/Universal-Generative-AI/pull/3
- #5: https://github.com/StrategyG/Universal-Generative-AI/pull/5

### 2.3 Integration constraints

1. PR #1 does not target main. Its base is feature/multimodal-platform-v1.
2. PR #2 is based on the hardening branch and therefore requires that baseline to remain compatible.
3. PR #5 is also based on the hardening branch. It is a specification layer, not a runtime implementation layer.
4. PR #3 targets main rather than the hardening branch. Its 88-commit head must not be assumed to be a clean additive patch on top of the hardening line.
5. Before a single release candidate can include PR #2 and PR #3, the owner must select a canonical integration base, reconcile PR #3's divergence, review migrations and overlapping contracts, and rerun the complete suite on the resulting exact SHA.
6. A green test on a branch that is not part of the release candidate is not evidence that the final composed candidate passes.
7. Do not merge, retarget, rebase, deploy, or change a production branch merely to make the graph look linear. Those are explicit repository-owner decisions.

**Current topology decision: BLOCKED for a unified release candidate.** The branches have different bases and no inspected evidence yet proves that all candidate changes have been composed and validated together.

---

## 3. Verified validation snapshot

### 3.1 Exact-SHA workflow evidence

| Candidate | Workflow | Run | Result | Scope and limitation |
|---|---|---:|---|---|
| Hardening SHA 61d5d385435514432edcfe8cd5a2222da3e1923b | CI | 41672722820 | FAIL | Ruff check failed; pytest did not run |
| Hardening SHA 61d5d385435514432edcfe8cd5a2222da3e1923b | Supply Chain Security | 41672722891 | PASS | Dependency audit workflow only; not a full supply-chain attestation |
| Model-router SHA 46c0237736365ac1bca7d36c04c06deee1a71d0f | CI | 41528276389 | PASS | Exact branch candidate; does not prove merge composition or live provider accounts |
| Model-router SHA 46c0237736365ac1bca7d36c04c06deee1a71d0f | Supply Chain Security | 41528276448 | PASS | Dependency-audit scope only |
| RAG SHA 50e75dcad541ac6fbcc3e2695d6361ca2933035a | Runtime integration validation | 41586343954 | PASS | Targeted runtime and Edge Function validation described by PR #3 |
| RAG SHA 50e75dcad541ac6fbcc3e2695d6361ca2933035a | Contract validation | 41586343957 | PASS | JSON Schema, OpenAPI and runtime-contract validation described by PR #3 |
| Documentation PR merge candidate 733a20508087173e0e097fe9f8b1f955b01496d1 | CI | 41673679774 | FAIL | Ruff failed before pytest; this is the GitHub PR merge candidate |
| Documentation PR merge candidate 733a20508087173e0e097fe9f8b1f955b01496d1 | Supply Chain Security | 41673679662 | PASS | Dependency-audit workflow only |

### 3.2 Current blocking CI finding

The failed CI log for the hardening line and the PR #5 merge candidate identifies:

- File: tests/test_mcp_server.py
- Line: 4
- Rule: Ruff F401
- Finding: app.auth.Principal is imported but unused.
- Outcome: Ruff exits with code 1.
- Consequence: pytest is skipped by the current sequential CI workflow.

This is a concrete, reproducible quality-gate failure. It should be fixed in the correct code-owning branch through a reviewed change, then all dependent PR merge candidates must be retested. Do not modify the documentation branch to hide or suppress a source-code lint finding.

The workflow definition currently installs the development, PostgreSQL and worker extras, then runs:

    ruff check app tests
    pytest -q

The test environment provisions PostgreSQL 16 and sets TEST_DATABASE_URL. A local test without equivalent PostgreSQL setup is not equivalent to this CI job.

### 3.3 What the green checks do not prove

- A dependency audit is not an SBOM, signed build provenance, container scan, secret-history audit, or model-weight integrity attestation.
- Model-router unit and contract tests do not prove a successful live request to every external provider, production quota enforcement, cost governance, or multi-region failover.
- RAG contract and runtime tests do not prove that the gateway is deployed, reachable, or allowed to publish institutional evidence.
- No check on an individual branch proves that the merged release candidate passes.
- A successful documentation build or test does not prove a running application.

---

## 4. Architecture decomposition and acceptance matrix

The state shown below is the observed engineering posture, not a statement that every feature in an open pull request has merged.

| ID | Bounded subsystem | Observed implementation | Current status | Acceptance evidence required |
|---|---|---|---|---|
| ARC-01 | API/control plane | FastAPI routes, Pydantic request/response schemas, health endpoints and generation/job interfaces exist in the hardening line | PARTIAL | OpenAPI diff, route auth matrix, malformed-input tests, request limits, stable errors and exact-SHA integration test |
| ARC-02 | Identity | OIDC/JWKS verification contract and tenant/project claims are described in the baseline | PARTIAL | Live IdP staging, key rotation, expired/revoked token tests, issuer/audience mismatch, role matrix and subject lifecycle |
| ARC-03 | Authorization | Project-scoped generation/job checks and server-owned workflow action policy exist in the baseline | PARTIAL | Per-operation authorization matrix, deny-by-default tests, privilege-escalation tests, revocation and cross-tenant adversarial tests |
| ARC-04 | Workflow planning | DAG validation, topological ordering, starter plans and optional PostgreSQL persistence are described | PARTIAL | Migration tests, cycle/duplicate/dependency property tests, durable read-back, tenant isolation and plan versioning |
| ARC-05 | Workflow execution | Workflow control documentation explicitly states execution_enabled=false and not_configured | BLOCKED | Durable scheduler, step executor, leases, retry, cancellation, restart recovery, audit and sandbox evidence |
| ARC-06 | Model provider router | PR #2 describes OpenAI-compatible, Anthropic and Gemini provider paths, catalog, normalized usage and SSE | PARTIAL | Exact-SHA review, provider contract tests, live provider smoke tests, streaming disconnect tests, timeout/retry matrix, usage reconciliation and failover tests |
| ARC-07 | Model governance | Registry and immutable model revision controls are described in the hardening and model work | PARTIAL | Independent model digest verification, license review, promotion approval, rollback and production inference evidence |
| ARC-08 | Image generation | Mock provider and optional Diffusers/SDXL adapter are described in the hardening README | PARTIAL | Pinned weights, license record, GPU/hardware matrix, deterministic smoke test, VRAM measurement, failure recovery and artifact verification |
| ARC-09 | External GPU workers | Worker-specific credentials, polling, heartbeats, claims and persisted queue behavior are described | PARTIAL | Compromise/revocation drill, lease fencing, stale worker rejection, duplicate completion test, hostile artifact test, sustained load and real GPU test |
| ARC-10 | Institutional RAG | PR #3 describes a gateway that checks a live release gate and calls a trusted retrieval path | PARTIAL / BLOCKED FOR LIVE USE | Reconciled branch, live Supabase evidence, RLS/grants review, query/corpus authorization, citation provenance, deletion and benchmark evidence |
| ARC-11 | Agent runtime | Planning and specialist role/quality contracts are present in repository PR descriptions | BLOCKED for autonomous execution | Isolated execution environment, filesystem/network policy, tool authorization, prompt-injection suite, sandbox escape tests, kill switch and immutable audit |
| ARC-12 | MCP | MCP server/control interfaces are present in the hardening line; workflow control explicitly does not imply tool execution | PARTIAL | OAuth scopes, per-tool authorization, host validation, tool poisoning tests, credential isolation, approval workflow, audit and kill switch |
| ARC-13 | A2A interoperability | The master design targets agent interoperability; no end-to-end A2A acceptance evidence was inspected | NOT VERIFIED | Versioned agent card/capability contract, identity propagation, task lifecycle, callback validation, replay protection and cross-agent authorization |
| ARC-14 | Artifact/object storage | Storage references and worker-side expectations exist; complete trusted artifact storage is a documented blocker | BLOCKED | Private bucket policy, short-lived scoped access, MIME/parser verification, content hash, malware policy, retention, deletion and tenant isolation |
| ARC-15 | Eventing/observability | Request IDs and selected structured logs are described in provider work; durable event ledger and full telemetry are not established by inspected evidence | PARTIAL | Trace propagation, append-only audit, metric labels without secrets/PII, queue-age alerts, provider cost telemetry and incident drill |
| ARC-16 | Supply chain | Dependency-audit workflow exists and passed on selected SHAs | PARTIAL | Lockfiles, SBOM, pinned actions/images, container scan, secret history audit, provenance, signed release digest and model asset provenance |
| ARC-17 | Deployment/release | Production gates and NO-GO controls are documented | BLOCKED | Protected branch, signed candidate, staging smoke, canary, rollback, backup/restore and human approval receipt tied to exact artifacts |
| ARC-18 | Learning/evaluation | Cross-model research and future learning workflow are specified in repository documentation | NOT VERIFIED for autonomous learning | Versioned dataset, lineage, reproducible training/evaluation, contamination checks, independent benchmark, human promotion and rollback |

### 4.1 Required architecture boundaries

The implementation must preserve these separations:

- Control plane: identity, policy, planning, approval, scheduling, cost limits and audit.
- Execution plane: model runtimes, workers, tools, agents and external providers.
- Data plane: PostgreSQL transactional records, vector retrieval, object storage and immutable evidence.
- Governance plane: model approval, policy versions, dataset approvals, release decisions and human attestations.

A model or agent may propose an action. It does not authorize that action. A worker may report an artifact. It does not establish artifact trust. A retriever may return a chunk. It does not establish that the chunk is approved, current, tenant-authorized, or safe to cite.

---

## 5. Canonical contract requirements

This section defines contracts to freeze before runtime execution. It does not claim that these contracts are already implemented.

### 5.1 API contract

Every externally callable operation must define:

- HTTP method and versioned route.
- Authentication scheme and machine/human principal type.
- Required role, tenant scope, project scope and resource ownership rule.
- Request schema, response schema and maximum serialized size.
- Idempotency semantics for create/execute operations.
- Timeout, rate, concurrency and token/byte limits.
- Stable error code, retryability and HTTP status mapping.
- Correlation ID and audit-event requirement.
- Data classification and redaction rules.
- Compatibility policy and deprecation window.

No endpoint may trust tenant_id, role, approval state, risk level, artifact trust, or model approval supplied only by an untrusted caller.

### 5.2 Error envelope

Target error responses should use one stable envelope:

| Field | Requirement |
|---|---|
| code | Stable machine-readable code |
| message | Safe user-facing explanation; no secrets or internal stack |
| request_id | Correlation identifier |
| retryable | Explicit Boolean |
| details | Typed safe details; omitted when not useful |
| policy_version | Version that produced a policy denial, when applicable |

The exact schema must be added to OpenAPI and tested. Do not return provider raw bodies, credentials, database strings, file paths or stack traces to callers.

### 5.3 Durable job state machine

Jobs and individual steps are separate aggregates. A job-level success cannot be inferred merely because a worker returned HTTP 200.

Target lifecycle:

    CREATED -> VALIDATED -> AWAITING_APPROVAL
    AWAITING_APPROVAL -> REJECTED | APPROVED
    APPROVED -> QUEUED
    QUEUED -> CLAIMED | CANCELLED | EXPIRED
    CLAIMED -> RUNNING | QUEUED | FAILED
    RUNNING -> SUCCEEDED | FAILED | CANCELLED | COMPENSATION_REQUIRED
    COMPENSATION_REQUIRED -> COMPENSATED | COMPENSATION_FAILED

Rules:

1. Every transition is validated by the server against the current state and policy version.
2. Every successful transition increments a monotonic version or sequence.
3. Updates use compare-and-set or an equivalent transaction to prevent concurrent writers from overwriting newer states.
4. Terminal states cannot be reopened in place. A retry after terminal failure creates a new attempt linked to the original job.
5. A cancellation request is not proof that an external process has physically stopped. The system must record requested, acknowledged, and confirmed termination separately where applicable.
6. A worker lease contains an expiry and fencing epoch. Results with an expired or older epoch are rejected.
7. A job is successful only after output artifacts are verified, required policy checks pass, and all mandatory steps are terminal-success.
8. Partial success and compensation outcomes must be explicit; they must not be reported as full success.
9. Retry policy is bounded by attempts, age, backoff, and error classification. Permanent auth, policy, validation and model-not-found errors are not retried as transient failures.
10. State transitions, approvals, claims, revocations, artifacts and failures produce auditable events.

### 5.4 Idempotency contract

For a mutating API:

- Require a caller-provided idempotency key or a server-generated operation identifier where replay protection is needed.
- Scope the key by tenant, principal and operation class.
- Persist the canonical request digest and original result.
- Same key plus same digest returns the original operation/result.
- Same key plus different digest returns a conflict and never silently mutates the original operation.
- Retention must exceed the maximum client retry/replay window.
- Tests must cover concurrent duplicate submission, process restart, timeout after commit, and delayed client retry.

### 5.5 Event envelope and transactional delivery

The canonical event envelope must include:

| Field | Requirement |
|---|---|
| event_id | Globally unique, immutable identifier |
| event_type | Namespaced event name |
| schema_version | Explicit version |
| occurred_at | UTC timestamp |
| tenant_id | Derived from authenticated server context |
| aggregate_type / aggregate_id | Resource whose state changed |
| aggregate_version | Monotonic version for ordering and stale-event detection |
| actor | Human, service or worker principal identifier |
| correlation_id | End-to-end request/trace correlation |
| causation_id | Parent command/event where applicable |
| policy_version | Authorization/policy version relevant to the change |
| payload | Typed, minimized, classified content |
| integrity | Digest or equivalent integrity reference for retained evidence |

Use a transactional outbox for database state plus event publication. Consumers must use an inbox/deduplication strategy. Delivery is at-least-once unless a stronger guarantee is explicitly implemented and tested. Exactly-once execution must not be claimed merely because duplicate events are filtered.

---

## 6. Security and trust acceptance requirements

| ID | Control | Mandatory test/evidence | Failure behavior |
|---|---|---|---|
| SEC-01 | Authentication | Invalid signature, wrong issuer/audience, expired token, missing claims, revoked key and JWKS outage | Deny by default |
| SEC-02 | Tenant isolation | Cross-tenant read/write, guessed identifiers, forged tenant claims, cache-key collision and background-job access | No cross-tenant data exposure |
| SEC-03 | Project authorization | User outside project, removed member, role downgrade and tenant-admin boundary | Deny immediately after policy freshness/revocation contract |
| SEC-04 | Service identity | Distinct short-lived credentials per worker/service; rotation and revocation drill | Revoke without broad user-key impact |
| SEC-05 | Secrets | Secret scanning, history scan, log redaction, env/config inspection and rotation proof | Block release on leaked active secret |
| SEC-06 | Database | Grants plus RLS, owner/bypass behavior, SECURITY DEFINER review, migration privilege test | Least privilege; fail closed |
| SEC-07 | Tool execution | Tool allowlist, per-tool scope, argument validation, destination/host allowlist and approval | Reject unknown or unauthorized tool |
| SEC-08 | Prompt injection | Direct and indirect injection across retrieved docs, files, tool output and model response | Treat content as untrusted data; no policy override |
| SEC-09 | Sandbox | Filesystem, process, network, syscall, resource and tenant boundary tests | Kill/contain and preserve audit |
| SEC-10 | Artifacts | Hash mismatch, MIME spoofing, parser bombs, path traversal, oversized data, malicious archives | Quarantine/reject; never publish |
| SEC-11 | Model supply chain | Immutable revision, source/license record, weight digest, loader provenance and signed/verified artifact | Deny unapproved model |
| SEC-12 | Audit | Privileged operation, approval, data export, policy change, release and credential actions | Append-only attributable record |
| SEC-13 | Abuse/cost | Rate burst, token exhaustion, GPU exhaustion, repeated retries and quota race | Enforce bounded admission before expensive work |
| SEC-14 | Network egress | SSRF, redirect, metadata service, private IP, DNS rebinding and unapproved host tests | Block unapproved egress |
| SEC-15 | Recovery | Restore drill, credential compromise, worker compromise and queue backlog scenarios | Contained recovery with reconciled state |

Human approval must be bound to an immutable operation digest containing the action, target, arguments digest, resource scope, policy version, requester, expiry and approver. Approval of a plan does not authorize later mutation of that plan without renewed approval.

---

## 7. RAG evidence and retrieval acceptance

### 7.1 Retrieval pipeline

The target flow is:

    Source registration
      -> authorization and corpus classification
      -> ingestion and parser validation
      -> canonical document and version identity
      -> chunking with stable locators
      -> embeddings with model/version lineage
      -> tenant/corpus-scoped index
      -> authorized retrieval
      -> reranking
      -> evidence verification
      -> answer/citation assembly
      -> audit and feedback

Every stage must retain document identity, version, source hash, parser version, chunking version, embedding model revision, index build ID and authorization scope.

### 7.2 Trust labels

At minimum, distinguish:

- received: content accepted but not validated;
- parsed: parser completed under an approved parser version;
- reviewed: content or source reviewed by an authorized reviewer;
- approved: eligible for the specific institutional corpus and use;
- revoked: no longer eligible;
- superseded: replaced by a newer approved version;
- quarantined: suspected malicious, malformed, or policy-violating content.

Retrieval rank is not a trust level. High semantic similarity does not promote a source. A caller cannot set trust labels.

### 7.3 RAG evaluation protocol

The benchmark must be frozen and versioned before final threshold tuning. It must include:

- Corpus and tenant scope, source versions and immutable hashes.
- Query set, intended task, expected evidence and answerability label.
- Positive and hard-negative examples.
- Temporal and superseded-document cases.
- Cross-tenant and unauthorized-document probes.
- Prompt-injection and poisoned-source examples.
- Exact-page or exact-span citation ground truth where the task requires it.

Report at least Recall@k, Precision@k, MRR, nDCG@k, citation precision, citation coverage, evidence entailment/support rate, abstention quality, latency and cost per query. Report the denominator, dataset split, confidence interval or repeated-run variance, and the exact model/index/configuration.

Thresholds must be calibrated with human-reviewed ground truth and declared before the release run. Do not invent generic targets such as a universal 95% accuracy threshold. A mandatory invariant is zero unauthorized cross-tenant disclosure in the adversarial suite.

### 7.4 RAG deletion and lifecycle

Acceptance tests must verify that revocation, deletion, source supersession and tenant membership changes propagate to:

- canonical records;
- chunks and embedding records;
- search indexes or namespaces;
- caches;
- generated answer caches;
- citations and evidence manifests;
- exported artifacts and backups according to the approved retention/deletion policy.

The system must be able to explain which document version and chunk supported a citation. A citation must fail closed if its source is revoked, superseded under a non-citable policy, hash-invalid, out of scope or missing its locator.

### 7.5 Institutional RAG release control

The PR #3 description reports a live release gate in NO-GO state with 2/9 technical gates and 0/4 operational gates satisfied as of its recorded assessment. Its gateway is described as refusing retrieval until the live release gate is GO. Treat those figures as PR-recorded evidence until the underlying Supabase project state and evidence artifacts are independently re-read.

No private staging or unreviewed evidence may be promoted into institutional citations. No gateway deploy or production SQL application is implied by a successful CI workflow.

---

## 8. Model runtime and provider acceptance

Each provider adapter must satisfy a provider-neutral contract for:

- capability declaration, context/output limits and supported modalities;
- authentication header and secret source;
- connect/read/overall timeout;
- retryable versus permanent error classification;
- rate-limit and overload handling;
- normalized usage, cost inputs and provider request identifiers;
- streaming chunk schema, completion marker and disconnect behavior;
- model ID plus immutable revision where the provider exposes it;
- data retention/training policy metadata where available;
- explicit fallback eligibility.

Fallback rules:

1. Retry only errors classified as transient.
2. Do not retry permanent invalid-credential, policy-denied, model-not-found or malformed-request errors.
3. A streamed response may switch provider only before any user-visible token is emitted, unless a formally reviewed resume protocol exists.
4. Never concatenate partial outputs from different model providers and represent them as a single coherent generation.
5. A provider response is untrusted input until schema and policy validation complete.

Acceptance evidence must include mocked contract tests, real provider smoke tests, timeout and rate-limit tests, stream cancellation, partial-output behavior, usage normalization and cost reconciliation. Mocked tests alone cannot pass live-provider acceptance.

---

## 9. Agent, MCP and A2A acceptance

### 9.1 Agent lifecycle

Separate these actions:

1. plan;
2. policy evaluation;
3. approval;
4. executor allocation;
5. execution;
6. artifact verification;
7. independent evaluation;
8. publication or external action;
9. reconciliation and audit.

The LLM planner cannot grant its own permission, modify the server-side risk registry, approve its own output, or mark an external action complete without independent confirmation.

### 9.2 MCP server and tools

Each tool registration must define:

- immutable tool identifier and schema version;
- owner and service identity;
- read/write/destructive side-effect classification;
- minimum OAuth scope and resource scope;
- input validation and output size limits;
- network destination policy;
- timeout, retry and concurrency budget;
- approval requirement;
- audit event and correlation behavior;
- revocation and kill-switch behavior.

Test malicious tool descriptions, tool-output prompt injection, schema-confusion, confused-deputy access, unauthorized scopes, token leakage, malicious redirects, host allowlist bypass and repeated external side effects.

MCP connectivity does not prove live Git synchronization, repository write ability, code execution, agent autonomy, or authorization. These must be independently verified per tool and operation.

### 9.3 Autonomous coding

Before enabling repository writes, require:

- dedicated GitHub App or narrowly scoped token;
- repository and branch allowlist;
- operation allowlist for read, branch, commit, PR, review and merge;
- protected-branch policy and required status checks;
- isolated worktree/container with no ambient credentials;
- secret-safe diff scanning;
- deterministic test execution on the proposed commit;
- human approval for merge, deploy, secret/config change and destructive operations;
- rollback or revert procedure;
- audit binding actor, repo, branch, SHA, diff digest, tests and approval.

The agent may open a PR. It must not bypass branch protection or self-approve a privileged change.

---

## 10. Data model and isolation acceptance

Minimum logical entities:

| Entity | Required ownership/scope | Key invariants |
|---|---|---|
| Tenant | tenant_id | Immutable identity; lifecycle and suspension state |
| Principal | issuer + subject | Stable external identity; role is not user-supplied |
| Project | tenant_id + project_id | Unique within tenant; membership authorization |
| Job | tenant_id + job_id | Versioned state; owner and idempotency metadata |
| Job step/attempt | tenant_id + job_id + step_id + attempt | Fenced lease and attempt identity |
| Approval | tenant_id + operation_digest | Immutable scope, expiry and approver |
| Artifact | tenant_id + artifact_id | Immutable digest, classification and lifecycle |
| Model revision | model_id + revision/digest | Immutable provenance and approval state |
| Dataset/corpus | tenant_id + corpus_id | Owner, classification, source lineage and publication state |
| Document/chunk | tenant_id + document_version + chunk_id | Stable locator, hash and trust state |
| Audit event | tenant_id + event_id | Append-only, attributable and tamper-evident |

The actual database schema may differ if an ADR justifies it. The invariants may not be dropped.

Database acceptance requires migrations from an empty database, upgrade from the prior supported version, transaction rollback, constraint behavior, concurrent update tests, RLS/grant tests, backup/restore and tenant adversarial testing. A PostgreSQL-backed unit test suite does not substitute for production data-isolation and recovery drills.

---

## 11. Observability, SLO and cost controls

### 11.1 Required telemetry

Every request/job/step must correlate through request_id, trace_id, tenant-safe correlation, job_id, step_id and provider request ID where applicable. Avoid using raw tenant IDs or user identifiers as unrestricted metric labels.

Required measures include:

- eligible request rate, success and error rate;
- p50/p95/p99 latency split by control-plane, provider and RAG path;
- queue depth, oldest queued age, lease expiry and retry counts;
- active workers, GPU utilization/VRAM and worker health;
- provider/model token usage and cost;
- RAG retrieval latency, evidence rejection and abstention;
- approval wait time and policy-denial rate;
- artifact storage bytes, retention age and verification failures;
- incident and rollback events.

### 11.2 Budget contract

Before production, freeze environment- and tenant-tier limits for request bytes, file bytes, prompt/context/output tokens, concurrent API requests, active jobs, per-worker GPU/VRAM/RAM, job wall time, lease duration, retries, storage, artifact retention, model spend and GPU spend.

Every expensive operation must pass admission control before execution. Quota and budget updates must be concurrency-safe. Define whether reservations are estimated, committed or reconciled, and prove that retries do not double-charge or bypass limits.

Existing specification SLOs are planning proposals, not measured performance. Do not call them achieved until a representative load test records workload, hardware, concurrency, warm/cold behavior, sample size, error rate and exact candidate SHA.

---

## 12. Quality engineering and release evidence pack

### 12.1 Required layers

| Test layer | Minimum evidence |
|---|---|
| Static analysis | Lint/type/security tooling versions and clean result |
| Unit | Policy, schema, state transitions, retry and normalization |
| Integration | API plus real PostgreSQL and migration path |
| Contract | OpenAPI/JSON Schema compatibility and provider/MCP contracts |
| Security | Tenant isolation, authz bypass, SSRF, injection, secret and sandbox tests |
| RAG quality | Frozen benchmark with metrics, denominators and confidence intervals |
| Model runtime | Live provider or pinned local model smoke, resource profile and output checks |
| Worker | Lease fencing, revocation, duplicate completion and restart recovery |
| Resilience | Load, soak, fault injection, backup/restore and multi-instance tests |
| Staging | Production-like identity, database, vector index, object storage and provider config |
| Release | Protected branch, signed artifacts, approver and exact digest, canary and rollback |

### 12.2 Evidence manifest

Each evidence record must contain:

- requirement_id and gate_id;
- repository, branch and full candidate SHA;
- exact command/workflow/test suite and tool version;
- runner image and environment identifier;
- non-secret configuration digest;
- dataset/model/index/migration/artifact digest where relevant;
- start/end timestamps and run identifier;
- pass/fail/blocked/not-run state;
- metrics, denominator, failed case IDs and limitations;
- immutable report URI and report checksum;
- operator or automation identity;
- reviewer identity, decision and review timestamp.

A release evidence manifest itself must be versioned and immutable after approval. Re-running a test creates a new record; it must not overwrite the historical result.

### 12.3 Exact-SHA release rule

A release candidate is a tuple, not just a Git commit:

    Candidate = {
      application_commit,
      configuration_digest,
      migration_set_digest,
      model_revision_and_weight_digest,
      dataset_and_index_version,
      container_image_digest,
      SBOM_and_provenance,
      evidence_manifest_digest
    }

Approval applies only to this tuple. Any change to a component invalidates the affected approval and requires the defined retest scope. The final release decision must identify all component digests.

---

## 13. Work packages and exit criteria

| Work package | Priority | Deliverables | Exit criteria |
|---|---|---|---|
| WP-00 Baseline integrity | P0 | Canonical integration branch, branch topology map, exact-SHA evidence ledger, CI repair | CI green on selected baseline; branch composition reviewed; no ambiguous release head |
| WP-01 Identity and tenancy | P1 | Human/service identity, RBAC matrix, tenant/project enforcement, revocation | Staging adversarial isolation suite passes; revoked identities lose access |
| WP-02 API/event/job contracts | P1 | OpenAPI, error schema, state machine, idempotency, outbox/inbox | Contract tests and database concurrency/restart tests pass |
| WP-03 Model runtime | P2 | Provider-neutral adapters, immutable model registry and live runtime | Real provider/model smoke and governance proof pass on candidate |
| WP-04 Trusted artifacts | P2 | Private object store, signed/scoped access, parser validation and lifecycle | Hash/MIME/tenant/deletion tests pass |
| WP-05 Institutional RAG | P3 | Ingestion, authorization, index lifecycle, retrieval, evidence and benchmark | Live release gate GO; RLS/grants and frozen RAG suite pass |
| WP-06 Agent/MCP runtime | P4 | Sandboxed executor, tool registry, OAuth authorization, approvals and kill switch | Adversarial tool/sandbox suite passes; all external effects audited |
| WP-07 Learning/evaluation | P5 | Dataset lineage, repeatable training/evaluation, independent promotion | Reproducible candidate with independent evaluation and rollback |
| WP-08 Production certification | P6 | SLO, capacity/cost budgets, supply-chain pack, backup/restore, canary/rollback | Every mandatory G0-G12 gate PASS on exact release tuple |

### 13.1 Immediate P0 actions

1. Fix the unused import finding in the code-owning hardening line through a reviewed source change; do not suppress the linter.
2. Rerun Ruff and pytest on the exact hardening candidate and its PR merge candidate.
3. Re-run dependent PR merge candidates because a changed base can change the composed result.
4. Select and record one canonical integration base. Document the reason for choosing it.
5. Reconcile PR #3 from main against the selected base; inspect all 88 commits, file overlap and migration ordering before deciding whether to rebase, cherry-pick or split the work.
6. Produce a single candidate branch containing only reviewed, intended changes; freeze its SHA.
7. Generate the first evidence manifest and mark every absent proof BLOCKED or NOT RUN.

No code merge, deployment, database mutation, secret provisioning or production setting change is authorized by this document.

---

## 14. Release decision

**Current overall decision: NO-GO.**

Reasons established by inspected repository evidence:

- The hardening line's CI fails before pytest due to Ruff F401.
- The documentation PR merge candidate also fails at the same lint finding.
- The code work is split across multiple draft PRs with different base branches.
- PR #3's RAG validation is targeted branch evidence, not proof of a unified release candidate or deployed gateway.
- The PR #3 description reports the institutional Supabase release gate as NO-GO; that status must be independently refreshed before any live activation.
- Durable workflow execution, trusted artifact storage, full agent sandboxing, complete tenant IAM/RBAC, and production operations remain documented gaps in the baseline.

A later candidate may change this decision only after fresh evidence is attached to its exact release tuple. Documentation completeness, subjective scores, a model's self-review, or isolated green workflows cannot override this rule.

---

## 15. Change control

- Any change to tenant boundaries, authorization, state transitions, model promotion, artifact trust, RAG benchmark thresholds, MCP tool permissions, event schema or release gates requires an ADR or equivalent reviewed rationale.
- Benchmark thresholds are frozen before the final candidate run. Post-result threshold changes require a rationale and a rerun.
- Exceptions require owner, risk description, compensating controls, expiry, approver and evidence.
- Evidence is immutable. Corrections append a superseding record; they do not erase failed history.
- Review this matrix whenever candidate branch topology, primary contracts, live provider integration, data classification or production scope changes.
