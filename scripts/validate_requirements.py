#!/usr/bin/env python3
"""Validate the requirement catalogue and its traceability, in both directions.

A catalogue that can drift from the test suite is documentation wearing a
schema. The property worth enforcing is reciprocity:

    a requirement naming a test that does not claim it        -> error
    a test claiming a requirement the catalogue does not name -> error

Neither side can be edited alone, so the catalogue cannot quietly rot away from
what is actually verified.

Component references resolve against real things: the component inventory, the
policy directory, the check registry, and files on disk. `verified_by` entries
resolve against pytest's own collection, so a renamed or deleted test fails
here rather than silently ceasing to verify anything.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from lib.inventory import ROOT, load_inventory, load_yaml  # noqa: E402

CATALOGUE = ROOT / "tooling" / "requirements" / "requirements.yml"
SCHEMA = ROOT / "tooling" / "schemas" / "requirements.schema.json"

# status -> whether verified_by is required
NEEDS_TESTS = {"implemented", "verified"}


class Result:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _fn_key(node_id: str) -> str:
    """Reduce a node id to its function: strip the parametrisation suffix.

    A marker sits on the function, so it necessarily covers every
    parametrisation of it. Comparing at function granularity is the honest
    reading of what the marker asserts; comparing at node granularity would
    demand a marker per parameter that the decorator cannot express.
    """
    path, _, rest = node_id.partition("::")
    return f"{path}::{rest.split('[', 1)[0]}"


def collect_tests() -> tuple[dict[str, set[str]], set[str]]:
    """Return (requirement id -> claiming function keys, all collected node ids)."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider",
         "--quiet", "--no-header"],
        cwd=ROOT, text=True, capture_output=True,
    )
    nodes = {ln.strip() for ln in r.stdout.splitlines() if "::" in ln}
    known_fns = {_fn_key(n) for n in nodes}

    claims: dict[str, set[str]] = defaultdict(set)
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        rel = str(path.relative_to(ROOT))
        # Parsed rather than scanned. Text matching kept failing on real
        # decorators: nested parentheses in parametrize(..., sorted(x)) defeat
        # a regex, and a multi-line parametrize list defeats a line scanner.
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fn_key = f"{rel}::{node.name}"
            if fn_key not in known_fns:
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                func = dec.func
                if not (isinstance(func, ast.Attribute) and func.attr == "req"):
                    continue
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        claims[arg.value].add(fn_key)
    return claims, nodes


def resolve_component(ref: str, inv, checks: set[str]) -> str | None:
    """Return an error message when a component reference resolves to nothing."""
    kind, _, value = ref.partition(":")
    if kind in {"workflow", "preset", "extension"}:
        return None if inv.by_ref(ref) else f"unknown {kind} {value!r}"
    if kind == "command":
        return None if value in inv.provided_commands() else f"no component provides {value!r}"
    if kind == "policy":
        return None if (ROOT / "policy" / value).is_file() else f"no policy file {value!r}"
    if kind == "check":
        return None if value in checks else f"unknown check id {value!r}"
    if kind == "script":
        return None if (ROOT / value).is_file() else f"no file {value!r}"
    return f"unknown reference kind {kind!r}"


def validate(result: Result) -> dict:
    data = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))

    try:
        import jsonschema

        jsonschema.validate(data, json.loads(SCHEMA.read_text(encoding="utf-8")))
    except ImportError:
        result.warn("jsonschema not installed; schema validation skipped")
    except Exception as exc:  # noqa: BLE001
        result.error(f"schema: {exc}")
        return data

    inv = load_inventory()
    check_rows = json.loads(subprocess.run(
        [sys.executable, "scripts/validate_source.py", "--list-checks", "--format", "json"],
        cwd=ROOT, text=True, capture_output=True,
    ).stdout)
    checks = {row["id"] for row in check_rows}

    claims, nodes = collect_tests()
    families = set(data["families"])
    seen: set[str] = set()

    for req in data["requirements"]:
        rid = req["id"]
        if rid in seen:
            result.error(f"{rid}: duplicate id")
        seen.add(rid)

        family = "-".join(rid.split("-")[:2])
        if family not in families:
            result.error(f"{rid}: family {family!r} is not in the allowlist")

        for ref in req["components"]:
            problem = resolve_component(ref, inv, checks)
            if problem:
                result.error(f"{rid}: component {ref!r}: {problem}")

        verified_by = req.get("verified_by", [])
        status = req["status"]

        if status in NEEDS_TESTS and not verified_by:
            result.error(f"{rid}: status {status!r} requires verified_by")
        if status == "withdrawn" and not (req.get("superseded_by") or req.get("rationale")):
            result.error(f"{rid}: withdrawn requires superseded_by or rationale")

        known_fns = {_fn_key(n) for n in nodes}
        for node in verified_by:
            # A parametrised test collects as func[param]; citing the bare
            # function is correct when every parametrisation verifies the
            # requirement, and citing one arbitrary parameter would misstate it.
            if node not in nodes and _fn_key(node) not in known_fns:
                result.error(f"{rid}: verified_by {node!r} is not a collected test")
                continue
            # Forward: the named test must claim this requirement back.
            if _fn_key(node) not in claims.get(rid, set()):
                result.error(
                    f"{rid}: {node} does not claim it "
                    f"(add @pytest.mark.req(\"{rid}\"))"
                )

    # Reverse direction: a test may not claim a requirement that does not name it.
    by_id = {r["id"]: r for r in data["requirements"]}
    for rid, nodes_claiming in claims.items():
        if rid not in by_id:
            result.error(f"test claims unknown requirement {rid!r}: {sorted(nodes_claiming)}")
            continue
        listed = {_fn_key(n) for n in by_id[rid].get("verified_by", [])}
        for fn in sorted(nodes_claiming - listed):
            result.error(f"{rid}: {fn} claims it but appears in no verified_by entry")

    return data


def report(data: dict, fmt: str) -> str:
    rows = data["requirements"]
    by_status: dict[str, int] = defaultdict(int)
    by_release: dict[str, list] = defaultdict(list)
    for r in rows:
        by_status[r["status"]] += 1
        by_release[r["release"]].append(r)

    if fmt == "json":
        return json.dumps({
            "total": len(rows),
            "by_status": dict(by_status),
            "by_release": {k: len(v) for k, v in by_release.items()},
        }, indent=2)

    lines = [f"# Requirement coverage\n", f"{len(rows)} requirements\n"]
    lines.append("| Status | Count |")
    lines.append("|---|---|")
    for status in ("verified", "implemented", "planned", "withdrawn"):
        if by_status.get(status):
            lines.append(f"| {status} | {by_status[status]} |")
    lines.append("\n| Release | Must | Verified |")
    lines.append("|---|---|---|")
    for rel in sorted(by_release):
        items = by_release[rel]
        musts = sum(1 for r in items if r["priority"] == "must")
        ok = sum(1 for r in items if r["priority"] == "must" and r["status"] == "verified")
        lines.append(f"| {rel} | {musts} | {ok} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", choices=["md", "json"], help="Print a coverage report.")
    ap.add_argument("--release", help="Also require every must for this release to be verified.")
    args = ap.parse_args()

    result = Result()
    data = validate(result)

    if args.release:
        for req in data["requirements"]:
            if (req["release"] == args.release and req["priority"] == "must"
                    and req["status"] != "verified"):
                result.error(
                    f"{req['id']}: must-level requirement for {args.release} "
                    f"is {req['status']!r}, not verified"
                )

    for w in result.warnings:
        print(f"WARNING {w}")
    for e in result.errors:
        print(f"ERROR   {e}")

    if args.report and not result.errors:
        print()
        print(report(data, args.report))

    if result.errors:
        print(f"\n{len(result.errors)} traceability errors")
        return 1
    print(f"\n{len(data['requirements'])} requirements, traceability consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
