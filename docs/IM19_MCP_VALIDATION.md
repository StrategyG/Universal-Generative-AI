# IM19 adapter validation record

## Implemented source-level coverage

The adapter package includes tests for:
- HTTPS-only MCP endpoint and exact /mcp path.
- Resource URI validation, invalid ports, embedded credentials, query/fragment rejection and non-finite timeout rejection.
- Explicit operator allowlist, absent optional server annotations, contradictory annotations, object input schema and hard-denied privileged tools.
- Mandatory pre-execution audit: if the durable audit sink fails before execution, no remote tool call occurs.
- Post-execution audit failure: adapter reports `execution_may_have_completed=True` so callers do not blindly retry.
- Redacted audit event shape excludes tool arguments and result bodies.
- Trusted actor identity is required by the workflow provider facade.

The pull-request workflow installs the package with the official MCP Python SDK extra, runs Ruff on the adapter/tests, and runs the adapter test suite.

## Runtime components

- `IM19ToolProvider` is a framework-neutral facade exposing `discover()` and `execute()`.
- The repository currently has no production agent/workflow registry to attach it to. Application-level wiring remains an integration task.
- OAuth is deliberately an injected `AccessTokenProvider`; no concrete issuer/client registration or secrets are assumed.
- Audit is a mandatory `AuditSink` protocol; a durable implementation must be supplied by the deployment.

## Required live integration tests not yet evidenced

These require a deployed IM19 staging endpoint and registered OAuth client:
- MCP initialize and tools/list against the real endpoint.
- A permitted read-only provider call.
- Expired, wrong-audience, insufficient-scope and revoked token rejection.
- Tenant isolation, 401/403, 429/503, timeout and oversized-result behavior.
- Confirmation that no bearer token or provider credential reaches logs/traces.
- Durable audit sink availability, redacted event delivery and fail-closed behavior during outages.
- UGAI workflow registry invocation through the facade.

## Release decision

The latest CI run validates package installation, lint and unit tests only. It does not prove a live IM19 HTTPS/OAuth connection, workflow deployment or production acceptance. Status remains **ADAPTER IMPLEMENTED / LIVE CONNECTION UNVERIFIED**.
