-- Narrow release-gate reader for the UGAI Supabase gateway.
-- Apply as a reviewed operator migration; this file does not run automatically.
-- The login password is set separately and must never be committed.

DO $role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ugai_rag_gate_reader') THEN
    CREATE ROLE ugai_rag_gate_reader
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
END
$role$;

ALTER ROLE ugai_rag_gate_reader
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;

GRANT CONNECT ON DATABASE postgres TO ugai_rag_gate_reader;
GRANT USAGE ON SCHEMA institutional_rag TO ugai_rag_gate_reader;

CREATE OR REPLACE FUNCTION institutional_rag.ugai_read_production_release_gate_v1()
RETURNS TABLE (
  decision text,
  technical_passed integer,
  technical_total integer,
  operational_passed integer,
  operational_total integer
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
  SELECT
    gate.decision,
    gate.technical_passed,
    gate.technical_total,
    gate.operational_passed,
    gate.operational_total
  FROM institutional_rag.production_release_decision_v1 AS gate;
$function$;

ALTER FUNCTION institutional_rag.ugai_read_production_release_gate_v1() OWNER TO postgres;

REVOKE ALL ON FUNCTION institutional_rag.ugai_read_production_release_gate_v1() FROM PUBLIC;
REVOKE ALL ON FUNCTION institutional_rag.ugai_read_production_release_gate_v1() FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION institutional_rag.ugai_read_production_release_gate_v1()
  TO ugai_rag_gate_reader;
