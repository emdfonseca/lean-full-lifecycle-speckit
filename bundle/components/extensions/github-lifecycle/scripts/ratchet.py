#!/usr/bin/env python3
"""Hold each measurable gate to the best it has ever done.

`quality-gates.yml` named sixteen gates and recorded what none of them
measured, so "do not make it worse" had no referent. A ratchet needs three
things: a baseline per gate, a rule that a measurement may not regress against
it, and a rule that the baseline moves only in the improving direction unless
somebody signs for the exception.

Three judgements, all in `quality-gates.yml`:

**A first run establishes a baseline and does not report a pass.** A first run
that reports a pass makes every later comparison meaningless, because the
baseline it silently recorded was never reviewed. This is the same shape as an
unreadable repository reading as empty.

**A gate declared ratcheted without a measure is refused, not skipped.** A gate
that silently opts out of the ratchet is the one that regresses.

**Loosening requires an exception naming the gate.** The ratchet turns one way
on its own; turning it back is a decision somebody signs, and the exception
mechanism already records exactly that.

**A baseline says what it measured, or it is refused.** A number with no scope
is not comparable: widen a coverage glob and the percentage falls because the
denominator grew, so the ratchet refuses a project for measuring more of
itself; narrow it and the percentage rises, the baseline follows on its own,
and the project is ratcheted into a measurement that flatters it. So
`conditions` is a baseline field, a baseline missing it is refused rather than
compared against, and a run under different conditions is held as its own
baseline rather than compared with somebody else's.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/quality-gates.yml",
    "policy/quality-gates.yml",
)

ESTABLISHED = "baseline_established"
IMPROVED = "improved"
HELD = "held"
REFUSED = "refused"

LOWER = "lower_is_better"
HIGHER = "higher_is_better"

CONDITIONS = "conditions"


def load_policy(root: Path | None = None) -> dict:
    root = root or project_root.resolve(required=False) or Path.cwd()
    for rel in POLICY_CANDIDATES:
        path = root / rel
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8"))["ratchet"]
    raise FileNotFoundError(
        f"none of {list(POLICY_CANDIDATES)} found; the governance preset must "
        "be installed")


def load_baselines(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@dataclass
class Outcome:
    verdict: str
    gate: str
    message: str
    baseline: float | None = None
    measurement: float | None = None
    new_baseline: float | None = None
    conditions: str = ""

    @property
    def passed(self) -> bool:
        # `established` is deliberately absent. A baseline is not a result.
        return self.verdict in (IMPROVED, HELD)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict, "gate": self.gate, "message": self.message,
            "baseline": self.baseline, "measurement": self.measurement,
            "new_baseline": self.new_baseline, "passed": self.passed,
            "conditions": self.conditions,
        }


def _scope(value) -> str:
    """The conditions a run or a baseline states, normalised. "" means none."""
    return str(value or "").strip()


def _entries(baselines: dict, gate: str) -> list[dict]:
    """Every baseline held for this gate.

    A gate holds one baseline per set of conditions, so the stored value is a
    mapping when there is one and a list when there are several. Both read the
    same way here.
    """
    entry = baselines.get(gate)
    if isinstance(entry, dict):
        return [entry]
    if isinstance(entry, list):
        return [e for e in entry if isinstance(e, dict)]
    return []


def _conditions_required(policy: dict) -> bool:
    """Whether the policy declares that a baseline records what it covered."""
    return CONDITIONS in (policy.get("baseline_fields") or [])


def _scope_problem(gate: str, entries: list[dict], conditions: str,
                   policy: dict) -> "Outcome | None":
    """Refuse a run that says nothing, or a baseline that said nothing."""
    if not _conditions_required(policy):
        return None
    if not conditions:
        return Outcome(
            REFUSED, gate,
            f"{gate}: this run states no conditions, so nothing says what the "
            f"measurement covered. quality-gates.yml declares {CONDITIONS!r} a "
            f"baseline field: name what was measured with --conditions.")
    unscoped = [e for e in entries
                if e.get("value") is not None and not _scope(e.get(CONDITIONS))]
    if unscoped:
        return Outcome(
            REFUSED, gate,
            f"{gate}: the recorded baseline ({unscoped[0]['value']}) records "
            f"no conditions, so nothing says what it measured. Widening what "
            f"is measured would read as a regression against it and narrowing "
            f"it as an improvement, so it is refused rather than compared "
            f"against. Re-record it with --conditions.",
            baseline=float(unscoped[0]["value"]), conditions=conditions)
    return None


def _select(entries: list[dict], conditions: str) -> dict | None:
    """The baseline taken under these conditions, and under no others."""
    for entry in entries:
        if (_scope(entry.get(CONDITIONS)) == conditions
                and entry.get("value") is not None):
            return entry
    return None


def _held_elsewhere(entries: list[dict], conditions: str) -> list[str]:
    """The other conditions this gate holds a baseline under."""
    others = {_scope(e.get(CONDITIONS)) for e in entries
              if e.get("value") is not None}
    return sorted(o for o in others if o and o != conditions)


def baseline_entry(policy: dict | None, value: float, produced_by: str,
                   conditions: str, today: date | None = None) -> dict:
    """Exactly the fields the policy declares, or a refusal to guess one.

    Read from `baseline_fields` rather than written out here, so a field added
    to the policy cannot leave the recorder writing the old set.
    """
    produced = {
        "value": value,
        "recorded_at": (today or date.today()).isoformat(),
        "produced_by": produced_by,
        CONDITIONS: conditions,
    }
    declared = list((policy or {}).get("baseline_fields") or list(produced))
    unknown = [name for name in declared if name not in produced]
    if unknown:
        raise ValueError(
            f"quality-gates.yml declares baseline field(s) {unknown} that the "
            f"ratchet cannot produce. A field the checker cannot write is a "
            f"field no baseline carries, so this is refused rather than "
            f"recorded without it.")
    return {name: produced[name] for name in declared}


def gate_spec(gate: str, policy: dict) -> dict:
    """The gate's measure, or a refusal that names the gate."""
    if gate not in policy["gates"]:
        raise KeyError(
            f"{gate!r} is not a ratcheted gate; ratcheted gates are "
            f"{sorted(policy['gates'])}")
    spec = policy["gates"][gate] or {}
    if not spec.get("measure") or spec.get("direction") not in (LOWER, HIGHER):
        raise ValueError(
            f"gate {gate!r} is declared ratcheted with no usable measure. A "
            f"gate that silently opts out of the ratchet is the one that "
            f"regresses, so this is refused rather than skipped.")
    return spec


def _worse(spec: dict, value: float, than: float) -> bool:
    return value > than if spec["direction"] == LOWER else value < than


def _better(spec: dict, value: float, than: float) -> bool:
    return value < than if spec["direction"] == LOWER else value > than


def assess(gate: str, measurement: float, baselines: dict, policy: dict,
           produced_by: str = "", today: date | None = None,
           conditions: str = "") -> Outcome:
    try:
        spec = gate_spec(gate, policy)
    except (KeyError, ValueError) as exc:
        return Outcome(REFUSED, gate, str(exc))

    conditions = _scope(conditions)
    entries = _entries(baselines, gate)
    problem = _scope_problem(gate, entries, conditions, policy)
    if problem is not None:
        return problem

    entry = _select(entries, conditions)
    if entry is None:
        elsewhere = _held_elsewhere(entries, conditions)
        held = ""
        if elsewhere:
            held = (f" This gate already holds a baseline under "
                    f"{', '.join(repr(o) for o in elsewhere)}; those measured "
                    f"something else, so this run was not compared against "
                    f"them and they are left where they are.")
        return Outcome(
            ESTABLISHED, gate,
            f"no baseline for {gate!r} under {conditions!r}; recording "
            f"{spec['measure']}={measurement} as the baseline for those "
            f"conditions. This is a baseline, not a pass: nothing has been "
            f"compared yet.{held}",
            measurement=measurement, new_baseline=measurement,
            conditions=conditions)

    baseline = float(entry["value"])
    if _worse(spec, measurement, baseline):
        return Outcome(
            REFUSED, gate,
            f"{gate}: {spec['measure']} regressed. Baseline {baseline}, "
            f"measured {measurement} ({spec['direction'].replace('_', ' ')}), "
            f"both under {conditions!r}.",
            baseline=baseline, measurement=measurement, conditions=conditions)

    if _better(spec, measurement, baseline):
        if not produced_by:
            return Outcome(
                REFUSED, gate,
                f"{gate}: {spec['measure']} improved to {measurement} but "
                f"nothing says what produced it. A baseline with no provenance "
                f"cannot be argued with later.",
                baseline=baseline, measurement=measurement,
                conditions=conditions)
        return Outcome(
            IMPROVED, gate,
            f"{gate}: {spec['measure']} improved from {baseline} to "
            f"{measurement} under {conditions!r}. Baseline moves, recorded as "
            f"produced by {produced_by}.",
            baseline=baseline, measurement=measurement,
            new_baseline=measurement, conditions=conditions)

    return Outcome(HELD, gate,
                   f"{gate}: {spec['measure']} held at {baseline} under "
                   f"{conditions!r}.",
                   baseline=baseline, measurement=measurement,
                   new_baseline=baseline, conditions=conditions)


def record(gate: str, outcome: Outcome, baselines: dict, produced_by: str,
           today: date | None = None, conditions: str | None = None,
           policy: dict | None = None) -> dict:
    """Write the new baseline. Only an improvement or a first run moves it.

    A baseline is written under the conditions it was taken under, and the
    baselines this gate holds under other conditions are left alone: they
    measured something else and nothing about this run bears on them.
    """
    if outcome.new_baseline is None or outcome.verdict == REFUSED:
        return baselines
    conditions = _scope(outcome.conditions if conditions is None else conditions)
    entry = baseline_entry(policy, outcome.new_baseline, produced_by,
                           conditions, today)
    kept = [e for e in _entries(baselines, gate)
            if _scope(e.get(CONDITIONS)) != conditions]
    kept.append(entry)
    updated = dict(baselines)
    updated[gate] = kept[0] if len(kept) == 1 else sorted(
        kept, key=lambda e: _scope(e.get(CONDITIONS)))
    return updated


def loosen(gate: str, proposed: float, baselines: dict, policy: dict,
           exception: dict | None = None, root: Path | None = None,
           conditions: str = "") -> Outcome:
    """Move a baseline the wrong way. Only an exception naming the gate can."""
    try:
        spec = gate_spec(gate, policy)
    except (KeyError, ValueError) as exc:
        return Outcome(REFUSED, gate, str(exc))

    conditions = _scope(conditions)
    entries = _entries(baselines, gate)
    problem = _scope_problem(gate, entries, conditions, policy)
    if problem is not None:
        return problem

    entry = _select(entries, conditions) or {}
    baseline = entry.get("value")
    if baseline is None:
        return Outcome(REFUSED, gate,
                       f"{gate!r} has no baseline under {conditions!r} to "
                       f"loosen.", conditions=conditions)
    baseline = float(baseline)
    if not _worse(spec, proposed, baseline):
        return Outcome(HELD, gate,
                       f"{gate}: {proposed} is not a loosening of {baseline}.",
                       baseline=baseline, new_baseline=proposed,
                       conditions=conditions)

    if not policy["loosening"]["requires_exception"]:
        return Outcome(IMPROVED, gate, f"{gate}: baseline loosened to {proposed}.",
                       baseline=baseline, new_baseline=proposed,
                       conditions=conditions)

    problems = exception_problems(gate, exception, policy, root)
    if problems:
        return Outcome(
            REFUSED, gate,
            f"{gate}: refusing to loosen the baseline from {baseline} to "
            f"{proposed}. {problems[0]} An approved exception is the only way "
            f"to loosen a ratchet; the ratchet turns the other way on its own.",
            baseline=baseline, measurement=proposed, conditions=conditions)

    return Outcome(IMPROVED, gate,
                   f"{gate}: baseline loosened from {baseline} to {proposed} "
                   f"under exception {exception.get('id')}.",
                   baseline=baseline, new_baseline=proposed,
                   conditions=conditions)


def exception_problems(gate: str, exception: dict | None, policy: dict,
                       root: Path | None = None) -> list[str]:
    """Whether this exception covers this gate. Validity is exception.py's job.

    Takes the root rather than reaching for `Path.cwd()`. It used to do the
    latter, which in a monorepo member read quality gates from the member and
    exception policy from wherever the command was launched.
    """
    if not exception:
        return ["No exception was supplied."]
    if policy["loosening"]["exception_must_name_gate"]:
        if str(exception.get("policy_rule") or "") != gate:
            return [f"Exception {exception.get('id')!r} names "
                    f"{exception.get('policy_rule')!r}, not {gate!r}."]
    import exception as exception_mod

    try:
        exception_policy = exception_mod.load_policy(root or Path.cwd())
    except FileNotFoundError:
        return ["The exception policy is not installed, so no exception can be "
                "confirmed valid."]
    result = exception_mod.validate(exception, exception_policy, date.today())
    if not result.accepted:
        return [f"Exception {exception.get('id')!r} is not valid: "
                f"{result.refusals[0]}"]
    if result.expired:
        return [f"Exception {exception.get('id')!r} has passed its review date."]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", required=True)
    ap.add_argument("--measurement", type=float)
    ap.add_argument("--loosen-to", type=float)
    ap.add_argument("--produced-by", default="",
                    help="Commit, run id, or PR that produced the measurement.")
    ap.add_argument("--conditions", default="",
                    help="What this run measured: the coverage glob, the "
                         "database backend, the analyser's rule set. A "
                         "baseline is compared only against a run under the "
                         "same conditions.")
    ap.add_argument("--exception", type=Path)
    ap.add_argument("--baselines", type=Path)
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
    ap.add_argument("--write", action="store_true",
                    help="Persist a moved baseline. Without this, reports only.")
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

    path = args.baselines or (args.policy_root / policy["baseline_file"])
    baselines = load_baselines(path)

    if args.loosen_to is not None:
        exception = (yaml.safe_load(args.exception.read_text(encoding="utf-8"))
                     if args.exception else None)
        outcome = loosen(args.gate, args.loosen_to, baselines, policy,
                         exception, args.policy_root,
                         conditions=args.conditions)
    elif args.measurement is not None:
        outcome = assess(args.gate, args.measurement, baselines, policy,
                         args.produced_by, conditions=args.conditions)
    else:
        print("one of --measurement or --loosen-to is required", file=sys.stderr)
        return 2

    if args.write and outcome.verdict != REFUSED:
        try:
            updated = record(args.gate, outcome, baselines, args.produced_by,
                             conditions=args.conditions, policy=policy)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        try:
            path = project_root.ensure_within(args.policy_root, path)
        except project_root.OutsideProjectError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(updated, sort_keys=True), encoding="utf-8")

    if args.format == "json":
        print(json.dumps(outcome.to_dict(), indent=2))
    else:
        print(f"{outcome.verdict.upper()}\n\n{outcome.message}")
        if outcome.verdict == ESTABLISHED:
            print("\nThis gate has not passed. It now has something to be "
                  "compared against.")
    return 0 if outcome.verdict != REFUSED else 1


if __name__ == "__main__":
    sys.exit(main())
