# Production Remediation V1 — Security and Operations Hardening

**Repository:** `StrategyG/Universal-Generative-AI`  
**Base:** `main`  
**Work branch:** `feature/production-readiness-hardening-v1`  
**Status:** Implementation candidate — review and CI evidence pending for the current head SHA  
**Release decision:** **NO-GO / NOT PRODUCTION VERIFIED**

This document records the changes in this feature branch. It does not assert that infrastructure has been provisioned, TLS certificates issued, secrets rotated, monitoring deployed, or backup/restore performed.

## 1. Scope and changes

### Implemented in this branch

| Area | Change | Evidence boundary |
|---|---|---|
| CI baseline | Removed the unused worker import that blocked Ruff; corrected the project-scope test fixture so it creates and reads the task under the same tenant before asserting project-level denial | Must pass on current exact head SHA |
| Secret delivery | Added supported `NAME_FILE` loading for API/database/worker/Redis/metrics secrets; rejects ambiguous direct + file sources; no secret values are emitted in error messages | Unit tests; no live secret manager |
| API rate limit | Added fixed-window limiter with local-only memory backend and shared Redis backend; unknown/unavailable Redis is fail-closed | Unit/API tests; Redis staging connectivity NOT RUN |
| Redis security | Production requires `rediss://`, Redis ACL password, certificate and hostname verification, and a fixed 60-second per-minute window | Configuration tests; certificate/ACL connection NOT VERIFIED |
| Readiness | Added `/readyz`; production readiness checks OIDC mode, persistent PostgreSQL queue, and an active Redis probe | Unit/CI tests; staging probes NOT RUN |
| Metrics | Added Prometheus request counter and duration histogram with only bounded `method` and `status` labels; endpoint requires `X-Metrics-Token` | Unit/API tests; scraper/dashboard/alerts NOT CONFIGURED |
| Security headers | Added nosniff, frame denial, referrer policy, permissions policy and production HSTS | Unit/API tests; public TLS termination NOT VERIFIED |
| Container | Dockerfile copies the `src` packages, installs the optional Redis operations dependency, creates a non-root UID/GID, and runs the API without root privileges | Docker build/image scan NOT RUN in this change |
| TLS ingress | Added Caddy automatic HTTPS reverse-proxy scaffold; API has no published host port; public ingress hides `/health`, `/readyz`, and `/metrics` | DNS, ACME issuance and real TLS handshake NOT RUN |
| Secret mounts | Production Compose expects mounted secret files and immutable API/Caddy image digests | Compose deployment/config validation and secret custody NOT RUN |
| PostgreSQL backup | Added custom-format `pg_dump` encrypted to an age recipient, with checksum and mode-0600 temporary libpq service file | Shell syntax/unit tests only; live backup NOT RUN |
| PostgreSQL restore | Added checksum verification, archive validation, isolated empty-target requirement and transactional restore without `--clean` | Shell syntax/unit tests only; live restore NOT RUN |

### Existing controls retained

The branch retains the existing production gates for OIDC, PostgreSQL `sslmode=verify-full`, workflow database separation, encrypted workflow payloads and model registry enforcement. These controls are not equivalent to live identity-provider, database, model, or tenant-isolation certification.

## 2. Deployment scaffold

The production topology is:

```text
Internet
   |
   v
Caddy (80/443, automatic HTTPS)
   |
   | private Docker network; trusted proxy address 172.30.0.2
   v
FastAPI API (non-root, no host-published port)
   |             |
   v             v
PostgreSQL     Redis TLS + ACL
   |
   v
Encrypted backup artifact (age) -> off-host retention target
```

Files:
- `compose.production.yaml`
- `deploy/Caddyfile`
- `Dockerfile`

Before using the scaffold, an operator must provide:
- `API_IMAGE` and `CADDY_IMAGE` as immutable registry digests (`@sha256:...`), never floating tags.
- Production domain, ACME email, and verified DNS records.
- OIDC issuer, audience and HTTPS JWKS URL.
- A PostgreSQL DSN file using `sslmode=verify-full` and the approved CA path.
- A separate least-privilege workflow PostgreSQL DSN file using `sslmode=verify-full`.
- Workflow payload encryption key and retained previous key IDs.
- High-entropy operator and metrics tokens.
- A Redis `rediss://` URL with ACL credentials and a CA-trusted certificate.
- Approved host firewall, Docker daemon, storage, update and incident policies.

The API container is only reachable through the Caddy private network. Uvicorn trusts forwarded headers only from Caddy's fixed private address. Changing the network topology requires changing and reviewing `FORWARDED_ALLOW_IPS`; do not trust arbitrary forwarded IP headers.

Operational endpoints are hidden at public ingress. A metrics collector must attach to the private network and authenticate directly to `/metrics`. No collector, dashboard, alert rule, or distributed tracing backend is deployed by this PR.

## 3. Secret handling and rotation

The loader supports mounted `NAME_FILE` values for the names listed in `.env.example`. It rejects simultaneous non-empty direct and file-based sources. Secret files must be read-only, access-restricted mounts supplied by the deployment secret manager/orchestrator.

The loader does not itself provide a secret manager, key vault, audit of secret reads, automated rotation, or zero-downtime rotation. Rotation procedure must be owned by the operator:
1. Create the replacement secret in the approved secret manager.
2. Update the mounted secret reference in the deployment system.
3. Roll API instances so new processes load the replacement.
4. Verify authenticated health/readiness and test the affected integration.
5. Revoke the old credential only after dependent services have migrated.
6. Record approver, timestamp, credential version/identifier and verification evidence — never the secret value.

## 4. Rate-limit semantics and limitations

- The Redis counter uses an atomic Lua fixed-window increment with expiry.
- Redis failures return HTTP 503 rather than bypassing the limiter.
- Exceeded requests return HTTP 429 with `Retry-After`.
- Production requires Redis over TLS, trusted certificate/hostname validation, ACL password and a one-minute window.
- Identity is based on the client IP after Uvicorn's trusted-proxy processing. The middleware does **not** yet enforce per-user, per-tenant, per-project, per-route or monetary quotas.
- The memory backend is for local development/tests only; it is single-process and not suitable for production.
- Limits must be calibrated against actual workloads and approved tenant tiers before production exposure.

## 5. Backup and restore

Run the backup helper from the reviewed release checkout:
- `bash scripts/ops/backup_postgres_encrypted.sh`

Required variables: `DATABASE_URL_FILE`, `AGE_RECIPIENT`, `BACKUP_DIR`.

Restore only into an isolated, empty target database:
- `bash scripts/ops/restore_postgres_isolated.sh`

Required variables: `BACKUP_FILE`, `AGE_IDENTITY_FILE`, `RESTORE_DATABASE_URL_FILE`, and the literal confirmation `RESTORE_CONFIRMATION=RESTORE_TO_ISOLATED_EMPTY_DATABASE`.

The restore helper verifies the encrypted file checksum, decrypts via the mounted age identity, validates the archive, checks that the target contains no user tables, and uses a single transaction without cleaning or dropping existing objects. No live backup or restore has been run. Backup schedules, off-host retention, object-lock/immutability, RPO, RTO and disaster-recovery exercise remain unconfigured.

## 6. Tests and verification

The CI workflow runs:
```bash
pip install -e ".[dev,mcp,postgres,worker]"
ruff check app src tests
pytest -q
```

This branch adds tests for:
- Secret file reading, newline handling and ambiguous sources.
- Production Redis TLS/ACL/metrics configuration.
- Rate-limit enforcement, 429 response, health exemptions and fail-closed behavior.
- Metrics authentication, low-cardinality labels and security headers.
- PostgreSQL DSN service-file validation, file mode, and shell syntax.

A green CI run validates the tested code on that exact commit only. It does not validate Caddy/DNS/TLS, real Redis/PostgreSQL certificates, secret manager access, host firewall, deployment, monitoring, backup/restore, OIDC production IdP, artifact trust, end-to-end tenant isolation or resilience.

## 7. Remaining blockers

| Priority | Remaining gap | Status |
|---|---|---|
| P0 | Live OIDC issuer/JWKS, production credentials, tenant/project adversarial isolation, least-privilege DB role verification | NOT VERIFIED |
| P0 | TLS certificate and public ingress validation on the actual domain | NOT RUN |
| P1 | Secret manager integration, rotation exercise and access audit | NOT VERIFIED |
| P1 | Per-tenant/project quotas, distributed abuse controls and cost budgets | NOT IMPLEMENTED |
| P1 | Monitoring collector, dashboards, alerts, traces, on-call ownership and incident exercise | NOT IMPLEMENTED |
| P1 | Live encrypted backup, off-host retention, restore drill, approved RPO/RTO | NOT RUN |
| P1 | Production branch protection/rulesets and mandatory CI review policy | NOT VERIFIED; not changed by this branch |
| P1 | Complete tenant-scoped external GPU jobs/artifacts and verified object storage | BLOCKED in platform baseline |
| P1 | Full sandbox, cooperative cancellation, append-only audit and durable DAG execution | BLOCKED/PARTIAL in platform baseline |
| P2 | Real model/provider/GPU smoke tests, workload benchmarks, performance and capacity budgets | NOT RUN |
| P2 | Container/SBOM/image provenance scans and immutable release artifact | NOT RUN |
| P2 | Multi-instance, failure-injection, backup/restore, canary and rollback exercises | NOT RUN |

## 8. Release decision

**NO-GO / NOT PRODUCTION VERIFIED.**

This branch improves code-level controls and supplies an operator deployment/backup scaffold. It does not deploy or certify an environment. Do not set the production-readiness score to 100 based on this branch or on CI alone. A readiness score must be recalculated only after the operational and security gates above are demonstrated on a frozen release tuple (code SHA, image digests, migrations, configuration versions and environment evidence).

No merge, production database migration, RLS/IAM change, branch-protection change or deployment is authorized by this work.
