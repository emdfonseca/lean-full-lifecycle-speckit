#!/usr/bin/env python3
"""Assess an outcome record, and refuse to conclude more than it supports.

Outcome Status had five values and no defined evidence, so validating one meant
asserting it. This makes the assessment a function of the record.

Four judgements, written in `outcome-policy.yml` so they are argued with once
rather than relitigated per outcome:

A regressed guardrail defeats a met target. Guardrails name the harm a success
is not permitted to cause, so a success that caused it is not one.

Insufficient evidence is not failure. An unelapsed window or an undersized
sample leaves the item Measuring; recording it as missed invents a result the
data does not support.

An unreadable data source blocks rather than concludes. Absent data is not
evidence of absence.

Only an authority validates. This script recommends, and says so in its output
rather than leaving the reader to know it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

SCHEMA_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/schemas/outcome-record.schema.json",
    "tooling/schemas/outcome-record.schema.json",
)
POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/outcome-policy.yml",
    "policy/outcome-policy.yml",
)

MEASURING = "Measuring"
VALIDATED = "Outcome Validated"
MISSED = "Outcome Missed / Inconclusive"

# The board carries one option for the last two, and the field is named for
# both. They are still different findings: a missed target is a result somebody
# can act on, an inconclusive one means the question is open and the next step
# is a better measurement rather than a post-mortem.
FINDING_MET = "met"
FINDING_NOT_MET = "not_met"
FINDING_INCONCLUSIVE = "inconclusive"


def _first(root: Path, candidates) -> Path:
    for rel in candidates:
        path = root / rel
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"none of {list(candidates)} found; the governance preset must be installed")


def load_schema(root: Path) -> dict:
    return json.loads(_first(root, SCHEMA_CANDIDATES).read_text(encoding="utf-8"))


def load_policy(root: Path) -> dict:
    return yaml.safe_load(_first(root, POLICY_CANDIDATES).read_text(encoding="utf-8"))


def load_record(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if "```" in text:
        match = re.search(r"```(?:yaml|json)?\n(.*?)\n```", text, re.DOTALL)
        if match:
            text = match.group(1)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("outcome record is not a mapping")
    return data


@dataclass
class Assessment:
    recommended_status: str | None = None
    blocking: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    # Which finding the status stands for. Two of them share one status.
    finding: str | None = None

    def to_dict(self) -> dict:
        return {
            "recommended_status": self.recommended_status,
            "finding": self.finding,
            "blocking": self.blocking,
            "reasons": self.reasons,
            # Stated, not implied. A reader must not need to know the policy to
            # know this is a recommendation.
            "is_recommendation_only": True,
            "validation_requires_authority": True,
        }


def assess(record: dict, schema: dict, policy: dict,
           data_source_readable: bool = True) -> Assessment:
    result = Assessment()
    try:
        import jsonschema

        jsonschema.validate(record, schema)
    except ImportError:
        result.blocking.append("jsonschema is not installed; schema not enforced")
    except Exception as exc:  # noqa: BLE001
        result.blocking.append(f"schema: {getattr(exc, 'message', exc)}")
        return result

    if not data_source_readable:
        result.blocking.append(
            f"the data source {record.get('data_source')!r} could not be read. "
            f"Absent data is not evidence of absence, so nothing is concluded.")
        return result

    # Evidence sufficiency comes before any verdict on the target: a result
    # computed from too little data is not a result.
    if not record.get("window_elapsed", False):
        result.recommended_status = MEASURING
        result.reasons.append(
            "the observation window has not elapsed. Insufficient evidence is "
            "not failure.")
        return result

    sample = int(record.get("sample_size", 0) or 0)
    minimum = int(record.get("minimum_sample", 0) or 0)
    if minimum and sample < minimum:
        result.recommended_status = MEASURING
        result.reasons.append(
            f"sample of {sample} is below the stated minimum of {minimum}, so "
            f"the result is not conclusive.")
        return result

    regressed = [g["name"] for g in record.get("guardrail_results") or []
                 if not g.get("held", True)]
    stated = str(record.get("result") or "").strip().lower()
    known = policy["assessment"]["result_values"]
    if stated and stated not in known:
        result.blocking.append(
            f"result {stated!r} is not one of {sorted(known)}. An unrecognised "
            f"reading cannot be judged, and guessing which it meant is how an "
            f"open question becomes a verdict.")
        return result
    target_met = bool(record.get("target_met", stated == FINDING_MET))

    if regressed:
        result.recommended_status = MISSED
        result.reasons.append(
            f"guardrail(s) regressed: {regressed}. A guardrail names the harm a "
            f"success is not permitted to cause, so a met target does not "
            f"override it.")
        if target_met:
            result.reasons.append(
                "the target was met, and that does not change the assessment.")
        return result

    if target_met:
        result.recommended_status = VALIDATED
        result.finding = FINDING_MET
        result.reasons.append(
            "target met with guardrails intact. An authority must still decide: "
            f"{policy['validation_authority']}.")
        return result

    result.recommended_status = MISSED
    if stated == FINDING_INCONCLUSIVE:
        # The window elapsed and the sample was large enough, and the result
        # still does not distinguish success from failure. Reporting that as a
        # miss tells a team its work failed on evidence that says no such
        # thing.
        result.finding = FINDING_INCONCLUSIVE
        result.reasons.append(
            "the measurement did not settle the question. This is not a missed "
            "target: the question is still open, and the next step is a better "
            "measurement rather than a post-mortem.")
    else:
        result.finding = FINDING_NOT_MET
        result.reasons.append("target not met, with sufficient evidence to say so.")
    return result


def check_authority(record: dict, status: str, policy: dict) -> list[str]:
    """Refuse Validated without a named authority."""
    if status != VALIDATED:
        return []
    who = str(record.get("validated_by") or "").strip()
    if not who:
        return [f"recording {VALIDATED!r} requires a named validating "
                f"authority: one of {policy['validation_authority']}. "
                f"An agent may recommend, never decide."]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", type=Path, required=True)
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
    ap.add_argument("--data-source-unreadable", action="store_true",
                    help="Assert the named data source could not be read.")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()
    try:
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        schema = load_schema(args.policy_root)
        policy = load_policy(args.policy_root)
        record = load_record(args.record)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = assess(record, schema, policy,
                    data_source_readable=not args.data_source_unreadable)
    if result.recommended_status:
        result.blocking.extend(
            check_authority(record, result.recommended_status, policy))

    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        for item in result.blocking:
            print(f"BLOCKING {item}")
        for reason in result.reasons:
            print(f"  {reason}")
        print(f"\nRecommended: {result.recommended_status or 'nothing'} "
              f"({len(result.blocking)} blocking)")
        print("This is a recommendation. Only "
              f"{policy['validation_authority']} may validate an outcome.")
    return 1 if result.blocking else 0


if __name__ == "__main__":
    sys.exit(main())
