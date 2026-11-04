#!/usr/bin/env python3
"""Validate Cataran Platform Contracts v1 schemas and golden fixtures."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "v1"
MANIFEST = CONTRACTS / "fixtures" / "manifest.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    manifest = load_json(MANIFEST)
    checked = 0
    errors: list[str] = []
    for entry in manifest["valid"] + manifest["invalid"]:
        schema_path = CONTRACTS / entry["schema"]
        document_path = CONTRACTS / "fixtures" / entry["document"]
        try:
            schema = load_json(schema_path)
            document = load_json(document_path)
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            should_be_valid = entry in manifest["valid"]
            try:
                validator.validate(document)
                is_valid = True
            except ValidationError:
                is_valid = False
            if is_valid != should_be_valid:
                expectation = "valid" if should_be_valid else "invalid"
                errors.append(f"{document_path.relative_to(ROOT)}: expected {expectation} fixture")
            checked += 1
        except Exception as exc:  # validation CLI must report file-specific failures
            errors.append(f"{entry['document']}: {type(exc).__name__}: {exc}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"PASS: {checked} golden fixtures and Draft 2020-12 schemas validated")
    print("NOTE: runtime consumer conformance is not established by schema validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
