# Universal Generative AI — Master Engineering Specification

**Document ID:** UGAI-MES-001  
**Version:** 1.0.0-draft  
**Status:** Strategic baseline approved for engineering decomposition; implementation acceptance pending  
**Last reviewed:** 2026-11-03  
**Primary repository:** `StrategyG/Universal-Generative-AI`  
**Reference implementation branch:** `hardening/institutional-production-v1`  
**Default branch:** `main`  
**Related repository (separate release boundary):** `StrategyG/ai-notebook-studio-v`

> This specification defines intended architecture, controls, acceptance criteria, and evidence. It is not a statement that every capability is implemented. A requirement becomes complete only when a test, deployment record, benchmark, or independently reviewed artifact proves it on an identified commit.

---

## 1. Decision and scope

### 1.1 Approval status

**Approved as a strategic master engineering specification. Not yet approved as an implementation-ready production release.**

The specification is intended to guide repository-level implementation and staged certification. API routes, diagrams, plans, mocked provider responses, documentation, and green unit tests alone do not establish production readiness.

The current release posture remains **NO-GO** until all mandatory release gates in Section 16 have PASS evidence on the exact release candidate.

### 1.2 Repository boundary

| Role | Repository | Boundary |
|---|---|---|
| Primary product | `StrategyG/Universal-Generative-AI` | This specification, API/control plane, model/provider interfaces, workflow control, RAG and agent capabilities |
| Related product | `StrategyG/ai-notebook-studio-v` | Separate repository, branch protection, CI, release, secrets, deployment and acceptance evidence |

The related repository is not implicitly part of a UGAI release. Cross-repository integration must use versioned APIs/contracts, explicit compatibility tests, and independently traceable commits and releases. A PR, migration, branch, or CI result in one repository must never be represented as proof of a change in the other.

### 1.3 In scope

- Modular AI control plane and public API contracts.
- Provider-independent model runtime and self-hosted open-weight inference path.
- Project- and tenant-scoped institutional RAG.
- Controlled agent execution and tool registry.
- MCP interoperability and external integration boundary.
- Durable job/workflow orchestration.
- Learning, evaluation, model registry and human-controlled promotion.
- Security, governance, observability, reliability and production certification.

### 1.4 Out of scope unless separately approved

- Training a foundation model from scratch as a prerequisite for the platform.
- Unrestricted autonomous access to user repositories, cloud accounts, databases or production environments.
- Treating an LLM output, retrieval result, worker-reported hardware claim, or model card as trusted authorization evidence.
- Cross-tenant administration through implicit service-role access.
- Automatic production promotion by the learning engine or agent.

---

## 2. Engineering principles

1. **Evidence over assertion.** Every completion claim points to a commit, test run, benchmark report, security finding disposition, deployment, or operational record.
2. **Security first.** Identity, authorization, secret management, auditability, isolation and resource ceilings precede tool execution and autonomy.
3. **Least privilege.** Each user, service, agent, worker and MCP client receives only the actions and data required for its task.
4. **Fail closed.** Unknown action, missing identity, stale policy, failed authorization, missing artifact evidence, or ambiguous state blocks the side effect.
5. **Modular monolith for control plane.** Avoid microservice distribution until independent scaling, isolation or ownership justifies the operational cost.
6. **Separate execution planes.** API/control plane, model inference, untrusted code execution, and GPU workers have distinct resource and security boundaries.
7. **Provider independence.** Provider adapters are replaceable behind stable contracts; vendor APIs are optional when the self-hosted profile is declared.
8. **Reproducibility.** Pin code commit, dependencies, container image, model revision/digest, dataset version, migration set and evaluation configuration.
9. **Human authority for high-impact changes.** Model approval, permission escalation, external write, deployment and production release require an authorized human decision.
10. **Observable state.** Every asynchronous operation has a durable state, correlation identifier, owner, timestamps and terminal outcome.

---

## 3. Target architecture

### 3.1 Logical architecture

```text
Clients: Web UI | ChatGPT | Claude | CLI | Institutional Apps
                         |
              API Gateway / AuthN
                         |
       Policy Enforcement + Tenant/Project Context
                         |
              Modular UGAI Control Plane
       +-----------------+--------------------+
       |                 |                    |
  Model Registry    Workflow Planner     RAG Control
       |                 |                    |
 Provider Router     Durable Job API     Retrieval API
       |                 |                    |
       +---------- Event / Job Contracts ----+
                         |
                Execution Dispatcher
             +-----------+------------+
             |           |            |
        Model Worker  Agent Sandbox  GPU Workers
             |           |            |
             +------ Artifact Broker -+
                         |
         PostgreSQL | Vector Index | Object Storage
                         |
        Audit | Metrics | Traces | Cost/Quota Records
```

This is a target logical design. Components shown in the diagram are not automatically implemented because they appear in the diagram.

### 3.2 Deployment boundaries

| Plane | Responsibilities | Trust boundary |
|---|---|---|
| Client plane | User interaction and request submission | Untrusted input |
| API/control plane | Authentication, authorization, validation, planning, job lifecycle | Trusted only after request verification |
| Data plane | PostgreSQL, vector index, object storage | Tenant-scoped; secrets and privileged roles remain server-side |
| Inference plane | Model loading and inference | Model output is untrusted data |
| Agent plane | Tool execution and code operations | Isolated, constrained, killable |
| Worker plane | External GPU execution | Worker claims are untrusted until output verification |
| Governance plane | Audit, policy, evaluation, approvals and release evidence | Append-only or tamper-evident where required |

### 3.3 Architectural decisions

- Use FastAPI modular monolith for the initial control plane.
- Use PostgreSQL for durable control-plane state and policy metadata.
- Use vector search behind a tenant-aware retrieval interface; do not couple business authorization to vector metadata alone.
- Use object storage for artifacts only after scoped access, immutability/versioning, checksums and content validation are implemented.
- Run inference and untrusted code in separately constrained workers.
- Treat MCP as an interoperability protocol for exposing approved tools/resources, not as an authorization bypass, repository synchronization mechanism, job scheduler, or agent runtime.
- Use Git operations and CI to establish repository synchronization and code delivery evidence.

---

## 4. Repository baseline and implementation truth

### 4.1 Verified baseline used for this specification

The repository was inspected on 2026-11-03. The default branch README describes an initialization-stage project and makes no production capability claim. The `hardening/institutional-production-v1` branch contains a more developed FastAPI foundation, OIDC contract, provider interfaces, workflow planning, model registry and external GPU queue foundations.

The hardening branch documentation explicitly describes the workflow control plane as planning-only: plans do not execute tools or workflow steps. The production gates document records NO-GO and lists remaining blockers.

### 4.2 Do not conflate branch states

- `main` is the default branch and must not be described as containing all hardening-branch implementation.
- `hardening/institutional-production-v1` is the engineering baseline for this specification.
- Feature branches and open PRs are proposals until reviewed, merged and tested.
- A successful GitHub connector/API operation does not prove that a custom ChatGPT MCP connection is deployed or active.
- A read-only MCP server does not imply write-capable autonomous engineering.

### 4.3 Baseline limitations to preserve in all reports

Unless new evidence supersedes them, treat the following as incomplete: complete tenant-aware IAM/RBAC; trusted artifact storage; fully executable durable DAG orchestration; full audit service; real multimodal provider validation; end-to-end agent sandbox; complete observability and cost enforcement; supply-chain attestations; load/resilience and restore tests; production deployment, canary and rollback certification.

---

## 5. Phase roadmap and exit criteria

Security is not a late phase. P1 security controls are prerequisites for any P2–P6 feature that can expose data, consume significant resources, or cause side effects.

### P0 — Audit and baseline

**Goal:** establish exactly what exists and what is missing.

Deliverables:
- Commit/branch/SHA inventory and repository boundary.
- Architecture and dependency inventory.
- Endpoint, data model, migration and secret inventory.
- Existing tests, CI state and known failure baseline.
- Threat model and prioritized risk register.
- Architecture Decision Records (ADRs) for major choices.
- Baseline resource and cost assumptions.

Exit criteria:
- Every baseline claim is linked to a file, commit or command output.
- All findings are classified as implemented, partial, planned, absent or not verified.
- No production readiness score is assigned from documentation alone.

### P1 — Contracts and security foundation

**Goal:** establish stable interfaces and mandatory controls before enabling agents or external writes.

Deliverables:
- Versioned API and event schemas.
- Authentication and authorization policy.
- Tenant/project isolation tests.
- Secret manager integration and key rotation procedure.
- Structured audit event schema.
- Tool registry, server-owned policy registry and command allowlist.
- Request size, timeout, concurrency, token and cost limits.
- CI gates and migration test harness.
- Kill switch and operator runbook for every executor.

Exit criteria:
- Unauthenticated and unauthorized access tests fail closed.
- Cross-tenant and cross-project negative tests show zero unauthorized reads/writes.
- No agent or MCP tool can invoke an unregistered action.
- High-impact action requires a human approval record bound to exact action parameters and actor identity.

### P2 — Independent model runtime

**Goal:** provide a reproducible self-hosted inference path with vendor APIs optional.

Deliverables:
- Stable model-provider interface and adapters.
- Open-weight model runtime on declared hardware.
- Immutable model ID, revision and file digest.
- Health/readiness, cancellation, timeout and bounded retry.
- Streaming contract and token usage normalization.
- Fallback policy that does not splice partial outputs from different providers.
- Reproducible quality, latency, throughput and cost benchmark.

Exit criteria:
- A model completes the declared smoke suite with external vendor API access disabled.
- The model revision and weight digest are recorded.
- API restart, worker restart and model-load failure behavior are tested.
- Quality is compared with a named baseline on a versioned evaluation set.

### P3 — Institutional RAG

**Goal:** deliver attributable, versioned, tenant-isolated retrieval.

Deliverables:
- Ingestion, parsing, chunking, embedding and indexing pipeline.
- Document identity, version, source URI, tenant/project scope and checksum.
- Retrieval policy and server-derived tenant filters.
- Citation/provenance contract.
- Deletion and re-indexing lifecycle.
- Golden evaluation dataset and adversarial tenant-isolation suite.
- Explicit no-evidence/abstention behavior.

Exit criteria:
- Recall, precision, citation correctness and latency are reported on a frozen dataset.
- Retrieval results include source/version provenance.
- Zero cross-tenant document, chunk, embedding, cache or citation leakage in adversarial tests.
- Deleted/revoked documents are not returned after the defined consistency window.

### P4 — Controlled agent engine

**Goal:** allow bounded, observable and reversible tool use.

Deliverables:
- Tool registry with JSON schema, owner, risk class and side-effect declaration.
- Isolated workspace/container/sandbox for untrusted code.
- Explicit path, network, process, CPU, memory, GPU and wall-clock limits.
- Job lease, heartbeat, idempotency and cancellation semantics.
- Approval gates for external-write, delete, publish, deploy and permission changes.
- Immutable action/audit trail and kill switch.
- Retry, dead-letter and reconciliation behavior.

Exit criteria:
- Prompt injection cannot grant new tools or permissions.
- A malicious or runaway task cannot access host secrets, unrelated workspaces or other tenants.
- Timeout, cancellation, lease expiry, retry and crash recovery tests pass.
- The operator can identify and stop an active task by job ID.

### P5 — Learning and model promotion

**Goal:** create an auditable learning pipeline without self-approval.

Deliverables:
- Dataset provenance, consent/rights, retention and privacy filtering.
- Data quality and contamination checks.
- Reproducible training/fine-tuning configuration.
- Candidate model registry and immutable artifact digest.
- Independent evaluation and regression suite.
- Human approval, staged promotion, disable and rollback workflow.

Required lifecycle:

```text
Data Candidate
   -> Provenance / Privacy / Quality Review
   -> Training or Adaptation Run
   -> Candidate Model + Immutable Digest
   -> Independent Evaluation
   -> Human Approval
   -> Staged Rollout
   -> Production Promotion
   -> Monitor / Disable / Rollback
```

Exit criteria:
- Training and evaluation are reproducible from pinned inputs/configuration.
- The training process cannot approve or promote its own output.
- Regression, safety and quality results are reviewed independently.
- Rollback to a previously approved digest is tested.

### P6 — Production certification

**Goal:** prove safe operation under realistic traffic and failure conditions.

Deliverables:
- Production-like staging environment and infrastructure-as-code.
- Load, stress, soak and failure-injection reports.
- Backup/restore and disaster-recovery evidence.
- Security assessment and remediation record.
- SLO dashboard, alert thresholds and incident runbooks.
- Canary rollout, rollback and post-deployment verification.
- Signed release evidence pack tied to exact commit and artifacts.

Exit criteria:
- Every mandatory release gate in Section 16 is PASS.
- Human release approval references exact code SHA, image digest, migrations and model digests.
- Rollback has been exercised, not merely documented.

---

## 6. Core contracts

### 6.1 API contract rules

All external API requests must:
- Be versioned under a stable prefix such as `/api/v1`.
- Use validated request/response schemas.
- Carry or derive authenticated subject, tenant, project and correlation context.
- Enforce authorization server-side for every object lookup and mutation.
- Return stable error codes without leaking secrets or internal stack traces.
- Define idempotency behavior for operations that may be retried.
- Define maximum payload, timeout and pagination limits.

OpenAPI output is a contract artifact. Breaking changes require a version transition or explicit compatibility plan.

### 6.2 Model provider contract

A provider adapter must declare:
- Provider and model identity.
- Immutable model revision or provider-side version where available.
- Supported modalities, context window and streaming capability.
- Request/response schema and normalized finish/error reasons.
- Timeout, cancellation and retry policy.
- Token/usage accounting where exposed.
- Data residency/retention characteristics where known.
- Whether inference is local/self-hosted or vendor-hosted.

Provider errors must be classified as transient, permanent, policy, capacity or configuration failures. Do not retry invalid credentials, unsupported model IDs or policy denials.

### 6.3 Job state machine

The following is the normative target state model; existing endpoints must be checked against it before claiming conformance.

```text
accepted -> queued -> leased -> running -> succeeded
                     |          |       -> failed
                     |          |       -> cancel_requested -> cancelled
                     |          -> lease_expired -> queued (bounded retry)
                     -> cancelled
```

Rules:
- Every job has immutable `job_id`, tenant, owner, project, request hash, policy version and timestamps.
- State transitions are server-owned and validated; clients cannot write arbitrary states.
- Every lease has owner/worker ID, expiry and heartbeat policy.
- A repeated idempotency key with the same request returns the original logical job; the same key with a different request returns conflict.
- Terminal states are immutable except for an explicitly modeled administrative reconciliation event.
- A late result from an expired or revoked worker is rejected.
- Cancellation is cooperative and must report whether remote compute was actually stopped; invalidating a lease is not proof that the remote process stopped.
- Retry count, retry class, next-attempt time and terminal reason are persisted.
- All transitions emit correlated audit events.

### 6.4 Event envelope

Every event must use a versioned envelope equivalent to:

```json
{
  "event_id": "uuid",
  "event_type": "job.state_changed",
  "schema_version": "1.0",
  "occurred_at": "RFC3339 timestamp",
  "correlation_id": "uuid",
  "causation_id": "uuid-or-null",
  "tenant_id": "opaque-tenant-id",
  "actor": {"type": "user|service|worker", "id": "opaque-id"},
  "subject": {"type": "job", "id": "opaque-job-id"},
  "policy_version": "policy-revision",
  "data": {}
}
```

Do not include bearer tokens, API keys, raw secrets, or unnecessary prompt/document content in events or logs. Use transactional outbox or an equivalent proven delivery strategy when database state and event publication must remain consistent.

---

## 7. Security and threat model

### 7.1 Mandatory baseline before tools or agents

- Authentication for every non-public operation.
- Server-side authorization for tenant, project, resource and action.
- Secret manager; no secrets in repository, prompt, notebook output, log or client bundle.
- Key rotation and revocation procedure.
- Audit records for reads of sensitive information and all side effects.
- Tool allowlist with typed schemas and server-owned risk policy.
- Explicit process, file path, network and resource restrictions for sandbox execution.
- Request/job timeout and cancellation.
- Per-tenant quota, rate and concurrency policy.
- Human approval for external writes, deployment, destructive action and policy changes.
- Emergency kill switch for agent dispatch and worker claims.

### 7.2 Threat scenarios and required controls

| Threat | Required controls | Required proof |
|---|---|---|
| Prompt injection in user/document/tool output | Treat retrieved/tool content as untrusted; separate instructions from data; policy gate tools | Adversarial prompt-injection suite |
| Excessive agent authority | Least privilege, per-tool scopes, approval for side effects | Tool authorization matrix and denied-action tests |
| Tenant data leakage | Tenant-scoped queries, object authorization, cache keys, artifact access | Cross-tenant adversarial suite |
| Secret disclosure | Secret manager, redaction, no secrets in prompts/logs, rotation | Secret scanning and canary-secret tests |
| Supply-chain compromise | Pinned dependencies/images/models, SBOM, provenance, signed artifacts | Scan and provenance report |
| Data/model poisoning | Dataset source provenance, quarantine, independent evaluation | Poisoning and contamination tests |
| Unbounded consumption | Input/token caps, concurrency quotas, timeouts, budget enforcement | Load and quota exhaustion tests |
| Unsafe output handling | Schema validation, escaping, content-type validation, safe file parsers | Fuzzing and malicious payload tests |
| Vector/embedding weakness | Tenant filter, namespace isolation, metadata validation, retrieval authorization | Adversarial vector-store tests |
| Worker compromise | Short-lived worker credential, revoke, isolated runtime, output verification | Revocation and malicious-worker tests |

### 7.3 Supabase/PostgreSQL tenant isolation

RLS is one control layer, not a complete tenant-security guarantee.

Required:
- Apply least-privilege SQL grants as well as RLS policies to every exposed table.
- Never expose a Supabase secret/service-role key to browser, user, notebook output or untrusted worker.
- Service-role/bypass-RLS operations must remain server-side and perform explicit tenant authorization before every query or mutation.
- Tenant ID must be derived from verified identity, never trusted from an arbitrary request field.
- Vector similarity queries must apply a server-derived tenant/project filter before results are returned.
- Cache key must include tenant, project, authorization scope, query/model/index version and relevant policy version.
- Artifact URLs must be short-lived and scoped; object ID obscurity is not authorization.
- Audit and admin tables must have independent restricted access.

Required negative test matrix:
- Tenant A cannot read Tenant B documents.
- Tenant A cannot retrieve Tenant B chunks/embeddings.
- Tenant A cannot read Tenant B conversation memory.
- Tenant A cannot read Tenant B jobs or workflow plans.
- Tenant A cannot retrieve Tenant B artifacts through signed URL or guessed object ID.
- Tenant A cannot infer Tenant B content through cache, logs, error messages or timing side channels beyond the accepted threat model.

**Acceptance: zero unauthorized cross-tenant disclosures or mutations** in the specified adversarial test suite. Any observed leakage is a release-blocking defect, not a percentage target.

### 7.4 MCP security boundary

MCP provides a standardized interaction surface; it does not itself make a tool safe.

- Authenticate clients and validate audience, issuer, expiry and scopes.
- Bind tool authorization to the authenticated principal and tenant/project context.
- Use explicit tool registration and schemas.
- Expose only the minimum resources/tools required by the connected client.
- Start with read-only tools; introduce write tools only after approval, idempotency, audit and rollback controls pass.
- Enforce host/origin validation and HTTPS in deployed Streamable HTTP services.
- Do not treat MCP connectivity as proof of repository synchronization or autonomous execution.
- Maintain a tool inventory, owner, risk classification and versioned policy for each tool.

### 7.5 Security reference baseline

Pin the exact edition, canonical source URL and access date in each security review. For this specification's review date, use the OWASP GenAI LLM Top 10 2026 as the current LLM application guidance, alongside the applicable OWASP web application and agentic-system guidance. Do not use a year label without verifying the actual published edition. See References.

---

## 8. RAG evaluation and acceptance protocol

### 8.1 Dataset protocol

Create an immutable, versioned evaluation set such as `rag-eval-v1` containing at least 500 labeled queries for the first institutional acceptance run. This is a proposed initial sample size, not a universal statistical guarantee.

Each record must include:
- Query ID and query text.
- Tenant/project and authorization context.
- Expected relevant document IDs and source versions.
- Expected evidence spans where citation correctness is evaluated.
- Query category (factual, multi-hop, temporal, ambiguous, unanswerable, adversarial).
- Labeler identity/process and adjudication status.
- Dataset version, checksum and creation date.

Keep evaluation data separate from training/fine-tuning data. Record known overlap and contamination checks.

### 8.2 Metric definitions

| Metric | Definition |
|---|---|
| Recall@10 | For each query, relevant gold items retrieved in top 10 divided by all relevant gold items; report macro average and per-category results |
| Precision@10 | Relevant items in top 10 divided by returned items in top 10; specify treatment of fewer than 10 results |
| MRR@10 | Mean reciprocal rank of the first relevant result, with zero for no relevant result |
| nDCG@10 | Discounted cumulative gain at 10 normalized by ideal ranking, using documented relevance grades |
| Citation correctness | Proportion of evaluated citation claims supported by the cited source/version and evidence span |
| Answer faithfulness | Proportion of factual answer claims entailed by retrieved evidence under the labeling rubric |
| Abstention quality | Correct abstentions on unanswerable/insufficient-evidence queries, balanced against unnecessary abstentions |
| Retrieval latency | p50/p95/p99 from request receipt to ranked result, measured separately from generation |
| Tenant leakage | Count of unauthorized cross-tenant results, artifacts or derived disclosures; release threshold is zero |

### 8.3 Proposed initial quality gates

These are **candidate targets** that must be calibrated against task/domain difficulty and a named baseline before being frozen for release:

- Recall@10 point estimate ≥ 0.90 on the frozen initial dataset.
- Citation correctness point estimate ≥ 0.95.
- Agent task success point estimate ≥ 0.90 on a separately defined task suite.
- Tenant leakage = 0.
- 95% confidence intervals, sample counts, category breakdowns and error analysis are mandatory.

For binary proportions, report a Wilson or exact binomial confidence interval and specify the method. For query-level retrieval metrics, report a bootstrap confidence interval over queries and preserve the sampling unit. Do not present a point estimate without its denominator and uncertainty.

The team must not tune on the final holdout set. Keep development, validation and final test partitions fixed and versioned.

### 8.4 No-evidence behavior

If relevant evidence is absent, inaccessible, stale, contradictory or below the configured confidence policy:
- Return a clear insufficient-evidence result.
- Do not fabricate citations or source facts.
- Do not silently broaden tenant scope.
- Offer a retrieval retry only within the caller's authorized scope.
- Record the abstention reason and evidence provenance without logging sensitive content unnecessarily.

---

## 9. Model independence and model runtime

### 9.1 Definition

**Model independence** means the primary inference path can run on a self-hosted open-weight model under the operator's control without a mandatory dependency on an external vendor API. It does not mean every model, capability, or modality is vendor-free.

### 9.2 Required proof

Run the declared inference test profile with outbound vendor API access denied or provider credentials absent. Record:
- Model repository and immutable revision/digest.
- License review and usage constraints.
- Hardware model, VRAM/RAM, driver, runtime and quantization.
- Context length and truncation policy.
- Quality/task-success metrics.
- Latency p50/p95/p99 and tokens/sec.
- Throughput under declared concurrency.
- GPU/CPU/RAM peak and steady-state usage.
- Error rate, restart recovery and warm/cold start.
- Cancellation and timeout behavior.
- Cost per successful task including compute, storage and operational overhead.

A successful boot or health endpoint is not proof of usable model quality or production capacity.

### 9.3 Provider routing rules

- Route only to providers/models permitted by the policy and data classification.
- Avoid sending restricted institutional data to a third-party provider unless an approved data-processing policy permits it.
- Retry only transient errors with bounded exponential backoff and jitter.
- Do not splice partial streamed output from one model with another.
- Record provider/model revision and policy decision for every generation.
- Keep provider fallback separate from model governance approval.

---

## 10. Agent execution and autonomous engineering

### 10.1 Tool execution contract

Each tool definition must include:
- Stable tool ID and semantic version.
- Input and output JSON schema.
- Required scope/role.
- Risk and side-effect class.
- Timeout, concurrency and resource requirements.
- Idempotency behavior.
- Audit event types.
- Approval requirement.
- Failure/retry semantics.
- Data classification and retention.

The LLM may propose a tool call but cannot assign its own authorization, risk class or approval status.

### 10.2 Repository engineering workflow

MCP is not a Git synchronization protocol. A safe autonomous engineering flow must use Git and CI explicitly:

```text
fetch remote
  -> verify expected base SHA
  -> create isolated branch/worktree
  -> inspect repository and policy
  -> modify files in sandbox
  -> run local tests and security checks
  -> inspect diff and generated files
  -> commit with traceable message
  -> push branch
  -> verify remote branch SHA
  -> create pull request
  -> wait for exact-commit CI and reviews
  -> human approval
  -> merge through protected branch policy
  -> verify deployed artifact and runtime health
```

Acceptance:
- Workspace and remote SHA are recorded.
- The system rejects unexpected base-branch movement or requests a rebase/review.
- The agent cannot change protected branch rules or bypass review.
- PR creation is not equivalent to merge; merge is not equivalent to deployment.
- CI status must refer to the exact head SHA under review.
- A human reviewer approves high-impact changes.

### 10.3 Human approval

Approval records must bind:
- Actor identity and role.
- Action/tool ID and version.
- Exact parameters or canonical parameter hash.
- Target resource and tenant/project.
- Risk classification and policy version.
- Expiry and one-time/replay behavior.
- Decision, timestamp and reason.

An approval for one action must not be reusable for a materially different target or parameter set.

---

## 11. Learning and model governance

- Preserve provenance for every source dataset and transformation.
- Define allowed data, consent/rights, retention, deletion and privacy policy before training.
- Detect duplicates, contamination, sensitive data and poisoned examples.
- Pin training code, dependencies, seeds, hyperparameters, base model revision and dataset digest.
- Store candidate artifacts immutably and record evaluation results.
- Keep training identity separate from evaluator and approver identities.
- Require independent regression/safety evaluation and authorized human approval.
- Stage promotion and monitor drift; define disable and rollback triggers.
- Never let a training job, model, agent or automated benchmark alone authorize production promotion.

---

## 12. Observability, SLO and operations

### 12.1 Required telemetry

Every request/job should carry a correlation ID and record:
- Actor/service identity, tenant and project pseudonymous IDs.
- Route, operation, policy and tool versions.
- Model/provider/revision where relevant.
- Job transitions, retry count, worker lease and terminal reason.
- Latency segments, tokens, resource use and cost attribution.
- Authorization outcomes and approval references.
- Error class and trace/span IDs.

Never log access tokens, API keys, private keys or raw secret values. Prompt and document content must be omitted or redacted by default, with explicit retention and access policy for any debugging capture.

### 12.2 SLI/SLO starting proposal

The following are initial planning targets, not measured claims. Freeze them only after workload characterization and a production-like load test.

| Service level indicator | Proposed starting target | Measurement |
|---|---:|---|
| Control-plane availability | ≥ 99.5% monthly | Successful eligible API requests / eligible requests |
| Non-inference API latency | p95 ≤ 1.0 s | Exclude model execution; segment by route |
| RAG retrieval latency | p95 ≤ 1.5 s | Query receipt to ranked results at declared load |
| MCP health tool latency | p95 ≤ 2.0 s | Authenticated request to response |
| MCP scoped read latency | p95 ≤ 5.0 s | Authenticated workflow-plan read |
| Control-plane 5xx rate | < 1% | Exclude caller-caused 4xx and planned maintenance, report separately |
| Unauthorized cross-tenant disclosure | 0 | Adversarial test and incident records |
| Durable job state loss | 0 acknowledged jobs lost | Restart/crash recovery test |

Inference latency and throughput must be specified per model/hardware profile; do not combine them with control-plane latency.

### 12.3 Resource and cost budgets

Before production, each environment and tenant tier must have explicit numeric limits for:
- Request body and upload bytes.
- Prompt/context/output tokens.
- Concurrent requests and active jobs.
- GPU worker concurrency and maximum GPU/VRAM/RAM.
- Per-job wall-clock time and lease duration.
- Retry count and maximum retry age.
- Storage bytes, artifact size and retention.
- Daily/monthly model and GPU spend.
- Per-tenant rate and concurrency quota.

The repository currently defines a 50 MiB upload default in its settings; this must be validated against proxy, parser and storage limits. Other budgets must be set from measured hardware/workload data before a release can pass. An undefined budget is a release blocker for the relevant expensive operation.

### 12.4 Reliability operations

Maintain:
- On-call and escalation ownership.
- Incident severity and communication policy.
- Runbooks for model outage, provider outage, queue backlog, database failure, worker compromise, data leak and rollback.
- Backup retention and restore objectives (RPO/RTO).
- Queue drain, worker revoke and emergency disable procedures.
- Capacity/cost dashboards and alerts.

---

## 13. Supply chain and reproducibility

Required for release:
- Dependency lock or fully reproducible dependency resolution.
- Pinned base images and build action versions.
- SBOM for application/container artifacts.
- Dependency vulnerability scan and remediation policy.
- Secret scanning and repository history review.
- Container/image scanning.
- Model source, license and immutable weight digest.
- Build provenance and release artifact digest.
- Migration checksum and ordered migration inventory.
- Signed or otherwise integrity-protected release evidence.

Do not claim “supply-chain secure” from a passing dependency scan alone. Include the scan tool/version, database date, scope, exceptions and artifact digest.

---

## 14. Test strategy and executable commands

### 14.1 Existing baseline commands

The reference branch CI currently defines the following test sequence:

```bash
python -m pip install -e ".[dev,postgres,worker]"
ruff check app tests
pytest -q
```

The repository CI workflow provisions PostgreSQL 16 for the job and sets `TEST_DATABASE_URL`. A local run that does not configure equivalent database services is not equivalent to the full CI run.

### 14.2 Required test layers

| Layer | Minimum checks |
|---|---|
| Unit | Schema validation, policy functions, state transitions, provider error mapping |
| API integration | Auth, tenant/project isolation, idempotency, pagination, request limits |
| Database integration | Migrations from empty DB, constraints, RLS/grants, transaction rollback |
| RAG evaluation | Retrieval metrics, citation evidence, abstention, deletion/version behavior |
| Agent security | Prompt injection, tool escalation, sandbox escape, timeout, cancellation |
| MCP integration | OAuth discovery/refresh, scope denial, host validation, tool-list and tool-call authorization |
| Worker integration | Provision/revoke, lease expiry, late result rejection, retry and crash recovery |
| Model runtime | Pinned model load, provider-offline path, quality, resource and restart tests |
| Resilience | Load, soak, failure injection, backup/restore, multi-replica behavior |
| Release | Exact-SHA CI, security scan, staging smoke, canary and rollback |

### 14.3 Commands not yet established

RAG benchmark, adversarial agent tests, MCP staging smoke tests, model benchmarks and resilience tests require dedicated runners and versioned suites. Do not invent a successful command or report them as passed before those runners exist.

When implemented, each runner must support a deterministic invocation that records:
- Suite and dataset version.
- Code commit and environment image.
- Configuration and model digests.
- Start/end timestamps.
- Result file and checksum.
- Pass/fail/blocked status and failed case IDs.

---

## 15. Acceptance evidence and reporting

Every requirement is tracked with one of these states:

- **PASS:** current reproducible evidence exists for the exact candidate.
- **FAIL:** a required check ran and failed.
- **BLOCKED:** a prerequisite or capability is absent.
- **NOT RUN:** the check has not been executed.
- **NOT VERIFIED:** evidence exists but has not been independently validated.
- **NOT APPLICABLE:** justified with reviewer approval and scope evidence.

Each evidence item contains:
- Requirement/control ID.
- Repository, branch and full commit SHA.
- Test/benchmark/tool and version.
- Environment and configuration reference (no secrets).
- Dataset/model/artifact digest when relevant.
- Run timestamp and operator/automation identity.
- Result, failure details and retained artifact URI.
- Reviewer and review date for manual evidence.

A status summary without linked evidence is an engineering assertion, not a certification result.

---

## 16. Mandatory release gates

| Gate | Pass condition |
|---|---|
| G0 — Scope and integrity | Primary/related repository boundary fixed; candidate SHA frozen; branch protection and reviewed PR verified |
| G1 — CI and quality | Lint, unit, integration, migration tests green on exact SHA |
| G2 — Identity and tenancy | Live auth; least privilege; tenant/project adversarial tests; revocation verified |
| G3 — Secrets and audit | Secret scan clean or approved exceptions; rotation/revocation tested; privileged actions traceable |
| G4 — Durable execution | Job state, idempotency, leases, restart recovery, retry and cancellation proven |
| G5 — Artifact trust | Scoped object access, immutable identifiers, checksum/MIME/parser validation and deletion proven |
| G6 — Model governance | Pinned model digest/license, independent evaluation, human promotion and rollback proven |
| G7 — RAG quality and safety | Frozen benchmark meets calibrated thresholds; evidence/provenance verified; cross-tenant leakage zero |
| G8 — Agent/MCP controls | Sandbox, tool allowlist, authorization, OAuth, approval, audit and kill switch tested |
| G9 — Operations | SLO telemetry, cost budgets, alerts, runbooks, backup/restore and incident ownership verified |
| G10 — Supply chain | Lock, SBOM, scans, provenance and immutable build artifact available |
| G11 — Resilience | Load/soak/failure-injection and disaster-recovery evidence meet approved objectives |
| G12 — Release control | Human approval binds exact code/config/model/migration artifacts; canary and rollback tested |

**Release rule:** any mandatory gate in FAIL, BLOCKED, NOT RUN or NOT VERIFIED results in **NO-GO**. A NOT APPLICABLE state requires a documented, reviewed rationale.

---

## 17. Maturity scoring policy

Scores describe evidence-backed maturity, not writing quality or model identity.

- **0–2:** concept or undocumented prototype.
- **3–4:** partial implementation; key controls or evidence missing.
- **5–6:** functional in a controlled environment; limited integration or reliability proof.
- **7–8:** broad implementation with reproducible tests and staging evidence; production controls still have gaps.
- **9:** all mandatory gates PASS on an identified release candidate, security and performance evidence reviewed, production deployment and rollback exercised.
- **10:** sustained production operation across a defined observation window, independently reviewed operational evidence, resilience and security controls continuously verified.

Do not publish an overall 9/10 or “production-ready” result while any mandatory release gate is not PASS. A strategic document may be rated separately from the implementation.

---

## 18. Immediate engineering backlog

Prioritize work in this order:

1. **P0 evidence inventory:** record exact branch/SHA and baseline status; compare `main` and hardening branch without conflating them.
2. **P1 identity/policy:** complete tenant/project authorization, secret manager, audit schema, tool registry and kill switch.
3. **P1 durable contracts:** finalize job state machine, event envelope, idempotency and error contract.
4. **P2 runtime:** prove self-hosted model inference with pinned weights and measured hardware profile.
5. **P3 RAG:** implement tenant-aware ingestion/retrieval, provenance, deletion and benchmark harness.
6. **P4 agents/MCP:** read-only interoperability first; then sandboxed actions under explicit authorization and human approval.
7. **P5 learning:** reproducible candidate training/evaluation and independent promotion.
8. **P6 certification:** load, security, restore, canary, rollback and evidence pack.

No phase is complete solely because its documentation has been written.

---

## 19. Review and change control

- This document is version-controlled and reviewed through PR.
- Changes to security, tenancy, state machine, model promotion, evaluation methodology or release gates require an ADR or an explicit rationale in the PR.
- Acceptance thresholds are versioned. Do not change a threshold after seeing final test results without recording the rationale and re-running the frozen suite.
- Production exceptions must identify owner, risk, compensating control, expiry and approver.
- Every release report states repository, branch, full SHA, environment, timestamp and evidence links.
- Review this specification at least quarterly and after a material security incident or architectural change.

---

## 20. References

References are pinned to the editions available at the review date; verify again when a new release is evaluated.

1. OWASP GenAI LLM Top 10 2026, current LLM application security release: https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/
2. OWASP GenAI LLM Top 10 2026 canonical source and release list: https://github.com/GenAI-Security-Project/GenAI-LLM-Top10
3. OWASP Top 10 web application project (separate from the GenAI LLM Top 10): https://owasp.org/projects/top-ten/
4. Supabase Row Level Security guidance, including grants and service-role/RLS behavior: https://supabase.com/docs/guides/database/postgres/row-level-security
5. Model Context Protocol specification: https://modelcontextprotocol.io/specification/latest
6. Universal Generative AI institutional workflow control document: `docs/INSTITUTIONAL_WORKFLOW_CONTROL.md`
7. Universal Generative AI production gates: `docs/INSTITUTIONAL_PRODUCTION_GATES.md`

---

## Final engineering decision

**Approved as a strategic master specification. Implementation-ready status and production certification remain pending evidence.**

The target is not a high score on paper. The target is a system whose security, correctness, performance, governance, recoverability and operational claims can be reproduced against an exact release candidate.
