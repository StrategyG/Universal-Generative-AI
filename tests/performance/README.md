# Performance validation

These profiles exercise the authenticated durable-task submission endpoint. They
must run against an isolated staging environment with a real PostgreSQL-backed
queue and registered worker. Do not run against production without an approved
change window.

## Baseline load profile

Defaults are deliberately explicit and overridable:

- Arrival rate: **50 requests/second**
- Duration: **10 minutes**
- Pre-allocated virtual users: **100**
- Maximum virtual users: **200**
- Accepted response: HTTP 202
- Acceptance ratio: greater than 99%
- HTTP failure ratio: below 1%
- Latency: p95 below 2 seconds; p99 below 5 seconds
- Dropped iterations: zero

Run with k6:

\`\`\`bash
BASE_URL=https://staging.example.test \\
AUTH_TOKEN="$RUSA_STAGING_BEARER_TOKEN" \\
PROJECT_ID=staging-project \\
RPS=50 DURATION=10m \\
k6 run tests/performance/k6/load.js
\`\`\`

## Stress profile

The stress test ramps through 25, 50, 100 and 150 requests/second, holds the
peak, then ramps down. HTTP 429 and 503 are accepted protective responses during
overload. Unexpected 5xx responses must remain zero and p95 latency must remain
below 5 seconds. Record the rejection ratio, peak throughput, latency and
recovery time with every run.

\`\`\`bash
BASE_URL=https://staging.example.test \\
AUTH_TOKEN="$RUSA_STAGING_BEARER_TOKEN" \\
PROJECT_ID=staging-project \\
k6 run tests/performance/k6/stress.js
\`\`\`

## Capacity decision

The 50 RPS / 100 pre-allocated VU profile is an initial engineering baseline,
not a claim about current capacity or a final business SLO. The release owner
must approve the target against expected tenant count, inference capacity,
database pool size, worker count, and GPU budget. API/control-plane and model
inference capacity must be measured separately.

Store each run's k6 summary, candidate SHA, staging image digest, database
topology, worker/GPU topology and environment configuration as release evidence.
Never include bearer tokens, connection strings or other secrets in test output.


## Safety, cost and staging preconditions

The load and stress profiles submit real durable notebook_task records. A
registered Notebook worker may execute model inference for each accepted task.
These are **not** harmless synthetic HTTP pings: an active worker can incur
provider/GPU cost and generate persistent queue, event and result data.

Before running either profile:

1. Use a disposable environment whose /health reports
   environment=staging, queue_backend=postgresql,
   queue_persistent=true and worker_scoped_credentials_enabled=true.
2. Configure a synthetic, deterministic or explicitly cost-capped inference
   route; do not point these profiles at live production model capacity.
3. Approve the request rate, duration, maximum spend and test window.
4. Define cleanup/retention for generated tasks, events, results and telemetry.
5. Use the manual workflow's explicit confirm_nonproduction_load_test input.
   The workflow refuses load/stress runs without it and checks staging health
   before starting k6.

The E2E test performs a separate identity preflight and refuses to submit a task
unless the API reports the expected staging environment and persistent
PostgreSQL-backed queue.
