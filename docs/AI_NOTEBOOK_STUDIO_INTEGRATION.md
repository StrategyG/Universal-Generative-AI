# AI Notebook Studio integration contract

**Status:** architecture and API contract proposal; not an operational integration.

Repositories:
- UGAI: https://github.com/StrategyG/Universal-Generative-AI
- IM19 MCP: https://github.com/StrategyG/im19-universal-mcp
- AI Notebook Studio: https://github.com/StrategyG/ai-notebook-studio-v

## 1. Purpose and ownership

UGAI is the central intelligence and orchestration control plane. AI Notebook Studio is the notebook workbench and execution plane. IM19 is the shared remote MCP gateway for external provider tools.

| Capability | Owning system | Explicitly not owned by |
|---|---|---|
| Notebook projects, notebooks, cells and collaboration | AI Notebook Studio | UGAI, IM19 |
| Kernel lifecycle, execution queue, isolation, resource limits and artifacts | AI Notebook Studio | UGAI, IM19 |
| Task planning, agent coordination, model selection and decision workflow | UGAI | AI Notebook Studio, IM19 |
| Cross-agent task state and orchestration policy | UGAI | AI Notebook Studio, IM19 |
| Remote MCP transport, provider OAuth, encrypted provider credentials and provider quotas | IM19 | AI Notebook Studio, UGAI |
| MCP tool discovery policy, workflow allowlist and invocation provenance | UGAI using its IM19 adapter | AI Notebook Studio, IM19 |
| Notebook user, tenant and resource authorization | AI Notebook Studio API | Browser UI, model, notebook kernel |
| Approval for consequential actions | Owning application policy; UGAI verifies approval receipts | Model output |

Do not move notebook execution into the MCP gateway. Do not duplicate the global agent registry, planner, model router or MCP gateway inside the notebook application.

## 2. Target topology

    User / Studio UI
          |
          v
    AI Notebook Studio API
      - authenticate user
      - verify tenant membership and notebook ownership
      - establish request and idempotency context
          |
          | authenticated service-to-service request
          v
    UGAI Orchestration API (target; not verified as deployed)
      - task lifecycle, policy, agent/model orchestration
      - decision workflow where appropriate
      - approved external tool registry
          |                         |
          | remote MCP adapter      | execution adapter
          v                         v
    IM19 MCP Gateway          Studio Execution API
      - OAuth audience          - service identity and task binding
      - connector policy        - enqueue/cancel/status
      - provider scopes         - isolated notebook runtime
          |                         |
          v                         v
    External providers         Ephemeral notebook worker
                               -> outputs/artifacts -> Studio API

The browser and notebook kernel must never receive IM19 bearer tokens, Google refresh tokens, UGAI service credentials or provider vault keys. The notebook runtime is not an MCP server and is not reachable through arbitrary MCP tool arguments.

## 3. Request and execution flow

1. Studio authenticates the user and resolves active tenant membership, role and notebook/project ownership. A valid JWT alone is not sufficient proof of active membership or resource ownership.
2. Studio submits a task to UGAI over an authenticated service-to-service channel. The trusted identity context is established by the API and token issuer; actor_id and tenant_id must not be accepted from model-generated arguments.
3. UGAI creates a task with a stable task ID, request ID and idempotency key. UGAI owns planning, agent selection, model orchestration, policy evaluation and task lifecycle.
4. For an external provider operation, UGAI uses its existing IM19ToolProvider integration seam. The actor identity comes from trusted UGAI authentication context. IM19 independently verifies its resource-bound token, scope and provider-side subject. Tool allowlists remain empty-by-default and operator controlled.
5. For notebook execution, UGAI calls a separate authenticated Studio execution API. Studio re-checks tenant, notebook ownership, task binding, permitted operation and quota before queuing work.
6. Studio executes code only in its own isolated worker/sandbox. UGAI and IM19 do not execute notebook code.
7. Studio returns a bounded status and result reference to UGAI. UGAI associates it with the task and returns a sanitized result to Studio.
8. Any consequential external write remains a separate operation requiring an action-bound, unexpired, actor-scoped approval receipt. A model statement that approval occurred is never evidence of approval.

## 4. Proposed API contracts (not implemented)

The route names below are proposed versioned interfaces, not claims about existing endpoints.

### Studio API to UGAI

- POST /api/v1/tasks — submit a task.
- GET /api/v1/tasks/{task_id} — read task state and bounded result metadata.
- POST /api/v1/tasks/{task_id}/cancel — request cancellation.

The submission contract should include request_id, idempotency_key, workspace_id and an allowlisted task intent; opaque notebook/project references; explicitly requested capabilities; and a bounded artifact manifest with content hashes and access-controlled references.

It must not accept caller-selected MCP server URLs, arbitrary MCP tool names, OAuth tokens, provider credentials, unbounded execution parameters or model-supplied tenant/actor claims.

### UGAI to Studio Execution API

- POST /api/v1/internal/executions — request a bounded execution.
- GET /api/v1/internal/executions/{execution_id} — obtain execution state.
- POST /api/v1/internal/executions/{execution_id}/cancel — request cancellation.

The execution request binds task_id, request_id, idempotency_key, tenant_id and actor_id from verified trusted context; notebook_id and immutable cell revision/source digest; approved runtime profile and bounded parameters; and CPU, memory, wall-clock, output-size and concurrency ceilings.

Studio must reject expired or wrong-audience credentials, mismatched tenant/actor, missing notebook permission, replayed or conflicting idempotency keys, unapproved runtime profiles and requests exceeding configured limits.

### Common response and state contract

Use the state machine:
ACCEPTED -> QUEUED -> RUNNING -> SUCCEEDED | FAILED | CANCELLED.

Cancellation is asynchronous and must report the final observed state. Never turn an unknown execution outcome into a blind retry.

Every inter-service call carries a request ID and distributed trace context. Logs and audit records contain identifiers, decisions, status, duration and bounded error codes, not tokens, secrets or unrestricted notebook output.

## 5. Security requirements

- Separate user authentication from service-to-service authentication. Use exact issuer, audience and scope validation.
- Require authoritative tenant membership, role freshness, object-level authorization and resource ownership before exposing business routes.
- Use short-lived, audience-bound service credentials. Never forward an IM19 credential to Studio or a notebook worker.
- Enforce deny-by-default outbound network policy for notebook workers. Block loopback, private, link-local and cloud metadata ranges; protect DNS resolution and redirects.
- Use ephemeral workers, read-only base images, non-root execution, filesystem quotas, process limits, CPU/memory quotas, deadlines and bounded output capture.
- Treat notebook cells, dependencies, uploaded files, provider results and model output as untrusted.
- Use immutable artifact references and content digests. Do not embed secrets in notebooks, execution logs or artifacts.
- Make audit failure block privileged operations. If post-execution audit fails, mark the outcome uncertain and reconcile by request/execution ID before retry.
- Require action-bound human approval for external writes, repository changes, deletion, publication, resource transfer or other high-impact side effects.

## 6. Existing implementation versus required work

| Item | Evidence state |
|---|---|
| UGAI IM19 client, strict configuration, token-provider seam, allowlist policy and redacted audit interface | Present in UGAI integration branch; unit-test evidence is recorded in PR #6 |
| UGAI decision workflow and approval-receipt boundary | Present in the decision workflow branch; not a deployed orchestration service |
| UGAI production workflow registry and externally reachable task API | Not verified / not implemented |
| IM19 remote MCP gateway and provider identity/scopes | Implemented code foundation; deployed HTTPS/OAuth acceptance remains outstanding |
| Studio JWT/JWKS identity foundation | Implemented foundation; active tenant membership and resource authorization remain outstanding |
| Studio notebook runtime, sandbox and execution API | Not implemented / not verified |
| End-to-end live integration across all three systems | Not tested; not operational |

## 7. Delivery sequence and release gates

1. Review and stabilize the existing UGAI-to-IM19 adapter dependency chain. Keep stacked PRs separate until prerequisite PRs are reviewed and merged in order.
2. Complete Studio identity authorization, tenant isolation and resource ownership before enabling task or execution routes.
3. Implement and test the Studio execution service independently, including sandbox escape, egress, quota, cancellation, crash recovery and artifact isolation.
4. Implement UGAI's authenticated task API and workflow registry, then attach the IM19 provider and Studio execution adapter.
5. Run contract tests with fake services, then staging tests using real issuer-bound credentials and isolated test tenants.
6. Verify traceability, idempotency, audit fail-closed behavior, revoked/expired credentials, cross-tenant denial, rate limits, timeouts and uncertain-outcome reconciliation.
7. Keep external writes disabled until approval verification and recovery acceptance pass.
8. Production promotion requires independent security review, backup/restore evidence, monitoring, incident response and explicit release approval.

**Release status: NO-GO for end-to-end production integration.** This document defines ownership and interface contracts only. It does not claim an operational UGAI API, a running Studio execution runtime, a live IM19 endpoint or successful cross-repository integration tests.
