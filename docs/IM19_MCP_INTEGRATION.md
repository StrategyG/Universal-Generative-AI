# IM19 Universal MCP integration

Status: planned adapter contract; not yet implemented in this repository.

The MCP server implementation is maintained separately in https://github.com/StrategyG/im19-universal-mcp. UGAI must consume it as a remote MCP client over authenticated Streamable HTTP after a real HTTPS deployment exists. A repository URL is not a server endpoint.

See the integration contract at https://github.com/StrategyG/im19-universal-mcp/blob/main/docs/UGAI_INTEGRATION.md for transport, OAuth, runtime adapter design, tool policy, Supabase data boundary and acceptance gates.

## Non-negotiable boundaries

- IM19 owns provider OAuth, encrypted provider credentials, MCP authentication, quotas and provider tool implementations.
- UGAI owns agent orchestration, dynamic tool discovery, per-workflow allowlists, policy enforcement and execution provenance.
- Never copy provider refresh tokens, MCP bearer tokens, OAuth codes, cookies or encryption keys into UGAI, prompts, notebooks, logs or Supabase RAG.
- Remote/cloud execution uses HTTPS Streamable HTTP, not localhost or a local stdio process.
- Default-deny tool exposure; no write-capable tools without a separately verified human approval and recovery workflow.

No live integration or production readiness is claimed by this document.