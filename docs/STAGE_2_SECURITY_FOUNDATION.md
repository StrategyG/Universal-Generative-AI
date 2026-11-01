# Stage 2 — Security Foundation

**Repository:** `StrategyG/Universal-Generative-AI`  
**Branch:** `feature/multimodal-platform-v1`  
**Status:** **PARTIAL — NOT PRODUCTION READY**  
**Scope:** OIDC integration contract and tenant/project-scoped generation history. No deployment, identity-provider connection, production database migration, or external infrastructure change was performed.

---

## 1. Implemented

| Control | Status | Evidence boundary |
|---|---|---|
| Pluggable OIDC identity contract | IMPLEMENTED | Configurable issuer, audience, JWKS URL, tenant/role/project claim names |
| JWT signature validation | IMPLEMENTED | PyJWT JWKS client; RS256 allowlist; issuer, audience, expiry, issued-at and subject requirements |
| Production fail-closed startup | IMPLEMENTED | Startup rejects disabled authentication and incomplete OIDC configuration in production |
| Development-only auth bypass | IMPLEMENTED | Disabled mode creates a local development principal only outside production |
| Principal mapping | IMPLEMENTED | Maps subject, tenant, roles and project IDs from verified token claims |
| Generation role check | IMPLEMENTED | Generation requires developer, project_owner, tenant_admin, or platform_admin |
| Project membership check | IMPLEMENTED | Authenticated generation requests require project_id and a matching project membership claim, except platform_admin |
| Job tenant/owner/project scope | IMPLEMENTED | Generation job records carry tenant_id, owner_subject and project_id |
| Job lookup authorization | IMPLEMENTED | SQL lookup scopes by tenant and owner/project/tenant-administrator membership; memory mode applies equivalent checks |
| Public provider error sanitization | IMPLEMENTED | Client response no longer receives raw provider exception text |
| Security regression tests | ADDED / CI NOT YET VERIFIED | OIDC token signature/audience tests, claim validation, role/project checks, route authentication, cross-tenant and cross-project job access |

## 2. Changed files

- `app/auth.py` — OIDC token verification, principal mapping, startup validation and authorization helpers.
- `app/config.py` — OIDC configuration settings.
- `app/main.py` — generation, job lookup and pipeline planning protected by principal dependencies.
- `app/schemas.py` — optional project_id added to generation request.
- `app/services/jobs.py` — principal-scoped job creation/read and public error sanitization.
- `app/services/external_gpu_queue.py` — tenant context passed to persistence.
- `app/services/postgres_gpu_queue.py` — tenant-scoped create/read queries and migration readiness check.
- `migrations/0007_generation_job_tenant_scope.sql` — ownership metadata and indexes for generation job history.
- `pyproject.toml` — PyJWT[crypto] dependency.
- `.env.example`, `README.md`, `docs/THREAT_MODEL.md` — configuration and threat-boundary documentation.
- `tests/test_auth.py`, `tests/test_generation_jobs.py` — security and database test coverage.

## 3. OIDC contract

The API validates RS256-signed bearer access tokens against the configured JWKS endpoint. It requires `sub`, `iss`, `aud`, `exp`, and `iat`, and compares issuer and audience to explicit configuration.

Configurable identity claims:
- tenant: `OIDC_TENANT_CLAIM` (default `tenant_id`)
- roles: `OIDC_ROLES_CLAIM` (default `roles`)
- projects: `OIDC_PROJECTS_CLAIM` (default `project_ids`)

The identity provider remains the source of truth for identity lifecycle, tenant assignment, role assignment, project membership, MFA, and token issuance. The repository does not implement its own password store or login service.

## 4. Data access boundary

New generation rows include tenant, owner subject and optional project metadata. Reads require:
- exact tenant match; and
- owner match, project-membership match, or tenant-administrator role.

A project ID supplied by a client is not trusted as proof of membership. For OIDC requests, project membership must be present in the verified token claims, unless the caller has the platform_admin role. Platform administrator access is still limited to the tenant asserted by the token.

Legacy generation rows with NULL ownership metadata remain inaccessible through the OIDC-scoped API. The migration does not assign old jobs to an arbitrary user.

## 5. Remaining blockers

The following are **NOT IMPLEMENTED / NOT VERIFIED**:

1. No live OIDC provider is configured or connected in the target environment.
2. No first-party organization/project database or live membership-revocation mechanism exists; membership freshness depends on token lifetime and identity-provider claims.
3. Model-registry and worker administration still rely on the static `WORKER_ADMIN_TOKEN`; human admin identity, role delegation and append-only actor audit are not complete.
4. External-GPU job records are not yet tenant/project scoped.
5. Artifact storage and artifact-level ownership/signed URL authorization remain absent.
6. Distributed rate limiting, quotas, concurrency budgets and cost controls remain absent.
7. Production database migration `0007` has not been applied; only the repository migration/test path is defined.
8. No actual provider deployment, production OIDC flow, penetration test, or production security review was performed.

## 6. Verification status

- Unit and route security tests: **ADDED; CI RESULT PENDING / NOT VERIFIED**.
- PostgreSQL migration and tenant-scoped persistence test: **ADDED; CI RESULT PENDING / NOT VERIFIED**.
- Live identity-provider authentication: **NOT RUN**.
- Production DB migration: **NOT RUN**.
- Rate-limit and quota testing: **NOT RUN**.
- Admin RBAC and external-GPU tenant isolation: **NOT IMPLEMENTED**.

Do not interpret the presence of OIDC code or a migration file as proof that an external identity provider or production database has been configured.

## 7. Release decision

**NO-GO FOR PRODUCTION.**

Stage 2 is PARTIAL. The most important generation API/job-history tenant boundary has been added, but privileged admin routes, external-GPU records, artifacts, rate limits and quotas still need independent controls and verification.

Recommended next work:
1. Complete human administrator RBAC and auditable privileged actions.
2. Add tenant/project ownership to external-GPU jobs.
3. Implement durable rate limits and per-tenant quotas.
4. Build artifact storage and scoped signed URL delivery.
5. Run CI and security tests, then validate against a real test identity provider before any production use.
