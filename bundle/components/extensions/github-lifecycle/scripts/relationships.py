#!/usr/bin/env python3
"""Native issue hierarchy and dependencies.

Two relationships, deliberately not conflated:

**Parent/sub-issue** is containment. An Epic's progress derives from its
children, so a wrong link silently changes what completing the parent requires.

**Blocked-by** is obstruction, and orthogonal to both containment and delivery
state (ADR 0004). A blocker may live in another repository; the API takes a
global issue id, so this works across projects.

Every link is read back. A structural write that reports success without taking
effect is harder to notice than a wrong field value, because nothing downstream
looks wrong until the parent completes over work that was never attached.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

from github_api import Conflict, GitHub, GitHubError, NotFound  # noqa: E402


class CycleError(Conflict):
    """The link would make an item its own ancestor."""


@dataclass(frozen=True)
class Link:
    parent: int
    child: int
    already_present: bool = False


def _issues(repo: str) -> str:
    return f"repos/{repo}/issues"


def children(gh: GitHub, repo: str, issue: int) -> list[int]:
    rows = gh.rest("GET", f"{_issues(repo)}/{issue}/sub_issues", paginate=True) or []
    if isinstance(rows, dict):
        rows = [rows]
    return [int(r["number"]) for r in rows if r.get("number") is not None]


def parent_of(gh: GitHub, repo: str, issue: int) -> int | None:
    payload = gh.rest("GET", f"{_issues(repo)}/{issue}") or {}
    url = payload.get("parent_issue_url")
    if not url:
        return None
    return int(str(url).rsplit("/", 1)[-1])


def ancestors(gh: GitHub, repo: str, issue: int, limit: int = 32) -> list[int]:
    """Walk up the containment chain. Bounded: a pre-existing cycle must not hang."""
    seen: list[int] = []
    current = parent_of(gh, repo, issue)
    while current is not None and len(seen) < limit:
        if current in seen:
            break
        seen.append(current)
        current = parent_of(gh, repo, current)
    return seen


def link_child(gh: GitHub, repo: str, parent: int, child: int,
               operation_id: str | None = None) -> Link:
    """Attach child to parent, refusing anything that would form a cycle."""
    if parent == child:
        raise CycleError(f"#{parent} cannot be its own parent")

    existing = children(gh, repo, parent)
    if child in existing:
        return Link(parent, child, already_present=True)

    # The parent must not already be contained by the child, directly or
    # otherwise. Checked before the write: a cycle is far easier to prevent
    # than to unpick.
    chain = ancestors(gh, repo, parent)
    if child in chain or child == parent:
        route = " -> ".join(f"#{n}" for n in [parent, *chain])
        raise CycleError(
            f"linking #{child} under #{parent} would form a cycle: #{child} "
            f"already contains it via {route}")

    issue_id = (gh.rest("GET", f"{_issues(repo)}/{child}", jq=".id") or None)
    if issue_id is None:
        raise NotFound(f"issue #{child} not found in {repo}")
    gh.rest("POST", f"{_issues(repo)}/{parent}/sub_issues",
            body={"sub_issue_id": int(issue_id)}, operation_id=operation_id)

    if child not in children(gh, repo, parent):
        raise Conflict(
            f"link of #{child} under #{parent} did not take; read-back does not "
            f"show it")
    return Link(parent, child)


def blockers(gh: GitHub, repo: str, issue: int, include_closed: bool = False) -> list[dict]:
    rows = gh.rest("GET", f"{_issues(repo)}/{issue}/dependencies/blocked_by",
                   paginate=True) or []
    if isinstance(rows, dict):
        rows = [rows]
    return [r for r in rows if include_closed or r.get("state") != "closed"]


def add_blocker(gh: GitHub, repo: str, issue: int, blocker_repo: str,
                blocker_issue: int, operation_id: str | None = None) -> bool:
    """Record that `issue` is blocked by another issue, in any repository.

    Returns False when the dependency already existed.
    """
    if blocker_repo == repo and blocker_issue == issue:
        raise CycleError(f"#{issue} cannot block itself")

    present = {(b.get("repository", {}).get("full_name"), b.get("number"))
               for b in blockers(gh, repo, issue, include_closed=True)}
    if (blocker_repo, blocker_issue) in present:
        return False

    blocker_id = gh.rest("GET", f"{_issues(blocker_repo)}/{blocker_issue}", jq=".id")
    if blocker_id is None:
        raise NotFound(f"issue {blocker_repo}#{blocker_issue} not found")
    gh.rest("POST", f"{_issues(repo)}/{issue}/dependencies/blocked_by",
            body={"issue_id": int(blocker_id)}, operation_id=operation_id)

    after = {(b.get("repository", {}).get("full_name"), b.get("number"))
             for b in blockers(gh, repo, issue, include_closed=True)}
    if (blocker_repo, blocker_issue) not in after:
        raise Conflict(
            f"dependency on {blocker_repo}#{blocker_issue} did not take; "
            f"read-back does not show it")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None,
                    help="owner/name. Defaults to the repository the extension config declares.")
    ap.add_argument("--audit", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_link = sub.add_parser("link", help="Attach a child to a parent.")
    p_link.add_argument("--parent", type=int, required=True)
    p_link.add_argument("--child", type=int, required=True)

    p_block = sub.add_parser("block", help="Record that an issue is blocked.")
    p_block.add_argument("--issue", type=int, required=True)
    p_block.add_argument("--blocked-by", required=True,
                         metavar="[owner/repo#]number",
                         help="A blocker here, or in another repository.")

    p_show = sub.add_parser("show", help="Children and blockers of an issue.")
    p_show.add_argument("--issue", type=int, required=True)

    args = ap.parse_args()
    try:
        target = config.resolve_target(args.repo, getattr(args, "project", None))
        args.repo = target.repo
        if hasattr(args, "project"):
            args.project = target.project
    except config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    gh = GitHub(audit_path=args.audit, dry_run=args.dry_run)
    try:
        if args.cmd == "link":
            link = link_child(gh, args.repo, args.parent, args.child)
            print(json.dumps({
                "parent": link.parent, "child": link.child,
                "already_present": link.already_present}, indent=2))
        elif args.cmd == "block":
            spec = args.blocked_by
            repo, _, number = spec.rpartition("#") if "#" in spec else (args.repo, "", spec)
            added = add_blocker(gh, args.repo, args.issue, repo or args.repo, int(number))
            print(json.dumps({"issue": args.issue, "blocked_by": spec,
                              "added": added}, indent=2))
        else:
            print(json.dumps({
                "issue": args.issue,
                "children": children(gh, args.repo, args.issue),
                "parent": parent_of(gh, args.repo, args.issue),
                "blocked_by": [
                    f"{b.get('repository', {}).get('full_name')}#{b['number']}"
                    for b in blockers(gh, args.repo, args.issue)],
            }, indent=2))
        return 0
    except GitHubError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
