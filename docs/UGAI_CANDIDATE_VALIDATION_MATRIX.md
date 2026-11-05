# UGAI Candidate Validation Matrix

**Candidate:** `validation/ugai-intelligence-candidate-v4`  
**Scope:** reasoning contracts, route catalog, exact-provider runtime, decision workflow, IM19 client, durable PostgreSQL workflow and replication contracts.

## CI commands

Run from repository root on the exact candidate SHA:

```bash
python -m pip install -e ".[dev,mcp,postgres,worker]"
ruff check app src tests
pytest -q
pytest -q tests/integration/test_postgres_workflow.py
```

The PostgreSQL integration workflow provisions a disposable PostgreSQL 16 service. It is not a production database test.

## Required coverage

| Area | Test module / evidence | Acceptance |
|---|---|---|
| Reasoning artifact schema | `tests/test_reasoning_schemas.py` | Strict schema, unique identifiers, valid evidence/claim links, calibration provenance |
| Model routing policy | `tests/test_reasoning_routing.py` | Approval, region, capability, quality, total cost and evaluator independence |
| Route catalog | `tests/test_reasoning_catalog.py` | Strict operator metadata, no self-granted approval, exact approved registry record |
| Exact-provider execution | `tests/test_text_model_router.py` | Exact selected provider, immutable model revision, no silent fallback |
| Reasoning execution service | `tests/test_reasoning_execution.py` | Primary, explicit fallback, independent evaluation, fail-closed review |
| Authenticated reasoning API | `tests/test_reasoning_api.py` | Verified principal, project scope, server-owned risk tier, mandatory review |
| AEPH / decision workflow | `tests/test_decision_workflow.py` | Stable idempotency, evidence failures, cancellation and approval boundaries |
| Durable task workflow | `tests/test_workflow_state_machine.py`, `tests/test_postgres_store_contract.py` | State transitions, lease fencing, retry limits and tenant scope |
| PostgreSQL integration | `tests/integration/test_postgres_workflow.py` | Real disposable database integration |
| Replication contracts | `tests/test_replication_contracts.py` | Monotonic sequencing, payload hash, duplicate/fencing rules |
| Supply chain | `.github/workflows/supply-chain-security.yml` | Dependency audit on pinned candidate |

## Non-CI release gates

Passing the above commands does not prove:
- The operator route metadata is current or commercially accurate.
- Provider APIs are reachable with production credentials.
- Live identity/secret injection, IM19 MCP, RAG_Cerdas, Notebook Studio or Cloudbrowser are integrated.
- RAG evidence is authorized, current, relevant or independently sourced.
- The full staged reasoning pipeline or calibration benchmark is complete.
- Production database migration, backup/restore, load, observability, rollback or deployment has passed.

These require separately captured staging or production evidence and human release approval. The candidate remains Draft and NO-GO for production until all release gates pass.
