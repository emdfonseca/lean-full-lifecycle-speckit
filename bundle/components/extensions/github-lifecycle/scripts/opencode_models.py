#!/usr/bin/env python3
"""Check that every model a role names actually exists.

`model-routing.yml` has named seven roles and left every `primary` null since
0.1.0. Nothing read the file and nothing checked an id, so a mapping written by
hand would name models nobody had verified.

`opencode models` is the authority. It lists what the installed CLI can
actually reach -- 57 entries on the machine this was written against -- and
asking it is cheap. A list maintained in this repository would be a second copy
that drifts, and the copy that drifts is the one nobody is testing.

Three judgements, all in `model-routing.yml`:

**An unresolved role is reported, not filled in.** A null primary is a decision
deferred until there is evidence, and a resolver that picked something to make
the report green would turn a deferred decision into an invented one.

**A fallback is verified like a primary.** A fallback is what runs when the
primary is unavailable, which is exactly when nobody is in a position to
discover it was never real.

**An unreadable inventory refuses.** An empty inventory treated as "nothing to
check against" verifies every id while appearing to verify them, which is worse
than not checking at all.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/model-routing.yml",
    "policy/model-routing.yml",
)


class InventoryError(Exception):
    """The installed model list could not be read."""


def load_policy(root: Path | None = None) -> dict:
    root = root or project_root.resolve(required=False) or Path.cwd()
    for rel in POLICY_CANDIDATES:
        path = root / rel
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"none of {list(POLICY_CANDIDATES)} found; the governance preset must "
        "be installed")


def read_inventory(policy: dict, runner=None) -> set[str]:
    """Every `provider/model` the installed CLI reports.

    Raises rather than returning an empty set: "no models" and "could not ask"
    are different facts, and collapsing them makes every id verifiable.
    """
    command = list(policy["resolution"]["inventory_command"])
    runner = runner or (lambda args: subprocess.run(
        args, capture_output=True, text=True, timeout=60))
    try:
        result = runner(command)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InventoryError(
            f"could not run {' '.join(command)} ({exc.__class__.__name__}). "
            f"Nothing is verified against an inventory that could not be read."
        ) from None
    if result.returncode != 0:
        raise InventoryError(
            f"{' '.join(command)} exited {result.returncode}: "
            f"{(result.stderr or '').strip()[:200]}")
    models = {line.strip() for line in (result.stdout or "").splitlines()
              if "/" in line.strip()}
    if not models:
        raise InventoryError(
            f"{' '.join(command)} reported no models. An empty inventory would "
            f"verify every id while appearing to verify them.")
    return models


def provider_of(model_id: str) -> str:
    return model_id.split("/", 1)[0]


@dataclass
class Report:
    verified: dict[str, list[str]] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        return {
            "verified": self.verified,
            "unresolved": self.unresolved,
            "problems": self.problems,
            "ok": self.ok,
            # Stated rather than implied: a clean report with unresolved roles
            # is not a resolved mapping.
            "fully_resolved": self.ok and not self.unresolved,
        }


def _check(model: str, role: str, slot: str, inventory: set[str],
           approved: list[str]) -> list[str]:
    problems = []
    if model not in inventory:
        problems.append(
            f"{role}: {slot} {model!r} is not in the installed inventory. "
            f"Nothing in this project can run it.")
    provider = provider_of(model)
    if approved and provider not in approved:
        problems.append(
            f"{role}: {slot} {model!r} comes from provider {provider!r}, which "
            f"is not approved. Approved providers are {approved}.")
    return problems


def verify(policy: dict, inventory: set[str]) -> Report:
    report = Report()
    approved = list(policy.get("approved_providers") or [])
    for role, spec in (policy["roles"] or {}).items():
        spec = spec or {}
        primary = spec.get("primary")
        fallbacks = list(spec.get("fallbacks") or [])
        if not primary:
            # Reported, never chosen. A null primary is a deferred decision.
            report.unresolved.append(role)
            if fallbacks:
                report.problems.append(
                    f"{role}: has fallbacks but no primary. A fallback with "
                    f"nothing to fall back from is not a mapping.")
            continue
        problems = _check(primary, role, "primary", inventory, approved)
        for fallback in fallbacks:
            # Verified like a primary: a fallback runs when the primary is
            # unavailable, which is exactly when nobody can discover it was
            # never real.
            problems += _check(fallback, role, "fallback", inventory, approved)
        report.problems.extend(problems)
        if not problems:
            report.verified[role] = [primary, *fallbacks]
    return report


# --- recording a resolution ---------------------------------------------------

class RecordError(Exception):
    """A mapping that may not be recorded."""


def record_path(policy: dict, root: Path) -> Path:
    return root / policy["resolution"]["record_path"]


def record(policy: dict, report: Report, evaluated_at: str, expires_at: str,
           root: Path) -> dict:
    """Build the record. Refuses a mapping that was never verified.

    Recording is what makes a mapping the one in force, so it is the wrong
    place to be generous. A report carrying problems is a failed verification,
    and an empty one is a verification that never ran.
    """
    if report.problems:
        raise RecordError(
            f"refusing to record: verification found {len(report.problems)} "
            f"problem(s). A mapping that failed verification is not one to put "
            f"in force.")
    if not report.verified:
        raise RecordError(
            "refusing to record: nothing was verified. An empty mapping "
            "recorded as current would be indistinguishable from a resolved "
            "one.")
    if policy["resolution"].get("expiry_required") and not expires_at:
        raise RecordError(
            "refusing to record: no expiry. A resolution with no visible "
            "expiry is trusted indefinitely, which is how a withdrawn model "
            "stays in a config.")
    for label, value in (("evaluated_at", evaluated_at),
                         ("expires_at", expires_at)):
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            raise RecordError(f"{label} {value!r} is not a date.") from None
    return {
        "evaluated_at": evaluated_at,
        "expires_at": expires_at,
        "roles": {role: {"primary": models[0], "fallbacks": models[1:]}
                  for role, models in report.verified.items()},
        "unresolved": list(report.unresolved),
    }


def read_record(path: Path, as_of: date | None = None) -> dict:
    """Read a recorded mapping and say whether it is still current."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    as_of = as_of or date.today()
    try:
        expires = date.fromisoformat(str(data.get("expires_at")))
    except (TypeError, ValueError):
        return dict(data, expired=True, current=False,
                    note="the record carries no usable expiry, so it cannot be "
                         "shown to be current")
    expired = expires < as_of
    return dict(data, expired=expired, current=not expired,
                note=("this resolution has passed its evaluation window and is "
                      "not the mapping in force" if expired else ""))


def unused_roles(policy: dict, search_roots: list[Path]) -> list[str]:
    """Roles nothing asks for.

    A role in the policy that no consumer names is either unfinished work or a
    leftover, and both are worth seeing. Reported rather than removed: deleting
    somebody's role because nothing references it yet is a decision, not
    tidying.
    """
    names = list((policy.get("roles") or {}).keys())
    text = []
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".yml", ".yaml", ".md"}:
                text.append(path.read_text(encoding="utf-8", errors="ignore"))
    joined = "\n".join(text)
    # A role is named when it is used as a value, not when the word appears.
    # A bare-word search reports `architect` used because a prompt mentions
    # "architecture", which is the difference between a reference and a
    # sentence.
    return [role for role in names
            if not re.search(rf"""(?:role|agent)\s*:\s*["']?{re.escape(role)}\b""",
                             joined)]

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
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
        inventory = read_inventory(policy)
    except (FileNotFoundError, KeyError, InventoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = verify(policy, inventory)
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for role, models in report.verified.items():
            print(f"verified   {role}: {', '.join(models)}")
        for role in report.unresolved:
            print(f"unresolved {role}")
        for problem in report.problems:
            print(f"\nREFUSED {problem}")
        if report.unresolved:
            print(f"\n{len(report.unresolved)} role(s) unresolved. Reported, "
                  f"not filled in: a null primary is a decision waiting on "
                  f"evidence.")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
