#!/usr/bin/env python3
"""Validate a discovery record.

Discovery output is `evidence_ephemeral` under `artifact-policy.yml`: it
reports what is there and never establishes what was wanted. A finding becomes
intent only through reconciliation with a spec, which is a separate act by a
different authority.

Three workflows read this record — prototype, spike, and the uncertainty branch
of story delivery — so a malformed one is reported rather than partially
consumed. A consumer that reads nine of eleven sections and proceeds is worse
than one that stops: it produces a confident answer from an incomplete picture.
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
    ".specify/presets/lean-full-lifecycle-governance/schemas/discovery-record.schema.json",
    "tooling/schemas/discovery-record.schema.json",
)
EMPTY_MARKERS = ("none", "nothing", "not examined", "n/a", "none found")


def load_schema(root: Path) -> dict:
    for rel in SCHEMA_CANDIDATES:
        path = root / rel
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        "discovery-record.schema.json not found; the governance preset must be "
        "installed")


def load_record(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if "```" in text:
        match = re.search(r"```(?:yaml|json)?\n(.*?)\n```", text, re.DOTALL)
        if match:
            text = match.group(1)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("discovery record is not a mapping")
    return data


def check(record: dict, schema: dict) -> list[str]:
    problems: list[str] = []
    try:
        import jsonschema

        jsonschema.validate(record, schema)
    except ImportError:
        problems.append("jsonschema is not installed; schema not enforced")
    except Exception as exc:  # noqa: BLE001 - the message is the useful part
        problems.append(f"schema: {getattr(exc, 'message', exc)}")
        return problems

    for section in schema["required"]:
        value = record.get(section) or []
        if not value:
            # An absent section and an empty one mean different things, and
            # only one of them was investigated.
            problems.append(
                f"{section} is empty. Say what was not found, or that the "
                f"section does not apply; an empty list does not distinguish "
                f"'nothing there' from 'never looked'.")
    return problems


def advisories(record: dict) -> list[str]:
    """Findings worth a reader's attention that do not invalidate the record."""
    out: list[str] = []
    observations = record.get("current_behaviour") or []
    inferred = [o for o in observations if o.get("source") == "inferred"]
    if inferred:
        out.append(
            f"{len(inferred)} of {len(observations)} behaviour observations are "
            f"inferred. These are evidence, not intent, and must be reconciled "
            f"with a spec before any acceptance criterion asserts them.")
    if not record.get("open_uncertainty"):
        out.append(
            "no open uncertainty recorded. Bounded discovery that answered "
            "every question is unusual; check nothing was resolved by guessing.")
    scope = " ".join(record.get("scope") or []).lower()
    if not any(marker in scope for marker in ("not", "excluded", "beyond", "outside")):
        out.append(
            "scope does not say what was deliberately not examined, so a "
            "reader cannot tell the boundary from an omission.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", type=Path, required=True)
    ap.add_argument("--policy-root", type=Path, default=Path.cwd())
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    try:
        schema = load_schema(args.policy_root)
        record = load_record(args.record)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problems = check(record, schema)
    notes = advisories(record) if not problems else []

    if args.format == "json":
        print(json.dumps({"blocking": problems, "advisory": notes}, indent=2))
    else:
        for problem in problems:
            print(f"BLOCKING {problem}")
        for note in notes:
            print(f"ADVISORY {note}")
        print(f"\n{len(problems)} blocking, {len(notes)} advisory")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
