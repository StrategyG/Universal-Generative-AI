# IM19 adapter validation record

## Implemented source-level coverage

The adapter package includes tests for:
- HTTPS-only MCP endpoint and exact /mcp path.
- Exact DNS host allowlist, same-host OAuth resource, IP-literal/wildcard/non-default-port rejection, malformed URI and non-finite timeout rejection.
- Explicit operator allowlist, absent optional server annotations, contradictory annotations, object input schema and hard-denied identity, Drive content/write/approval-status and raw Cloudbrowser tools.
- Mandatory pre-execution audit: if the durable audit sink fails before execution, no remote tool call occurs.
- Post-execution audit failure: adapter reports `execution_may_have_completed=True` so callers do not blindly retry.
- Redacted audit event shape excludes tool arguments and result bodies.
- Trusted actor identity is required by the workflow provider facade.
- Exact OAuth resource audience and `im19:read` scope are passed to the token-provider interface.

## MCP SDK compatibility

- Targets the repository's locked MCP Python SDK `2.3.x` using `streamable_http_client` and `httpx2.AsyncClient`.
- Uses SDK 2.x snake_case model fields (`input_schema`, `is_error`, `read_only_hint`, `destructive_hint`) while serializing protocol objects with Pydantic aliases.
- Explicitly bounds connection pool, timeout and SSE event size; cross-origin redirects are disabled at the HTTP client.

## CI evidence

- Current UGAI PR #6 head: `76c65e54dced8b179bd9efc8c2f035dbd172b29f`.
- GitHub Actions run [41703308083](https://github.com/StrategyG/Universal-Generative-AI/actions/runs/41703308083): dependency install PASS, Ruff PASS, 42 tests PASS.
- The CI workflow validates the adapter package, policy, audit behavior and SDK 2.x transport contract. It does not exercise a live IM19 endpoint or OAuth issuer.

## Runtime components

- `IM19ToolProvider` is a framework-neutral facade exposing `discover()` and `execute()`.
- The repository currently has no production agent/workflow registry to attach it to. Application-level wiring remains an integration task.
- OAuth is deliberately an injected `AccessTokenProvider`; it requests the exact resource audience and `im19:read` scope. No concrete issuer/client registration or secrets are assumed.
- Audit is a mandatory `AuditSink` protocol; a durable implementation must be supplied by the deployment.

## Required live integration tests not yet evidenced

These require a deployed IM19 staging endpoint and registered OAuth client:
- MCP initialize and tools/list against the real endpoint.
- A permitted read-only provider call.
- Expired, wrong-audience, insufficient-scope and revoked token rejection.
- Tenant isolation, 401/403, 429/503, timeout and oversized-result behavior.
- Egress policy blocks loopback, private, link-local and metadata destinations, with DNS-rebinding tests.
- Confirmation that no bearer token or provider credential reaches logs/traces.
- Durable audit sink availability, redacted event delivery and fail-closed behavior during outages.
- UGAI workflow registry invocation through the facade.

## Release decision

Status remains **ADAPTER IMPLEMENTED / LIVE CONNECTION UNVERIFIED**. It is not production acceptance until live OAuth, deployment, network-isolation, audit-sink and workflow-registry evidence passes.
