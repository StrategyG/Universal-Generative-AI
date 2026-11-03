# UGAI Runtime ↔ Supabase Institutional RAG

Status: runtime adapter and a dedicated Supabase gateway implementation are committed for review. The gateway is **not deployed** by this change. No production database schema, data, secret, or existing Edge Function was modified.

## Runtime path

**UGAI caller → FastAPI /v1/knowledge/retrieve → InstitutionalRagAdapter → ugai-institutional-retrieve → release decision view → existing institutional-rag-search → im19_match_trusted_v1**

The UGAI adapter calls only the dedicated gateway. It never calls the legacy Edge Function directly. The gateway:

1. Requires a separate server-to-server x-ugai-service-key.
2. Accepts only institutional_approved; unknown fields and other corpora are rejected.
3. Reads the live institutional_rag.production_release_decision_v1 using a fixed read-only query.
4. Requires exactly 9/9 technical and 4/4 operational release gates, with decision GO.
5. Only then calls the existing institutional-rag-search function, which calls public.im19_match_trusted_v1.
6. Validates source/chunk identifiers, SHA-256 content hash and exact page locator.
7. Emits a typed evidence record. Internal source_path, database errors, credentials and raw upstream payloads are not returned.

The evidence trust fields are derived by the gateway only after the database release view returns GO and the existing trusted RPC returns a validated page-scoped result. They are never accepted from the UGAI request.

## Fail-closed behavior

The live Supabase release view currently reports NO_GO (2/9 technical and 0/4 operational). The gateway therefore returns 503 RELEASE_GATE_NO_GO and does not call the search function. Missing DB connectivity, malformed gate results, unavailable upstream retrieval, wrong service authentication or invalid evidence produce safe errors; none falls back to staging or legacy data.

This is an integration implementation, not production approval. Repository CI and mocked adapter tests do not attest live deployment or live end-to-end behavior.

## Runtime configuration

Set these variables only in the private UGAI backend environment:

- UGAI_API_BEARER_TOKEN: a randomly generated high-entropy token (minimum 32 characters) protecting the FastAPI retrieval route.
- UGAI_INSTITUTIONAL_RAG_GATEWAY_URL: deployed URL ending in /functions/v1/ugai-institutional-retrieve.
- UGAI_INSTITUTIONAL_SERVICE_KEY: separate high-entropy shared service key; must match the Supabase secret with the same name.
- UGAI_RAG_TIMEOUT_SECONDS: optional, 1–60 seconds; default 15.

The Supabase Edge Function requires project runtime variables SUPABASE_DB_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and existing RAG_CHATGPT_API_KEY, plus a new UGAI_INSTITUTIONAL_SERVICE_KEY. The database connection and service-role key remain inside Supabase Edge Functions. Never copy a secret or service-role key into GitHub source, browser/client code, notebooks, logs or this repository.

## Local execution

From runtime/:

    python -m venv .venv
    . .venv/bin/activate
    python -m pip install -e ".[test]"
    export UGAI_API_BEARER_TOKEN='<local-secret-at-least-32-characters>'
    export UGAI_INSTITUTIONAL_RAG_GATEWAY_URL='http://127.0.0.1:54321/functions/v1/ugai-institutional-retrieve'
    export UGAI_INSTITUTIONAL_SERVICE_KEY='<local-gateway-secret>'
    uvicorn ugai_rag.api:app --host 127.0.0.1 --port 8000

The route requires Authorization: Bearer <UGAI_API_BEARER_TOKEN> and a JSON request:

    {
      "query": "What are the main policy risks?",
      "scope": {"corpus": ["institutional_approved"]},
      "limit": 5
    }

## Supabase deployment (reviewed operator action)

After reviewing the code and setting the new secret through Supabase's secret manager:

    supabase functions deploy ugai-institutional-retrieve --no-verify-jwt

The function disables platform JWT verification only because it authenticates every request itself using the dedicated service key. Do not expose this gateway to browsers. Keep the existing institutional-rag-search function unchanged. Deployment is not performed by this repository change because it publishes a new live endpoint and requires operator-managed secret provisioning.

## Verification

CI runs Python compilation and unit/API tests using mocked HTTP transport. A production integration test must still verify: gateway authentication; NO_GO blocks before the legacy search is invoked; GO permits only validated published citations; no private/staging corpus can be selected; source hashes and exact page locators survive the mapping; and request IDs are preserved end-to-end. Production remains NO_GO until the live database release view changes through its independent governance process.
