#!/usr/bin/env python3
"""What a prototype or spike learned, and what becomes of it.

`artifact-policy.yml` has classed a prototype `ephemeral` with
`promote_only_by_explicit_decision` from the beginning. Nothing enforced it.

The failure that prevents is a quiet one. Nobody decides to ship prototype
code. It is left in place because deleting it needs a reason and keeping it
needs none, and by the time anyone notices it is load-bearing. Requiring the
decision inverts that: the work cannot complete until somebody says what
happens to the artifacts.

Promotion is refused without an approver and a reason. Both are unguessable,
so defaulting either would make the deliberate decision automatic again.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

SCHEMA_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/schemas/disposal-record.schema.json",
    "tooling/schemas/disposal-record.schema.json",
)
POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/artifact-policy.yml",
    "policy/artifact-policy.yml",
)


def _first(root: Path, candidates) -> Path:
    for rel in candidates:
        path = root / rel
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"none of {list(candidates)} found; the governance preset must be installed")


def load_schema(root: Path) -> dict:
    return json.loads(_first(root, SCHEMA_CANDIDATES).read_text(encoding="utf-8"))


def load_contract(root: Path) -> dict:
    policy = yaml.safe_load(_first(root, POLICY_CANDIDATES).read_text(encoding="utf-8"))
    return policy["artifacts"]["prototype"]["disposal_record"]


def load_record(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if "```" in text:
        match = re.search(r"```(?:yaml|json)?\n(.*?)\n```", text, re.DOTALL)
        if match:
            text = match.group(1)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("disposal record is not a mapping")
    return data


def check(record: dict, schema: dict, contract: dict) -> list[str]:
    problems: list[str] = []
    try:
        import jsonschema

        jsonschema.validate(record, schema)
    except ImportError:
        problems.append("jsonschema is not installed; schema not enforced")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"schema: {getattr(exc, 'message', exc)}")
        return problems

    decision = record.get("decision")
    if decision == "promote":
        missing = [f for f in contract["promote_requires"] if not record.get(f)]
        if missing:
            problems.append(
                f"promotion requires {missing}. Neither can be inferred, and "
                f"defaulting either would make the deliberate decision "
                f"automatic again.")
    if decision in ("delete", "archive") and not record.get("artifacts"):
        problems.append(
            f"decision is {decision!r} but no artifacts are named, so nobody "
            f"can check the disposal happened.")

    if record.get("kind") == "spike":
        missing = [f for f in contract["spike_required_fields"] if not record.get(f)]
        if missing:
            problems.append(
                f"a spike states its boundary before it starts; missing "
                f"{missing}. Without them it is open-ended investigation, not a "
                f"spike.")

    if not record.get("findings"):
        problems.append(
            "no findings recorded. 'unresolved' is a legitimate finding; "
            "silence is not.")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", type=Path, required=True)
    ap.add_argument("--policy-root", type=Path, default=Path.cwd())
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    try:
        schema = load_schema(args.policy_root)
        contract = load_contract(args.policy_root)
        record = load_record(args.record)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problems = check(record, schema, contract)
    if args.format == "json":
        print(json.dumps({"blocking": problems,
                          "decision": record.get("decision")}, indent=2))
    else:
        for problem in problems:
            print(f"BLOCKING {problem}")
        print(f"\n{len(problems)} blocking")
        if not problems:
            print(f"Disposal decided: {record.get('decision')}.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
