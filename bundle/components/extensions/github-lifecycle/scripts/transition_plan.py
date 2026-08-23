#!/usr/bin/env python3
"""Plan and apply exactly one lifecycle transition.

Split deliberately: planning reads and decides, applying writes what was
decided. A plan is a durable artifact a human approves, which is what makes the
approval reviewable rather than a prompt someone clicked past.

The safety properties, in the order they matter:

A plan records the state it observed. Applying re-reads and refuses if the
value has moved since — a plan built from a stale read must not overwrite
someone else's change.

A transition must be legal. `state-machine.yml` defines the edges, and one that
is not listed is refused rather than allowed because the target looks
plausible.

Nothing infers completion from issue state. There is no code path from an
issue being closed to a delivery state, which is what
`infer_output_done_from_closed_issue: false` requires. A check that merely
warns would still be a path.

Exactly one field and one value per plan. A plan that could change two things
cannot be approved for one of them.

Named `transition_plan` rather than `plan`: a module named `plan.py` in a
directory first on `sys.path` is a collision waiting to happen, and this
package already lost a day to `inspect.py` shadowing the standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from field_backend import FieldBackend, for_inspection  # noqa: E402
from github_api import Conflict, Forbidden, GitHub, GitHubError, NotFound  # noqa: E402
from inspect_target import Inspection, inspect  # noqa: E402

PLAN_BLOCK = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)


class PlanError(GitHubError):
    """The plan is unusable: malformed, stale, or for a different target."""


@dataclass(frozen=True)
class TransitionPlan:
    plan_id: str
    issue: str
    role: str
    observed: str | None
    target: str
    field_name: str
    authority: str
    evidence_required: list[str]
    operation_id: str

    def to_yaml(self) -> str:
        return yaml.safe_dump(asdict(self), sort_keys=False, default_flow_style=False)

    def to_markdown(self) -> str:
        ev = "\n".join(f"- {e}" for e in self.evidence_required) or "- (none)"
        return (
            f"# Transition plan {self.plan_id}\n\n"
            f"Move **{self.issue}** {self.role} from "
            f"`{self.observed}` to `{self.target}`.\n\n"
            f"Writes exactly one value: the `{self.field_name}` field.\n\n"
            f"## Authority required\n\n`{self.authority}`\n\n"
            f"## Evidence required\n\n{ev}\n\n"
            f"## Machine-readable plan\n\n"
            f"```yaml\n{self.to_yaml().rstrip()}\n```\n\n"
            f"Applying re-reads the current value and refuses if it is no "
            f"longer `{self.observed}`.\n"
        )

    @classmethod
    def from_markdown(cls, text: str) -> "TransitionPlan":
        match = PLAN_BLOCK.search(text)
        if not match:
            raise PlanError("plan file contains no machine-readable yaml block")
        data = yaml.safe_load(match.group(1)) or {}
        missing = {f for f in cls.__dataclass_fields__} - set(data)
        if missing:
            raise PlanError(f"plan is missing {sorted(missing)}")
        return cls(**{k: data[k] for k in cls.__dataclass_fields__})


def load_state_machine(root: Path) -> dict:
    """The installed policy, not a copy compiled into this script."""
    for candidate in (
        root / ".specify/presets/lean-full-lifecycle-governance/policy/state-machine.yml",
        root / "policy/state-machine.yml",
    ):
        if candidate.is_file():
            return yaml.safe_load(candidate.read_text(encoding="utf-8"))
    raise PlanError(
        "state-machine.yml not found; the governance preset must be installed"
    )


def find_transition(machine: dict, current: str | None, target: str) -> dict:
    values = machine["delivery_status"]["values"]
    if target not in values:
        raise PlanError(f"{target!r} is not a delivery status; known: {values}")
    for edge in machine["delivery_status"]["transitions"]:
        if edge.get("from") == current and edge["to"] == target:
            return edge
    legal = [e["to"] for e in machine["delivery_status"]["transitions"]
             if e.get("from") == current]
    raise PlanError(
        f"{current!r} -> {target!r} is not a legal transition. "
        f"From {current!r} the legal targets are {legal or ['(none)']}."
    )


def operation_id(issue: str, role: str, observed: str | None, target: str) -> str:
    """Stable for one intent, so a retry is detectable and a re-run is not."""
    digest = hashlib.sha256(
        f"{issue}|{role}|{observed}|{target}".encode("utf-8")
    ).hexdigest()
    return f"tr-{digest[:16]}"


TERMINAL_STATE = "Output Done"


def child_issue_numbers(gh: GitHub, owner: str, repo: str, issue_number: int) -> list[int]:
    rows = gh.rest("GET", f"repos/{owner}/{repo}/issues/{issue_number}/sub_issues",
                   paginate=True) or []
    if isinstance(rows, dict):
        rows = [rows]
    return [int(r["number"]) for r in rows if r.get("number") is not None]


def incomplete_children(gh: GitHub, backend: FieldBackend, inspection: Inspection,
                        issue_number: int, role: str) -> list[tuple[int, str | None]]:
    """Children not yet in the terminal delivery state.

    Judged by delivery state, never by whether the child's issue is closed.
    GitHub's sub_issues_summary counts closures, and a child closed as a
    duplicate has not been delivered -- enforcing the rule with that evidence
    would let a parent complete over abandoned work.
    """
    out: list[tuple[int, str | None]] = []
    for number in child_issue_numbers(gh, inspection.owner, inspection.repo, issue_number):
        try:
            value = backend.read(number, role).value
        except NotFound:
            # Not on the board: it has no delivery state, so it cannot be done.
            value = None
        if value != TERMINAL_STATE:
            out.append((number, value))
    return out


def build_plan(backend: FieldBackend, inspection: Inspection, machine: dict,
               issue_number: int, target: str, role: str = "delivery_state",
               gh: GitHub | None = None) -> TransitionPlan:
    current = backend.read(issue_number, role)
    edge = find_transition(machine, current.value, target)

    if target == TERMINAL_STATE and gh is not None:
        blocking = incomplete_children(gh, backend, inspection, issue_number, role)
        if blocking:
            listed = ", ".join(f"#{n} ({v or 'not on the board'})" for n, v in blocking)
            raise PlanError(
                f"cannot complete #{issue_number}: its progress derives from its "
                f"children, and these are not {TERMINAL_STATE}: {listed}"
            )
    issue = f"{inspection.owner}/{inspection.repo}#{issue_number}"
    # Fail here rather than at apply time if the target is not a real option.
    inspection.field_for(role).option_id(target)
    return TransitionPlan(
        plan_id=operation_id(issue, role, current.value, target).replace("tr-", "plan-"),
        issue=issue,
        role=role,
        observed=current.value,
        target=target,
        field_name=current.field_name,
        authority=str(edge["authority"]),
        evidence_required=[str(e) for e in edge.get("evidence") or []],
        operation_id=operation_id(issue, role, current.value, target),
    )


def apply_plan(backend: FieldBackend, inspection: Inspection, plan: TransitionPlan,
               evidence: dict[str, str], *, machine: dict) -> Any:
    expected_issue_prefix = f"{inspection.owner}/{inspection.repo}#"
    if not plan.issue.startswith(expected_issue_prefix):
        raise PlanError(
            f"plan targets {plan.issue!r}, but this run inspected "
            f"{inspection.owner}/{inspection.repo}"
        )
    issue_number = int(plan.issue.rsplit("#", 1)[1])

    missing = [e for e in plan.evidence_required if e not in evidence]
    if missing:
        raise Forbidden(
            f"evidence required by {plan.authority!r} not asserted: {missing}"
        )

    # Re-validate against policy: a plan can outlive a policy change.
    find_transition(machine, plan.observed, plan.target)

    current = backend.read(issue_number, plan.role)
    if current.value == plan.target:
        # Already where the plan intended. Re-running an applied transition
        # changes nothing rather than reporting drift: the plan's purpose is
        # served, and refusing here would make retry-after-timeout unusable.
        return current
    if current.value != plan.observed:
        raise Conflict(
            f"plan is stale: it observed {plan.observed!r} but {plan.issue} "
            f"{plan.role} is now {current.value!r}. Re-plan rather than "
            f"overwrite a change this plan did not account for."
        )
    return backend.write(issue_number, plan.role, plan.target,
                         operation_id=plan.operation_id)


@dataclass(frozen=True)
class Inconsistency:
    issue: int
    problem: str

    def __str__(self) -> str:
        return f"#{self.issue}: {self.problem}"


def audit_board(gh: GitHub, backend: FieldBackend, inspection: Inspection,
                role: str = "delivery_state") -> list[Inconsistency]:
    """Board state that contradicts the policy.

    The transition command enforces these for anyone who uses it, but
    `gh issue close` and the project UI both bypass it. Reports rather than
    repairs: repairing silently would hide how the drift happened, and the
    drift is the interesting part.
    """
    found: list[Inconsistency] = []
    issues = gh.rest(
        "GET", f"repos/{inspection.owner}/{inspection.repo}/issues?state=all",
        paginate=True,
    ) or []
    if isinstance(issues, dict):
        issues = [issues]

    for issue in issues:
        number = issue.get("number")
        if number is None or issue.get("pull_request"):
            continue
        try:
            value = backend.read(int(number), role).value
        except NotFound:
            continue                      # not on the board; not this check's concern

        if value is None:
            found.append(Inconsistency(number, "on the board with no delivery state"))
            continue
        if issue.get("state") == "closed" and value != TERMINAL_STATE:
            found.append(Inconsistency(
                number,
                f"closed while delivery state is {value!r}. "
                f"Closure follows completion; it cannot precede it."))
        if value == TERMINAL_STATE:
            blocking = incomplete_children(gh, backend, inspection, int(number), role)
            if blocking:
                listed = ", ".join(f"#{n} ({v or 'not on the board'})" for n, v in blocking)
                found.append(Inconsistency(
                    number,
                    f"is {TERMINAL_STATE} but these children are not: {listed}"))
    return found


def _setup(repo: str, project: int | None, audit: Path | None, dry_run: bool = False):
    owner, _, name = repo.partition("/")
    if not owner or not name:
        raise PlanError("--repo must be owner/name")
    gh = GitHub(audit_path=audit, dry_run=dry_run)
    inspection = inspect(gh, owner, name, project)
    if not inspection.usable:
        raise PlanError(
            f"target is not usable: missing={inspection.missing_roles} "
            f"ambiguities={inspection.ambiguities}"
        )
    return gh, inspection, for_inspection(gh, inspection)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--project", type=int, default=None)
    ap.add_argument("--audit", type=Path, default=None)
    ap.add_argument("--policy-root", type=Path, default=Path.cwd())
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="Write a transition plan. Reads only.")
    p_plan.add_argument("--issue", type=int, required=True)
    p_plan.add_argument("--to", required=True)
    p_plan.add_argument("--role", default="delivery_state")
    p_plan.add_argument("--out", type=Path, required=True)

    p_apply = sub.add_parser("apply", help="Apply an approved plan.")
    p_apply.add_argument("--plan", type=Path, required=True)
    p_apply.add_argument("--evidence", action="append", default=[],
                         metavar="KEY=VALUE",
                         help="Assert one required evidence item. Repeatable.")
    p_apply.add_argument("--dry-run", action="store_true")

    sub.add_parser("audit", help="Report board state that contradicts the policy.")

    args = ap.parse_args()
    try:
        machine = load_state_machine(args.policy_root)
        gh, inspection, backend = _setup(
            args.repo, args.project, args.audit,
            dry_run=getattr(args, "dry_run", False),
        )

        if args.cmd == "plan":
            plan = build_plan(backend, inspection, machine, args.issue,
                              args.to, args.role, gh=gh)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(plan.to_markdown(), encoding="utf-8")
            print(f"Write exactly {args.out}")
            print(plan.to_yaml())
            return 0

        if args.cmd == "audit":
            problems = audit_board(gh, backend, inspection)
            for item in problems:
                print(item)
            print(f"\n{len(problems)} inconsistencies")
            return 1 if problems else 0

        plan = TransitionPlan.from_markdown(args.plan.read_text(encoding="utf-8"))
        evidence = dict(
            item.split("=", 1) if "=" in item else (item, "asserted")
            for item in args.evidence
        )
        result = apply_plan(backend, inspection, plan, evidence, machine=machine)
        print(json.dumps({
            "issue": plan.issue, "role": plan.role,
            "from": plan.observed, "to": result.value,
            "operation_id": plan.operation_id,
            "audit": [a.outcome for a in gh.audit],
        }, indent=2))
        return 0
    except (PlanError, NotFound, Conflict, Forbidden) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
