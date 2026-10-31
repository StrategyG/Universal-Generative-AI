# Threat Model

## Scope and assets

Protected assets include user prompts and source images, generated assets, model weights and revisions, API credentials, worker credentials, database records, tenant/project metadata, provenance records, and operator actions.

## Trust boundaries and principal threats

| Boundary | Threat | Required control | Current state |
|---|---|---|---|
| Client → API | Unauthorized job submission, IDOR, resource exhaustion | User AuthN, RBAC, tenant/project ACL, quotas, rate limiting | BLOCKED |
| API → PostgreSQL | Injection, privilege escalation, unbounded query load | Parameterized SQL, restricted DB role, TLS, network policy, backups | PARTIAL / environment dependent |
| API → worker | Credential theft, impersonation, stale worker, replay | Scoped short-lived identity, rotation/revocation, signed lease token | BLOCKED; shared prototype token only |
| Worker → storage | Arbitrary URL fetch, broad credentials, malicious output | Signed scoped URLs, allowlisted storage origin, file/type/size/checksum validation | BLOCKED |
| Model source → runtime | Malicious or changed model code, license mismatch | Immutable revision pinning, source allowlist, license review, isolated runtime | BLOCKED |
| Artifact → pipeline | Parser exploit, archive traversal, malformed GLB/MP4 | Safe parsers, size bounds, path normalization, sandboxing, format validation | BLOCKED |
| CI → artifact | Dependency compromise, poisoned container | Pinned dependencies, SBOM, scanners, provenance, protected release workflow | BLOCKED |
| Operator → production | Accidental or unauthorized release/destructive change | Human approval, separation of duties, audit record, rollback | PARTIAL |

## High-risk abuse cases

1. **Stolen shared worker token:** attacker claims jobs and submits false output metadata. Mitigate with per-worker scopes, short expiry, revocation and lease-bound credentials.
2. **Worker-supplied URL/path:** SSRF or path traversal during input fetch or output acceptance. Workers must only use server-issued signed URLs and immutable asset IDs; server validates actual stored bytes.
3. **Poisoned model revision:** arbitrary model code or incompatible license executes in a notebook. Use reviewed model IDs, immutable commit pinning, license allowlist and isolated runtime.
4. **Malformed media parser input:** crafted GLB/ZIP/video causes resource exhaustion or parser exploit. Enforce compressed/uncompressed size limits, sandbox parsers and isolate render workers.
5. **Cross-tenant access:** a guessed job or asset ID leaks another tenant’s work. Derive tenant ownership from authenticated user context and authorize every read/write.
6. **Queue starvation / duplicate work:** worker crashes, lease expiry, or repeated submissions waste GPU quota. Use durable idempotency, leases, attempt caps, dead-letter handling and cost limits.
7. **Secret disclosure:** API tokens appear in logs, notebook output or source control. Use secret stores, redact headers, rotate leaked credentials and scan commits.

## Current residual risk

The current platform is a prototype. Shared-token worker authentication, missing user identity/tenant isolation, missing artifact verification, and unverified model sources leave critical attack paths open. PostgreSQL support does not itself make the API secure or production-ready.

## Incident response minimum

Revoke affected worker credentials, disable the external worker endpoint if compromise is suspected, preserve job/audit/database evidence, quarantine suspect artifacts, rotate secrets, inspect model revision provenance, and only re-enable processing after an operator-approved recovery.
