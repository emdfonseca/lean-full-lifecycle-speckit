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
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import project_root  # noqa: E402
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

# Where a disposal record is expected. Searched rather than configured: a
# configurable location is one more thing to get wrong on the path that already
# refuses four ways.
DISPOSAL_DIR = ".specify/lifecycle/disposal"
# Markers in an issue that say uncertainty work informed it.
UNCERTAINTY_MARKERS = ("prototype", "spike")


def disposal_required(current_state: str | None, issue_number: int,
                      inspection: Inspection, gh: GitHub | None,
                      root: Path | None = None,
                      uncertainty_mode: str | None = None) -> bool:
    """True when this item was informed by a prototype or spike and has no record.

    Two sources, because one of them missed the case the guard exists for.

    The run's own `uncertainty_mode`. A story labelled `story` and run with
    `uncertainty_mode: prototype` builds a prototype and never triggered this,
    which is exactly the item most likely to ship prototype code -- the label
    describes what the item is, not what the run did.

    And the item's labels, which catch a prototype whose disposal is being
    skipped in a later run that declares no mode at all. A label is a decision
    somebody made, and prose is not.
    """
    if str(uncertainty_mode or "").strip().lower() in UNCERTAINTY_MARKERS:
        return not _disposal_recorded(issue_number, root)
    if gh is None:
        return False
    try:
        issue = gh.rest(
            "GET", f"repos/{inspection.owner}/{inspection.repo}/issues/{issue_number}"
        ) or {}
    except GitHubError:
        return False
    if not isinstance(issue, dict):
        # A response that is not an issue cannot say the item came from a
        # prototype. Refusing completion on that basis would block the
        # transition for a reason unrelated to disposal.
        return False
    labels = {str(lbl.get("name", "")).lower()
              for lbl in issue.get("labels") or [] if isinstance(lbl, dict)}
    if not labels.intersection(UNCERTAINTY_MARKERS):
        return False
    return not _disposal_recorded(issue_number, root)


def _disposal_recorded(issue_number: int, root: Path | None) -> bool:
    directory = (Path(root) if root else Path.cwd()) / DISPOSAL_DIR
    if not directory.is_dir():
        return False
    return any(directory.glob(f"*{issue_number}*"))


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
               gh: GitHub | None = None,
               uncertainty_mode: str | None = None) -> TransitionPlan:
    current = backend.read(issue_number, role)
    edge = find_transition(machine, current.value, target)

    if target == TERMINAL_STATE and disposal_required(
            current.value, issue_number, inspection, gh,
            uncertainty_mode=uncertainty_mode):
        raise PlanError(
            f"#{issue_number} was informed by a prototype or spike, and no "
            f"disposal record was found. artifact-policy.yml classes those "
            f"artifacts ephemeral with promotion only by explicit decision; "
            f"completing without deciding is how prototype code becomes "
            f"production code by default. Record a disposal at "
            f"{DISPOSAL_DIR}/<id>.md.")

    if target == START_STATE and gh is not None:
        waiting = unfinished_blockers(gh, backend, inspection, issue_number, role)
        if waiting:
            listed = ", ".join(f"{name} ({state})" for name, state in waiting)
            raise PlanError(
                f"cannot start #{issue_number}: it is blocked by {listed}. "
                f"state-machine.yml already says an item Ready and blocked "
                f"claims to be startable and is not; with teams working in "
                f"parallel that ordering is what keeps one from building on "
                f"something that has not landed.")

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
    # Presence was the whole check, so `--evidence required_ci_green=false`
    # passed exactly as `=true` did. A key whose value denies the thing the key
    # names is not an assertion, and reading it as one is worse than not asking.
    denied = sorted(e for e in plan.evidence_required
                    if str(evidence[e]).strip().lower() in DENIALS)
    if denied:
        raise Forbidden(
            f"evidence asserted as false: {denied}. Supply the evidence or do "
            f"not make the transition; a recorded denial is not an approval."
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


def states_asserting_work(machine: dict) -> list[str]:
    """Delivery states that claim somebody is working on the item right now.

    Everything that is neither the entry state nor a terminal one. `Inbox`
    asserts nothing beyond existence, `Output Done` asserts completion and
    `Retired` asserts abandonment, so a closed item resting at any of those
    says nothing false. The states in between say work is under way, which a
    closed item cannot make true.

    Terminal states are read from the machine, not counted from the end. This
    was `values[1:-1]`, which silently encoded "one terminal, and it is last";
    adding `Retired` made `Output Done` assert work and would have flagged
    every completed item (#160).

    Still derived rather than named here, for the reason
    `closure_exempt_reasons` gives: a second copy of the policy is the copy
    that drifts.
    """
    values = list(machine["delivery_status"]["values"])
    terminal = set(machine["delivery_status"].get("terminal_states") or values[-1:])
    entry = values[0]
    return [v for v in values if v != entry and v not in terminal]


def closure_exempt_reasons(machine: dict) -> set[str]:
    """Close reasons that do not require the terminal delivery state.

    Derived from `state-machine.yml`'s `closure` block rather than listed here.
    A route declaring `set_output_done: false` closes work that never reached
    Output Done and must not be made to -- requiring a delivery state the work
    did not earn is how a board starts recording fiction.

    Exemption is the allowlist, not the denylist. A reason the policy has not
    considered is reported and looked at rather than silently permitted because
    nobody wrote it down, which is the conservative direction for a rule whose
    whole job is to notice a board that stopped being true.
    """
    exempt = set()
    for route in (machine.get("closure") or {}).values():
        if not isinstance(route, dict):
            continue
        if route.get("set_output_done") is False:
            name = str(route.get("close_reason") or "")
            if name:
                exempt.add(name)
    return exempt


@dataclass(frozen=True)
class Inconsistency:
    issue: int | None
    problem: str

    def __str__(self) -> str:
        # `None` is the working tree rather than an issue. The audit compared
        # the board to the policy and never to what had actually been built,
        # so the one finding that is about no single item needed somewhere to
        # live.
        where = f"#{self.issue}" if self.issue is not None else "working tree"
        return f"{where}: {self.problem}"


def audit_board(gh: GitHub, backend: FieldBackend, inspection: Inspection,
                role: str = "delivery_state",
                machine: dict | None = None,
                root: Path | None = None) -> list[Inconsistency]:
    """Board state that contradicts the policy.

    The transition command enforces these for anyone who uses it, but
    `gh issue close` and the project UI both bypass it. Reports rather than
    repairs: repairing silently would hide how the drift happened, and the
    drift is the interesting part.

    The delivery states are ordered by `state-machine.yml`, not by constants
    here, because "further along than" is a fact about the policy and a second
    copy of that order is the copy that drifts.
    """
    found: list[Inconsistency] = []
    machine = machine or load_state_machine(
        project_root.resolve(None, required=False) or Path.cwd())
    values = machine["delivery_status"]["values"]
    exempt_reasons = closure_exempt_reasons(machine)
    asserts_work = set(states_asserting_work(machine))
    issues = gh.rest(
        "GET", f"repos/{inspection.owner}/{inspection.repo}/issues?state=all",
        paginate=True,
    ) or []
    if isinstance(issues, dict):
        issues = [issues]

    in_progress: list[int] = []
    for issue in issues:
        number = issue.get("number")
        if number is None or issue.get("pull_request"):
            continue
        try:
            value = backend.read(int(number), role).value
        except NotFound:
            continue                      # not on the board; not this check's concern

        if value == START_STATE and issue.get("state") != "closed":
            in_progress.append(int(number))
        if value is None:
            found.append(Inconsistency(number, "on the board with no delivery state"))
            continue
        if issue.get("state") == "closed" and value != TERMINAL_STATE:
            reason = str(issue.get("state_reason") or "completed")
            # Only the routes the policy says require delivery. Reporting a
            # not_planned closure would report the policy's own sanctioned
            # route as a contradiction of the policy.
            if reason not in exempt_reasons:
                found.append(Inconsistency(
                    number,
                    f"closed as {reason!r} while delivery state is {value!r}. "
                    f"Closure follows completion; it cannot precede it."))
            elif value in asserts_work:
                # Exempt from reaching Output Done, which is the policy's own
                # route, and not exempt from leaving a state that claims
                # somebody is working. Those were one exemption and are two
                # claims (#139).
                found.append(Inconsistency(
                    number,
                    f"closed as {reason!r} and left at {value!r}, which claims "
                    f"work is under way. The closure is correct and the column "
                    f"is not: nothing is being done to a closed item."))
        if value == "Ready":
            blocking = blockers(gh, inspection.owner, inspection.repo, int(number))
            if blocking:
                named = ", ".join(
                    f"{b.get('repository', {}).get('full_name', '?')}#{b['number']}"
                    for b in blocking)
                found.append(Inconsistency(
                    number,
                    f"is Ready but blocked by {named}. It claims to be "
                    f"startable and is not."))
        is_epic = item_type_of(issue, {"epic"}) == "epic"
        if is_epic or value == TERMINAL_STATE:
            # Read children only when a rule could use them. For every other
            # item this costs nothing, which is why the gate is here and not
            # inside the rule.
            problem = parent_disagreement(
                values, value,
                child_states(gh, backend, inspection, int(number), role),
                is_epic)
            if problem:
                found.append(Inconsistency(number, problem))

    drift = working_tree_disagreement(root, in_progress)
    if drift:
        found.append(Inconsistency(None, drift))
    return found


def modified_tracked_files(root: Path) -> list[str] | None:
    """Tracked files with uncommitted changes, or None if git cannot answer.

    None rather than an empty list when git is unavailable or the directory is
    not a repository: "nothing changed" and "we could not look" are different
    answers, and reporting the second as the first is how a check quietly
    stops working.

    Untracked files are excluded. A scratch file is not evidence that delivery
    began, and counting it would make the rule fire constantly and then be
    ignored.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def working_tree_disagreement(root: Path | None,
                              in_progress: list[int]) -> str | None:
    """Work that has been built while the board says nothing was started.

    The audit's other rules compare the board to the policy. This one compares
    it to the working tree, which is the comparison that was missing: the board
    records what is claimed and the tree records what was done, and nothing
    reconciled them.

    Reports rather than prevents. #99 established that an events guard is not
    installable by the bundle, so refusing the commit is not available; saying
    the two disagree is.
    """
    if root is None:
        return None
    changed = modified_tracked_files(root)
    if not changed:
        return None
    if in_progress:
        return None
    listed = ", ".join(sorted(changed)[:5])
    more = f" and {len(changed) - 5} more" if len(changed) > 5 else ""
    return (f"{len(changed)} tracked file(s) modified while no item is "
            f"{START_STATE}: {listed}{more}. `Ready` -> `{START_STATE}` takes "
            f"the evidence `work_started`, which means nothing if the work "
            f"started first. Move the item, or say which item this is.")


def blockers(gh: GitHub, owner: str, repo: str, issue_number: int) -> list[dict]:
    """Unresolved issues this one is blocked by, in any repository.

    Dependencies take a global issue id, so a blocker may live in another
    project. That is the case this exists for: work waiting on a dependency
    nobody here can schedule.
    """
    rows = gh.rest("GET", f"repos/{owner}/{repo}/issues/{issue_number}/dependencies/blocked_by",
                   paginate=True)
    if rows is None:
        # An empty list means no blockers; nothing means we could not look.
        # Treating the second as the first is how this check quietly stops
        # working, and it is the exact failure P9 hit five times.
        raise PlanError(
            f"the blockers of #{issue_number} could not be determined. Nothing "
            f"is permitted to start on an unread dependency list.")
    if isinstance(rows, dict):
        rows = [rows]
    return [r for r in rows if r.get("state") != "closed"]


START_STATE = "In Progress"


def unfinished_blockers(gh: GitHub, backend: FieldBackend,
                        inspection: Inspection, issue_number: int,
                        role: str = "delivery_state") -> list[tuple[str, str]]:
    """Blockers that have not been delivered, named with why they still block.

    A blocker in this repository is judged by delivery state, the same way a
    child is: an issue closed as a duplicate has not been delivered, and one at
    Output Done has been whether or not somebody has closed it yet.

    A blocker in another repository has no delivery state we can read -- its
    board is not ours -- so closure is the only signal available. The refusal
    says which of the two answered, because a reader who does not know that
    cannot tell what would clear it.
    """
    out: list[tuple[str, str]] = []
    here = f"{inspection.owner}/{inspection.repo}"
    for row in blockers(gh, inspection.owner, inspection.repo, issue_number):
        full = (row.get("repository") or {}).get("full_name") or here
        number = int(row["number"])
        if full != here:
            out.append((f"{full}#{number}", "open (its board is not ours to read)"))
            continue
        try:
            value = backend.read(number, role).value
        except NotFound:
            value = None
        if value != TERMINAL_STATE:
            out.append((f"#{number}", value or "not on the board"))
    return out


@dataclass(frozen=True)
class ChildState:
    """One child's delivery state, and what stops it moving if anything."""

    number: int
    state: str | None
    blocked_by: str | None

    @property
    def delivered(self) -> bool:
        return self.state == TERMINAL_STATE

    @property
    def movable(self) -> bool:
        """Able to advance today.

        Delivered children have stopped on purpose and blocked ones cannot
        move at all. Everything else can: an item in Refining is being
        refined, and refinement is progress even though nothing is built yet.
        """
        return not self.delivered and self.blocked_by is None

    def describe(self) -> str:
        if self.delivered:
            return f"#{self.number} (delivered)"
        if self.blocked_by:
            return f"#{self.number} (blocked by {self.blocked_by})"
        return f"#{self.number} ({self.state or 'not on the board'})"


def child_states(gh: GitHub, backend: FieldBackend, inspection: Inspection,
                 issue_number: int, role: str = "delivery_state") -> list[ChildState]:
    """Every child's delivery state and what blocks it, read once.

    Blockers are judged the way `unfinished_blockers` judges them -- by
    delivery state in this repository, by closure elsewhere -- so a blocker
    sitting at Output Done but not yet closed correctly stops blocking. A
    delivered child is not asked about blockers: nothing can block work that
    is finished, and asking would spend a request per child to learn it.
    """
    out: list[ChildState] = []
    for number in child_issue_numbers(gh, inspection.owner, inspection.repo, issue_number):
        try:
            value = backend.read(number, role).value
        except NotFound:
            value = None
        if value == TERMINAL_STATE:
            out.append(ChildState(number, value, None))
            continue
        waiting = unfinished_blockers(gh, backend, inspection, number, role)
        out.append(ChildState(
            number, value,
            ", ".join(name for name, _ in waiting) if waiting else None))
    return out


def parent_disagreement(values: list[str], claimed: str,
                        children: list[ChildState], is_epic: bool) -> str | None:
    """How a parent's own delivery state contradicts its children's, or None.

    One rule rather than one per angle. Overstating and understating are the
    same error measured in opposite directions, and separate rules examining
    one relationship drift apart the first time any of them changes -- which
    is exactly what happened between #87 and #96.

    The scope is not uniform, and pretending it were would be the drift in
    another form. A parent at Output Done over an undelivered child is wrong
    whatever its type: nothing is complete while part of it is not. The other
    angles are epic-only, because `item-types.yml` says an epic's progress
    *derives* from its children. A story owns its own progress and may sit in
    any state regardless of what hangs beneath it.
    """
    if not children:
        # An undecomposed epic is a decomposition gap with a different fix.
        # Reporting it here would put two problems behind one message.
        return None

    rank = {name: index for index, name in enumerate(values)}
    here = rank.get(claimed)
    if here is None:
        return None

    if claimed == TERMINAL_STATE:
        outstanding = [c for c in children if not c.delivered]
        if outstanding:
            return (f"is {TERMINAL_STATE} but these children are not: "
                    f"{', '.join(c.describe() for c in outstanding)}")
        return None

    if not is_epic:
        return None

    if all(c.delivered for c in children):
        listed = ", ".join(f"#{c.number}" for c in children)
        return (f"is {claimed} but every child is delivered ({listed}). "
                f"Nothing remains for it to be {claimed} about.")

    started = [c for c in children
               if rank.get(c.state or "", -1) >= rank[START_STATE]]
    if here < rank[START_STATE] and started:
        return (f"is {claimed} but these children have already started or "
                f"finished: {', '.join(c.describe() for c in started)}. "
                f"{claimed} claims nothing has been built yet.")

    if claimed == START_STATE and not any(c.movable for c in children):
        return (f"is {START_STATE} but no child can move: "
                f"{', '.join(c.describe() for c in children)}. An epic's "
                f"progress derives from its children, so this claims work "
                f"that nothing on the board can do.")
    return None


@dataclass(frozen=True)
class QueueEntry:
    issue: int
    state: str
    blocked_by: list[str]
    item_type: str = "unknown"

    @property
    def startable(self) -> bool:
        return self.state == "Ready" and not self.blocked_by

    @property
    def decomposable(self) -> bool:
        return self.item_type == "epic"


def item_type_of(issue: dict, decomposable: set[str]) -> str:
    """Type from labels. Item types are labels in the repository-scoped model."""
    names = {str(lbl.get("name", "")).lower() for lbl in issue.get("labels") or []}
    for candidate in ("epic", "story", "bug", "spike"):
        if candidate in names:
            return candidate
    return "unknown"


def ready_queue(gh: GitHub, backend: FieldBackend, inspection: Inspection,
                role: str = "delivery_state",
                decomposable: set[str] | None = None) -> list[QueueEntry]:
    """Every open item's delivery state and what blocks it.

    Two things are called the Ready queue and only one of them is: items that
    are Ready, and items that are Ready *and unblocked*. Only the second can
    be started, and only the second should be counted when deciding whether
    refinement needs to run further ahead.
    """
    issues = gh.rest("GET", f"repos/{inspection.owner}/{inspection.repo}/issues?state=open",
                     paginate=True) or []
    if isinstance(issues, dict):
        issues = [issues]

    entries: list[QueueEntry] = []
    for issue in issues:
        number = issue.get("number")
        if number is None or issue.get("pull_request"):
            continue
        try:
            state = backend.read(int(number), role).value
        except NotFound:
            continue
        if state is None:
            continue
        blocking = blockers(gh, inspection.owner, inspection.repo, int(number))
        entries.append(QueueEntry(
            issue=int(number),
            state=state,
            blocked_by=[f"{b.get('repository', {}).get('full_name', '?')}#{b['number']}"
                        for b in blocking],
            item_type=item_type_of(issue, decomposable or {"epic"}),
        ))
    return entries


DEFAULT_QUEUE_TARGET = 3


@dataclass(frozen=True)
class QueueReport:
    """The queue sorted into the four answers a reader actually wants.

    The sorting lived inside `main`, where the only way to reach it was to run
    the command and read its printed lines. `status.py` wants the same four
    buckets and the same shortfall sentence; parsing them back out of stdout
    would be a second reading of a format nothing promised to keep.
    """

    startable: list[QueueEntry]
    blocked: list[QueueEntry]
    refinable: list[QueueEntry]
    awaiting: list[QueueEntry]
    target: int = DEFAULT_QUEUE_TARGET

    @property
    def shortfall(self) -> int:
        return max(0, self.target - len(self.startable))

    @property
    def advice(self) -> str:
        """What to do about the queue, in the sentence the command already used."""
        if not self.shortfall:
            return f"Queue is at target ({self.target})."
        source = ("Refine from the safe list" if self.refinable
                  else "Decompose an Epic first; nothing is refinable")
        return (f"{self.shortfall} short of a startable queue of {self.target}. "
                f"{source}. Those items have no open blocker, so nothing "
                f"in flight can change their shape.")


def classify_queue(entries: list[QueueEntry],
                   target: int = DEFAULT_QUEUE_TARGET) -> QueueReport:
    """Sort queue entries into startable, blocked, refinable and awaiting.

    An Epic is decomposed, not refined to Ready. Listing them together tells a
    refiner to do the wrong thing, which is why `awaiting` is separate from
    `refinable` rather than a note on one list.
    """
    pending = [e for e in entries
               if e.state in ("Inbox", "Refining") and not e.blocked_by]
    return QueueReport(
        startable=[e for e in entries if e.startable],
        blocked=[e for e in entries if e.blocked_by],
        refinable=[e for e in pending if not e.decomposable],
        awaiting=[e for e in pending if e.decomposable],
        target=target,
    )


def in_progress_issues(entries: list[QueueEntry]) -> list[int]:
    """Open items the board says are being worked on.

    `audit_board` derives the same set while walking every issue, open and
    closed. A closed item left at `In Progress` is a contradiction the audit
    reports on its own; for the working-tree comparison what matters is whether
    anybody has claimed the work, and an open item is the honest reading of
    that.
    """
    return [e.issue for e in entries if e.state == START_STATE]


def open_target(repo: str, project: int | None, audit: Path | None,
                dry_run: bool = False):
    """Resolve the board this run will read, refusing an unusable target.

    Public because `status.py` opens the same board for the same reason. A
    leading underscore said "nothing else needs this", and something did.
    """
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


# Values that deny what their key names. Not an allowlist of truth: an agent
# writes free text here and no word list can make an assertion honest. This
# only stops the reading where a denial counted as evidence.
DENIALS = frozenset({"false", "no", "none", "0", "not", "unverified", "unknown", ""})


def expected_state(raw: str | None) -> str | None:
    """What `--expect` names, with the empty string meaning "no state".

    `state-machine.yml` declares the edge out of the null state, and argparse
    can never make a string equal `None` -- so the one transition that repairs
    an item placed on the board without a delivery state was unreachable from
    this CLI, and repairing one meant `gh project item-edit` with a raw field
    id and option id, outside the extension entirely.
    """
    return raw if (raw or "").strip() else None


def post_comment(gh, inspection, plan, path: Path) -> str:
    """Post the delivery record on the issue the plan named.

    CLAUDE.md tells a reader to read the issue rather than re-derive the work,
    and nothing in the bundle produced that comment. It rides on the transition
    because the transition already sits behind a gate, already names an
    approved plan, and already writes to this issue -- a second command would
    be a second thing to forget.
    """
    body = path.read_text(encoding="utf-8").strip()
    if not body:
        raise Forbidden(
            f"{path} is empty. A comment that says nothing is worse than no "
            f"comment: it looks like the record was written.")
    issue = int(plan.issue.rsplit("#", 1)[1])
    gh.rest("POST",
            f"repos/{inspection.owner}/{inspection.repo}/issues/{issue}/comments",
            body={"body": body},
            operation_id=f"{plan.operation_id}-comment")
    return str(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None,
                    help="owner/name. Defaults to the repository the extension config declares.")
    ap.add_argument("--project", type=int, default=None)
    ap.add_argument("--audit", type=Path, default=None)
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="Write a transition plan. Reads only.")
    p_plan.add_argument("--issue", type=int, required=True)
    p_plan.add_argument("--to", required=True)
    p_plan.add_argument("--role", default="delivery_state")
    p_plan.add_argument("--uncertainty-mode", default=None,
                        help="The mode a run would use, so the preview refuses the same way the apply will.")
    p_plan.add_argument("--out", type=Path, default=None,
                        help="Write the plan to a file. Optional: without it this previews what the transition needs and writes nothing.")

    p_apply = sub.add_parser(
        "apply", help="Apply one approved transition, refusing if the board moved.")
    p_apply.add_argument("--issue", type=int, required=True)
    p_apply.add_argument("--to", required=True)
    p_apply.add_argument("--role", default="delivery_state")
    p_apply.add_argument("--expect", required=True, metavar="STATE",
                         help="The state this transition was approved against. The write is refused if the board is no longer there, which is what stops one run overwriting a change it never saw. Pass an empty string for an item on the board with no delivery state.")
    p_apply.add_argument("--evidence", action="append", default=[],
                         metavar="KEY=VALUE",
                         help="Assert one required evidence item. Repeatable.")
    p_apply.add_argument("--uncertainty-mode", default=None,
                         help="The mode this run used. prototype or spike requires a disposal record before Output Done, whatever the item is labelled.")
    p_apply.add_argument("--comment", type=Path, default=None,
                         help="Post this file as an issue comment after the transition succeeds. The record of what was built and what it exposed.")
    p_apply.add_argument("--dry-run", action="store_true")

    sub.add_parser("audit", help="Report board state that contradicts the policy.")

    p_queue = sub.add_parser(
        "queue", help="Show what is startable now, what is blocked, and what is next.")
    p_queue.add_argument("--target", type=int, default=DEFAULT_QUEUE_TARGET,
                         help="Desired number of startable items.")

    args = ap.parse_args()
    try:
        target = config.resolve_target(args.repo, getattr(args, "project", None))
        args.repo = target.repo
        if hasattr(args, "project"):
            args.project = target.project
    except config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        machine = load_state_machine(args.policy_root)
        gh, inspection, backend = open_target(
            args.repo, args.project, args.audit,
            dry_run=getattr(args, "dry_run", False),
        )

        if args.cmd == "plan":
            plan = build_plan(backend, inspection, machine, args.issue,
                              args.to, args.role, gh=gh,
                              uncertainty_mode=args.uncertainty_mode)
            if args.out is not None:
                out = project_root.ensure_within(args.policy_root, args.out)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(plan.to_markdown(), encoding="utf-8")
                print(f"Write exactly {out}")
            print(plan.to_yaml())
            return 0

        if args.cmd == "audit":
            problems = audit_board(gh, backend, inspection, machine=machine,
                                   root=args.policy_root)
            for item in problems:
                print(item)
            print(f"\n{len(problems)} inconsistencies")
            return 1 if problems else 0

        if args.cmd == "queue":
            report = classify_queue(
                ready_queue(gh, backend, inspection), args.target)
            print(f"Startable now ({len(report.startable)}):")
            for e in report.startable:
                print(f"  #{e.issue} [{e.item_type}]")
            print(f"\nBlocked ({len(report.blocked)}):")
            for e in report.blocked:
                print(f"  #{e.issue} [{e.state}] blocked by {', '.join(e.blocked_by)}")
            print(f"\nSafe to refine ahead ({len(report.refinable)}):")
            for e in report.refinable:
                print(f"  #{e.issue} [{e.state}] {e.item_type}")
            print(f"\nAwaiting decomposition ({len(report.awaiting)}):")
            for e in report.awaiting:
                print(f"  #{e.issue} [{e.state}] {e.item_type}")
            print(f"\n{report.advice}")
            return 0

        # Compare-and-swap, which is the whole of what the plan file bought.
        # It recorded an observed value so applying could refuse when the board
        # had moved since; `--expect` says the same thing in one flag, and
        # without a 335-file directory nothing reads twice.
        current = backend.read(args.issue, args.role)
        issue_ref = f"{inspection.owner}/{inspection.repo}#{args.issue}"
        if current.value == args.to:
            # Already applied. A retry after a timeout changes nothing rather
            # than reporting drift against a value it itself wrote.
            print(json.dumps({
                "issue": issue_ref, "role": args.role,
                "from": args.to, "to": args.to,
                "operation_id": None, "commented": None,
                "audit": [a.outcome for a in gh.audit],
            }, indent=2))
            return 0
        expected = expected_state(args.expect)
        if current.value != expected:
            raise Conflict(
                f"expected {expected!r} but {issue_ref} {args.role} is now "
                f"{current.value!r}. Re-read the board rather than overwriting a "
                f"change this run did not account for.")
        plan = build_plan(backend, inspection, machine, args.issue, args.to,
                          args.role, gh=gh,
                          uncertainty_mode=args.uncertainty_mode)
        evidence = dict(
            item.split("=", 1) if "=" in item else (item, "asserted")
            for item in args.evidence
        )
        result = apply_plan(backend, inspection, plan, evidence, machine=machine)
        commented = None
        if args.comment is not None:
            # After the write, never before. A comment describing a transition
            # that was then refused is a false record, and this one is the
            # record a reader is told to trust over re-deriving the work.
            commented = post_comment(gh, inspection, plan, args.comment)
        print(json.dumps({
            "issue": plan.issue, "role": plan.role,
            "from": plan.observed, "to": result.value,
            "operation_id": plan.operation_id,
            "commented": commented,
            "audit": [a.outcome for a in gh.audit],
        }, indent=2))
        return 0
    except (PlanError, NotFound, Conflict, Forbidden,
            project_root.OutsideProjectError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
