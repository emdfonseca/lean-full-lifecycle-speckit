#!/usr/bin/env python3
"""Split a Story too large to start, or merge two that turned out to be one.

Deliberately not part of `decompose`. That command creates children under an
Epic; these create *siblings* and end the original. `item-types.yml` says only
Epics are decomposed and that a Story needing splitting is two Stories, so
making the new Stories children of the old one would contradict the policy
while looking like the obvious implementation. Two opposite models in one file
is how the wrong one gets called.

Both operations answer the same question the backlog usually loses: what
became of the original. A split that leaves the original open has produced
three items where there was one, and nobody can tell which carries the work.

Three refusals:

Neither will strand children. An open child under a Story about to be ended is
the case that loses work, so it is refused and the children are named.

Split will not create children of the original. The new Stories take the
original's parent, or no parent, and a test asserts the original never gains a
child.

Merge will not drop the item that carries the work. `--keep` and `--drop` are
both required and must differ, because inferring which survives from argument
order is how the wrong one gets closed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture as capture_mod  # noqa: E402
import config  # noqa: E402
import project_root  # noqa: E402
import relationships  # noqa: E402
import retire as retire_mod  # noqa: E402
from github_api import GitHub, GitHubError, NotFound  # noqa: E402


def split(gh: GitHub, repo: str, issue: int, proposals: list[capture_mod.Candidate | dict],
          reason: str, machine: dict, project: int | None = None,
          policy_root: Path | None = None, dry_run: bool = False) -> dict:
    """Replace one Story with the Stories it should have been."""
    if len(proposals) < 2:
        return {"issue": issue, "action": "refused", "problems": [
            "a split produces at least two Stories; one is a rewrite, and "
            "`edit` is what that needs"]}
    if not (reason or "").strip():
        return {"issue": issue, "action": "refused", "problems": [
            "no reason given. The reason is what tells a later reader why the "
            "original was not simply worked on."]}

    open_kids = retire_mod.open_children(gh, repo, issue)
    if open_kids:
        return {"issue": issue, "action": "refused", "problems": [
            f"#{issue} has open children {open_kids}. Splitting it would leave "
            f"them under an item that is about to be ended; close or reparent "
            f"them first."]}

    # The new Stories take the original's parent, never the original. Only
    # Epics are decomposed.
    parent = relationships.parent_of(gh, repo, issue)

    created = []
    for entry in proposals:
        row = entry if isinstance(entry, dict) else {"title": entry}
        result = capture_mod.create_item(
            gh, repo, row["title"], row.get("body", ""),
            row.get("type", "story"), parent=parent, project=project,
            policy_root=policy_root, found_in=issue)
        created.append(result)

    numbers = [c["number"] for c in created if c.get("number")]
    ended = retire_mod.retire(
        gh, repo, issue,
        f"{reason.strip()}\n\nSplit into "
        + ", ".join(f"#{n}" for n in numbers) + ".",
        "not_planned", machine=machine)
    return {"issue": issue, "action": "split", "created": numbers,
            "parent": parent, "original": ended}


def merge(gh: GitHub, repo: str, keep: int, drop: int, reason: str,
          machine: dict) -> dict:
    """Leave one Story carrying the work of two."""
    problems: list[str] = []
    if keep == drop:
        problems.append("--keep and --drop are the same item")
    if not (reason or "").strip():
        problems.append(
            "no reason given. Merging is a judgement that two items were one, "
            "and the judgement is the part worth recording.")
    open_kids = retire_mod.open_children(gh, repo, drop) if keep != drop else []
    if open_kids:
        problems.append(
            f"#{drop} has open children {open_kids}. Merging would leave them "
            f"under an item that no longer carries work; reparent them to "
            f"#{keep} first.")
    if problems:
        return {"keep": keep, "drop": drop, "action": "refused",
                "problems": problems}

    ended = retire_mod.retire(gh, repo, drop, reason, "duplicate",
                              superseded_by=keep, machine=machine)
    if ended.get("action") == "refused":
        return {"keep": keep, "drop": drop, "action": "refused",
                "problems": ended["problems"]}
    return {"keep": keep, "drop": drop, "action": "merged", "dropped": ended}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--project", type=int, default=None)
    ap.add_argument("--policy-root", type=Path, default=None)
    ap.add_argument("--audit", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_split = sub.add_parser("split", help="Replace a Story with the Stories it should have been.")
    p_split.add_argument("--issue", type=int, required=True)
    p_split.add_argument("--proposals", type=Path, required=True)
    p_split.add_argument("--reason", default="")

    p_merge = sub.add_parser("merge", help="Leave one Story carrying the work of two.")
    p_merge.add_argument("--keep", type=int, required=True)
    p_merge.add_argument("--drop", type=int, required=True)
    p_merge.add_argument("--reason", default="")

    args = ap.parse_args()
    try:
        target = config.resolve_target(args.repo, args.project)
        args.repo, args.project = target.repo, target.project
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
    except (config.ConfigError, project_root.ProjectRootError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    machine = retire_mod.load_machine(args.policy_root)
    gh = GitHub(audit_path=args.audit, dry_run=args.dry_run)
    try:
        if args.cmd == "split":
            rows = capture_mod.load_proposals_json(args.proposals) \
                if hasattr(capture_mod, "load_proposals_json") \
                else json.loads(args.proposals.read_text(encoding="utf-8")).get("proposals", [])
            result = split(gh, args.repo, args.issue, rows, args.reason,
                           machine, args.project, args.policy_root, args.dry_run)
        else:
            result = merge(gh, args.repo, args.keep, args.drop, args.reason, machine)
    except (GitHubError, NotFound) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 1 if result.get("action") == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
