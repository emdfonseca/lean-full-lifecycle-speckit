#!/usr/bin/env python3
"""Validate a pilot run record against tooling/pilots/metrics.yml.

A pilot report that looks complete because its hard fields defaulted is worse
than one that is visibly incomplete: the first ends the phase, the second
prompts someone to finish it. So this refuses two things.

A verdict with no evidence. The verdict is the part that invites a shrug and
the evidence is what stops it. `held` on its own says a property held; it does
not say how anyone knows.

`unrecorded`, always. It is what the template ships with, so a record nobody
filled in cannot be signed off, and an empty field can never be read as a
measured one.

`unmeasured` where the metric declares it cannot apply.
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
    vocabulary = set(contract.get("verdicts") or {})
    metrics = record.get("metrics") or {}

    for field in ("stream", "owner", "target", "started", "finished"):
        if not record.get(field):
            problems.append(
                f"{field!r} is missing. A pilot with no {field} cannot be "
                f"signed off, and the 0.9.0 gate asks for a named owner.")

    unknown = sorted(set(metrics) - set(declared))
    if unknown:
        problems.append(
            f"{unknown} are not metrics metrics.yml declares. A verdict "
            f"against an invented metric records nothing and reads as though "
            f"it recorded something.")

    for name, spec in declared.items():
        if name not in metrics:
            problems.append(
                f"{name!r} was not recorded. Absent is not a verdict; state "
                f"one, or state that nothing could be measured.")
            continue
        entry = metrics[name] if isinstance(metrics[name], dict) else {}
        verdict = entry.get("verdict")

        if verdict is None:
            problems.append(
                f"{name!r} has no verdict. Every entry answers with one of "
                f"{sorted(vocabulary)}.")
            continue
        if verdict not in vocabulary:
            problems.append(
                f"{name!r} has verdict {verdict!r}, which metrics.yml does "
                f"not declare. The vocabulary is {sorted(vocabulary)}.")
            continue
        if verdict == "unrecorded":
            problems.append(
                f"{name!r} is unrecorded. Nobody filled it in, which is the "
                f"one verdict a finished record may never carry.")
        allowed = spec.get("verdicts")
        if allowed and verdict not in allowed:
            problems.append(
                f"{name!r} answers {verdict!r}, but this one is a judgement "
                f"the run either upheld or did not: {allowed}.")
        if not str(entry.get("evidence") or "").strip():
            problems.append(
                f"{name!r} states {verdict!r} with no evidence. The verdict is "
                f"the part that invites a shrug; the evidence is what stops "
                f"it. Say how it was checked, not that it was.")

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
