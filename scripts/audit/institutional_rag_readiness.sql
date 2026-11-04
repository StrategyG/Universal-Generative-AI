-- UGAI V3.0 Institutional RAG release audit
-- READ-ONLY: SELECT statements only. Run against the intended Supabase project.
-- Snapshot evidence must include project ID, timestamp, and exact output.
-- Never paste secrets, API keys, JWTs, or document contents into an audit artifact.

-- 1) Authoritative release gates. Re-run immediately before every promotion.
SELECT 'production_readiness_v1' AS source, to_jsonb(v) AS result
FROM institutional_rag.production_readiness_v1 AS v;

SELECT 'production_release_decision_v1' AS source, to_jsonb(v) AS result
FROM institutional_rag.production_release_decision_v1 AS v;

-- 2) Raw inventory. Counts are not quality or publication evidence.
SELECT 'rag.documents' AS object_name, count(*) AS row_count FROM rag.documents
UNION ALL
SELECT 'rag.chunks', count(*) FROM rag.chunks
UNION ALL
SELECT 'rag.chunks_with_embedding', count(*) FROM rag.chunks WHERE embedding IS NOT NULL
UNION ALL
SELECT 'institutional_rag.source_documents', count(*) FROM institutional_rag.source_documents
UNION ALL
SELECT 'institutional_rag.document_chunks', count(*) FROM institutional_rag.document_chunks
UNION ALL
SELECT 'institutional_rag.document_chunks_with_embedding', count(*) FROM institutional_rag.document_chunks WHERE embedding IS NOT NULL
UNION ALL
SELECT 'institutional_rag.embedding_jobs', count(*) FROM institutional_rag.embedding_jobs
UNION ALL
SELECT 'institutional_rag.embedding_model_approvals', count(*) FROM institutional_rag.embedding_model_approvals
UNION ALL
SELECT 'institutional_rag.knowledge_candidates', count(*) FROM institutional_rag.knowledge_candidates
UNION ALL
SELECT 'institutional_rag.reviewer_registry', count(*) FROM institutional_rag.reviewer_registry
UNION ALL
SELECT 'institutional_rag.review_votes', count(*) FROM institutional_rag.review_votes
UNION ALL
SELECT 'institutional_rag.evaluation_cases', count(*) FROM institutional_rag.evaluation_cases
UNION ALL
SELECT 'institutional_rag.evaluation_results', count(*) FROM institutional_rag.evaluation_results
UNION ALL
SELECT 'institutional_rag.production_release_evidence', count(*) FROM institutional_rag.production_release_evidence
ORDER BY object_name;

-- 3) Embedding job and knowledge candidate state distributions.
SELECT 'embedding_job_state' AS category, status::text AS state, count(*) AS row_count
FROM institutional_rag.embedding_jobs
GROUP BY status
UNION ALL
SELECT 'knowledge_candidate_review_status', review_status::text, count(*)
FROM institutional_rag.knowledge_candidates
GROUP BY review_status
ORDER BY category, state;

-- 4) RLS, table owners, and direct role privileges.
SELECT
  n.nspname AS schema_name,
  c.relname AS relation_name,
  pg_get_userbyid(c.relowner) AS owner_name,
  c.relrowsecurity AS rls_enabled,
  c.relforcerowsecurity AS force_rls,
  has_schema_privilege('anon', n.oid, 'USAGE') AS anon_schema_usage,
  has_schema_privilege('authenticated', n.oid, 'USAGE') AS authenticated_schema_usage,
  has_table_privilege('anon', c.oid, 'SELECT') AS anon_select,
  has_table_privilege('authenticated', c.oid, 'SELECT') AS authenticated_select,
  has_table_privilege('service_role', c.oid, 'SELECT') AS service_role_select
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname IN ('rag', 'institutional_rag')
  AND c.relkind IN ('r', 'p', 'v', 'm')
ORDER BY n.nspname, c.relname;

-- 5) Explicit RLS policies. An empty result is not itself proof of exposure:
-- combine with schema usage, table grants, ownership, and runtime-role evidence.
SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies
WHERE schemaname IN ('rag', 'institutional_rag')
ORDER BY schemaname, tablename, policyname;

-- 6) Privileged roles. Protect BYPASSRLS and superuser credentials.
SELECT rolname, rolsuper, rolbypassrls, rolcanlogin
FROM pg_roles
WHERE rolname IN ('anon', 'authenticated', 'service_role', 'postgres', 'authenticator')
ORDER BY rolname;

-- 7) SECURITY DEFINER functions in exposed/application schemas.
-- Review function body, fixed search_path, EXECUTE grants, and caller authorization.
SELECT
  n.nspname AS schema_name,
  p.proname AS function_name,
  pg_get_userbyid(p.proowner) AS owner_name,
  p.prosecdef AS security_definer,
  p.proconfig AS function_settings,
  has_function_privilege('anon', p.oid, 'EXECUTE') AS anon_execute,
  has_function_privilege('authenticated', p.oid, 'EXECUTE') AS authenticated_execute,
  has_function_privilege('public', p.oid, 'EXECUTE') AS public_execute,
  pg_get_functiondef(p.oid) AS function_definition
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
WHERE p.prosecdef
  AND n.nspname IN ('public', 'rag', 'institutional_rag')
ORDER BY n.nspname, p.proname;

-- 8) Advisor findings must also be captured through Supabase Dashboard/API.
-- This SQL script does not replace Supabase Security and Performance Advisors.
