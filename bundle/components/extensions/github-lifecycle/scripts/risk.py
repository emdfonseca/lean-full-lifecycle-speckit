#!/usr/bin/env python3
"""Score an item's risk from policy, and name the controls that risk requires.

`risk-policy.yml` scored twelve dimensions and named seven overrides to high,
and nothing read it. A policy nothing reads is a document: it looks like a
control, survives review as a control, and refuses nothing.

Three decisions define this command:

It scores from the policy, never from a judgement of its own. Every weight,
threshold, override and control set is read from the installed file. A number
this script invented would be an opinion wearing a policy's clothes.

An override wins outright. `authentication_or_authorization_boundary_change`
makes an item high regardless of what the dimensions add up to, because the
dimensions describe degree and the overrides describe kind. A weighted sum that
could out-vote an auth-boundary change would be a scoring system that argues
with its own policy.

It reports the controls; it does not certify them. `high` requires an
`authorized_security_review`, and nothing here can decide that one happened.
Naming what is required and what is unmet is the whole job -- claiming a
control is satisfied is the failure this exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/risk-policy.yml",
    "policy/risk-policy.yml",
)

RISK_ROLE = "risk"


def load_policy(root: Path | None = None) -> dict:
    base = root or project_root.resolve(required=False) or Path.cwd()
    for rel in POLICY_CANDIDATES:
        candidate = base / rel
        if candidate.is_file():
            return yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    raise FileNotFoundError(
        "risk-policy.yml not found; the governance preset must be installed")


@dataclass
class Score:
    level: str
    total: int
    maximum: int
    per_dimension: dict[str, int] = field(default_factory=dict)
    contributions: dict[str, int] = field(default_factory=dict)
    overrides: list[str] = field(default_factory=list)
    unknown_dimensions: list[str] = field(default_factory=list)
    unknown_overrides: list[str] = field(default_factory=list)
    unrated: list[str] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)

    @property
    def overridden(self) -> bool:
        return bool(self.overrides)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "total": self.total,
            "maximum": self.maximum,
            "per_dimension": self.per_dimension,
            "contributions": self.contributions,
            "overrides": self.overrides,
            "overridden": self.overridden,
            "unknown_dimensions": self.unknown_dimensions,
            "unknown_overrides": self.unknown_overrides,
            "unrated": self.unrated,
            "controls": self.controls,
            # Stated rather than implied: naming a control is not evidence it
            # was performed, and a reader must not have to infer that.
            "controls_are_required_not_satisfied": True,
        }


def level_for(total: int, policy: dict) -> str:
    """The band this total falls in, read from the policy's thresholds.

    Bands are checked in the policy's declared order rather than by comparing
    against hardcoded names, so a preset that renames or adds a band still
    resolves. A total matching nothing is an error in the policy, not a
    silent `low`.
    """
    thresholds = policy["score"]["thresholds"]
    for name, bounds in thresholds.items():
        low = bounds.get("minimum")
        high = bounds.get("maximum")
        if (low is None or total >= low) and (high is None or total <= high):
            return name
    raise ValueError(
        f"score {total} falls in no band of {sorted(thresholds)}; "
        f"risk-policy.yml thresholds do not cover the range")


def highest_band(policy: dict) -> str:
    """The band an override escalates to.

    Taken as the band with the greatest minimum rather than the literal string
    "high", so the escalation follows a renamed policy instead of silently
    escalating to a band that no longer exists.
    """
    thresholds = policy["score"]["thresholds"]
    return max(thresholds, key=lambda name: thresholds[name].get("minimum") or 0)


def score(ratings: dict, policy: dict,
          overrides: list[str] | None = None) -> Score:
    """Score one item. Ratings are per-dimension, 0..maximum from the policy."""
    weights = policy["dimensions"]
    bounds = policy["score"]["per_dimension"]
    lowest, highest = bounds["minimum"], bounds["maximum"]

    unknown = sorted(set(ratings) - set(weights))
    unrated = sorted(set(weights) - set(ratings))

    per_dimension: dict[str, int] = {}
    contributions: dict[str, int] = {}
    for name, weight in weights.items():
        if name not in ratings:
            continue
        value = int(ratings[name])
        if not lowest <= value <= highest:
            raise ValueError(
                f"{name}={value} is outside {lowest}..{highest}; "
                f"risk-policy.yml sets that range")
        per_dimension[name] = value
        contributions[name] = value * int(weight)

    total = sum(contributions.values())
    maximum = sum(int(w) * highest for w in weights.values())

    declared = list(policy.get("overrides_to_high") or [])
    asked = list(overrides or [])
    applied = [o for o in asked if o in declared]
    unknown_overrides = sorted(set(asked) - set(declared))

    level = highest_band(policy) if applied else level_for(total, policy)
    controls = list((policy.get("controls") or {}).get(level) or [])

    return Score(level=level, total=total, maximum=maximum,
                 per_dimension=per_dimension, contributions=contributions,
                 overrides=applied, unknown_dimensions=unknown,
                 unknown_overrides=unknown_overrides, unrated=unrated,
                 controls=controls)


def problems(result: Score) -> list[str]:
    """Reasons this scoring must not be acted on as it stands."""
    out: list[str] = []
    if result.unknown_dimensions:
        out.append(
            f"{result.unknown_dimensions} are not dimensions risk-policy.yml "
            f"declares. A rating against an invented dimension scores nothing "
            f"and reads as though it scored something.")
    if result.unknown_overrides:
        out.append(
            f"{result.unknown_overrides} are not overrides risk-policy.yml "
            f"declares. An override that does not exist cannot escalate, and "
            f"naming one suggests it did.")
    if result.unrated:
        out.append(
            f"{result.unrated} were not rated. An unrated dimension counts as "
            f"zero, so the total understates the risk; rate them or state why "
            f"they do not apply.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rating", action="append", default=[], metavar="NAME=N",
                    help="Per-dimension rating. Repeatable.")
    ap.add_argument("--override", action="append", default=[], metavar="NAME",
                    help="An override risk-policy.yml declares. Repeatable. "
                         "Any one makes the item high outright.")
    ap.add_argument("--ratings", type=Path, default=None,
                    help="YAML mapping of dimension to rating, instead of "
                         "repeating --rating.")
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, "
                         "then the nearest ancestor with a .specify/ directory.")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    try:
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        policy = load_policy(args.policy_root)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    ratings: dict[str, int] = {}
    if args.ratings:
        loaded = yaml.safe_load(args.ratings.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            print("error: --ratings must be a mapping of dimension to rating",
                  file=sys.stderr)
            return 2
        ratings.update({str(k): int(v) for k, v in loaded.items()})
    for pair in args.rating:
        name, _, value = pair.partition("=")
        if not value.strip().lstrip("-").isdigit():
            print(f"error: --rating {pair!r} is not NAME=N", file=sys.stderr)
            return 2
        ratings[name.strip()] = int(value)

    if not ratings and not args.override:
        print("error: nothing to score; pass --rating, --ratings, or --override",
              file=sys.stderr)
        return 2

    try:
        result = score(ratings, policy, args.override)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    found = problems(result)
    if args.format == "json":
        print(json.dumps({**result.to_dict(), "problems": found}, indent=2))
    else:
        print(f"risk: {result.level}  ({result.total}/{result.maximum})")
        if result.overridden:
            print(f"overridden to {result.level} by {result.overrides}; "
                  f"the dimensions did not decide this")
        print("\nrequired controls, none of them certified here:")
        for control in result.controls:
            print(f"  - {control}")
        for problem in found:
            print(f"\nPROBLEM {problem}")
        print(f"\n{len(found)} problem(s).")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
