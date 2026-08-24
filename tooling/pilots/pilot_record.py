#!/usr/bin/env python3
"""Validate a pilot run record against tooling/pilots/metrics.yml.

A pilot report that looks complete because its hard fields defaulted is worse
than one that is visibly incomplete: the first ends the phase, the second
prompts someone to finish it. So this refuses two things.

A witnessed metric cannot be absent. It is an observation about a person
working -- how often they stepped in, whether the run needed repair, what they
thought of it -- and nobody can reconstruct it afterwards. `null` is not a
value; if nothing happened, say `0` and say so.

An observed metric that could not be read is `null` with a reason, never
omitted. "We did not measure it" and "it was zero" are different results, and
a report that renders them identically is not evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

CONTRACT = Path(__file__).resolve().parent / "metrics.yml"


def load_contract(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONTRACT).read_text(encoding="utf-8")) or {}


def check(record: dict, contract: dict) -> list[str]:
    problems: list[str] = []
    declared = {m["id"]: m for m in contract.get("metrics") or []}
    metrics = record.get("metrics") or {}

    for field in ("stream", "owner", "target", "started", "finished"):
        if not record.get(field):
            problems.append(
                f"{field!r} is missing. A pilot with no {field} cannot be "
                f"signed off, and the 0.9.0 gate asks for a named owner.")

    unknown = sorted(set(metrics) - set(declared))
    if unknown:
        problems.append(
            f"{unknown} are not metrics metrics.yml declares. A value against "
            f"an invented metric records nothing and reads as though it "
            f"recorded something.")

    for name, spec in declared.items():
        if name not in metrics:
            problems.append(
                f"{name!r} was not recorded. Absent is not zero; state the "
                f"value or state that it was not collected.")
            continue
        entry = metrics[name]
        value = entry.get("value") if isinstance(entry, dict) else entry
        if spec["source"] == "witnessed" and value is None:
            problems.append(
                f"{name!r} is witnessed and has no value. Nobody can "
                f"reconstruct it afterwards, so a null here is a gap in the "
                f"pilot rather than a gap in the data.")
        if value is None and isinstance(entry, dict) and not entry.get("why"):
            problems.append(
                f"{name!r} is null with no reason. Not measured and zero are "
                f"different results.")

    # `[]` is the explicit claim "nothing failed", which is the whole point.
    # A falsy check here would reject the very record shape this asks for.
    if "failures" not in record:
        problems.append(
            "'failures' is missing. An empty list is a claim worth making "
            "explicitly; omitting it leaves a reader unable to tell a clean "
            "run from an unrecorded one.")
    for index, failure in enumerate(record.get("failures") or []):
        if not isinstance(failure, dict) or not failure.get("tracked_by"):
            problems.append(
                f"failures[{index}] names no tracked_by. Every pilot failure "
                f"becomes a backlog item; one that does not is a finding the "
                f"pilot lost.")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", type=Path, required=True)
    ap.add_argument("--contract", type=Path, default=None)
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    try:
        record = yaml.safe_load(args.record.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not isinstance(record, dict):
        print("error: pilot record is not a mapping", file=sys.stderr)
        return 2

    problems = check(record, load_contract(args.contract))
    if args.format == "json":
        print(json.dumps({"problems": problems, "complete": not problems}, indent=2))
    else:
        for problem in problems:
            print(f"INCOMPLETE {problem}")
        print(f"\n{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
