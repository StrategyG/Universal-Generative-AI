# IM19 Universal MCP integration

Status: a reusable UGAI remote MCP adapter is implemented on branch `integration/im19-mcp-adapter-v1`; live connectivity is not yet verified.

The MCP server implementation is maintained in https://github.com/StrategyG/im19-universal-mcp. UGAI consumes it as a remote MCP client over authenticated Streamable HTTP after a real HTTPS deployment exists. A repository URL is not a server endpoint.

Implementation: [UGAI PR #6](https://github.com/StrategyG/Universal-Generative-AI/pull/6). The adapter package is under `src/ugai_mcp/` and includes HTTPS endpoint validation, an injected OAuth token-provider interface, MCP SDK session initialization, dynamic tool discovery, default-deny read-only policy, bounded execution and unit tests.

## Ownership and trust boundaries

- IM19 owns provider OAuth, encrypted provider credentials, MCP authentication, quotas and provider tool implementations.
- UGAI owns agent orchestration, dynamic tool discovery, per-workflow allowlists, policy enforcement and execution provenance.
- Never copy provider refresh tokens, MCP bearer tokens, OAuth codes, cookies or encryption keys into UGAI prompts, notebooks, logs or Supabase RAG.
- Remote/cloud execution uses HTTPS Streamable HTTP, not localhost or a local stdio process.
- Default-deny tool exposure; no write-capable tools without a separately verified human approval and recovery workflow.

## Runtime configuration

The adapter validates `IM19_MCP_URL` (HTTPS, exact `/mcp` path), `IM19_MCP_RESOURCE`, explicit `IM19_ALLOWED_READ_TOOLS`, timeout and response-size limits. OAuth token acquisition is an injected `AccessTokenProvider`; deployment must implement it against the registered OAuth issuer and secret manager. No static bearer token is supported by the adapter.

## Remaining live-connection gates

1. Deploy IM19 behind public HTTPS and verify the MCP resource URL.
2. Register UGAI as an OAuth client with the exact IM19 resource audience and required read scope.
3. Implement and test the deployment-specific OAuth token provider.
4. Wire the adapter into the UGAI workflow/tool registry and add a redacted audit sink.
5. Run staging tests for initialize, tools/list, an approved read-only tool call, invalid/expired/wrong-audience tokens, insufficient scope, 401/403, 429/503, timeout, oversized result and cross-tenant isolation.

No live integration or production readiness is claimed until these tests pass against deployed services.
