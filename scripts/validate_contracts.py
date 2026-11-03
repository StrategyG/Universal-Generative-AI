from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def assert_valid(validator: Draft202012Validator, instance: dict[str, Any], label: str) -> None:
    errors = list(validator.iter_errors(instance))
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise AssertionError(f"{label} should be valid: {messages}")


def assert_invalid(validator: Draft202012Validator, instance: dict[str, Any], label: str) -> None:
    if validator.is_valid(instance):
        raise AssertionError(f"{label} should be rejected by the schema")


def validate_plan_semantics(plan: dict[str, Any]) -> None:
    steps = plan["steps"]
    budgets = plan["budgets"]
    step_ids = [step["step_id"] for step in steps]

    if len(step_ids) != len(set(step_ids)):
        raise ValueError("step_id values must be unique")
    if len(steps) > budgets["max_total_steps"]:
        raise ValueError("plan exceeds max_total_steps")
    if sum(step["kind"] == "retrieve" for step in steps) > budgets["max_retrieval_calls"]:
        raise ValueError("plan exceeds max_retrieval_calls")
    if sum(step["kind"] == "tool" for step in steps) > budgets["max_tool_calls"]:
        raise ValueError("plan exceeds max_tool_calls")

    known_ids = set(step_ids)
    graph: dict[str, list[str]] = {}
    for step in steps:
        dependencies = step["depends_on"]
        if any(dependency not in known_ids for dependency in dependencies):
            raise ValueError(f"step {step['step_id']} has an unknown dependency")
        graph[step["step_id"]] = dependencies

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise ValueError("workflow dependency graph contains a cycle")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in graph[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in step_ids:
        visit(step_id)


def validate_retrieval_plan_semantics(plan: dict[str, Any]) -> None:
    count = len(plan["sub_questions"])
    if count > plan["budgets"]["max_sub_questions"]:
        raise ValueError("retrieval plan exceeds max_sub_questions")


def assert_semantic_valid(fn: Any, instance: dict[str, Any], label: str) -> None:
    try:
        fn(instance)
    except (KeyError, TypeError, ValueError) as exc:
        raise AssertionError(f"{label} should be semantically valid: {exc}") from exc


def assert_semantic_invalid(fn: Any, instance: dict[str, Any], label: str) -> None:
    try:
        fn(instance)
    except (KeyError, TypeError, ValueError):
        return
    raise AssertionError(f"{label} should fail semantic validation")


def validate_semantic_examples(
    plan_schema: dict[str, Any],
    evidence_schema: dict[str, Any],
    retrieval_plan_schema: dict[str, Any],
    claim_schema: dict[str, Any],
) -> None:
    plan_validator = Draft202012Validator(plan_schema)
    base_plan: dict[str, Any] = {
        "schema_version": "1.0",
        "workflow_type": "qa_grounded",
        "goal": "Answer using eligible evidence",
        "risk_class": "low",
        "data_classification": "internal",
        "steps": [{
            "step_id": "retrieve",
            "kind": "retrieve",
            "depends_on": [],
            "timeout_ms": 10000,
            "max_output_bytes": 200000,
            "max_attempts": 1,
            "side_effect": "none"
        }],
        "budgets": {
            "max_total_steps": 1,
            "max_parallel_steps": 1,
            "max_retrieval_calls": 1,
            "max_tool_calls": 0,
            "deadline_ms": 20000
        },
        "policy_version": "policy-test-v1"
    }
    assert_valid(plan_validator, base_plan, "bounded retrieval-only plan")
    assert_semantic_valid(validate_plan_semantics, base_plan, "bounded retrieval-only plan")

    missing_tool_definition = json.loads(json.dumps(base_plan))
    missing_tool_definition["steps"][0]["kind"] = "tool"
    assert_invalid(plan_validator, missing_tool_definition, "tool step without registry reference")

    unconfirmed_destructive_step = json.loads(json.dumps(base_plan))
    unconfirmed_destructive_step["steps"][0]["side_effect"] = "destructive"
    unconfirmed_destructive_step["steps"][0]["requires_confirmation"] = False
    assert_invalid(plan_validator, unconfirmed_destructive_step, "unconfirmed destructive action")

    cyclic_plan = json.loads(json.dumps(base_plan))
    cyclic_plan["steps"] = [
        {"step_id": "step_a", "kind": "analyze", "depends_on": ["step_b"], "timeout_ms": 1000,
         "max_output_bytes": 1000, "max_attempts": 1, "side_effect": "none"},
        {"step_id": "step_b", "kind": "analyze", "depends_on": ["step_a"], "timeout_ms": 1000,
         "max_output_bytes": 1000, "max_attempts": 1, "side_effect": "none"}
    ]
    cyclic_plan["budgets"]["max_total_steps"] = 2
    assert_valid(plan_validator, cyclic_plan, "schema-valid cyclic plan")
    assert_semantic_invalid(validate_plan_semantics, cyclic_plan, "cyclic plan")

    missing_dependency = json.loads(json.dumps(base_plan))
    missing_dependency["steps"][0]["depends_on"] = ["does_not_exist"]
    assert_semantic_invalid(validate_plan_semantics, missing_dependency, "plan with missing dependency")

    over_budget_plan = json.loads(json.dumps(base_plan))
    over_budget_plan["steps"].append({
        "step_id": "retrieve_again", "kind": "retrieve", "depends_on": ["retrieve"],
        "timeout_ms": 10000, "max_output_bytes": 1000, "max_attempts": 1, "side_effect": "none"
    })
    assert_semantic_invalid(validate_plan_semantics, over_budget_plan, "plan exceeding total steps/retrieval budget")

    evidence_validator = Draft202012Validator(evidence_schema)
    staging_record: dict[str, Any] = {
        "evidence_id": "evidence-test-1",
        "corpus_id": "private_research",
        "source_id": "source-test-1",
        "source_title": "Internal research excerpt",
        "source_hash": "a" * 64,
        "locator": {"locator_type": "pdf_page", "page_start": 1, "page_end": 1},
        "excerpt": "A provisional excerpt for schema validation only.",
        "retrieval_method": "keyword",
        "relevance_score": 0.8,
        "evidence_tier": "private_staging",
        "review_status": "pending",
        "publication_state": "unpublished",
        "trusted": False,
        "user_citation_eligible": False,
        "retrieved_at": "2026-11-03T00:00:00Z"
    }
    assert_valid(evidence_validator, staging_record, "private staging evidence")
    unsafe_staging = json.loads(json.dumps(staging_record))
    unsafe_staging["user_citation_eligible"] = True
    assert_invalid(evidence_validator, unsafe_staging, "staging evidence marked citation eligible")

    approved_record = json.loads(json.dumps(staging_record))
    approved_record.update({
        "evidence_id": "evidence-approved-test",
        "corpus_id": "institutional_approved",
        "evidence_tier": "approved",
        "review_status": "approved",
        "publication_state": "published",
        "trusted": True,
        "user_citation_eligible": True
    })
    assert_valid(evidence_validator, approved_record, "approved published evidence")

    private_notebook_record = json.loads(json.dumps(staging_record))
    private_notebook_record.update({
        "evidence_id": "private-notebook-evidence",
        "corpus_id": "private_notebook",
        "evidence_tier": "private_notebook",
        "review_status": "unknown",
        "trusted": False,
        "user_citation_eligible": True
    })
    assert_valid(evidence_validator, private_notebook_record, "request-authorized private notebook evidence")

    retrieval_validator = Draft202012Validator(retrieval_plan_schema)
    retrieval_plan: dict[str, Any] = {
        "schema_version": "1.0",
        "intent": "comparison",
        "needs_rag": True,
        "original_query": "Compare Q1 and Q2 sales",
        "preserve_terms": ["Q1", "Q2", "sales"],
        "sub_questions": [{
            "id": "q1_sales",
            "question": "What were sales in Q1?",
            "corpora": ["institutional_approved", "legacy_rag"],
            "methods": ["keyword", "semantic"],
            "required_evidence_tiers": ["approved", "legacy"],
            "top_k": 8
        }],
        "budgets": {
            "max_sub_questions": 1,
            "max_retrieval_calls": 2,
            "max_refinement_rounds": 1,
            "deadline_ms": 30000
        },
        "required_citations": True
    }
    assert_valid(retrieval_validator, retrieval_plan, "bounded retrieval plan")
    assert_semantic_valid(validate_retrieval_plan_semantics, retrieval_plan, "bounded retrieval plan")

    private_notebook_plan = json.loads(json.dumps(retrieval_plan))
    private_notebook_plan["sub_questions"][0]["corpora"] = ["private_notebook"]
    private_notebook_plan["sub_questions"][0]["required_evidence_tiers"] = ["private_notebook"]
    private_notebook_plan["sub_questions"][0]["filters"] = {"notebook_id": "authorized-notebook-id"}
    assert_valid(retrieval_validator, private_notebook_plan, "private notebook retrieval plan")
    unsafe_retrieval = json.loads(json.dumps(retrieval_plan))
    unsafe_retrieval["sub_questions"][0]["corpora"] = ["private_staging"]
    assert_invalid(retrieval_validator, unsafe_retrieval, "planner attempting to request private staging as standard corpus")
    over_question_budget = json.loads(json.dumps(retrieval_plan))
    over_question_budget["budgets"]["max_sub_questions"] = 0
    assert_semantic_invalid(validate_retrieval_plan_semantics, over_question_budget, "retrieval plan exceeding subquestion budget")

    claim_validator = Draft202012Validator(claim_schema)
    supported_claim: dict[str, Any] = {
        "claim_id": "claim-1",
        "claim_text": "Revenue increased in Q2.",
        "claim_type": "direct_fact",
        "evidence_ids": ["evidence-approved-test"],
        "support_verdict": "supported",
        "confidence_band": "high",
        "assumptions": [],
        "contradictions": []
    }
    assert_valid(claim_validator, supported_claim, "direct fact with evidence reference")
    unsupported_claim = json.loads(json.dumps(supported_claim))
    unsupported_claim["evidence_ids"] = []
    assert_invalid(claim_validator, unsupported_claim, "direct fact without evidence reference")


def main() -> int:
    schema_paths = {
        "plan": CONTRACTS / "plan-spec.schema.json",
        "evidence": CONTRACTS / "evidence-record.schema.json",
        "retrieval_plan": CONTRACTS / "retrieval-plan.schema.json",
        "claim": CONTRACTS / "claim-ledger.schema.json",
    }
    schemas = {name: load_json(path) for name, path in schema_paths.items()}

    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)

    validate_semantic_examples(
        schemas["plan"],
        schemas["evidence"],
        schemas["retrieval_plan"],
        schemas["claim"],
    )

    openapi_path = CONTRACTS / "openapi-v1.yaml"
    with open(openapi_path, "r", encoding="utf-8") as handle:
        openapi_spec = yaml.safe_load(handle)

    if not isinstance(openapi_spec, dict):
        raise ValueError("OpenAPI document must be a YAML mapping")

    validate(openapi_spec)

    print("Contract validation passed:")
    for path in schema_paths.values():
        print(f"- {path.name}: valid JSON Schema draft 2020-12")
    print("- positive and negative planner/evidence/claim examples passed")
    print("- DAG cycle, missing dependency, and budget validation passed")
    print("- openapi-v1.yaml: valid OpenAPI document")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Contract validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
