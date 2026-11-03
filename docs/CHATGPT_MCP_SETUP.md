# ChatGPT MCP integration (read-only baseline)

## What this adds

The platform exposes a separate MCP Streamable HTTP process at `/mcp` with two read-only tools:

- `get_platform_health`: returns a sanitized API/queue health summary.
- `get_workflow_plan(plan_id)`: reads a saved workflow plan by forwarding the caller's OIDC bearer token to the existing API. The API remains the authority for tenant, owner, and project authorization.

There are deliberately no repository write, database mutation, generation, worker administration, model approval, or deployment tools in this baseline.

## Important ChatGPT plan limitation

As of 2026-11-03, OpenAI documents custom MCP server connections on ChatGPT web for Business and Enterprise/Edu. Pro can connect custom MCP servers with read/fetch permissions. Free is not listed as supported for custom MCP connections. Custom MCP connections are not available in the ChatGPT mobile app. Therefore a Free account cannot complete the ChatGPT-side connection; the server can be prepared and deployed, but the account plan and web UI must support custom MCP before connection.

See the current OpenAI Help Center article: https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt

## Identity-provider prerequisite

This server is an OAuth 2.1 resource server. It does not issue user tokens or implement a login/consent server. The configured OIDC provider must:

1. Publish valid OpenID Connect / OAuth authorization-server discovery metadata.
2. Support authorization-code flow with PKCE and issue access tokens whose issuer, audience, expiry, and claims match the platform's existing OIDC contract.
3. Support refresh tokens and advertise/issue `offline_access` (or the provider's equivalent) so ChatGPT can maintain the connection.
4. Include the configured tenant, roles, and project membership claims. The MCP verifier grants only the `ugai:read` scope to known platform roles.

The existing API OIDC verifier currently validates RS256 tokens against `OIDC_ISSUER`, `OIDC_AUDIENCE`, and `OIDC_JWKS_URL`. A provider that cannot perform the OAuth authorization flow and refresh-token lifecycle must be integrated before ChatGPT can authenticate.

## Environment

Configure these values in the deployment secret/environment manager; do not commit real credentials:

| Variable | Required value |
|---|---|
| `AUTH_MODE` | `oidc` |
| `ENVIRONMENT` | `production` for production deployment |
| `OIDC_ISSUER` | HTTPS issuer URL of the real identity provider |
| `OIDC_AUDIENCE` | Audience expected by the platform API |
| `OIDC_JWKS_URL` | HTTPS JWKS URL |
| `OIDC_TENANT_CLAIM` | Usually `tenant_id` |
| `OIDC_ROLES_CLAIM` | Usually `roles` |
| `OIDC_PROJECTS_CLAIM` | Usually `project_ids` |
| `MCP_RESOURCE_URL` | Exact public endpoint, e.g. `https://mcp.example.com/mcp` |
| `MCP_ALLOWED_HOSTS` | Explicit comma-separated host allowlist, e.g. `mcp.example.com,mcp.example.com:*` |
| `MCP_ALLOWED_ORIGINS` | Optional comma-separated browser origins; leave empty if no browser client is used |
| `UGAI_API_BASE_URL` | HTTPS base URL of the existing Universal Generative AI API |
| `MCP_HOST` | Usually `0.0.0.0` inside the container |
| `MCP_PORT` | Defaults to `8001` |

`MCP_RESOURCE_URL` must exactly match the public MCP endpoint. The host allowlist must contain only the deployed hostname; do not disable DNS-rebinding protection as a shortcut.

## Install and run

The MCP Python SDK is included in the project dependencies.

```bash
pip install -e ".[dev]"
python -m app.mcp_server
```

The process listens on `MCP_HOST:MCP_PORT` and serves Streamable HTTP at `/mcp`. Put it behind a TLS-terminating reverse proxy and route the public `/mcp` path to this process. Keep the API service separately reachable at `UGAI_API_BASE_URL`.

## Local validation

```bash
ruff check app/mcp_server.py tests/test_mcp_server.py
pytest -q tests/test_mcp_server.py
```

For an end-to-end validation, test OAuth discovery, token refresh, rejected/expired tokens, tenant isolation, and the MCP tool list with an MCP Inspector before exposing the endpoint to ChatGPT.

## Connect from ChatGPT (when the account supports it)

Use ChatGPT on the web, not Android:

1. Open Settings / Apps or the workspace Plugins page.
2. Choose Add custom MCP server.
3. Enter the public HTTPS endpoint, e.g. `https://mcp.example.com/mcp`.
4. Configure OAuth using the OIDC provider.
5. Scan the tools and confirm that only the read-only tools above are available.
6. Test health and a workflow plan belonging to the authenticated user.

Do not connect the service until TLS, OAuth discovery, token refresh, host allowlisting, and authorization tests pass.

## Deployment status

This branch adds the MCP server code and setup guide only. It does not create a hosting service, public endpoint, DNS record, TLS certificate, OAuth application, OIDC secret, or ChatGPT connection. Those require the owner's hosting and identity-provider configuration. No production deployment or ChatGPT connection is claimed.
