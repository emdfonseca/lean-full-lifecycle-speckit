#!/usr/bin/env python3
"""Validate the acceptance registry and optionally enforce the P12 exit gate."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jsonschema  # noqa: E402

from lib.inventory import ROOT, load_yaml  # noqa: E402
from validate_requirements import Result, _fn_key, collect_tests  # noqa: E402

REGISTRY = ROOT / "tooling" / "acceptance-scenarios.yml"
SCHEMA = ROOT / "tooling" / "schemas" / "acceptance-scenarios.schema.json"


def collect_pytest_evidence() -> tuple[set[str], set[str]]:
    """Return all collected nodes and function keys marked as wording-only."""
    _, nodes = collect_tests()
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-m", "wording",
         "-p", "no:cacheprovider", "--quiet", "--no-header"],
        cwd=ROOT, text=True, capture_output=True,
    )
    if run.returncode not in {0, 5}:
        raise RuntimeError(f"pytest wording collection failed: {run.stderr.strip()}")
    wording = {_fn_key(line.strip()) for line in run.stdout.splitlines() if "::" in line}
    return nodes, wording


def validate_registry(
    path: Path = REGISTRY,
    *,
    phase: str | None = None,
    collected: tuple[set[str], set[str]] | None = None,
) -> tuple[Result, dict]:
    result = Result()
    data = load_yaml(path)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema_errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(data),
        key=lambda error: list(error.absolute_path),
    )
    for error in schema_errors:
        location = ".".join(str(part) for part in error.absolute_path) or "registry"
        result.error(f"schema {location}: {error.message}")
    if schema_errors:
        return result, data

    if collected is None:
        collected = collect_pytest_evidence()
    nodes, wording = collected
    known_functions = {_fn_key(node) for node in nodes}
    seen_ids: set[str] = set()
    seen_names: set[tuple[str, str]] = set()

    for scenario in data["scenarios"]:
        scenario_id = scenario["id"]
        identity = (scenario["group"], scenario["name"])
        if scenario_id in seen_ids:
            result.error(f"{scenario_id}: duplicate id")
        if identity in seen_names:
            result.error(f"{scenario_id}: duplicate scenario {identity[0]}/{identity[1]}")
        seen_ids.add(scenario_id)
        seen_names.add(identity)

        scenario_phase = scenario["phase"]
        status = scenario.get("status")
        verified_by = scenario.get("verified_by", [])
        if scenario_phase == "p12" and status in {"covered", "partial"}:
            for node in verified_by:
                function = _fn_key(node)
                if node not in nodes and function not in known_functions:
                    result.error(f"{scenario_id}: verified_by {node!r} is not a collected test")
                elif function in wording:
                    result.error(
                        f"{scenario_id}: verified_by {node!r} is wording-marked, "
                        "not behavioral evidence"
                    )
        if scenario_phase == "p12" and status == "absent" and verified_by:
            result.error(f"{scenario_id}: absent scenarios cannot have verified_by")
        if scenario_phase == "p13" and (status is not None or verified_by):
            result.error(f"{scenario_id}: P13 scenarios cannot have test status or evidence")
        if scenario_phase == "blocked":
            if not scenario.get("missing") or scenario.get("tracked_by", 0) <= 0:
                result.error(
                    f"{scenario_id}: blocked scenarios require missing and positive tracked_by"
                )

        if (phase == "p12" and scenario_phase == "p12"
                and scenario["priority"] == "must" and status != "covered"):
            result.error(
                f"{scenario_id}: must P12 scenario {scenario['name']!r} is {status!r}, not covered"
            )

    return result, data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["p12"], help="Enforce the named exit gate.")
    args = parser.parse_args()

    try:
        result, data = validate_registry(phase=args.phase)
    except RuntimeError as exc:
        print(f"ERROR   {exc}")
        return 1

    for warning in result.warnings:
        print(f"WARNING {warning}")
    for error in result.errors:
        print(f"ERROR   {error}")
    if result.errors:
        print(f"\n{len(result.errors)} acceptance registry errors")
        return 1
    print(f"\n{len(data['scenarios'])} acceptance scenarios, registry consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
