# Repeatable Institutional RAG Readiness Audit

Run `institutional_rag_readiness.sql` as a read-only audit against the intended Supabase project.

## Procedure

1. Confirm the project ID and environment before execution.
2. Use a read-only database role where available. Do not use a production service key in a client, notebook, or shared terminal.
3. Execute the SQL sections without modifying them. The script contains SELECT statements only.
4. Capture the result of both production readiness views, the inventory, state distributions, RLS/grants, role flags, and SECURITY DEFINER functions.
5. Separately capture Supabase Security and Performance Advisor results.
6. Record timestamp, project ID, SQL file commit SHA, operator, and reviewer.
7. Compare results against the acceptance gates in `docs/roadmap/UGAI-V3-P0-EXECUTION-AND-ACCEPTANCE.md`.

## Interpretation safeguards

- Raw document/chunk counts do not establish data quality or publication.
- RLS enabled with no policy is not automatically public exposure; verify schema usage, grants, ownership, BYPASSRLS, function grants, API exposure, and actual runtime roles.
- A service-role key bypasses RLS and must remain server-side and tightly scoped.
- A function with gateway JWT verification disabled may implement its own authentication; inspect the handler and verify tenant authorization, rate limits, secret rotation, and logging redaction.
- Never create fake approvals, reviewers, evaluation records, or published evidence to satisfy gates.
- Never weaken a readiness view simply to obtain a passing result.
- This audit is read-only and does not authorize migrations, data backfills, policy changes, secret changes, or cutover.

## Evidence record

For every run, retain:
- project ID and timestamp;
- repository commit SHA containing this audit;
- readiness and release decision view output;
- inventory and status counts;
- RLS/grant/role/function output;
- Supabase Security and Performance Advisor output;
- reviewer sign-off and blockers.
