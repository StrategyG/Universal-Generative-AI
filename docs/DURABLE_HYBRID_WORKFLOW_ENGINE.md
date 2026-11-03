# UGAI Durable Hybrid Workflow Engine — V1.0

**Status:** implementation is staged on this feature branch. The SQL file in this PR is a schema blueprint only. No live Supabase migration, database update, production credential, or worker deployment is claimed.

## Responsibility boundaries

- UGAI owns task identity, tenant isolation, state transitions, planning contracts, approval coordination, evidence digests and completion gates.
- Model providers return typed proposals only. Model output cannot write workflow state or choose unrestricted tools.
- IM19 remains the remote MCP transport and provider credential boundary. UGAI applies task-specific allowlists.
- Supabase PostgreSQL stores durable tasks, state versions, worker leases, idempotency keys and append-only events in a private schema.
- Hybrid workers share the same task store: local workers handle short bounded tasks; dedicated worker services handle long-running or isolated tasks. Worker identity and tool permissions remain separate.

## State machine

~~~text
received -> observing -> planning -> executing -> verifying -> succeeded
awaiting_approval -> executing (verified receipt required)
awaiting_clarification -> observing (user response required)
failed -> received (explicitly safe retry; maximum two retries)
blocked -> observing (operator override required)
succeeded / cancelled -> terminal
~~~

The transition policy is deterministic and separate from model output. Every transition uses an expected version and a worker lease token. A transition clears the lease atomically so a capable worker can claim the next stage.

## Recovery and concurrency

- Claim uses PostgreSQL row locking with SKIP LOCKED inside a short transaction.
- Every claim issues a fresh random fencing token.
- Heartbeat and transition require the worker ID, token, and unexpired lease to match.
- State update and event append commit in one transaction.
- A crashed worker leaves the last durable state. A new worker can reclaim the task after lease expiry.
- Lease expiry does not prove that an external action failed. Reconcile with the same idempotency key before retrying uncertain side effects.

## Security and evidence

- Task creation stores an input digest, not raw model prompts or hidden reasoning.
- Event metadata and task metadata use explicit allowlists.
- Evidence remains in governed RAG/source systems; workflow records keep provenance references and hashes.
- Model self-critique cannot mark a task verified.
- A task reaches succeeded only after external completion gates pass and evidence is recorded.
- Append-only events protect against ordinary application mutation; stronger evidence retention needs external signed checkpoints or WORM storage.

## Deployment prerequisites

1. Generate the actual migration with `supabase migration new create_ugai_workflow_runtime`; copy the reviewed schema blueprint into that generated file.
2. Apply only to an isolated Supabase development branch first.
3. Create a dedicated database login and grant membership in `ugai_workflow_runtime`. Do not connect workers as the database owner or broad service role.
4. Keep the workflow schema outside the exposed Data API schemas. Do not grant `anon` or `authenticated` access.
5. Keep provider tokens in IM19 or an approved secret manager, never in RAG or task metadata.
6. Run unit, PostgreSQL concurrency, staging integration, backup/restore and crash-recovery tests before production.

## Acceptance tests

- Concurrent workers cannot hold the same live lease.
- A stale worker cannot heartbeat or transition after lease replacement.
- A stale task version is rejected without appending an event.
- An idempotency key cannot be reused with a different actor, task type, or payload digest.
- Unapproved execution, missing clarification, blind retry, terminal-state edits and unapproved blocked recovery are rejected.
- State updates and event records are atomic.
- Uncertain external writes are not automatically retried.
- RLS and grants deny public client roles while the dedicated worker role has least privilege.
- The release gate cannot report success without test evidence tied to the current task version and plan digest.
