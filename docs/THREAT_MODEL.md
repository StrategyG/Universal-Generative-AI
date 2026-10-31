# Threat Model

## Scope and protected assets

Protected assets include user prompts and source media, generated files, model weights and revisions, API/operator credentials, worker credentials, PostgreSQL records, project/tenant data, provenance records and administrative actions.

## Trust boundaries and principal threats

| Boundary | Threat | Required controls | Current state |
|---|---|---|---|
| Client → API | Unauthorized submission, IDOR, resource exhaustion | User AuthN, RBAC, tenant/project ACLs, quotas and rate limits | BLOCKED |
| API → PostgreSQL | Injection, privilege escalation, unbounded queries | Parameterized SQL, restricted DB role, TLS, network policy and backups | PARTIAL / environment dependent |
| Operator → worker provisioning | Unauthorized worker creation or token rotation | Separate admin secret, one-time token response, token expiry, hashed storage and explicit revocation | PARTIAL; one static admin secret, no admin identity/role system |
| Worker → API | Token theft, impersonation, stale worker, replay | Per-worker random credentials, token hash, expiry/revocation, worker-ID binding and TLS | PARTIAL / CI verified; no cryptographic per-lease token |
| Worker → scheduler | Falsified GPU or task capability claims | Capability allowlist, hardware attestation, measured runtime identity and server-side policy | BLOCKED; worker metadata is self-reported |
| Worker → storage | Arbitrary URL fetch, broad credentials, malicious output | Server-issued signed URLs, storage-origin allowlist, scoped access and content validation | BLOCKED |
| Model source → runtime | Malicious/changed model code or license mismatch | Immutable revision pinning, model source allowlist, license approval and runtime isolation | BLOCKED |
| Artifact → pipeline | Parser exploit, path traversal, malformed GLB/ZIP/video | Sandboxed parsers, archive path checks, size bounds, MIME/signature/checksum and format validation | BLOCKED |
| CI → release artifact | Dependency compromise or poisoned container | Pinned dependencies, SBOM, scanners, build provenance and protected release workflow | BLOCKED |
| Operator → production | Accidental or unauthorized release/destructive change | Separation of duties, human approval, audit record and rollback | PARTIAL |

## Implemented worker credential controls

The PostgreSQL worker registry currently:
- issues a random worker-specific token during operator provisioning;
- stores only the SHA-256 token hash, not the plaintext token;
- enforces expiry and active/revoked status;
- allows re-provisioning to rotate the token and clear previous capability registration;
- binds authenticated worker requests to the provisioned worker ID and platform;
- supports operator revocation.

The external worker client requires HTTPS for remote API hosts, keeps credentials in request headers, refreshes reported available VRAM/RAM, renews job leases while inference runs, and stops polling after credential/identity rejection.

## Residual high-risk abuse cases

1. **Compromised operator secret:** an attacker with `WORKER_ADMIN_TOKEN` can provision or revoke workers and create production external-GPU jobs. Use a managed secret store, strict operator access, rotation and external audit controls.
2. **Stolen worker token:** an attacker can impersonate that worker until the token is revoked or expires. Revoke and re-provision the affected worker; monitor last heartbeat and job events.
3. **Forged capability report:** a notebook can claim more GPU VRAM or task capability than it has. Treat reported values as scheduler hints only; add runtime attestation or controlled worker images before trusting them for high-cost work.
4. **Worker-supplied asset URI:** a worker can report an arbitrary path/URL or fake completion metadata. Do not trust it; accept completion only after the control plane verifies the stored object, checksum, MIME type and expected format.
5. **Cross-tenant access:** guessed job or asset identifiers may expose another customer's work because user/tenant authorization is not implemented. Do not expose this prototype to untrusted multi-tenant users.
6. **Stale/replayed completion:** current lease ownership is tied to worker ID and expiry, not a separate unique cryptographic lease token. A stronger lease capability is still required.
7. **Poisoned model revision:** unreviewed model code or incompatible license may execute inside a notebook. Use immutable revision pins, source allowlists, license review and isolated runtimes.
8. **Malformed media:** crafted GLB/ZIP/video can exploit parsers or exhaust memory/CPU. Validate and sandbox any future parser/rendering workers.
9. **Secret disclosure:** tokens may leak through logs, notebook outputs or source control. Redact authorization headers, use notebook secret stores and scan commits.

## Incident response minimum

Revoke affected worker tokens, disable worker access if compromise is suspected, preserve relevant database/job evidence, quarantine suspicious output, rotate the operator secret, review model revision and input provenance, and resume processing only after an operator-approved recovery. The current platform does not yet provide a complete append-only audit trail or incident automation.

## Current residual risk

**NOT PRODUCTION READY.** Worker-scoped credentials and capability scheduling materially improve the external-GPU trust boundary, but the platform still lacks user/tenant isolation, signed leases, artifact verification, hardware attestation, model governance, full auditability and live multimodal validation.
