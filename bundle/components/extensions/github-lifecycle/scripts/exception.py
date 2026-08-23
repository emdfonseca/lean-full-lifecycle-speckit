#!/usr/bin/env python3
"""Validate an exception against the policy that has never been read.

`exception-policy.yml` has named ten required fields and four forbidden shapes
since 0.1.0, and no code has ever looked at it. An unenforced exception policy
is worse than none: it is a document teams cite while doing the opposite.

The four shapes, and why each is forbidden:

**Blanket.** "The legacy code" is not a scope. An exception that names no
particular thing cannot be reviewed, because nobody can tell what it covers.

**Ownerless.** Present but empty is absent. A placeholder owner is how an
exception survives with nobody to answer for it.

**Permanent without approval.** Permanence is the one disposition that outlives
everybody involved, so it is the one that must name who chose it.

**Hiding new violations.** An exception over a glob cannot tell an existing
violation from one added tomorrow unless it records what existed when it was
written. Without that baseline it silently widens on every commit.

An expired exception is reported, not deleted, and stops suppressing its rule.
Deleting it would lose the record of what was accepted and by whom.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/exception-policy.yml",
    "policy/exception-policy.yml",
)
GLOB = re.compile(r"[*?\[]")


def load_policy(root: Path) -> dict:
    for rel in POLICY_CANDIDATES:
        path = root / rel
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"none of {list(POLICY_CANDIDATES)} found; the governance preset must "
        "be installed")


def load_record(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if "```" in text:
        match = re.search(r"```(?:yaml|json)?\n(.*?)\n```", text, re.DOTALL)
        if match:
            text = match.group(1)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("exception record is not a mapping")
    return data


@dataclass
class Result:
    refusals: list[str] = field(default_factory=list)
    expired: bool = False
    suppresses_rule: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.refusals

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "refusals": self.refusals,
            "expired": self.expired,
            "suppresses_rule": self.suppresses_rule,
            "notes": self.notes,
        }


def _blank(value, placeholders) -> bool:
    return str(value or "").strip().lower() in placeholders


def check_required(record: dict, policy: dict) -> list[str]:
    placeholders = set(
        policy["detection"]["ownerless_exception"]["placeholder_values"])
    problems = []
    for name in policy["required"]:
        if name not in record:
            problems.append(f"missing required field {name!r}.")
        elif _blank(record[name], placeholders):
            problems.append(
                f"field {name!r} is present but empty. Present but empty is "
                f"absent; a placeholder is how an exception survives with "
                f"nobody to answer for it.")
    return problems


def check_blanket(record: dict, policy: dict) -> list[str]:
    rules = policy["detection"]["blanket_legacy_exception"]
    scope = str(record.get("scope") or "").strip()
    problems = []
    if scope.lower() in {s.lower() for s in rules["whole_repository_scopes"]}:
        problems.append(
            f"scope {scope!r} names no particular thing. An exception nobody "
            f"can bound is one nobody can review.")
    else:
        # Segments before any glob. `legacy/**` is one directory from the root;
        # `src/legacy/parser/**` is a place.
        head = scope.split("*")[0].strip("/")
        segments = [s for s in head.split("/") if s]
        if GLOB.search(scope) and len(segments) < rules["minimum_path_segments"]:
            problems.append(
                f"scope {scope!r} covers a directory tree from too near the "
                f"root to be a scope. Name the place, not the codebase.")
    rule = str(record.get("policy_rule") or "").strip().lower()
    if rule in {w.lower() for w in rules["rule_wildcards"]}:
        problems.append(
            f"policy_rule {rule!r} names a family of rules rather than a rule. "
            f"An exception to everything is a policy change.")
    return problems


def check_permanent(record: dict, policy: dict) -> list[str]:
    rules = policy["detection"]["permanent_exception_without_explicit_approval"]
    if str(record.get("disposition") or "") != rules["disposition"]:
        return []
    placeholders = set(
        policy["detection"]["ownerless_exception"]["placeholder_values"])
    problems = []
    for name in rules["requires"]:
        if _blank(record.get(name), placeholders):
            problems.append(
                f"a permanent exception must name {name!r}. Permanence is the "
                f"one disposition that outlives everybody involved, so it is "
                f"the one that must say who chose it.")
    return problems


def check_baseline(record: dict, policy: dict) -> list[str]:
    rules = policy["detection"]["exception_hiding_new_violations"]
    if not rules["requires_baseline_when_scope_is_a_glob"]:
        return []
    scope = str(record.get("scope") or "")
    if not GLOB.search(scope):
        return []
    if record.get(rules["baseline_field"]):
        return []
    return [
        f"scope {scope!r} is a glob and records no {rules['baseline_field']!r}. "
        f"Without one it cannot tell an existing violation from one added "
        f"tomorrow, so it widens on every commit."]


def check_expiry(record: dict, policy: dict, as_of: date) -> tuple[bool, list[str]]:
    raw = record.get("review_or_expiry_at")
    if not raw:
        return False, []
    try:
        when = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return False, [f"review_or_expiry_at {raw!r} is not a date."]
    if when < as_of:
        return True, []
    return False, []


def validate(record: dict, policy: dict, as_of: date) -> Result:
    result = Result()
    result.refusals.extend(check_required(record, policy))
    result.refusals.extend(check_blanket(record, policy))
    result.refusals.extend(check_permanent(record, policy))
    result.refusals.extend(check_baseline(record, policy))

    expired, problems = check_expiry(record, policy, as_of)
    result.refusals.extend(problems)
    result.expired = expired

    disposition = str(record.get("disposition") or "")
    active = disposition in policy["expiry"]["suppresses_rule_while"]
    result.suppresses_rule = active and not expired and result.accepted
    if expired:
        result.notes.append(
            "This exception has passed its review date. It is reported, not "
            "deleted -- deleting it would lose what was accepted and by whom -- "
            "and it no longer suppresses its rule.")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", type=Path, required=True)
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
    ap.add_argument("--as-of", default=date.today().isoformat(),
                    help="Date to judge expiry against. Defaults to today.")
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
        record = load_record(args.record)
        as_of = date.fromisoformat(args.as_of)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = validate(record, policy, as_of)
    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        for refusal in result.refusals:
            print(f"REFUSED {refusal}")
        for note in result.notes:
            print(f"\n{note}")
        print(f"\n{'Accepted' if result.accepted else 'Refused'}. "
              f"Suppresses its rule: {result.suppresses_rule}.")
    return 0 if result.accepted and not result.expired else 1


if __name__ == "__main__":
    sys.exit(main())
