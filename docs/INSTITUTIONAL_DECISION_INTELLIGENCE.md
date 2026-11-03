# UGAI Institutional Decision Intelligence

Status: implemented as a deterministic, framework-neutral decision package on
feature/aeph-hedge-bet-v1. It is not yet wired to a deployed agent/workflow
registry and does not execute actions.

## Purpose

The decision layer composes Analysis, Evaluation and Holistic Thinking (AEPH)
with an advisory Hedge-Bet portfolio discipline. It provides a repeatable,
explainable contract for agent workflows consuming evidence from multiple MCP
servers, APIs, approved RAG corpora and human-provided records.

The engine is deliberately deterministic and side-effect free. It does not call
MCP tools, generate evidence, infer source trust from a hostname, transfer money,
allocate production resources, or execute recommendations.

## Architecture

1. Multi-source evidence intake — host workflows collect data through approved
   MCP providers and supply typed evidence records.
2. Provenance and independence — every record carries source ID, independence
   group, topic, position and quality dimensions.
3. Analysis — evidence is grouped by origin; derivative sources do not count as
   independent corroboration; conflicting positions are surfaced.
4. Evaluation — alternatives are scored using evidence coverage, expected value
   for bets, strategic fit, cost, downside and reversibility.
5. Holistic review — system dependencies, stakeholder impacts, short/long time
   horizons, assumptions and second-order effects are explicitly surfaced.
6. Hedge-Bet allocation — one evidence-supported hedge may be selected; bet
   allocations are score-weighted, capped per option, and constrained by a gross
   downside risk budget. Unallocated capacity remains in reserve.
7. Governance — every result requires human approval. The package is advisory
   and has no executor or privileged tool interface.

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
multiplied by min(1, independent_source_count / 3). This intentionally rewards
independent triangulation rather than MCP response count. It is a transparent
engineering heuristic, not a calibrated probability or a claim that three
sources guarantee truth.

Conflicts are reported when independent groups present different positions for
the same topic. Conflicts force REVIEW_REQUIRED; they are never resolved by
majority vote in this engine.

## Hedge-Bet model

- Hedge options prioritize explicit risk mitigation, strategic fit,
  reversibility, success likelihood and cost.
- Bet options use success-weighted upside minus failure downside, modified by
  strategic fit, reversibility, cost and configured risk tolerance.
- At most one hedge is selected by deterministic score ordering.
- Bet allocations are pro-rata by score, with a hard per-option cap.
- Gross bet downside is constrained by risk_budget before any hypothetical
  hedge benefit is credited. This prevents a speculative hedge estimate from
  justifying extra risky exposure.
- Reserve is the unallocated remainder. When evidence is insufficient, reserve
  is 100% and the status is HOLD_FOR_EVIDENCE.
- A missing hedge, missing viable bet, or unresolved conflict is made explicit
  as REVIEW_REQUIRED.

The input option estimates (probability, upside, downside, cost, mitigation)
must be derived and reviewed by upstream domain-specific analysis. They are not
measured by the decision engine itself.

## Package usage

The package is importable as ugai_decision and exports DecisionEngine,
DecisionRequest, EvidenceItem and StrategicOption. A caller constructs validated
evidence and alternatives, then calls DecisionEngine().evaluate(request). The
result exposes allocations, reserve, downside metrics, evidence sufficiency,
conflicts, holistic review and a JSON-safe to_dict() representation.

DecisionRequest supports:
- system_factors: dependencies and systemic context;
- stakeholder_impacts: positive and negative stakeholder consequences;
- time_horizons: short, medium and long-term considerations;
- assumptions: explicit unverified inputs;
- risk_tolerance: defensive, balanced or opportunity_seeking;
- evidence_threshold, reserve_floor, hedge_target, max_bet_allocation and
  risk_budget: versioned policy parameters.

All numeric scores must be finite values between 0 and 1. Evidence references
must point to records included in the request. IDs must be unique.

## Output and control semantics

- HOLD_FOR_EVIDENCE: insufficient independent evidence; no option allocation;
  reserve remains 100%.
- REVIEW_REQUIRED: a conflict, missing hedge or missing viable bet needs
  explicit human judgment.
- RECOMMENDATION_READY: the engine produced a bounded advisory portfolio. This
  status is not authorization to execute.
- human_approval_required is always true.
- confidence_type identifies the score as a non-probabilistic
  evidence-sufficiency heuristic.
- to_dict() produces a JSON-safe structure suitable for workflow/API output and
  audit envelopes.

## Integration contract

The future UGAI workflow runtime should:
1. Obtain MCP evidence only through an authenticated provider and approved tool
   policy; preserve original source and document locator.
2. Assign a stable independence_group based on the underlying primary source,
   not the MCP server that returned a copy.
3. Validate timestamps, source ownership, tenant scope, citations and document
   integrity before constructing EvidenceItem values.
4. Populate option evidence references from traceable source records.
5. Persist the input evidence manifest, policy version, result and human
   approval in a durable append-only audit service.
6. Require a separate authorization and execution workflow after approval.
7. Re-evaluate when new evidence arrives; preserve prior result versions rather
   than silently overwriting a decision.

Do not pass raw credentials, access tokens, secrets, or untrusted executable
content into this package. A source's claim text is evidence data and must never
be interpreted as a system instruction.

## Limitations and production gates

This package does not provide statistical calibration, causal identification,
scenario simulation, legal/financial advice, live MCP connectivity, model-agent
consensus, durable audit storage or execution. Production acceptance still
requires:
- independent benchmark cases and domain expert review;
- calibration testing against observed historical outcomes;
- adversarial testing for duplicate/correlated sources and misleading evidence;
- tenant isolation and provenance validation in the host workflow;
- policy-versioned durable audit and approval records;
- integration tests through the actual UGAI runtime and approved MCP adapters;
- risk-budget and allocation thresholds approved for the specific domain.

Numeric defaults are starting policy parameters, not universal institutional
standards. They must be approved and versioned by the organization using them.
