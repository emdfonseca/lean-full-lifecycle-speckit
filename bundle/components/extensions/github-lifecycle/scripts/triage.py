#!/usr/bin/env python3
"""Assess an incoming item: what it is, whether it exists already, what next.

Triage decides *what* an item is, never *when* it will be done. Those are
different decisions by different people, and conflating them is how a triage
queue becomes a commitment nobody agreed to.

Three refusals define it:

It cannot reach Ready. Inbox to Refining is the only transition it proposes;
Ready requires a readiness verdict, which is a separate authority.

It will not convert an observation into work. An item with no reproduction and
no stated outcome is a discovery note, and filing it as work makes the backlog
less trustworthy rather than more complete.

It does not record inferred behaviour as intent. Behaviour read from code with
nothing agreeing it was wanted is labelled inferred, because a later reader
cannot otherwise tell a decision from an observation.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture as capture_mod  # noqa: E402
from github_api import GitHub, GitHubError  # noqa: E402

# Triage proposes this and nothing further along.
TRIAGE_TARGET = "Refining"
FORBIDDEN_TARGETS = ("Ready", "In Progress", "Output Done")


@dataclass
class Assessment:
    issue: int
    title: str
    duplicates: list[dict] = field(default_factory=list)
    proposed_type: str | None = None
    evidence_missing: list[str] = field(default_factory=list)
    inferred_claims: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    recommended_priority: str | None = None
    priority_reasoning: str = ""

    @property
    def is_observation(self) -> bool:
        """True when there is not enough here to be work."""
        return bool(self.evidence_missing)

    @property
    def proposed_transition(self) -> str | None:
        if self.duplicates or self.is_observation:
            return None
        return TRIAGE_TARGET

    def to_dict(self) -> dict:
        data = asdict(self)
        data["is_observation"] = self.is_observation
        data["proposed_transition"] = self.proposed_transition
        # Stated rather than implied: a reader must not have to know the rules
        # to know a commitment was not made.
        data["priority_is_recommendation_only"] = True
        data["ready_not_reachable_by_triage"] = True
        return data


def assess(gh: GitHub, repo: str, issue_number: int,
           threshold: float = capture_mod.DEFAULT_THRESHOLD) -> Assessment:
    issue = gh.rest("GET", f"repos/{repo}/issues/{issue_number}") or {}
    if not issue.get("number"):
        raise GitHubError(f"issue #{issue_number} not found in {repo}")

    title = str(issue.get("title", ""))
    body = str(issue.get("body") or "")
    labels = {str(l.get("name", "")) for l in issue.get("labels") or []}
    proposed = next((t for t in ("bug", "story", "spike", "epic") if t in labels), None)

    duplicates = [
        asdict(c) for c in capture_mod.search_duplicates(gh, repo, title, threshold)
        if c.number != issue_number
    ]
    missing = capture_mod.has_evidence(body, proposed) if proposed else ["type"]

    return Assessment(
        issue=issue_number, title=title, duplicates=duplicates,
        proposed_type=proposed, evidence_missing=missing,
    )


def check_target(target: str) -> None:
    """Guard the boundary rather than trusting callers to respect it."""
    if target in FORBIDDEN_TARGETS:
        raise GitHubError(
            f"triage cannot move an item to {target!r}. It proposes "
            f"{TRIAGE_TARGET!r} only; {target!r} requires a separate decision "
            f"by a different authority.")
    if target != TRIAGE_TARGET:
        raise GitHubError(f"triage proposes {TRIAGE_TARGET!r}, not {target!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--threshold", type=float, default=capture_mod.DEFAULT_THRESHOLD)
    ap.add_argument("--target", default=TRIAGE_TARGET,
                    help="Transition to propose. Only Refining is permitted.")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--audit", type=Path, default=None)
    args = ap.parse_args()

    gh = GitHub(audit_path=args.audit)
    try:
        check_target(args.target)
        assessment = assess(gh, args.repo, args.issue, args.threshold)
    except GitHubError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    payload = json.dumps(assessment.to_dict(), indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    # Non-zero when there is something a person must decide before anything
    # is written.
    return 1 if assessment.proposed_transition is None else 0


if __name__ == "__main__":
    sys.exit(main())
