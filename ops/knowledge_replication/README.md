# PostgreSQL VM replication deployment

This directory is a deployment template, not a live deployment. Keep the Supabase project active.

## Provisioning

1. Create a Linux VM with encrypted persistent storage and private networking.
2. Install Docker Engine and Compose from the vendor's supported repository.
3. Copy `.env.example` to a VM-local `.env`; set a unique random admin password in a secret manager. Never commit the real file.
4. Review `docker-compose.yml`, firewall rules, backup policy and volume sizing before starting.
5. Start PostgreSQL on loopback only. Provide remote worker access through a private VPN or SSH tunnel; do not bind 5432 to a public interface.
6. Apply `sql/001_control_plane.sql` and verify the tables and indexes.
7. Create separate non-superuser roles for replication, backup, monitoring and human administration. Grant only the required schema/table privileges.
8. Configure TLS, connection limits, disk alerts, log retention, automated patching and tested off-host backups.

The Compose file mounts SQL into PostgreSQL's first-initialization directory. That directory is only run when the data volume is initialized for the first time. For an existing volume, apply reviewed SQL explicitly with a migration process; do not delete the volume to rerun initialization.

## Worker contract

`src/ugai_replication/contracts.py` defines the transport-neutral boundary. A production adapter must implement:

- source outbox reads with a stable per-stream cursor;
- destination transactions that atomically write the business row, idempotency receipt and checkpoint;
- fencing/lease validation to prevent an expired worker from committing;
- schema-version validation and quarantine for unknown events;
- bounded retry with exponential backoff and jitter;
- structured redacted logs and metrics.

The contract tests use in-memory fakes. They do not prove PostgreSQL concurrency, Supabase access, or end-to-end replication.

## Source-side outbox requirement

An event must be inserted in the same database transaction as the corresponding source row mutation. Do not emit events after commit from application memory: a process crash between the row commit and event emission would lose the change.

Before adding triggers or modifying source tables, inventory every writer, table, RLS policy, trigger, function and transaction path. Add outbox emission only to explicitly approved tables and test rollback semantics. Never assume that a generic trigger can safely serialize every RAG table.

## Baseline snapshot and restore

Use a client-side `pg_dump --format=custom` with a dedicated read-only source role and a consistent snapshot. Capture schema and extension inventory separately. Encrypt the dump before upload, calculate SHA-256 over ciphertext, and store a signed/non-secret manifest. Restore into a disposable database first. Compare schema objects, row counts, vector dimensions, constraints, indexes and sampled content hashes.

## Google Drive archive

Use a dedicated service account and a dedicated folder with minimum access. Upload ciphertext only. Keep the encryption recipient/key reference separate from the archive. Record Drive file ID and checksum in the manifest, but never store credentials or encryption key material in Git or database metadata. Add independent immutable/WORM storage if immutability is required.

## Cutover safety

The worker has no cutover operation. Cutover requires a human-run change window and explicit approval after reconciliation, lag, backup and rollback gates pass. Supabase remains available throughout rehearsal and the rollback period.
