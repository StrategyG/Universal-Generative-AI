# Universal Generative AI

A modular platform for generative AI workflows, designed to support multimodal generation pipelines and extensible model providers.

## MCP integration

The UGAI integration branch contains a reusable IM19 remote MCP client package under `src/ugai_mcp/`.

- IM19 owns MCP transport, OAuth resource authentication, provider OAuth, encrypted provider credentials, provider-side quotas and audit.
- UGAI owns orchestration, OAuth token-provider integration, dynamic tool discovery, workflow-specific allowlists and execution policy.
- Remote connection uses the deployed IM19 HTTPS Streamable HTTP resource ending in `/mcp`. A GitHub repository URL is not a runtime endpoint.
- Supabase may store non-secret integration metadata and redacted audit events; credentials, access tokens, refresh tokens, OAuth codes and encryption keys must remain outside RAG.

### Implemented in this branch

- HTTPS-only endpoint validation and exact `/mcp` path requirement.
- OAuth token-provider interface bound to the configured IM19 resource audience.
- MCP initialize and dynamic `tools/list` discovery using the official Python MCP SDK.
- Default-deny tool policy with an empty-by-default, operator-reviewed allowlist. The inspected IM19 0.3 server does not emit read-only annotations; contradictory annotations are still rejected if present.
- Bounded calls, SDK-compatible timeout values, serialized response-size limit and fail-closed error mapping.
- Unit tests for tool policy and configuration validation.

### Not yet complete

This is an adapter implementation, not proof of a live connection. A deployment-specific OAuth token provider, IM19 HTTPS deployment, live issuer/client/resource registration, workflow runtime wiring, redacted audit sink, and staging end-to-end tests are still required. No live provider credentials or secrets are stored in this repository.

See [docs/IM19_MCP_INTEGRATION.md](docs/IM19_MCP_INTEGRATION.md), [adapter validation gates](docs/IM19_MCP_VALIDATION.md), and the [IM19 server repository](https://github.com/StrategyG/im19-universal-mcp).

## Repository status

UGAI remains an evolving platform. Do not describe the whole platform or this connector as production-ready until the runtime, security, operational and live integration acceptance gates pass.
