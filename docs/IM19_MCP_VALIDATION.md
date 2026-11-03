# IM19 adapter validation record

## Implemented source checks

The pull request adds unit tests for:
- HTTPS-only endpoint and exact /mcp path validation.
- Rejection of URL-embedded credentials.
- Explicit tool allowlist enforcement.
- Read-only and non-destructive server annotation enforcement.
- Object input schema requirement.

The pull-request workflow installs the project with the official MCP Python SDK extra, runs Ruff on the adapter/tests, and runs the adapter test suite.

## Required integration tests not yet evidenced

These require a deployed IM19 staging endpoint and registered OAuth client:
- MCP initialize and tools/list against the real endpoint.
- A permitted read-only provider call.
- Expired, wrong-audience, insufficient-scope and revoked token rejection.
- Tenant isolation, 401/403, 429/503, timeout and oversized-result behavior.
- Confirmation that no bearer token or provider credential reaches logs/traces.
- Redacted audit event delivery and fail-closed behavior when the audit sink is unavailable.

## Release decision

Until the live tests above have exact endpoint, environment, test run and commit evidence, the integration status is **IMPLEMENTED ADAPTER / LIVE CONNECTION UNVERIFIED**. This is not production acceptance.