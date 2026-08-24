#!/usr/bin/env python3
"""Retire a Story that will not be delivered, or supersede one another carries.

Both close an item without delivering it, and `state-machine.yml` already had
the routes: `not_planned` for work decided against, `duplicate` for work another
item now carries. Both declare `set_output_done: false`, so neither invents a
delivery state the work did not earn -- which is the failure the whole closure
block exists to prevent.

Three refusals define this:

It will not retire without a reason. "Not needed" is a decision and the reason
is the only part a later reader can act on; a retirement with no reason is
indistinguishable from an abandonment.

It will not supersede without naming what carries the work. A superseded item
whose successor is unrecorded has lost the work rather than moved it, and
GitHub's own `duplicate` marking is meaningless without the reference.

It will not silently strand children. An item with live children is the case
most likely to lose work, so it is refused unless every child is already
closed, and the refusal names them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import project_root  # noqa: E402
import relationships  # noqa: E402
import yaml  # noqa: E402
from github_api import GitHub, GitHubError, NotFound  # noqa: E402

MACHINE_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/state-machine.yml",
    "policy/state-machine.yml",
)


def load_machine(root: Path | None = None) -> dict:
    base = root or project_root.resolve(required=False) or Path.cwd()
    for rel in MACHINE_CANDIDATES:
        candidate = base / rel
        if candidate.is_file():
            return yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    raise FileNotFoundError(
        "state-machine.yml not found; the governance preset must be installed")


def undelivered_routes(machine: dict) -> dict[str, str]:
    """Close reasons that end an item without delivering it, keyed by name.

    Read from the policy, so a route added there is available here without
    this file changing. A route requiring a delivery state is not one of these:
    completing work is what `transition` is for.
    """
    routes = {}
    for name, spec in (machine.get("closure") or {}).items():
        if isinstance(spec, dict) and spec.get("set_output_done") is False:
            reason = str(spec.get("close_reason") or name)
            routes[str(name)] = reason
    return routes


def open_children(gh: GitHub, repo: str, issue: int) -> list[int]:
    """Children not yet closed.

    Judged by issue state rather than delivery state: this is about work that
    would be orphaned, and an open child is orphaned whatever the board says.
    """
    out = []
    for child in relationships.children(gh, repo, issue):
        payload = gh.rest("GET", f"repos/{repo}/issues/{child}") or {}
        if payload.get("state") != "closed":
            out.append(child)
    return out


def problems(reason: str, route: str, routes: dict[str, str],
             superseded_by: int | None, issue: int,
             children_open: list[int]) -> list[str]:
    found: list[str] = []
    if route not in routes:
        found.append(
            f"{route!r} is not a route state-machine.yml declares for "
            f"undelivered work; it has {sorted(routes)}")
    if not (reason or "").strip():
        found.append(
            "no reason given. A retirement with no reason is "
            "indistinguishable from an abandonment, and the reason is the "
            "only part a later reader can act on.")
    if route == "duplicate" and superseded_by is None:
        found.append(
            "superseding needs --superseded-by naming the item that carries "
            "the work. Without it the work has been lost rather than moved.")
    if superseded_by is not None and superseded_by == issue:
        found.append(f"#{issue} cannot supersede itself")
    if children_open:
        found.append(
            f"#{issue} has open children {children_open}. Closing it would "
            f"leave them under an item that no longer carries work; close or "
            f"reparent them first.")
    return found


def body_note(route: str, reason: str, superseded_by: int | None) -> str:
    if superseded_by is not None:
        return (f"Superseded by #{superseded_by}.\n\n{reason.strip()}\n")
    return f"Retired ({route}).\n\n{reason.strip()}\n"


def retire(gh: GitHub, repo: str, issue: int, reason: str, route: str,
           superseded_by: int | None = None,
           machine: dict | None = None,
           operation_id: str | None = None) -> dict:
    machine = machine or load_machine()
    routes = undelivered_routes(machine)

    # Offline refusals first. A bad route or a missing reason is decidable
    # without the API, and spending a request to reject an invocation that
    # could never have worked is how a command becomes slow to be wrong.
    found = problems(reason, route, routes, superseded_by, issue, [])
    if found:
        return {"issue": issue, "action": "refused", "problems": found}

    found = problems(reason, route, routes, superseded_by, issue,
                     open_children(gh, repo, issue))
    if found:
        return {"issue": issue, "action": "refused", "problems": found}

    gh.rest("POST", f"repos/{repo}/issues/{issue}/comments",
            body={"body": body_note(route, reason, superseded_by)},
            operation_id=operation_id)
    if superseded_by is not None:
        gh.rest("POST", f"repos/{repo}/issues/{superseded_by}/comments",
                body={"body": f"Supersedes #{issue}.\n\n{reason.strip()}\n"})

    gh.rest("PATCH", f"repos/{repo}/issues/{issue}",
            body={"state": "closed", "state_reason": routes[route]})

    check = gh.rest("GET", f"repos/{repo}/issues/{issue}") or {}
    if check.get("state") != "closed" or check.get("state_reason") != routes[route]:
        raise GitHubError(
            f"retire of #{issue} did not take: read back state="
            f"{check.get('state')!r} reason={check.get('state_reason')!r}")
    return {
        "issue": issue, "action": "retired", "route": route,
        "state_reason": routes[route], "superseded_by": superseded_by,
        "reason": reason.strip(),
        # Stated so a reader never has to infer it: closing this way is
        # deliberately not a delivery.
        "delivery_state_unchanged": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None,
                    help="owner/name. Defaults to the configured repository.")
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--reason", default="",
                    help="Why. Required: the only part a later reader can act on.")
    ap.add_argument("--route", default="not_planned",
                    help="A closure route state-machine.yml declares for "
                         "undelivered work.")
    ap.add_argument("--superseded-by", type=int, default=None, metavar="N",
                    help="The item that now carries the work. Required with "
                         "--route duplicate.")
    ap.add_argument("--policy-root", type=Path, default=None)
    ap.add_argument("--audit", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        target = config.resolve_target(args.repo, None)
        args.repo = target.repo
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
    except (config.ConfigError, project_root.ProjectRootError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    gh = GitHub(audit_path=args.audit, dry_run=args.dry_run)
    try:
        result = retire(gh, args.repo, args.issue, args.reason, args.route,
                        args.superseded_by, load_machine(args.policy_root))
    except (GitHubError, NotFound) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 1 if result.get("action") == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
