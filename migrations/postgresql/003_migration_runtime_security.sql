-- Post-restore security policy contract for the UGAI RAG environment.
-- The migration runner applies the equivalent SQL after it moves the three
-- empty Supabase Auth foreign keys to ugai_identity.actors.
-- Review and apply only if provisioning a target database manually.

CREATE SCHEMA IF NOT EXISTS ugai_identity;
CREATE TABLE IF NOT EXISTS ugai_identity.actors (
    id uuid PRIMARY KEY,
    actor_kind text NOT NULL DEFAULT 'human_or_service_actor',
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ugai_runtime') THEN
        CREATE ROLE ugai_runtime NOLOGIN;
    END IF;
END
$roles$;

GRANT USAGE ON SCHEMA rag,institutional_rag,extensions,ugai_identity TO ugai_runtime;

-- Keep anonymous and authenticated web/API roles denied. Only the private
-- backend group role is granted access. Runtime role has no LOGIN attribute.
DO $secure$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT n.nspname AS schema_name,c.relname AS table_name,c.relkind,c.relrowsecurity
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname IN ('rag','institutional_rag')
      AND c.relkind IN ('r','p','v','m')
  LOOP
    IF item.relkind IN ('v','m') THEN
      IF item.relkind='v' THEN
        EXECUTE format('ALTER VIEW %I.%I SET (security_invoker=true)',
                       item.schema_name,item.table_name);
      END IF;
      EXECUTE format('GRANT SELECT ON %I.%I TO ugai_runtime',
                     item.schema_name,item.table_name);
    ELSE
      EXECUTE format('GRANT SELECT,INSERT,UPDATE ON %I.%I TO ugai_runtime',
                     item.schema_name,item.table_name);
      IF item.schema_name='rag' AND item.table_name='audit_events' THEN
        EXECUTE format('REVOKE UPDATE ON %I.%I FROM ugai_runtime',
                       item.schema_name,item.table_name);
      END IF;
      IF item.relrowsecurity THEN
        EXECUTE format('DROP POLICY IF EXISTS ugai_backend_runtime ON %I.%I',
                       item.schema_name,item.table_name);
        EXECUTE format(
          'CREATE POLICY ugai_backend_runtime ON %I.%I FOR ALL TO ugai_runtime USING (true) WITH CHECK (true)',
          item.schema_name,item.table_name);
      END IF;
    END IF;
  END LOOP;
END
$secure$;

GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA rag,institutional_rag TO ugai_runtime;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA rag,institutional_rag TO ugai_runtime;
REVOKE ALL ON SCHEMA rag,institutional_rag FROM PUBLIC,anon,authenticated;
