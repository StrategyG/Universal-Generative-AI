# Supabase decision audit adapter

This integration adds a durable adapter for the existing `DecisionAuditSink`
contract. It writes redacted UGAI workflow events to
`ugai_audit.decision_events`, a private schema separate from the existing
`rag.audit_events` and `institutional_rag` corpus.

## Security boundary

- The `ugai_audit` schema is not added to the exposed Supabase Data API
  schemas. The table is reachable through the narrow
  `public.append_ugai_decision_event` RPC only.
- `anon` and `authenticated` receive no schema, table, or RPC privileges.
- The RPC is `SECURITY INVOKER`, uses a fixed `pg_catalog` search path, and
  is executable only by `service_role`.
- RLS is enabled on the table. Supabase's `service_role` bypasses RLS, so
  RLS is not claimed as a restriction on that role. Table grants are revoked
  explicitly for `service_role` and only `INSERT` is granted back.
- UPDATE and DELETE are rejected by a database trigger. TRUNCATE is both
  denied by table privileges and guarded by a statement trigger.
- The adapter requires an asynchronous Supabase client and validates bounded
  event metadata before sending it. It does not copy evidence text, credentials,
  or execution-plan contents into the audit event.
- The Supabase secret API key is a high-privilege backend credential that maps
  to `service_role` and bypasses RLS across the project. The per-table grants
  in this migration protect this audit table; they do not reduce the key's
  project-wide privileges. Keep the key server-side, create a separate secret
  key for this backend component, and never put it in browser code, shared
  notebooks, or source control.

Append-only controls protect against ordinary application identities. They do
not make the database owner or Supabase project administrator cryptographically
incapable of changing data. Stronger evidentiary guarantees require external
immutable/WORM retention or independently signed export checkpoints.

## Apply sequence

1. Review `supabase/migrations/20261104000100_create_ugai_decision_audit.sql`.
2. Apply it to an isolated Supabase development branch, not the production
   project.
3. Verify schema/table existence, RLS, schema/table/function grants, and
   UPDATE/DELETE/TRUNCATE rejection with a database test suite.
4. Configure a server-side asynchronous Supabase client using the project's
   `sb_secret_...` API key, stored in the host's secret manager.
5. Instantiate `SupabaseDecisionAuditSink(client)` and inject it into
   `DecisionWorkflow`; audit write failure remains fail-closed.
6. Run staging tests for denied anon/authenticated RPC access, successful
   append, duplicate event IDs, mutation rejection, and audit outage.

The migration is staged in this PR only. It has not been applied to the
Supabase project. No credentials, live connection, production deployment, or
execution endpoint are configured.

## References

- [Supabase API keys and server-side secret-key handling](https://supabase.com/docs/guides/getting-started/api-keys)
- [Supabase Row Level Security: grants and policies](https://supabase.com/docs/guides/database/postgres/row-level-security)
