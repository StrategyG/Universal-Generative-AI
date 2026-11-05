# P0 Core Contracts & Identity Compatibility

**Contract version:** 1.0.0-draft  
**Status:** Proposed cross-repository baseline; implementation and live IdP compatibility are NOT VERIFIED.  
**Scope:** Universal-Generative-AI (UGAI), AI Notebook Studio V, and IM19 Universal MCP.  
**Deployment constraint:** Target deployment is 100% local. A local OIDC issuer may implement this contract; a hosted identity provider is not required.

## 1. Goals and invariants

1. Establish one interoperable user identity vocabulary across the three services.
2. Keep service audiences separate; a token minted for one API must not be accepted by another.
3. Preserve a stable issuer-scoped subject and tenant boundary across token exchange.
4. Keep Notebook tenant membership and role authorization database-authoritative.
5. Keep IM19 provider-account identity distinct from the human subject and MCP gateway authentication.
6. Fail closed on missing, malformed, expired, wrong-issuer, wrong-audience, or unsupported-algorithm tokens.
7. Never treat identity fields in a task payload as identity or authorization evidence.

## 2. Canonical access-token profile

The local OIDC issuer / token-exchange service MUST issue short-lived signed JWT access tokens with:

| Claim/header | Requirement | Meaning |
|---|---|---|
| iss | Required; exact configured issuer | Local identity issuer |
| sub | Required, non-empty, max 255 chars | Stable issuer-scoped user or workload subject |
| aud | Required; exact service audience | One target API; do not reuse across services |
| exp | Required | Expiration |
| iat | Required | Issuance time |
| tenant_id | Required canonical UUID string | Tenant boundary |
| roles | Required bounded array of strings | Coarse platform roles, not resource membership |
| scope | Optional space-delimited string | API capabilities for this audience |
| project_ids | Required for UGAI task/generation calls; array of opaque IDs | Project memberships visible to UGAI |
| kid | Required in JWT header | Key identifier from configured local JWKS |

**P0 algorithm profile:** RS256 for the common baseline because UGAI currently verifies RS256 only. A service may support additional algorithms only after an explicit contract revision and cross-service tests. Never accept none or derive algorithms from untrusted token content.

tenant_id MUST be a UUID string compatible with Notebook's UUID parser. UGAI may retain its string representation internally, but MUST validate canonical UUID syntax at the boundary. sub is opaque and MUST NOT be interpreted as an email address or mutable username.

## 3. Canonical role vocabulary

Allowed platform role values for token interoperability:
- platform_admin
- tenant_admin
- project_owner
- developer
- read_only

A token role is only a coarse platform assertion. It MUST NOT bypass Notebook's active membership lookup, IM19's service/account/scope checks, or project/resource-specific authorization. Notebook membership roles (owner, admin, editor, member, viewer) remain database-owned and map to permissions only inside Notebook.

## 4. Audience and token-exchange rules

Use distinct configured audiences, for example ai-notebook-api, universal-generative-ai, and im19-mcp. Values are deployment configuration, not universal constants.

- A Notebook user token is accepted only by Notebook.
- Notebook-to-UGAI forwarding uses RFC 8693 token exchange or an equivalent local issuer-controlled, audience-restricted exchange.
- The exchanged UGAI token preserves the same issuer-scoped sub and tenant_id, and contains only project memberships and roles required by policy.
- IM19 remote MCP authentication is a separate gateway resource audience. A Google/provider OAuth token is never a substitute for the IM19 gateway access token.
- Provider access tokens remain encrypted in IM19's provider vault and are never returned to the browser or passed as UGAI/Notebook bearer tokens.
- No service may accept a token merely because its signature is valid; issuer, audience, time claims, tenant and authorization context must all validate.

## 5. Service-specific mapping

### UGAI
- Map sub to Principal.subject.
- Map tenant_id to Principal.tenant_id; validate UUID syntax before accepting it.
- Map roles to Principal.roles.
- Map project_ids to Principal.project_ids.
- Enforce audience universal-generative-ai (or configured deployment-specific UGAI audience).
- Continue enforcing project membership and tenant/owner/project data scope server-side.

### AI Notebook Studio
- Map sub to Principal.subject.
- Parse tenant_id as UUID.
- Parse bounded roles and scope; do not use token roles as a substitute for active membership.
- Resolve (tenant_id, subject, status=active) from the tenant-membership database for protected tenant APIs.
- Derive permissions from persisted Notebook membership role and policy table.
- Use server-side token exchange for UGAI calls; browser clients never receive exchanged tokens or client secrets.

### IM19 Universal MCP
- Authenticate the MCP caller against configured IM19 resource issuer/audience.
- Preserve authenticated sub as the human/workload principal.
- Keep (provider, account_id) as a separate linked external-account identity.
- Enforce provider scopes, account binding, mutation policy and exact-action approval independently.
- Never equate provider account_id with tenant_id, sub, or OAuth client ID.

## 6. Error and trust behavior

- Missing bearer token: 401 with WWW-Authenticate.
- Invalid/expired/wrong issuer/wrong audience token: uniform 401; do not leak verification details.
- Valid identity but missing tenant membership, role, scope, project access, or approval: 403 (or 404 where resource-existence privacy is required).
- Identity configuration unavailable: 503 / readiness NO-GO; never silently fall back to anonymous or development identity in production.
- Claims, task payloads, MCP outputs and A2A messages are untrusted inputs. Only verified issuer-signed claims and server-side records may establish identity/authorization.
- No cross-tenant fallback, wildcard tenant, caller-selected tenant override, or trust in forwarded identity headers.

## 7. Local-only deployment profile

The production topology MUST be deployable on a private local network with:
- a local OIDC issuer and local JWKS endpoint;
- separate service audiences and confidential service clients;
- local PostgreSQL for tenant membership and service state;
- encrypted local secret storage / key management;
- TLS at every network boundary where bearer tokens traverse a network;
- explicit service-to-service token exchange;
- no mandatory Supabase, hosted IdP, or external cloud control plane.

External model APIs or identity providers may be optional integrations only; they are not prerequisites for the local baseline.

## 8. P0 acceptance criteria

- [ ] Contract version and claim names are identical across the three repositories.
- [ ] A single local issuer can mint a Notebook-audience token and a separate UGAI-audience exchanged token for the same sub and UUID tenant_id.
- [ ] Wrong issuer, audience, signature, algorithm, expiry, malformed UUID tenant, and missing subject are rejected.
- [ ] Notebook rejects inactive/missing membership even when token roles contains an elevated role.
- [ ] UGAI rejects project IDs absent from verified token and rejects cross-tenant job reads.
- [ ] IM19 rejects a provider token presented as an MCP gateway token and rejects cross-subject/provider/account access.
- [ ] Provider account identifiers cannot override user subject or tenant identity.
- [ ] No service accepts identity or roles from request body fields or untrusted headers.
- [ ] Cross-repository contract tests run in CI with synthetic keys and no production secrets.
- [ ] Local deployment smoke test verifies issuer discovery/JWKS, token exchange, all three audiences, and negative authorization cases.

## 9. Known compatibility gaps to resolve in implementation

| Gap | Current evidence | Required action |
|---|---|---|
| Tenant type | UGAI accepts any non-empty string; Notebook parses UUID | Add UUID validation at UGAI boundary |
| Role semantics | UGAI consumes token roles; Notebook authorizes from DB membership | Keep roles coarse; membership remains Notebook authority |
| Project membership | UGAI consumes project_ids; Notebook forwarding uses DB membership and token exchange | Define exact exchange mapping and stale-membership behavior |
| Audience isolation | Services configure their own audiences | Add negative cross-audience contract tests |
| Algorithm profile | UGAI currently RS256; Notebook uses configured allowlist | Pin RS256 common profile in local issuer and tests |
| IM19 principal | IM19 separates subject, provider and account ID | Add explicit identity mapping tests; do not collapse identities |
| Local issuer | deployment settings exist but live shared issuer not verified | Add local OIDC test fixture and end-to-end test |

## 10. Governance

This is a proposed contract baseline, not proof of implementation. Any change to required claims, role vocabulary, audience, token-exchange semantics or tenant identifier format requires a versioned contract change and updates to all three adapters/tests. Do not mark P0 VERIFIED until acceptance criteria execute in CI and the local integration test produces artifacts.
