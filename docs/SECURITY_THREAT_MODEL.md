# Security Threat Model

Status: Initial review based on live Supabase inspection on 2026-11-03. Revalidate before release.

## Assets

- Supabase service-role key and Edge Function secrets.
- Custom RAG API credential.
- AI provider API keys.
- Private source documents, excerpts, embeddings, and review records.
- User conversations, uploaded files, generated artifacts, and workflow traces.
- Evidence approval state, source hashes, and reviewer identity.

## Trust boundaries

1. Browser/client → UGAI API.
2. UGAI orchestrator → Supabase Edge Function.
3. Edge Function → PostgREST/RPC using service-role credentials.
4. Orchestrator → model providers.
5. Orchestrator → MCP/tools and external URLs.
6. Untrusted source content → model context.

## Findings and required controls

### T1. Edge Function uses custom shared-key authentication

Observed: `institutional-rag-search` has `verify_jwt=false` and compares `x-rag-api-key` against `RAG_CHATGPT_API_KEY`.

Controls:
- Keep the credential server-side only; never place it in browser code, notebook output, logs, prompts, or Git.
- Prefer verified JWT/service-to-service identity with audience and scope claims. If a shared key remains, rotate it, scope it to this service, support overlap rotation, and record key ID (never key value).
- Add per-key rate limits, request quotas, revocation, anomaly monitoring, and audit principal.
- CORS is not authentication; non-browser clients can call the endpoint.
- Confirm secret is present and non-empty at startup; fail closed.

### T2. Request body is read fully before the 12,000-character check

Observed: the function calls `req.text()` and only then checks `raw.length`. This does not bound memory consumed while reading an oversized body, and character count is not UTF-8 byte count.

Controls:
- Reject excessive `Content-Length` early, but do not rely on it alone.
- Read the request stream with a strict byte counter and cancel once the configured limit is exceeded.
- Apply gateway-level request and concurrency limits.

### T3. RLS advisor findings

Observed: 21 `institutional_rag` tables have RLS enabled with no policies. Service-role grants are present; the legacy `rag` tables have a `deny_api_roles` policy.

Interpretation: this can be an intentional private-service design. It is not evidence by itself of public data exposure. Verify schema/table/function grants, default privileges, exposed schemas, RPC execute privileges, Edge Function auth, and service-role use. Do not add permissive policies simply to silence the advisor.

### T4. Private staging and approved evidence must not mix

Observed: `search_staged_hybrid_v1` labels its results `UNAPPROVED_INTERNAL_RESEARCH_ONLY`. Staging knowledge relations and synthesis require human review/publication gates.

Controls:
- Enforce separate retrieval endpoints, response types, logs, and UI labels.
- Reject staging records in normal answer generation.
- Never let model output mutate approval, trust, publication, or reviewer fields.
- Human approvals must use authenticated reviewer identity and auditable quorum rules.

### T5. Prompt injection through retrieved documents and tool output

Controls:
- Treat every excerpt, web capture, and tool result as untrusted data.
- Delimit source material and explicitly forbid treating it as instructions.
- Tool execution is server-side, allowlisted, schema-validated, permission-checked, and budget-limited.
- Never expose secrets or privileged system instructions in model context.
- Verify citations and claims after generation.

### T6. Provider key and data exfiltration

Controls:
- Secret manager/environment only; redact headers and provider payloads.
- Apply provider allowlists, outbound network controls, timeouts, and data classification.
- Do not send restricted source content to providers not approved for that data class.
- Fallback providers must pass the same privacy and capability policy.

### T7. SSRF, file upload, and artifact handling

Controls:
- Deny loopback, link-local, private, metadata-service, and non-allowlisted destinations for URL ingestion.
- Validate file signatures, MIME, size, decompression ratio, archive paths, and parser timeouts.
- Malware scan where supported; store uploads outside executable paths.
- Use signed, short-lived artifact URLs and content-disposition safeguards.

## Release-blocking tests

- Missing/invalid/expired credential → 401/403.
- Oversized chunked body → rejected without unbounded buffering.
- Unauthorized role cannot select from private schemas or execute private RPCs.
- Staging-only evidence never appears in standard user answer response.
- Prompt injection in document cannot invoke tools or alter system policy.
- No secret appears in application, database, edge, or model-provider logs.
- Provider timeout/retry cannot exceed workflow budget.
- Cross-user and cross-tenant retrieval tests return zero unauthorized records.
