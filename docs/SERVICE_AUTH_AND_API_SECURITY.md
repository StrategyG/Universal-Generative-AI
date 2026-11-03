# Service Authentication and API Security Specification

**Status:** target design for the current Supabase Edge Function boundary.

## 1. Observed current boundary

The Edge Function institutional-rag-search is ACTIVE, version 4, and deployed with verify_jwt=false. It authenticates using a static x-rag-api-key compared to RAG_CHATGPT_API_KEY. It then uses SUPABASE_SERVICE_ROLE_KEY from server environment to invoke a narrow database RPC. The client does not need and must never receive the service-role key.

This is a custom shared-secret boundary, not Supabase JWT verification. CORS restricting browser origins is not authentication.

## 2. Target machine identity

Preferred target: short-lived signed workload token, verified inside the Edge Function, with:
- issuer (iss): registered UGAI workload;
- audience (aud): exact Institutional RAG service;
- subject (sub): workload/service identity;
- scopes: minimum operation, initially knowledge:retrieve;
- issued-at (iat), expiry (exp), and unique token ID (jti);
- key ID (kid) for rotation and audit;
- optional tenant context only if independently derived from a signed, authorized claim.

Recommended lifetime: at most five minutes. Use asymmetric signing and a controlled verification key set where practical. Key rotation must allow a bounded overlap window and support immediate revocation.

Do not place a long-lived Supabase service-role JWT into the custom workload token. The Edge Function verifies workload identity, then uses its own server secret to invoke approved RPCs.

If an interim shared key is retained:
- use high-entropy random material;
- keep in function secrets and UGAI secret manager only;
- store a key identifier, not the value, in logs;
- rotate with explicit overlap and revocation;
- apply per-key quotas, concurrency, and anomaly monitoring;
- compare fixed-length hashes with a vetted constant-time primitive;
- plan removal date and migration owner.

## 3. Edge Function request handling

Current implementation reads req.text() and checks raw.length only after full body allocation. This is not a strict memory bound and measures characters rather than UTF-8 bytes.

Required handling:
1. Reject Content-Length above the configured byte limit before reading.
2. Stream the body and stop/cancel once the strict byte limit is exceeded; Content-Length is advisory only.
3. Enforce JSON content type and reject duplicate/unsupported fields.
4. Validate query length in UTF-8 bytes, not only JavaScript string characters.
5. Limit result count and excerpt bytes server-side.
6. Set an explicit end-to-end timeout and cancel database fetch on deadline.
7. Use request IDs and stable error codes; never return SQL, database response bodies, or provider internals.

## 4. API controls

- Apply per-principal rate limits and per-tenant concurrency quotas.
- Add IP-based abuse controls only as supplemental signals, not as identity.
- Restrict methods and headers to the minimal set.
- Validate Origin when present, but do not trust Origin as proof of identity.
- Require POST for search payloads; do not place private queries in GET URLs.
- Disable caching of authenticated evidence and set no-store.
- Enforce TLS and secure service-to-service egress.
- Do not log Authorization or custom auth headers.
- Apply output byte caps and field allowlists.

## 5. Database boundary

The Edge Function should call only explicitly permitted RPCs. It must not accept an RPC name, table name, SQL fragment, schema, or arbitrary PostgREST path from the caller.

Review:
- function EXECUTE privileges for anon/authenticated/service_role;
- schema USAGE privileges;
- direct table SELECT grants;
- default privileges and exposed schemas;
- SECURITY DEFINER usage and fixed search_path;
- service-role secret storage and rotation;
- audit principal and RPC operation.

The service role is privileged. RLS on tables must not be treated as a restriction on service-role behavior. Protect the server boundary and narrow the allowed operations.

## 6. Release gate and evidence policy

A valid workload token does not authorize staging evidence for a user-facing answer. Authentication, corpus authorization, evidence eligibility, and production release decision are separate checks.

The Edge Function must not:
- expose staging results through the approved route;
- treat RRF score as trust;
- promote evidence or create human review votes;
- allow caller-supplied trust/publication fields;
- return user-citation eligibility when release status is not GO.

## 7. Security acceptance tests

| Test | Expected |
|---|---|
| Missing token | 401 |
| Invalid signature / unknown kid | 401 |
| Wrong audience or issuer | 403 |
| Expired token | 401 |
| Valid token lacking knowledge:retrieve scope | 403 |
| Revoked key/token | 401/403 |
| Excess body bytes with chunked transfer | 413 without unbounded buffering |
| Wrong content type | 415 |
| Invalid JSON/schema | 400 |
| Caller-supplied trusted=true | Rejected or ignored; never authoritative |
| Client-supplied RPC/table path | Rejected |
| Rate limit exceeded | 429 with Retry-After |
| Release gate NO_GO | No user-citation-eligible evidence |
| Supabase RPC 5xx | Safe 503, no database details |
| Secret in log scan | Zero matches |

## 8. Rollout without breaking the current connector

1. Add new versioned route or authentication verifier while retaining current endpoint for a controlled transition.
2. Configure overlapping credentials/tokens in secret manager.
3. Test old and new callers in non-production.
4. Move one caller to the new identity.
5. Monitor authentication failures and retrieval parity.
6. Revoke old shared key after all consumers migrate.
7. Keep rollback instructions and emergency revocation tested.

No authentication or Edge Function change is performed by this design document.
