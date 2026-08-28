#!/usr/bin/env python3
"""Decide the next lifecycle step for one item, from policy alone.

This is the router the five `speckit.work.*` commands sit on. It answers one
question -- given an item at this state, of this type, with these blockers and
these children, what happens next and what would refuse it -- and it answers it
by reading `state-machine.yml`, `item-types.yml` and the workflow manifests
rather than by holding its own copy of any of them.

**It never names a state.** Not one delivery state appears as a literal here.
The entry state, the terminal states, the retirement target and the forward
transition are all derived from the policy, because a router that hardcodes a
state name is the way two surfaces over one policy become two policies -- which
is the risk #182 names, and this repository has removed one such copy already.

**It never reads the board.** Board facts arrive as arguments: `--state`,
`--type`, `--blocked-by`, `--child-state`. That is deliberate. The board is
`github-lifecycle`'s to read, it reads it behind `--expect` guards and audited
calls, and a second GitHub client living here would be the second copy in a
different disguise. The command files say which command supplies each fact.

The one thing it does read off the disk is the feature directory, to tell a
finished step from an unfinished one. A workflow step declares what it
`produces`; if that artifact is there, the step is done. Steps that produce
nothing nameable are reported as unverifiable rather than guessed at, because
"we could not tell" and "not done" are different answers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

# Policy is read from the governance preset when installed, and from the source
# checkout when it is not. Same order every other script in this bundle uses.
STATE_MACHINE = (
    ".specify/presets/lean-full-lifecycle-governance/policy/state-machine.yml",
    "policy/state-machine.yml",
)
ITEM_TYPES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/item-types.yml",
    "policy/item-types.yml",
)
WORKFLOW_DIRS = (
    ".specify/workflows",
    "bundle/components/workflows",
)


class RouterError(Exception):
    """The next step could not be decided, and was not guessed at."""


def _load(root: Path, candidates: tuple[str, ...], what: str) -> dict:
    for rel in candidates:
        path = root / rel
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raise RouterError(
        f"{what} was not found under {root}. The governance preset must be "
        f"installed, or this must be the source checkout.")


def load_policy(root: Path) -> tuple[dict, dict]:
    return (_load(root, STATE_MACHINE, "state-machine.yml"),
            _load(root, ITEM_TYPES, "item-types.yml"))


def load_workflow(root: Path, workflow_id: str) -> dict | None:
    """A workflow manifest by id, or None when it is not installed."""
    for rel in WORKFLOW_DIRS:
        path = root / rel / workflow_id / "workflow.yml"
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return None


# --- what the policy says, derived rather than named --------------------------

def states(machine: dict) -> list[str]:
    return list(machine["delivery_status"]["values"])


def terminal_states(machine: dict) -> set[str]:
    declared = machine["delivery_status"].get("terminal_states")
    return set(declared or states(machine)[-1:])


def retirement_state(machine: dict) -> str | None:
    """The terminal state every live state can reach.

    Derived, not named. `state-machine.yml` says retirement "ends an item that
    was never delivered" and is "reachable from every live state"; that
    reachability is the property, and it distinguishes retirement from the
    terminal state a state reaches by being finished. Naming the state here
    would be the second copy this module exists to avoid.
    """
    live = [s for s in states(machine) if s not in terminal_states(machine)]
    if not live:
        return None
    reachable_from = {}
    for edge in machine["delivery_status"]["transitions"]:
        reachable_from.setdefault(edge.get("to"), set()).add(edge.get("from"))
    for candidate in terminal_states(machine):
        if set(live) <= reachable_from.get(candidate, set()):
            return candidate
    return None


def startable_state(machine: dict) -> str | None:
    """The state an item is refined *to*, from which work may start.

    Derived from the edge into whatever `refuses_transition_to` names: the
    state work starts at is the one that edge leaves, so the state refinement
    produces is that edge's `from`. Naming it here would be the second copy,
    and the policy comment that explains the rule already names neither.
    """
    refused = (machine.get("blocking") or {}).get("refuses_transition_to")
    if not refused:
        return None
    for edge in machine["delivery_status"]["transitions"]:
        if edge.get("to") == refused:
            return edge.get("from")
    return None


def forward_transition(machine: dict, state: str) -> dict | None:
    """The transition that advances an item out of `state`.

    Every live state has two edges out: onward, and retirement. Retirement is
    what `change` does and never what `continue` does, so it is excluded here
    by identity rather than by name.
    """
    retire = retirement_state(machine)
    for edge in machine["delivery_status"]["transitions"]:
        if edge.get("from") == state and edge.get("to") != retire:
            return edge
    return None


def workflow_for(item_types: dict, state: str, item_type: str) -> str | None:
    """The workflow that carries an item of this type at this state."""
    block = (item_types.get("state_workflows") or {}).get(state)
    if not isinstance(block, dict):
        return None
    return block.get(item_type) or block.get("default")


def type_facts(item_types: dict, item_type: str) -> dict:
    entry = (item_types.get("types") or {}).get(item_type) or {}
    return {
        "decomposable": bool(entry.get("decomposable")),
        "carries_outcome": bool(entry.get("carries_outcome")),
        "known": bool(entry),
    }


# --- what would refuse the step ----------------------------------------------

def refusals(machine: dict, item_types: dict, state: str, item_type: str,
             blocked_by: list[str], child_states: list[str]) -> list[str]:
    """Every reason the next step cannot be taken, in the policy's own terms."""
    found: list[str] = []
    blocking = machine.get("blocking") or {}
    onward = forward_transition(machine, state)
    target = onward.get("to") if onward else None

    if blocked_by:
        named = ", ".join(blocked_by)
        refused_target = blocking.get("refuses_transition_to")
        if refused_target and target == refused_target:
            found.append(
                f"blocked by {named}, and state-machine.yml refuses "
                f"{state!r} -> {refused_target!r} while a blocker is open.")
        elif (blocking.get("refine_ahead_requires") == "no_open_blocker"
                and target == startable_state(machine)):
            # "An item with an open blocker should not be refined to Ready:
            # the blocker may change what it means." Scoped to the transition
            # that produces the startable state and no further -- at that
            # state `refuses_transition_to` is the rule, and reporting both
            # would say one thing twice.
            found.append(
                f"blocked by {named}, and refine_ahead_requires is "
                f"no_open_blocker, so this item should not be refined to "
                f"{target!r} until the blocker closes.")

    if type_facts(item_types, item_type)["decomposable"] and target in terminal_states(machine):
        unfinished = [s for s in child_states if s not in terminal_states(machine)]
        if unfinished:
            found.append(
                f"{len(unfinished)} child/children are not terminal "
                f"({', '.join(sorted(set(unfinished)))}). item-types.yml: a "
                f"decomposable item may not reach {target!r} while any child "
                f"is in another delivery state.")
    return found


# --- which workflow step is next ---------------------------------------------

def flatten_steps(workflow: dict) -> list[dict]:
    """Every step, including those nested inside a switch's cases, in order."""
    out: list[dict] = []

    def walk(steps):
        for step in steps or []:
            if not isinstance(step, dict):
                continue
            out.append(step)
            for case in (step.get("cases") or {}).values():
                walk(case)
            walk(step.get("steps"))

    walk((workflow.get("steps") or []))
    return out


def step_done(feature_dir: Path | None, produces: str) -> bool | None:
    """Whether a step's declared artifact is present. None when unknowable."""
    if feature_dir is None:
        return None
    target = feature_dir / produces
    if produces.endswith("/"):
        return target.is_dir() and any(target.iterdir())
    return target.exists()


def next_step(workflow: dict, feature_dir: Path | None) -> dict:
    """The first step whose artifact is absent, and what could not be judged.

    A step that declares no `produces` cannot be told finished from unfinished
    without a second record of progress, and #182 rules that out. Those steps
    are listed as unverifiable and the caller is told to read the item rather
    than being handed a guess.
    """
    unverifiable: list[str] = []
    for step in flatten_steps(workflow):
        produces = step.get("produces")
        if not produces:
            if step.get("command") or step.get("type") in (None, "shell"):
                unverifiable.append(str(step.get("id")))
            continue
        done = step_done(feature_dir, str(produces))
        if done is False:
            return {"step": step, "unverifiable": unverifiable}
        if done is None:
            return {"step": step, "unverifiable": unverifiable,
                    "note": "no feature directory, so no artifact could be "
                            "checked; this is the workflow's first producing "
                            "step, not necessarily the next one to run"}
    return {"step": None, "unverifiable": unverifiable}


# --- the answer ---------------------------------------------------------------

def route(root: Path, state: str, item_type: str,
          blocked_by: list[str] | None = None,
          child_states: list[str] | None = None,
          feature_dir: Path | None = None,
          issue: int | None = None) -> dict:
    machine, item_types = load_policy(root)
    blocked_by = blocked_by or []
    child_states = child_states or []

    if state not in states(machine):
        raise RouterError(
            f"{state!r} is not a delivery state. state-machine.yml declares "
            f"{states(machine)}.")
    if not type_facts(item_types, item_type)["known"]:
        raise RouterError(
            f"{item_type!r} is not an item type. item-types.yml declares "
            f"{sorted((item_types.get('types') or {}))}.")

    facts = type_facts(item_types, item_type)
    onward = forward_transition(machine, state)
    workflow_id = workflow_for(item_types, state, item_type)
    answer: dict = {
        "issue": issue,
        "item_type": item_type,
        "state": state,
        "workflow": workflow_id,
        "transition": None,
        "step": None,
        "unverifiable": [],
        "refusals": refusals(machine, item_types, state, item_type,
                             blocked_by, child_states),
        "notes": [],
    }

    if state in terminal_states(machine):
        if workflow_id and not facts["carries_outcome"]:
            # The outcome axis exists for types that carry an outcome. Sending
            # a type that does not down it would manufacture a measurement.
            answer["workflow"] = None
            answer["notes"].append(
                f"{item_type!r} does not carry an outcome, so nothing follows "
                f"this state.")
        elif workflow_id:
            answer["notes"].append(
                "the outcome axis follows; the reopen edge out of this state "
                "is left to a person, per #182.")
        return answer

    if onward:
        answer["transition"] = {
            "from": state,
            "to": onward.get("to"),
            "evidence": list(onward.get("evidence") or []),
            "authority": onward.get("authority"),
        }

    if workflow_id is None:
        answer["notes"].append(
            f"item-types.yml names no workflow for {state!r}; the transition "
            f"above is the whole of the next step.")
        return answer

    workflow = load_workflow(root, workflow_id)
    if workflow is None:
        answer["notes"].append(
            f"{workflow_id!r} is named by item-types.yml and is not installed, "
            f"so its steps could not be read.")
        return answer

    found = next_step(workflow, feature_dir)
    answer["unverifiable"] = found["unverifiable"]
    if found.get("note"):
        answer["notes"].append(found["note"])
    step = found["step"]
    if step is not None:
        answer["step"] = {
            "id": step.get("id"),
            "command": step.get("command"),
            "produces": step.get("produces"),
        }
    else:
        answer["notes"].append(
            "every step with a declared artifact has produced it; what remains "
            "produces nothing nameable, so read the item rather than trusting "
            "a guess here.")
    return answer


def render(answer: dict) -> str:
    lines = []
    label = f"#{answer['issue']} " if answer.get("issue") else ""
    lines.append(f"{label}[{answer['item_type']}] at {answer['state']}")
    if answer["refusals"]:
        lines.append("\nRefused:")
        for item in answer["refusals"]:
            lines.append(f"  {item}")
    if answer["transition"]:
        t = answer["transition"]
        lines.append(f"\nNext transition: {t['from']} -> {t['to']}")
        lines.append(f"  evidence: {', '.join(t['evidence']) or 'none'}")
        lines.append(f"  authority: {t['authority']}")
    if answer["workflow"]:
        lines.append(f"\nWorkflow: {answer['workflow']}")
    if answer["step"]:
        s = answer["step"]
        produces = f" -> {s['produces']}" if s.get("produces") else ""
        lines.append(f"Next step: {s['id']} ({s['command']}){produces}")
    if answer["unverifiable"]:
        lines.append(f"\nCannot be judged from the tree "
                     f"({len(answer['unverifiable'])}): "
                     f"{', '.join(answer['unverifiable'])}")
    for note in answer["notes"]:
        lines.append(f"\n{note}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", required=True,
                    help="The item's delivery state, as the board reports it.")
    ap.add_argument("--type", dest="item_type", required=True,
                    help="The item type, from its labels.")
    ap.add_argument("--issue", type=int, default=None,
                    help="For labelling the report. Nothing is fetched.")
    ap.add_argument("--blocked-by", action="append", default=[],
                    metavar="REF", help="One open blocker. Repeatable.")
    ap.add_argument("--child-state", action="append", default=[],
                    metavar="STATE", help="One child's delivery state. Repeatable.")
    ap.add_argument("--feature-dir", type=Path, default=None,
                    help="The feature directory, when one exists. Without it no "
                         "artifact is checked and the report says so.")
    ap.add_argument("--root", type=Path, default=None,
                    help="Project root. Defaults to the working directory.")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args()

    try:
        answer = route(args.root or Path.cwd(), args.state, args.item_type,
                       args.blocked_by, args.child_state, args.feature_dir,
                       args.issue)
    except RouterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(answer, indent=2) if args.format == "json"
          else render(answer))
    # A refusal is the answer, not a failure to answer.
    return 0


if __name__ == "__main__":
    sys.exit(main())
