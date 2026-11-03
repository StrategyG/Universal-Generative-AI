# Workflow and Agent Control Specification

**Status:** target design. No agent runtime is deployed yet.

## 1. Workflow types

| Workflow | Retrieval requirement | Tools | Completion condition |
|---|---|---|---|
| qa_grounded | Approved evidence required by task policy | None or calculator | Claims validated and citations resolved |
| compare_sources | At least two eligible sources where comparison requires it | Calculator, table builder | Similarities, differences, dates, and conflicts represented |
| deep_research | Approved evidence first; private research tier isolated | Search connector, document tools | Evidence gaps and evidence tiers reported |
| document_ingestion | No answer retrieval | Parsers, OCR only when necessary, embedding worker | Source hash, page map, chunks and embedding checks pass |
| multimodal_generation | Optional context retrieval | Image/audio/video/3D provider | Artifact validation and job completion |
| decision_analysis | Evidence plus explicit assumptions | Calculator, scenario tool | Alternatives, risks, assumptions, recommendation separated |

## 2. Workflow state machine

Allowed states:
- RECEIVED
- AUTHENTICATED
- AUTHORIZED
- CLASSIFIED
- PLANNED
- PLAN_VALIDATED
- RUNNING
- WAITING_FOR_RETRIEVAL
- WAITING_FOR_TOOL
- WAITING_FOR_HUMAN
- VERIFYING
- COMPLETED
- COMPLETED_WITH_WARNINGS
- NEEDS_INPUT
- CANCELLED
- FAILED
- EXPIRED

Terminal states: COMPLETED, COMPLETED_WITH_WARNINGS, NEEDS_INPUT, CANCELLED, FAILED, EXPIRED.

Every transition is server-initiated and recorded with timestamp, actor/service, prior state, new state, reason code, and trace ID. Invalid transitions fail closed.

Main path:
RECEIVED → AUTHENTICATED → AUTHORIZED → CLASSIFIED → PLANNED → PLAN_VALIDATED → RUNNING → VERIFYING → COMPLETED

Branches:
- Missing required data → NEEDS_INPUT.
- Protected side effect requiring approval → WAITING_FOR_HUMAN.
- User cancellation → CANCELLED.
- Budget or deadline exhausted → FAILED with BUDGET_EXCEEDED or DEADLINE_EXCEEDED.
- Evidence absent → COMPLETED_WITH_WARNINGS or NEEDS_INPUT according to task policy; never silently invent evidence.

## 3. Plan schema semantics

Each step contains:
- step_id: unique within workflow;
- kind: classify, retrieve, rerank, analyze, calculate, tool, verify, compose;
- depends_on: step IDs forming a directed acyclic graph;
- input_refs: references to previous step outputs, not arbitrary SQL or code;
- tool_name and validated tool_args only for tool steps;
- timeout_ms, max_output_bytes, max_attempts;
- required_evidence_tiers;
- risk_class;
- side_effect: none, reversible, external, destructive;
- requires_confirmation.

Validator requirements:
1. No unknown fields.
2. Unique step IDs and no cycles.
3. Every dependency exists.
4. Every tool exists in the server registry.
5. Arguments validate against that tool version's schema.
6. Step count and aggregate budgets remain within policy.
7. No planner-proposed policy override, arbitrary URL, credential, SQL, shell, or code execution.
8. Policy forces confirmation for protected side effects regardless of planner value.

## 4. Default bounded budgets (initial proposal)

These are configurable guardrails, not measured production SLOs.

| Control | Interactive default | Deep research default |
|---|---:|---:|
| Planner revisions | 1 | 2 |
| DAG steps | 8 | 20 |
| Parallel steps | 3 | 5 |
| Retrieval calls | 3 | 8 |
| Tool calls | 3 | 12 |
| Attempts per step | 2 | 3 |
| Workflow wall time | 45 s | 180 s |
| Retrieved excerpt budget | 12,000 tokens | 40,000 tokens |
| Total model context | Per-model policy | Per-model policy |
| Cost cap | Tenant-configured | Tenant-configured |

Enforce per-step and aggregate limits. A local timeout does not prove a provider-side job stopped; retain provider request IDs and invoke cancellation where supported.

## 5. Agent responsibilities and forbidden actions

### Planner
May decompose a task and choose registered workflow templates. Cannot execute tools, approve evidence, or alter tenant policy.

### Retriever
May call only allowed corpus APIs and strategies. Cannot raise evidence tier or read staging data unless workflow scope explicitly allows it.

### Research analyst
May compare retrieved evidence and propose hypotheses. Must mark inference and contradictory evidence.

### Domain analyst
May apply political, business, technical, scientific, or operational frameworks. Must identify temporal validity, actor incentives, causal uncertainty, source limitations, and assumptions.

### Verifier
Checks claim-to-evidence support, citation integrity, contradiction handling, freshness, and arithmetic consistency. Cannot manufacture sources.

### Composer
Produces user-facing output from verified claim objects and explicit inference/assumption objects. Cannot cite IDs absent from the verified evidence ledger.

## 6. Evidence ledger and claim ledger

Every proposed factual claim is represented internally with:
claim_id, claim_text, claim_type, evidence_ids, support_verdict, confidence_band, time_scope, assumptions, contradictions, verifier_version.

Claim types:
- direct_fact
- derived_calculation
- interpretation
- forecast
- recommendation
- unknown_or_unverified

Rules:
- direct_fact requires direct source support.
- derived_calculation requires auditable inputs and formula.
- interpretation requires supporting evidence and must be labelled interpretation.
- forecast requires scenario assumptions and uncertainty.
- recommendation must show objective, trade-offs, and constraints.
- unknown_or_unverified cannot be presented as established fact.

## 7. Human-in-the-loop policy

Require human confirmation for:
- external publication or sending;
- purchases, financial transactions, account changes;
- destructive data mutation or schema changes;
- promotion of staged evidence/knowledge;
- privilege or reviewer registry changes;
- high-impact decisions with irreversible side effects.

A model's textual claim that approval was given is not approval. Approval must be a separate authenticated user action linked to an immutable action preview.

## 8. Failure and retry model

Retry only transient failures: network timeout, provider 429 (respect Retry-After), and selected 5xx responses. Use exponential backoff with jitter and a strict workflow deadline.

Do not retry:
- invalid schema or unsupported tool arguments;
- 401/403;
- evidence policy rejection;
- budget exhaustion;
- human rejection;
- deterministic data-integrity errors.

Use circuit breakers per provider and retrieval backend. Maintain separate concurrency pools for interactive chat and background jobs.

## 9. Streaming events

SSE event types:
- workflow.accepted
- workflow.classified
- plan.validated
- retrieval.started
- retrieval.completed
- tool.started
- tool.completed
- response.delta
- citation.verified
- workflow.completed
- workflow.warning
- workflow.failed

Each event carries request_id, workflow_id, sequence, timestamp, and versioned payload. Do not stream internal chain-of-thought, hidden prompts, credentials, or unrestricted private evidence.

## 10. Cancellation and resumability

- Persist workflow/step status before starting external side effects.
- Use idempotency keys for tools that support them.
- Cancellation stops scheduling new steps and signals cancellable providers/tools.
- Resume only from persisted state whose step inputs and policy version remain valid.
- On resume, re-check authorization and policy; do not reuse expired signed URLs or credentials.
