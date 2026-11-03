# IM19 Universal MCP integration

Status: reusable UGAI remote MCP adapter implemented on branch `integration/im19-mcp-adapter-v1`; live connectivity is not yet verified.

The MCP server is maintained in https://github.com/StrategyG/im19-universal-mcp. UGAI consumes it as a remote MCP client over authenticated Streamable HTTP after a real HTTPS deployment exists. A repository URL is not a server endpoint.

Implementation: [UGAI PR #6](https://github.com/StrategyG/Universal-Generative-AI/pull/6). Package `src/ugai_mcp/` includes HTTPS endpoint validation, an injected OAuth token-provider interface, MCP SDK session initialization, dynamic tool discovery, explicit allowlist policy, bounded execution and unit tests.

## Ownership and trust boundaries

- IM19 owns provider OAuth, encrypted provider credentials, MCP authentication, quotas and provider tool implementations.
- UGAI owns agent orchestration, dynamic tool discovery, per-workflow allowlists, policy enforcement and execution provenance.
- Never copy provider refresh tokens, MCP bearer tokens, OAuth codes, cookies or encryption keys into UGAI prompts, notebooks, logs or Supabase RAG.
- Remote/cloud execution uses HTTPS Streamable HTTP, not localhost or a local stdio process.
- Default-deny tool exposure; write-capable tools remain excluded from the default allowlist.

## Runtime configuration

The adapter validates `IM19_MCP_URL` (HTTPS, exact `/mcp` path), `IM19_MCP_RESOURCE`, explicit `IM19_ALLOWED_READ_TOOLS`, timeout and response-size limits. OAuth token acquisition is an injected `AccessTokenProvider`; deployment must implement it against the registered OAuth issuer and secret manager. No static bearer token is supported.

## Important server-contract detail

The inspected IM19 0.3 `src/im19_mcp/server.py` registers tools without MCP read-only annotations. Therefore, UGAI cannot treat annotations as the authoritative safety signal. The adapter uses an empty-by-default, operator-reviewed tool-name allowlist. If a server does supply annotations, contradictory read-only/destructive hints cause denial.

A conservative initial allowlist to review against the live server is:
- `list_available_services`
- `get_service_capabilities`
- `get_connection_status`
- `youtube_get_channel`
- `youtube_list_videos`
- `youtube_get_analytics`
- `drive_search_files`
- `drive_list_folder`
- `drive_get_metadata`

Do not add `drive_read_file` until restricted-scope consent and content-handling review pass. Do not add `drive_create_folder`, authorization/confirmation tools, or raw Cloudbrowser task tools to a general agent allowlist.

## Remaining live-connection gates

1. Deploy IM19 behind public HTTPS and verify the exact MCP resource URL.
2. Register UGAI as an OAuth client with the exact IM19 resource audience and required read scope.
3. Implement and test the deployment-specific OAuth token provider.
4. Wire the adapter into the UGAI workflow/tool registry and add a redacted audit sink.
5. Run staging tests for initialize, tools/list, approved read-only calls, invalid/expired/wrong-audience tokens, insufficient scope, 401/403, 429/503, timeout, oversized result and cross-tenant isolation.

No live integration or production readiness is claimed until these tests pass against deployed services.
