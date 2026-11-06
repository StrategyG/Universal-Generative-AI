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
