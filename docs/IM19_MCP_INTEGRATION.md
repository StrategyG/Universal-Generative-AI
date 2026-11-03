# IM19 Universal MCP integration

Status: reusable UGAI remote MCP adapter and framework-neutral tool-provider facade implemented on branch `integration/im19-mcp-adapter-v1`; live connectivity is not verified.

The MCP server is maintained in https://github.com/StrategyG/im19-universal-mcp. UGAI consumes it as a remote MCP client over authenticated Streamable HTTP after a real HTTPS deployment exists. A repository URL is not a server endpoint.

Implementation: [UGAI PR #6](https://github.com/StrategyG/Universal-Generative-AI/pull/6). Package `src/ugai_mcp/` includes strict endpoint/resource validation, an injected OAuth token-provider interface, MCP session initialization, dynamic tool discovery, a framework-neutral workflow provider, default-deny policy, mandatory redacted audit and bounded execution.

## Ownership and trust boundaries

- IM19 owns MCP transport, authentication, provider OAuth, encrypted provider credentials, quotas and provider-side audit.
- UGAI owns orchestration, dynamic tool discovery, per-workflow allowlists, policy enforcement and execution provenance.
- The trusted UGAI authentication layer must supply `actor_id`; never accept it from model-generated tool arguments.
- Never copy provider refresh tokens, MCP bearer tokens, OAuth codes, cookies or encryption keys into prompts, notebooks, logs or Supabase RAG.
- Remote/cloud execution uses HTTPS Streamable HTTP, not localhost or a local stdio process.

## Runtime adapter

Use `IM19ToolProvider` from `ugai_mcp.runtime` as a framework-neutral integration seam. Construct one provider per authenticated workflow/request with `IM19Config.from_env()`, an organization-approved `AccessTokenProvider` implementation bound to the exact IM19 resource audience, a durable `AuditSink`, and `actor_id` from the trusted UGAI authentication context.

The provider exposes `discover()` and `execute(tool_name, arguments)`. The application owner must attach these methods to the UGAI workflow tool registry; the adapter is not proof that such runtime wiring or remote connectivity is live.

## Tool safety

The allowlist is empty by default and must be explicitly configured by an operator. The inspected IM19 0.3 server registers tools without MCP read-only annotations; UGAI therefore uses an operator-reviewed allowlist. Contradictory annotations deny access if present.

Hard-denied regardless of allowlist: `request_service_authorization`, `confirm_service_authorization`, `disconnect_service`, `drive_read_file`, `drive_create_folder`, `cloudbrowser_get_task`, and `cloudbrowser_list_tasks`.

## Configuration validation

- `IM19_MCP_URL` must be an absolute HTTPS URL with the exact path `/mcp`, no credentials, query, fragment or non-default port.
- `IM19_MCP_RESOURCE` must be an absolute HTTPS URI on the same DNS hostname as the MCP endpoint.
- `IM19_MCP_ALLOWED_HOSTS` is required and accepts only exact DNS hostnames. Wildcards, IP literals, malformed labels, whitespace, duplicate entries and localhost are rejected.
- `IM19_ALLOWED_READ_TOOLS` remains empty by default. Configured names are syntax-checked, unique and capped at 128.
- Timeout must be finite and between 0 and 120 seconds; response size is bounded from 1 KiB to 10 MB.

These are application-level configuration controls, not a complete SSRF boundary. Production must enforce outbound network policy at the egress firewall/resolver, block loopback/private/link-local/metadata-service ranges, and test DNS rebinding. A DNS allowlist alone cannot guarantee that a hostname resolves to a safe address at connection time.

## Audit behavior

A durable audit sink is mandatory for tool execution. The adapter writes a redacted STARTED event before calling IM19, then a terminal event afterward. Events contain request ID, trusted actor ID, tool name, outcome, duration and a bounded error code; they deliberately omit arguments, provider results and tokens. Failed pre-call audit prevents the remote call. A post-call audit failure must be reconciled using the request ID; callers must not blindly retry potentially completed operations.

Supabase may store non-secret integration metadata, approved tool manifests, workflow references and redacted audit records. It must not store MCP bearer tokens, Google refresh tokens, encryption keys, OAuth codes or browser cookies. RAG retrieval is not an authorization decision or source of executable tool permissions.

## Remaining live-connection gates

1. Deploy IM19 behind public HTTPS and verify the exact MCP resource URL.
2. Register UGAI as an OAuth client with the exact IM19 resource audience and required read scope.
3. Implement the deployment-specific token provider using managed secrets.
4. Implement and verify the durable audit sink and fail-closed behavior.
5. Attach `IM19ToolProvider.discover/execute` to the deployed UGAI workflow registry.
6. Run staging tests for initialize, tools/list, approved read-only calls, invalid/expired/wrong-audience tokens, insufficient scope, 401/403, 429/503, timeout, oversized result, DNS rebinding and cross-tenant isolation.

No live integration or production readiness is claimed until these tests pass against deployed services.
