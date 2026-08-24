#!/usr/bin/env python3
"""Rolling-wave decomposition: enough children to fill the horizon, no more.

The horizon is a **target count of Ready children**, not a time window. That
choice matters: it makes the amount of planning depend on how much work is
actually startable rather than on the calendar, which is what a Ready queue
exists to regulate.

It also makes decomposition and refinement cooperate rather than compete.
Creating children does not fill the queue — only refining them to Ready does —
so an Epic whose children are all Inbox has not met its target and correctly
invites more refinement rather than more decomposition.

Proposing is separate from creating. Creation is the least reversible thing
this extension does, so it happens only against an approved proposal file.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

import capture as capture_mod  # noqa: E402
import relationships  # noqa: E402
from field_backend import FieldBackend, for_inspection  # noqa: E402
from github_api import GitHub, GitHubError, NotFound  # noqa: E402
from inspect_target import Inspection, inspect  # noqa: E402

READY = "Ready"
TERMINAL = "Output Done"


@dataclass
class Horizon:
    epic: int
    target: int
    children: dict[int, str | None] = field(default_factory=dict)

    @property
    def ready(self) -> list[int]:
        return [n for n, state in self.children.items() if state == READY]

    @property
    def done(self) -> list[int]:
        return [n for n, state in self.children.items() if state == TERMINAL]

    @property
    def in_flight(self) -> list[int]:
        return [n for n, state in self.children.items()
                if state not in (READY, TERMINAL, None)]

    @property
    def shortfall(self) -> int:
        return max(0, self.target - len(self.ready))

    @property
    def met(self) -> bool:
        return self.shortfall == 0

    def to_dict(self) -> dict:
        return {
            "epic": self.epic, "target": self.target,
            "children": {str(k): v for k, v in self.children.items()},
            "ready": self.ready, "done": self.done, "in_flight": self.in_flight,
            "shortfall": self.shortfall, "horizon_met": self.met,
            "advice": self._advice(),
        }

    def _advice(self) -> str:
        if self.met:
            return (f"Horizon met: {len(self.ready)} Ready children. "
                    f"Decompose no further.")
        unrefined = [n for n, s in self.children.items()
                     if s not in (READY, TERMINAL, None)]
        if len(unrefined) >= self.shortfall:
            return (f"{self.shortfall} short, but {len(unrefined)} existing "
                    f"children are not yet Ready. Refine those before creating "
                    f"more; decomposition does not fill the queue, refinement "
                    f"does.")
        return (f"{self.shortfall} short and only {len(unrefined)} unrefined "
                f"children exist. Propose up to "
                f"{self.shortfall - len(unrefined)} more.")


def read_horizon(gh: GitHub, backend: FieldBackend, inspection: Inspection,
                 epic: int, target: int) -> Horizon:
    repo = f"{inspection.owner}/{inspection.repo}"
    horizon = Horizon(epic=epic, target=target)
    for number in relationships.children(gh, repo, epic):
        try:
            horizon.children[number] = backend.read(number, "delivery_state").value
        except NotFound:
            horizon.children[number] = None
    return horizon


@dataclass(frozen=True)
class Proposal:
    title: str
    body: str
    type: str = "story"


def load_proposals(path: Path) -> list[Proposal]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("proposals") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("proposal file must hold a list under 'proposals'")
    return [Proposal(title=r["title"], body=r.get("body", ""),
                     type=r.get("type", "story")) for r in rows]


def apply_proposals(gh: GitHub, backend: FieldBackend, inspection: Inspection,
                    epic: int, target: int, proposals: list[Proposal],
                    threshold: float = capture_mod.DEFAULT_THRESHOLD) -> dict:
    repo = f"{inspection.owner}/{inspection.repo}"
    horizon = read_horizon(gh, backend, inspection, epic, target)

    if horizon.met:
        return {"created": [], "skipped": [], "horizon": horizon.to_dict(),
                "action": "none", "reason": horizon._advice()}

    created, skipped = [], []
    # Never create more than the horizon needs, whatever was proposed.
    allowance = horizon.shortfall
    for proposal in proposals:
        if len(created) >= allowance:
            skipped.append({"title": proposal.title,
                            "reason": "beyond the horizon; deliberately left undecomposed"})
            continue
        duplicates = capture_mod.search_duplicates(gh, repo, proposal.title, threshold)
        if duplicates:
            skipped.append({"title": proposal.title,
                            "reason": f"candidate duplicate of #{duplicates[0].number}"})
            continue
        missing = capture_mod.has_evidence(proposal.body, proposal.type)
        if missing:
            skipped.append({"title": proposal.title,
                            "reason": f"a {proposal.type} needs {missing}"})
            continue
        item = capture_mod.create_item(gh, repo, proposal.title, proposal.body,
                                       proposal.type,
                                       project=inspection.project_number)
        if item.get("dry_run"):
            created.append(item)
            continue
        relationships.link_child(gh, repo, epic, item["number"])
        # Read back the link rather than trusting either write. An orphaned
        # child is worse than none: it exists, and nothing derives from it.
        if item["number"] not in relationships.children(gh, repo, epic):
            raise GitHubError(
                f"created #{item['number']} but it is not a child of #{epic}")
        created.append(item)

    after = read_horizon(gh, backend, inspection, epic, target)
    return {
        "created": created, "skipped": skipped,
        "horizon": after.to_dict(),
        "action": "created" if created else "none",
        "undecomposed": [s["title"] for s in skipped
                         if "beyond the horizon" in s["reason"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None,
                    help="owner/name. Defaults to the repository the extension config declares.")
    ap.add_argument("--project", type=int, default=None)
    ap.add_argument("--epic", type=int, required=True)
    ap.add_argument("--target", type=int, default=3,
                    help="Desired count of Ready children.")
    ap.add_argument("--audit", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Report the horizon. Reads only.")

    p_apply = sub.add_parser("apply", help="Create approved children.")
    p_apply.add_argument("--proposals", type=Path, required=True)
    p_apply.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()
    try:
        target = config.resolve_target(args.repo, getattr(args, "project", None))
        args.repo = target.repo
        if hasattr(args, "project"):
            args.project = target.project
    except config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    owner, _, name = args.repo.partition("/")
    gh = GitHub(audit_path=args.audit, dry_run=getattr(args, "dry_run", False))
    try:
        inspection = inspect(gh, owner, name, args.project)
        if not inspection.usable:
            print(f"target is not usable: {inspection.missing_roles} "
                  f"{inspection.ambiguities}", file=sys.stderr)
            return 1
        backend = for_inspection(gh, inspection)

        if args.cmd == "status":
            print(json.dumps(
                read_horizon(gh, backend, inspection, args.epic, args.target).to_dict(),
                indent=2))
            return 0

        proposals = load_proposals(args.proposals)
        result = apply_proposals(gh, backend, inspection, args.epic,
                                 args.target, proposals)
        print(json.dumps(result, indent=2))
        return 0
    except (GitHubError, ValueError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
