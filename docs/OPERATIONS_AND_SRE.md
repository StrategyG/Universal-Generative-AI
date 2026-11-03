# Operations, Observability, and Reliability Engineering

**Status:** target operational standard; no production runtime is currently implemented.

## 1. Service objectives (provisional)

Establish baselines before committing public SLOs. Candidate targets for a first interactive release:

| Signal | Provisional target | Measurement |
|---|---:|---|
| API availability | >=99.5% monthly | Successful authenticated requests / eligible requests |
| First streamed token | p95 <=3 s | API accepted → first response delta |
| Approved retrieval | p95 <=2 s | Retrieval started → result returned |
| Simple grounded response | p95 <=15 s | Request accepted → final response |
| Workflow crash rate | <0.5% | Internal-fault failures / started workflows |
| Citation integrity | 100% valid IDs and locators | Final citation validation |
| Budget enforcement | 100% enforced | Over-budget workflow stopped or downgraded |

These are candidate objectives, not guarantees. Adjust after realistic load and cost tests. Define exclusions for user cancellation, invalid requests, and provider outages explicitly.

## 2. Required telemetry

Every trace carries:
- trace_id, request_id, workflow_id, conversation_id;
- pseudonymous tenant/principal identifier;
- service name, version, environment, deployment SHA;
- plan version and executed step count;
- retrieval corpus/method, result count and evidence IDs (not raw excerpts by default);
- provider/model ID, adapter version, token usage, latency, retry count, fallback reason;
- tool name/version, input hash, output size, duration, result code;
- citation count, verification result, abstention reason;
- estimated/final cost where available.

Never log raw auth headers, API keys, full private document contents, hidden prompts, or chain-of-thought. Apply structured redaction and retention limits.

## 3. Metrics

### API
request rate, success/error ratio, p50/p95/p99 latency, 401/403/413/429/5xx rates, in-flight requests, queue depth, worker saturation.

### Retrieval
calls by corpus/method and evidence tier, no-evidence ratio, latency/timeout by RPC, candidate count, duplicate rate, source diversity, citation validation failures, staging evidence blocked from production output.

### Model/provider
latency, timeout, 429/5xx, context overflow, input/output tokens, cost, fallback rate, circuit state, quota exhaustion, capability-policy rejections.

### Workflow
duration by type, state transition and terminal-state distribution, retries, abandoned jobs, cancellation delay, human approval wait time, cost per successful workflow.

## 4. Alert classes

- P0: suspected secret exposure, cross-tenant data leak, unapproved evidence published, production citation hash mismatch.
- P1: all providers unavailable, RAG unavailable beyond budget, release gate changes unexpectedly, queue age exceeds threshold.
- P2: elevated latency, retry/fallback spike, no-evidence rate anomaly, worker backlog.
- P3: optimization opportunities and low-impact advisor notices.

Every alert must have owner, runbook, threshold, and escalation path.

## 5. Resilience

- Explicit connect/read/write timeouts on outbound calls.
- Bounded retries with jitter and global deadline.
- Circuit breaker per provider and retrieval backend.
- Bulkheads for chat, ingestion, and media generation.
- Fail-closed authorization and evidence policy.
- Graceful degradation: return partial result only with warning and provenance, otherwise abstain.
- Durable job state and idempotency for long-running side effects.
- Cancellation propagation where supported.

## 6. Backup, restore, and rollback

Before production:
- Document database backup cadence and retention.
- Test restore to isolated project and verify row counts, constraints, indexes, RPCs, Edge Function compatibility, and evidence hashes.
- Prefer forward-only migrations; destructive changes require reviewed migration and tested restore path.
- Version Edge Functions and pin model/provider configuration.
- Rollback application image, function version, and feature flags independently.
- Revoke/reverse governance approvals through explicit auditable events, not silent audit-history mutation.

## 7. Capacity and cost controls

- Separate concurrency pools for chat, retrieval, ingestion, and rendering.
- Enforce per-user, per-tenant, per-provider, and per-workflow budgets.
- Set max upload bytes, archive expansion ratio, page count, image dimensions, audio/video duration, parser CPU/memory/time.
- Set model context/output token caps and maximum parallel agents.
- Record provider pricing snapshots with effective dates; do not hardcode assumed prices.
- Stop runaway jobs on deadline or budget exhaustion.

## 8. Incident runbooks

Minimum runbooks:
1. credential compromise and rotation;
2. unauthorized retrieval/data exposure;
3. database outage or degraded connection pool;
4. embedding model mismatch or hash-integrity failure;
5. provider outage and fallback;
6. prompt-injection/tool misuse;
7. runaway cost or queue backlog;
8. failed migration/Edge Function rollout;
9. citation corruption or source version drift;
10. restore and disaster recovery.

Each incident records timeline, affected tenants/corpora, scope evidence, containment, recovery, and preventive actions.
