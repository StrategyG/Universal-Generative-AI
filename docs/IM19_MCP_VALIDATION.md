# IM19 adapter validation record

## Implemented source checks

The adapter branch includes unit tests for:
- HTTPS-only endpoint and exact `/mcp` path validation.
- Rejection of URL-embedded credentials, query strings, fragments and non-default ports.
- Required exact DNS hostname allowlisting for the MCP endpoint.
- Same-host validation between the OAuth resource URI and MCP endpoint.
- Rejection of wildcard and IP-literal host allowlist entries.
- Finite timeout and bounded response-size configuration.
- Rejection of duplicate or malformed tool names.
- Explicit tool allowlist enforcement.
- Read-only and non-destructive server annotation enforcement.
- Object input schema requirement.

The pull-request workflow installs the project with the official MCP Python SDK extra, runs Ruff on the adapter/tests, and runs the adapter test suite. These checks must pass on the exact final PR head before review/merge; this document does not assert a pass.

## Security boundary and limitation

The hostname allowlist is an application configuration guardrail. It is not a complete SSRF defense and does not replace network-level egress enforcement. Production infrastructure must resolve and validate destinations at connection time, block loopback/private/link-local/metadata-service ranges, and mitigate DNS rebinding. Do not treat an allowlisted DNS name as proof that its resolved address is safe.

## Required integration tests not yet evidenced

These require a deployed IM19 staging endpoint and registered OAuth client:
- MCP initialize and tools/list against the real endpoint.
- A permitted read-only provider call.
- Expired, wrong-audience, insufficient-scope and revoked token rejection.
- Tenant isolation, 401/403, 429/503, timeout and oversized-result behavior.
- Outbound egress restrictions, DNS rebinding and private-address denial.
- Confirmation that no bearer token or provider credential reaches logs/traces.
- Redacted audit event delivery and fail-closed behavior when the audit sink is unavailable.
- Workflow/tool-registry invocation and operator approval of the exact exposed tools.

## Release decision

Until the live tests above have exact endpoint, environment, test run and commit evidence, the integration status is **IMPLEMENTED ADAPTER / LIVE CONNECTION UNVERIFIED**. This is not production acceptance.
