# Testing strategy and production quality gates

This strategy is intentionally broader than unit testing. A green unit-test job
is necessary but never sufficient for production approval.

## Required test layers

| Layer | Required evidence | Release acceptance |
|---|---|---|
| Unit | Isolated business logic, validators, state machines, provider adapters and error paths | All critical modules meet line and branch coverage thresholds |
| Integration | PostgreSQL 16, migrations, RLS, worker/API roles, queue leases, retries and provider contracts | All required integrations pass against real disposable services |
| API | Positive, validation, authentication, authorization and error responses for each operation | Every OpenAPI operation has a maintained test case; no undocumented sensitive route |
| Security | Authentication negatives, tenant isolation, SQL injection, secret redaction, SAST and dependency audit | No unmitigated Critical/High issue |
| Load | Authenticated task submission at the approved baseline | Acceptance, latency, error and dropped-iteration thresholds pass |
| Stress | Ramp beyond baseline and observe protective controls | Controlled 429/503 responses; no uncontrolled 5xx or cascading failure |
| Regression | Complete suite on the release candidate | No existing behavior regresses |
| E2E | Real user token → API → PostgreSQL → worker/agent → persisted result | A real task reaches a verified result on staging |

## Coverage policy

pytest-cov collects line and branch data for app, ugai_decision,
ugai_mcp, ugai_replication and ugai_workflow.

scripts/check_critical_coverage.py enforces **at least 90% line coverage and
at least 90% branch coverage for each listed critical module**. A missing module
in the coverage report is a failure. The gate is not an aggregate average:
strong coverage in one module cannot hide a weak critical module.

Coverage is only a floor. Assertions must check meaningful outputs, state
transitions, authorization outcomes, persistence effects and failure behavior.
Tests that merely execute a line without checking its result do not establish
correctness. Tests must not be deleted, weakened or skipped to manufacture a
green report.

## Local CI-equivalent commands

```bash
python -m pip install -e ".[dev,mcp,postgres,worker]"
ruff check app src tests scripts
bandit -q -r app src -ll -x tests
pytest -q -m "not e2e" \\
  --cov=app \\
  --cov=ugai_decision \\
  --cov=ugai_mcp \\
  --cov=ugai_replication \\
  --cov=ugai_workflow \\
  --cov-branch \\
  --cov-report=term-missing \\
  --cov-report=json:coverage.json
python scripts/check_critical_coverage.py coverage.json
```

The PostgreSQL integration tests require a disposable PostgreSQL 16 database
through TEST_DATABASE_URL. They must not be pointed at a production database.

## Staging-only validation

The manual GitHub Actions workflow named Staging E2E and Performance Validation
supports three suites:

- e2e: real user-to-agent lifecycle; requires the staging URL, bearer token
  and project ID as GitHub Actions secrets.
- load: default 50 requests/second for 10 minutes, 100 pre-allocated VUs,
  p95 below 2 seconds, p99 below 5 seconds, less than 1% failed requests and
  zero dropped iterations.
- stress: controlled ramp from 25 to 150 requests/second; 429/503 are
  acceptable protective responses, unexpected 5xx must remain zero.

These are initial API/control-plane baselines. The release owner must approve
final targets based on actual tenant concurrency, worker count, database pool
capacity, model-provider limits and GPU capacity. Inference throughput and
latency require a separate model/GPU benchmark.

## Evidence and release decision

Every release candidate must retain:

1. Exact commit SHA and build/image digest.
2. Test and coverage reports.
3. PostgreSQL integration logs and migration revision.
4. Security scanner output and approved vulnerability exceptions.
5. k6 summary, topology and target capacity.
6. E2E task ID, correlation ID and result digest (never bearer tokens).
7. Human approval bound to the exact artifact and deployment target.

A suite that has not run is NOT RUN, not PASS. Staging-only suites are not
considered passed merely because the workflow exists. Any mandatory gate that
is FAIL, NOT RUN, BLOCKED or NOT VERIFIED keeps the release **NO-GO**.
