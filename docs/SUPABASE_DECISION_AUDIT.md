# Supabase decision audit adapter

This integration adds a durable adapter for the existing `DecisionAuditSink`
contract. It writes redacted UGAI workflow events to
`ugai_audit.decision_events`, a schema separate from the existing
`rag.audit_events` and `institutional_rag` corpus.

## Security boundary

- The schema is private and is not added to the Supabase exposed Data API schemas.
- `anon` and `authenticated` receive no schema or table privileges.
- Only the server-side `service_role` is granted schema usage and table INSERT.
- RLS is enabled with an INSERT-only service-role policy.
- UPDATE, DELETE, and TRUNCATE are blocked by database triggers.
- The adapter accepts an already-configured server-side async Supabase client;
  credentials and client lifecycle remain the host application's responsibility.
- Never put a service-role/secret key in browser code, notebooks shared with
  untrusted users, or repository secrets committed as plaintext.

Append-only controls protect against ordinary application identities. They do
not make the database owner or Supabase project administrator cryptographically
incapable of changing data. Stronger evidentiary guarantees require external
immutable/WORM retention or independently signed export checkpoints.

## Apply sequence

1. Review `supabase/migrations/20261104000100_create_ugai_decision_audit.sql`.
2. Apply it to a Supabase development branch, not the production project.
3. Verify schema/table existence, RLS, grants, and mutation-trigger behavior.
4. Configure a server-side async Supabase client with the least-privilege
   service identity and instantiate `SupabaseDecisionAuditSink(client)`.
5. Inject the sink into `DecisionWorkflow`; audit failure remains fail-closed.
6. Run staging tests for denied anon/authenticated access, successful append,
   duplicate event IDs, update/delete/truncate rejection, and audit outage.

This change does not apply a database migration, configure credentials, connect
a live endpoint, or enable production execution.
