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


def main() -> int:
    plan_schema = load_json(CONTRACTS / "plan-spec.schema.json")
    evidence_schema = load_json(CONTRACTS / "evidence-record.schema.json")

    Draft202012Validator.check_schema(plan_schema)
    Draft202012Validator.check_schema(evidence_schema)

    openapi_path = CONTRACTS / "openapi-v1.yaml"
    with openapi_path.open("r", encoding="utf-8") as handle:
        openapi_spec = yaml.safe_load(handle)

    if not isinstance(openapi_spec, dict):
        raise ValueError("OpenAPI document must be a YAML mapping")

    validate(openapi_spec)

    print("Contract validation passed:")
    print("- plan-spec.schema.json: valid JSON Schema draft 2020-12")
    print("- evidence-record.schema.json: valid JSON Schema draft 2020-12")
    print("- openapi-v1.yaml: valid OpenAPI document")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Contract validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
