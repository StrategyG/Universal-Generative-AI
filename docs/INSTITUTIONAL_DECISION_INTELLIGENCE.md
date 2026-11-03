# UGAI Institutional Decision Intelligence

Status: AEPH/Hedge-Bet decision engine and a framework-neutral, multi-source
orchestration runtime are implemented on feature/decision-orchestration-runtime-v1.
This package is not yet attached to a deployed UGAI agent registry and has no
production audit, approval, OAuth or action-execution service configured.

## Purpose

The decision layer composes Analysis, Evaluation and Holistic Thinking (AEPH)
with an advisory Hedge-Bet portfolio discipline. Its runtime accepts evidence
from multiple authenticated MCP providers, APIs, approved RAG corpora and
human-provided records through a common source contract.

The decision engine is deterministic and side-effect free. The orchestration
runtime coordinates injected interfaces; production services must implement
those interfaces. No service credentials or production endpoint are embedded.

## Architecture

1. **MCP and evidence intake** — operator-configured source adapters query only
   approved tools and normalize results into typed evidence records.
2. **Provenance and independence** — records preserve source ID, primary-source
   independence group, topic, position, quality dimensions and stable locator.
3. **Analysis** — evidence is grouped by origin; derivative sources do not count
   as independent corroboration; conflicting positions are surfaced.
4. **Evaluation** — alternatives are scored using evidence coverage, expected
   value for bets, strategic fit, cost, downside and reversibility.
5. **Holistic review** — system dependencies, stakeholder impacts, short/medium/
   long time horizons, assumptions and second-order effects are surfaced.
6. **Hedge-Bet allocation** — one evidence-supported hedge may be selected; bet
   allocations are score-weighted, capped per option and constrained by a gross
   downside risk budget. Unallocated capacity remains in reserve.
7. **Governance** — a decision snapshot and evidence manifest are sent to an
   approval gateway. Execution is a separate step requiring a verified,
   unexpired, actor- and plan-scoped approval receipt.

## Evidence scoring

A single evidence record receives this heuristic quality score:

| Dimension | Weight |
|---|---:|
| Source reliability | 25% |
| Evidence quality | 25% |
| Relevance | 20% |
| Freshness | 15% |
| Verified status | 15% |

For aggregation, only the strongest evidence record in each independence group
contributes to the mean. The evidence sufficiency score is the mean quality score
multiplied by min(1, independent_source_count / 3). This rewards independent
triangulation rather than MCP response count. It is a transparent engineering
heuristic, not a calibrated probability or a guarantee that three sources prove
a claim.

Conflicts are reported when independent groups present different positions for
the same topic. Conflicts force REVIEW_REQUIRED; they are not resolved by
majority vote in the decision engine.

## Hedge-Bet model

- Hedge options prioritize explicit risk mitigation, strategic fit,
  reversibility, success likelihood and cost.
- Bet options use success-weighted upside minus failure downside, modified by
  strategic fit, reversibility, cost and configured risk tolerance.
- At most one hedge is selected by deterministic score ordering.
- Bet allocations are pro-rata by score, with a hard per-option cap.
- Gross bet downside is constrained by risk_budget before any hypothetical
  hedge benefit is credited. A speculative hedge estimate cannot justify extra
  risky exposure.
- Reserve is the unallocated remainder. When evidence is insufficient, reserve
  is 100% and the status is HOLD_FOR_EVIDENCE.
- A missing hedge, missing viable bet or unresolved conflict is made explicit as
  REVIEW_REQUIRED.

The input option estimates (probability, upside, downside, cost, mitigation)
must be derived and reviewed by upstream domain-specific analysis. The decision
engine does not estimate those values itself.

## Multi-MCP orchestration runtime

The package exports:

- `MCPToolEvidenceSource` and `MCPToolQuery`: an adapter that uses an injected
  provider's `discover()` and `execute()` methods. Tool names and argument
  builders are operator-owned configuration; the model does not choose tools.
  The source is bound to one trusted actor ID and rejects actor mismatch.
- `DecisionWorkflow`: concurrently collects required sources with bounded
  concurrency and timeout, rejects partial collection by default, rejects
  duplicate evidence IDs and wrong source attribution, evaluates the decision,
  generates a canonical plan through trusted application code, and requests
  human approval.
- `DecisionAuditSink`: a mandatory durable audit interface. Failure to write
  the initial event blocks evidence collection. Later audit failures fail the
  workflow closed and expose whether a remote action may already have completed.
- `ApprovalGateway`: must persist the decision snapshot, evidence manifest,
  evidence digest, source IDs, exact plan digest and idempotency key.
- `ApprovalVerifier`: must verify the human identity, decision ID, exact plan
  digest, scope and expiry, and return a trusted ApprovalReceipt.
- `ExecutionPort`: an injected action adapter that must independently enforce
  authorization and idempotency.

The human approval request receives a compact evidence manifest containing the
evidence ID, topic, claim position, source ID, primary-source independence
group, quality dimensions, verification flag and stable provenance locator.
Raw document contents and credentials are not copied into the manifest. The
manifest is hashed and its digest is recorded in audit.

Execution is possible only when the decision status is RECOMMENDATION_READY,
the actor matches the authenticated decision actor, the plan digest is
unchanged, and the approval verifier returns a matching, unexpired receipt.
Unknown execution outcomes must be reconciled with the same idempotency key;
callers must not retry blindly.

## Output and control semantics

- HOLD_FOR_EVIDENCE: insufficient independent evidence; no option allocation;
  reserve remains 100%.
- REVIEW_REQUIRED: a conflict, missing hedge or missing viable bet needs
  explicit human judgment; no executable plan is generated.
- RECOMMENDATION_READY: the engine produced a bounded advisory portfolio and
  the trusted plan builder may create a proposed execution plan. This is not
  authorization to execute.
- human_approval_required is always true.
- confidence_type identifies the score as a non-probabilistic
  evidence-sufficiency heuristic.
- Evidence manifests and decision snapshots are suitable for durable approval
  and audit storage when implemented with organization-specific access control.

## Usage boundaries

A workflow caller must obtain actor_id from trusted UGAI authentication context,
not model arguments. For IM19, construct IM19ToolProvider for the same actor,
open its asynchronous session, then provide it to MCPToolEvidenceSource.
Each query must name an operator-approved tool and use a trusted argument
builder. The extractor is application-owned code and must identify the true
primary source rather than treating every MCP response as independent.

Do not pass raw credentials, access tokens, secrets or untrusted executable
content into this package. Source text is evidence data and must never be
interpreted as a system instruction.

## Validation evidence

The orchestration runtime, approval evidence manifest and tests were
validated on exact code/test commit
`ea8f594c0bf7e434622fa2baac593cc4d6df99d1` in GitHub Actions run
[41689797041](https://github.com/StrategyG/Universal-Generative-AI/actions/runs/41689797041):
Ruff reported `All checks passed!` and the full suite reported
`59 passed in 0.18s`. Later commits only update documentation. CI verifies
package installation, lint and mocked unit tests, not live connector,
production approval or execution services.

## Limitations and production gates

The package does not provide statistical calibration, causal identification,
scenario simulation, legal/financial advice, live MCP connectivity, durable
audit storage, a production approval service or a production executor.
Production acceptance still requires:
- independent benchmark cases and domain expert review;
- calibration testing against observed historical outcomes;
- adversarial testing for duplicate/correlated sources and misleading evidence;
- tenant isolation and provenance validation in the host workflow;
- policy-versioned durable audit, approval records and signed receipt verification;
- live tests against each deployed MCP provider, OAuth audience and scope;
- a sandboxed, least-privilege, idempotent execution adapter with reconciliation;
- risk-budget and allocation thresholds approved for the specific domain.

Numeric defaults are starting policy parameters, not universal institutional
standards. They must be approved and versioned by the organization using them.
