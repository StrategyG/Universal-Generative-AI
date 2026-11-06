#!/usr/bin/env python3
"""Fail when a critical production module misses line or branch coverage targets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CRITICAL_FILES = (
    "app/auth.py",
    "app/config.py",
    "app/task_api.py",
    "app/notebook_task_worker.py",
    "app/reasoning/api.py",
    "app/providers/router.py",
    "app/services/postgres_gpu_queue.py",
    "src/ugai_workflow/state_machine.py",
    "src/ugai_workflow/postgres_store.py",
    "src/ugai_workflow/worker.py",
    "src/ugai_workflow/payload_cipher.py",
    "src/ugai_mcp/auth.py",
    "src/ugai_mcp/policy.py",
    "src/ugai_decision/engine.py",
)


def _normalise(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _coverage_percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else 100.0 * covered / total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage_json", nargs="?", default="coverage.json")
    parser.add_argument("--minimum", type=float, default=90.0)
    args = parser.parse_args()

    report_path = Path(args.coverage_json)
    if not report_path.is_file():
        print(f"Coverage report not found: {report_path}", file=sys.stderr)
        return 2

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read coverage report: {exc}", file=sys.stderr)
        return 2

    indexed = {_normalise(path): data for path, data in report.get("files", {}).items()}
    failures: list[str] = []
    print(f"Critical module coverage gate: line >= {args.minimum:.1f}%, branch >= {args.minimum:.1f}%")
    print("| Module | Line coverage | Branch coverage | Result |")
    print("|---|---:|---:|---|")

    for expected_path in CRITICAL_FILES:
        data = indexed.get(expected_path)
        if data is None:
            failures.append(f"{expected_path}: missing from coverage report")
            print(f"| \`{expected_path}\` | n/a | n/a | FAIL (not measured) |")
            continue

        summary = data.get("summary", {})
        line_percent = _coverage_percent(
            int(summary.get("covered_lines", 0)),
            int(summary.get("num_statements", 0)),
        )
        branch_total = int(summary.get("num_branches", 0))
        branch_percent = _coverage_percent(
            int(summary.get("covered_branches", 0)),
            branch_total,
        )
        passed = line_percent >= args.minimum and branch_percent >= args.minimum
        result = "PASS" if passed else "FAIL"
        print(
            f"| \`{expected_path}\` | {line_percent:.1f}% | "
            f"{branch_percent:.1f}% | {result} |"
        )
        if not passed:
            failures.append(
                f"{expected_path}: line={line_percent:.1f}%, "
                f"branch={branch_percent:.1f}%"
            )

    if failures:
        print("\nCoverage gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nAll critical modules meet the line and branch coverage targets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
