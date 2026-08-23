#!/usr/bin/env python3
"""Decide whether a repository already has a product in it.

Greenfield bootstrap writes a constitution and scaffolding on the assumption
the repository is empty. Run against a real codebase it scaffolds over
somebody's work, which is destructive and easy to miss until later.

Two judgements, both in `bootstrap-policy.yml`:

Counts never decide. A repository of forty configuration files is empty and one
with a single domain module is not, so a verdict names the files it found and
never how many. `stated_reason` is asserted to contain no count for that reason.

An unreadable repository is not an empty one. Here the safe-looking default is
the destructive one, so failing to enumerate blocks rather than reporting no
mismatch.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/bootstrap-policy.yml",
    "policy/bootstrap-policy.yml",
)

NO_MISMATCH = "no_mismatch"
MISMATCH = "mismatch"
BLOCKED = "blocked"

# How many named files a reason carries. The rest are in `evidence`; a reason
# that lists eighty paths is not read, and one that says "80 files" is the
# count this whole module refuses to decide on.
NAMED_IN_REASON = 3


def load_policy(root: Path) -> dict:
    for rel in POLICY_CANDIDATES:
        path = root / rel
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8"))["mismatch"]
    raise FileNotFoundError(
        f"none of {list(POLICY_CANDIDATES)} found; the governance preset must "
        "be installed")


@dataclass
class Verdict:
    verdict: str
    stated_reason: str = ""
    evidence: list[str] = field(default_factory=list)
    recommends: str | None = None

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "stated_reason": self.stated_reason,
            "evidence": self.evidence,
            "recommends": self.recommends,
            "decided_on": "named files",
        }


def is_scaffolding(rel: str, policy: dict) -> bool:
    name = Path(rel).name
    if name in policy["scaffolding_files"]:
        return True
    for pattern in policy["scaffolding_paths"]:
        if fnmatch.fnmatch(rel, pattern) or rel.startswith(pattern.rstrip("*/")):
            return True
    # Configuration written in a programming language: the suffix says code and
    # the name says configuration. The name wins.
    return any(name.endswith(s) for s in policy["configuration_suffixes"])


def is_application_code(rel: str, policy: dict) -> bool:
    if is_scaffolding(rel, policy):
        return False
    return Path(rel).suffix in policy["code_suffixes"]


def enumerate_files(root: Path) -> list[str]:
    """Every file under root, relative and POSIX-separated.

    Raises rather than returning a partial list: a half-read repository that
    happens to miss the one module present would report no mismatch, which is
    the failure this module exists to prevent.
    """
    out = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out.append(path.relative_to(root).as_posix())
    return out


def classify(files: list[str], policy: dict) -> Verdict:
    application = [f for f in files if is_application_code(f, policy)]
    if not application:
        return Verdict(
            NO_MISMATCH,
            stated_reason=(
                "Every file is environment, configuration, or scaffolding. "
                "Nothing carries application or domain logic."),
        )
    named = ", ".join(application[:NAMED_IN_REASON])
    tail = " and other files listed in the evidence" \
        if len(application) > NAMED_IN_REASON else ""
    return Verdict(
        MISMATCH,
        stated_reason=(
            f"This repository already carries application logic, in {named}"
            f"{tail}. Greenfield bootstrap would scaffold over it."),
        evidence=application,
        recommends=policy["handoff"]["to"],
    )


def assess(root: Path, policy: dict) -> Verdict:
    try:
        files = enumerate_files(root)
    except OSError as exc:
        return Verdict(BLOCKED,
                       stated_reason=f"{policy['on_unreadable']['reason'].strip()} "
                                     f"({exc.__class__.__name__})")
    return classify(files, policy)


# A digit that is standing in for "how many". Filenames carry digits (`v2`,
# `oauth2`), so the check is for a count, not for a numeral.
COUNT_SHAPED = re.compile(
    r"\b\d+\s+(?:files?|modules?|matches?|items?|sources?)\b"
    r"|\b(?:count|total)\b", re.IGNORECASE)


def reason_states_a_count(reason: str) -> bool:
    return bool(COUNT_SHAPED.search(reason))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", type=Path, default=Path.cwd(),
                    help="Repository to assess.")
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
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
    except (FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = assess(args.path, policy)
    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"{result.verdict.upper()}\n\n{result.stated_reason}")
        if result.evidence:
            print("\nEvidence:")
            for item in result.evidence:
                print(f"  {item}")
        if result.recommends:
            print(f"\nRecommended: {result.recommends}")
    return 0 if result.verdict == NO_MISMATCH else 1


if __name__ == "__main__":
    sys.exit(main())
