#!/usr/bin/env python3
"""One read-only answer to "what is true here, and what do I run next".

Four commands already held the answer and none of them held all of it: the
doctor knows whether the project is wired, `transition_plan queue` knows what
is startable, `transition_plan audit` knows where the board contradicts the
policy, and only the audit compared any of it to the working tree. Assembling
those was four invocations and a mental join, which a newcomer cannot do and an
agent resuming after a break does not do.

This composes them. It establishes no fact of its own and it writes nothing --
every section is produced by the module that already owned it, called rather
than shelled out to and parsed back. That is the whole design constraint: a
status command that re-derived any of this would be a second implementation of
a rule, and the second copy is the one that drifts.

Two things it will not do.

It never reports a board state it could not read. An unwired project gets the
doctor's report and the reason the board was unreachable, and no queue and no
audit -- a status command that answered "0 startable" because it could not
reach GitHub would be worse than one that failed.

It never routes. `speckit.github-lifecycle.transition` performs transitions
behind a gate; repeating that decision here, one command earlier and without
the gate, is how a read-only report becomes a way to move the board.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import doctor  # noqa: E402
import project_root  # noqa: E402
import transition_plan as tp  # noqa: E402

from github_api import GitHubError  # noqa: E402


def working_tree(root: Path | None, in_progress: list[int] | None) -> dict:
    """What the working tree holds, and whether the board accounts for it.

    Three answers, not two. "Nothing changed" and "we could not look" are
    already distinguished by `modified_tracked_files`, which returns None when
    git cannot answer; this keeps that distinction and adds the one the audit
    could not express -- changes the board *does* account for, naming the items
    that account for them. An agent resuming mid-story needs that far more than
    it needs the drift warning, and the audit is silent in exactly that case
    because there is nothing wrong to report.
    """
    if root is None:
        return {"status": "unknown",
                "detail": "no project root, so the working tree was not read"}
    changed = tp.modified_tracked_files(root)
    if changed is None:
        return {"status": "unknown", "modified": None,
                "detail": "git could not answer, so the tree was not compared "
                          "against the board"}
    if not changed:
        return {"status": "clean", "modified": []}
    if in_progress is None:
        # The board was not read, so nothing here can be attributed to it.
        # Saying "drift" would be a claim about a board state we do not have.
        return {"status": "unattributed", "modified": changed,
                "detail": f"{len(changed)} tracked file(s) modified. The board "
                          f"was not read, so whether an item accounts for them "
                          f"is unknown."}
    if in_progress:
        return {"status": "accounted", "modified": changed,
                "in_progress": in_progress,
                "detail": f"{len(changed)} tracked file(s) modified, and "
                          f"{', '.join(f'#{n}' for n in in_progress)} "
                          f"{'is' if len(in_progress) == 1 else 'are'} "
                          f"{tp.START_STATE}."}
    return {"status": "drift", "modified": changed,
            "in_progress": [],
            "detail": tp.working_tree_disagreement(root, [])}


def collect(root: Path, repo: str | None = None, project: int | None = None,
            integration: str | None = None,
            target_size: int = tp.DEFAULT_QUEUE_TARGET) -> tuple[dict, int]:
    """The whole report, and the exit code that describes it.

    Exit 0 means the board was read, findings or not: the audit's own non-zero
    exit is a gate's answer, and status is not a gate. Exit 2 means the board
    could not be read, which is the one outcome a caller must not mistake for
    an empty board.
    """
    report: dict = {"root": str(root), "doctor": doctor.report(root, integration)}

    try:
        resolved = config.resolve_target(repo, project, root=root)
    except config.ConfigError as exc:
        report["target"] = None
        report["board"] = {"status": "unread", "reason": str(exc)}
        report["working_tree"] = working_tree(root, None)
        return report, 2

    report["target"] = {"repo": resolved.repo, "project": resolved.project,
                        "source": resolved.source}
    try:
        machine = tp.load_state_machine(root)
        gh, inspection, backend = tp.open_target(resolved.repo, resolved.project,
                                                 audit=None)
        entries = tp.ready_queue(gh, backend, inspection)
        # root=None deliberately: the working-tree rule is reported once,
        # under its own key, with the accounted case the audit cannot express.
        # Left in, the same sentence would appear twice in one output.
        findings = tp.audit_board(gh, backend, inspection, machine=machine,
                                  root=None)
    except (tp.PlanError, GitHubError, project_root.OutsideProjectError,
            OSError) as exc:
        report["board"] = {"status": "unread",
                           "reason": f"{type(exc).__name__}: {exc}"}
        report["working_tree"] = working_tree(root, None)
        return report, 2

    queue = tp.classify_queue(entries, target_size)
    report["board"] = {"status": "read"}
    report["queue"] = {
        "target": queue.target,
        "startable": [{"issue": e.issue, "item_type": e.item_type}
                      for e in queue.startable],
        "blocked": [{"issue": e.issue, "state": e.state,
                     "blocked_by": e.blocked_by} for e in queue.blocked],
        "refinable": [{"issue": e.issue, "state": e.state,
                       "item_type": e.item_type} for e in queue.refinable],
        "awaiting_decomposition": [{"issue": e.issue, "state": e.state,
                                    "item_type": e.item_type}
                                   for e in queue.awaiting],
        "advice": queue.advice,
    }
    report["audit"] = {
        "findings": [{"issue": f.issue, "problem": f.problem} for f in findings],
        "count": len(findings),
    }
    report["working_tree"] = working_tree(root, tp.in_progress_issues(entries))
    return report, 0


def render(report: dict) -> str:
    """The same fields as the JSON form, laid out for a person.

    Same fields, not a summary of them: a text form that dropped something the
    JSON carried would make `--format json` the only honest one, and then the
    default output is the one nobody can trust.
    """
    lines: list[str] = []
    doc = report["doctor"]
    target = report.get("target")
    board = report["board"]

    if target:
        project = f" project {target['project']}" if target["project"] else ""
        lines.append(f"Target: {target['repo']}{project} "
                     f"(from {target['source']})")
    else:
        lines.append("Target: unresolved")

    lines.append(f"Wiring: gh_auth={doc['gh_auth']['status']} "
                 f"repository={doc['repository']['status']} "
                 f"config={doc['config_source']} "
                 f"script_flavour={doc['script_flavour']['status']} "
                 f"integration={doc['integration']['integration'] or 'undeclared'}")
    missing = [b["binary"] for b in doc["binaries"]
               if b.get("status") == "missing"]
    if missing:
        lines.append(f"  missing binaries: {', '.join(missing)}")

    if board["status"] != "read":
        lines.append("")
        lines.append(f"Board: not read. {board['reason']}")
        lines.append("No queue and no audit follow: neither can be answered "
                     "without the board, and an empty one would read as an "
                     "empty board.")
    else:
        queue = report["queue"]
        lines.append("")
        lines.append(f"Startable now ({len(queue['startable'])}):")
        for e in queue["startable"]:
            lines.append(f"  #{e['issue']} [{e['item_type']}]")
        lines.append(f"\nBlocked ({len(queue['blocked'])}):")
        for e in queue["blocked"]:
            lines.append(f"  #{e['issue']} [{e['state']}] blocked by "
                         f"{', '.join(e['blocked_by'])}")
        lines.append(f"\nSafe to refine ahead ({len(queue['refinable'])}):")
        for e in queue["refinable"]:
            lines.append(f"  #{e['issue']} [{e['state']}] {e['item_type']}")
        lines.append(f"\nAwaiting decomposition "
                     f"({len(queue['awaiting_decomposition'])}):")
        for e in queue["awaiting_decomposition"]:
            lines.append(f"  #{e['issue']} [{e['state']}] {e['item_type']}")
        lines.append(f"\n{queue['advice']}")

        audit = report["audit"]
        lines.append(f"\nAudit ({audit['count']} inconsistencies):")
        for f in audit["findings"]:
            where = f"#{f['issue']}" if f["issue"] is not None else "working tree"
            lines.append(f"  {where}: {f['problem']}")

    tree = report["working_tree"]
    lines.append(f"\nWorking tree: {tree['status']}")
    if tree.get("detail"):
        lines.append(f"  {tree['detail']}")
    for name in (tree.get("modified") or [])[:5]:
        lines.append(f"  {name}")
    extra = len(tree.get("modified") or []) - 5
    if extra > 0:
        lines.append(f"  and {extra} more")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None,
                    help="owner/name. Defaults to the repository the extension config declares.")
    ap.add_argument("--project", type=int, default=None)
    ap.add_argument("--integration", default=None,
                    help="Override the integration doctor reports on. Without "
                         "it the project's own integration.json decides.")
    ap.add_argument("--target", type=int, default=tp.DEFAULT_QUEUE_TARGET,
                    help="Desired number of startable items.")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
    args = ap.parse_args()

    try:
        root = project_root.resolve(args.policy_root, required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report, code = collect(root, args.repo, args.project, args.integration,
                           args.target)
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(render(report))
    return code


if __name__ == "__main__":
    sys.exit(main())
