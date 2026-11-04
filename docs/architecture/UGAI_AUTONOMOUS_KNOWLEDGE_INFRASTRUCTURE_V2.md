# UGAI Autonomous Knowledge Infrastructure V2.0

## Decision record

- Supabase project `uktauwysjkseqrnbjwzy` remains the production source of truth.
- A separately operated PostgreSQL VM is the disaster-recovery and migration target.
- Synchronization is hybrid: transactional outbox/change capture for incremental changes plus scheduled full/incremental backup artifacts.
- Google Drive is an encrypted archive destination, not a live database and not inherently immutable.
- IM19 remains the only external MCP gateway. Database replication workers use narrowly scoped database/network credentials and do not bypass UGAI tool policy.
- No cutover, source deletion, source pause, or destructive schema change is authorized by this design.

## Logical architecture

```text
UGAI services
    |
    v
Supabase (PRIMARY / source of truth)
    |  same-transaction outbox records
    v
Outbox reader -> durable checkpoint -> idempotent apply worker
    |                                  |
    |                                  v
    |                          PostgreSQL VM (DR target)
    |
    +--> scheduled pg_dump/custom-format backup
                 |
           encrypt + SHA-256
                 |
          Google Drive archive
```

The initial delivery uses an outbox contract and replayable worker boundary. It does not claim that a cross-provider logical replication slot is enabled or supported. Before selecting native CDC, verify Supabase plan, network access, WAL/slot permissions, publication support, and operational limits. If any prerequisite is unavailable, use the outbox adapter.

## Required invariants

1. Supabase remains writable and authoritative throughout shadow replication.
2. Every source mutation requiring replication emits an outbox event in the same transaction as the mutation.
3. Event identity is globally unique; destination application is idempotent.
4. A checkpoint advances only after the destination transaction commits.
5. Ordering is preserved per aggregate/key; global ordering is not assumed unless explicitly configured.
6. Deletes are represented as tombstones; no silent hard-delete omission.
7. Schema and payload versions are explicit. Unknown versions are quarantined, not guessed.
8. PII and secrets are excluded from event payloads unless explicitly approved and encrypted.
9. Backup artifacts are encrypted before upload, checksummed, retained by policy, and restore-tested.
10. Any divergence blocks cutover and triggers reconciliation.

## Target VM baseline

- Ubuntu LTS or equivalent supported Linux.
- PostgreSQL 16 with pgvector extension matching the source vector capability.
- Private network access only; TLS required for remote database clients.
- Firewall: database port reachable only from approved worker/admin addresses.
- Dedicated non-superuser roles for replication writer, backup, monitoring, and operator.
- Encrypted volume, encrypted off-host backups, disk monitoring, WAL/archive policy.
- Automated security updates with controlled PostgreSQL major-version upgrades.
- VM snapshot is supplementary; it is not a substitute for database-native backups.

Do not expose PostgreSQL directly to the public internet. Do not put credentials in repository files, logs, issue comments, or RAG content.

## Control schema

Apply `ops/knowledge_replication/sql/001_control_plane.sql` to the PostgreSQL VM only after reviewing the target. It creates a dedicated `ugai_sync` schema for checkpoints, event receipts, run history, quarantine, and backup manifests. It does not alter Supabase.

## Delivery phases and gates

### Phase A — provision target (not performed by repository commit)
- Provision VM, storage, firewall, DNS, TLS, monitoring and secret manager.
- Install PostgreSQL/pgvector and create least-privilege roles.
- Verify restore from a disposable test backup.

Gate: connection test from the designated worker; no public database exposure.

### Phase B — baseline snapshot
- Capture source schema, extensions, policies, functions, triggers, indexes and grants.
- Produce a consistent source backup.
- Encrypt and hash the artifact before upload.
- Restore into an isolated target database.
- Compare object inventory and row counts; validate vector dimensions and representative checksums.

Gate: zero unexplained schema/object differences; backup checksum and restore test pass.

### Phase C — incremental hybrid sync
- Deploy source-side outbox emission for explicitly approved tables.
- Run worker in shadow mode.
- Apply events with idempotency receipts and per-stream checkpoints.
- Reconcile source and target counts, key ranges, tombstones and sampled content hashes.
- Exercise duplicate delivery, out-of-order delivery, worker crash, lease expiry and retry.

Gate: zero unresolved divergence over an agreed observation window; measured lag within the agreed RPO.

### Phase D — cutover rehearsal
- Freeze schema changes, not source availability.
- Capture final watermark and drain the queue.
- Run full reconciliation and application read-only smoke tests against target.
- Rehearse rollback to Supabase without data loss.

Gate: explicit human approval. This repository automation must never cut over autonomously.

### Phase E — controlled cutover
- Only after approval, switch read traffic using a reversible configuration flag.
- Keep Supabase intact and recoverable during the observation period.
- Promote PostgreSQL only after application, security, performance and recovery acceptance.
- Retire Supabase only under a separate explicit decision after retention and rollback windows expire.

## Backup and Drive policy

Use PostgreSQL custom-format dumps, encrypt locally with age or an approved KMS envelope, compute SHA-256, and upload the ciphertext plus a non-secret manifest. The manifest records source project identifier, capture timestamp, schema migration/version, object inventory, dump format, encryption key identifier (never key material), checksum, and restore-test status.

Google Drive access must use a dedicated service identity with minimum folder scope. Drive versioning/retention is useful but does not make the archive immutable. For stronger ransomware protection, add an independent object-lock/WORM destination.

## Operational SLOs

Targets are planning objectives, not current guarantees:
- RPO: <= 5 minutes only after event capture, lag monitoring and recovery tests demonstrate it.
- RTO: 30-60 minutes only after timed restore/failover exercises demonstrate it.
- Backup: daily full baseline plus more frequent incremental/outbox continuity according to cost and data volume.
- Alert on stale checkpoint, growing queue, checksum mismatch, quarantine growth, failed backup, low disk, certificate expiry and failed restore drill.

## Cutover checklist

- [ ] VM hardened and private-only
- [ ] PostgreSQL/pgvector versions and extensions compatible
- [ ] Schema, RLS/policies, grants, functions, triggers, indexes inventoried
- [ ] Baseline backup encrypted, checksum verified, restore verified
- [ ] Outbox covers every in-scope write path
- [ ] Idempotency and ordering behavior tested
- [ ] Delete/tombstone and schema-version behavior tested
- [ ] Reconciliation passes with zero unexplained divergence
- [ ] Lag and backup-age SLOs observed
- [ ] Application integration and security tests pass
- [ ] Rollback rehearsal passes
- [ ] Human approval recorded
- [ ] Supabase retained through agreed rollback window

## Current execution status

This document and the control-plane SQL are repository artifacts only. They do not provision a VM, access production credentials, create a Drive archive, copy RAG rows, deploy a worker, or prove a restore. Those operations require an operator-controlled runner and secrets supplied through a secret manager.
