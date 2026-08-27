#!/usr/bin/env python3
"""Find out at bootstrap whether the project can run the framework's workflows.

Five workflows shell out to `devbox run verify` and one to
`devbox run release-verify`. These are the only two shell commands the framework
permits anywhere, and nothing has ever checked that the target project defines
them. Today a user finds out at their first delivery, several steps into real
work, from a shell error that reports a failed command rather than a missing
prerequisite.

Three judgements, all in `bootstrap-policy.yml`:

Present and missing are reported separately. "Verification is not set up" tells
a user nothing about which of the two to add.

Generation requires a stack decision. A minimal verification script has to run
something, and what to run is a stack decision. Generating one without it means
inventing the project's toolchain and calling it a default.

An overlay may only satisfy a declared framework command. The project side is
arbitrary by nature -- it is whatever the project already runs -- so it reaches a
human gate. The framework side is a fixed list, because an overlay that could
name any command would route around the only restriction on what a workflow may
execute.

A fourth judgement, over the quality gates rather than the two shell commands.
Every gate `quality-gates.yml` declares is resolved, declined, or filed on a
project, and a gate in none of the three is the finding. That is the whole
point: the contract today produces no outcome for any gate at once, so nothing
distinguishes a gate the owner rejected from one nobody looked at. `declined`
carries its reason for exactly that reason. `filed` names the backlog item
created for the gate and leaves it unresolved, because filing work is not doing
it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/bootstrap-policy.yml",
    "policy/bootstrap-policy.yml",
)

# The gates are declared in their own policy file, which cannot be reached from
# bootstrap-policy without pointing one policy at another.
GATE_POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/quality-gates.yml",
    "policy/quality-gates.yml",
)

# A proposed filing has to meet the same contract the item would, or the batch
# a person approves contains items that cannot be created.
ITEM_TYPE_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/item-types.yml",
    "policy/item-types.yml",
)


def load_policy(root: Path) -> dict:
    for rel in POLICY_CANDIDATES:
        path = root / rel
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data["verification_commands"]
    raise FileNotFoundError(
        f"none of {list(POLICY_CANDIDATES)} found; the governance preset must "
        "be installed")


def load_gate_policy(root: Path) -> dict:
    for rel in GATE_POLICY_CANDIDATES:
        path = root / rel
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"none of {list(GATE_POLICY_CANDIDATES)} found; the governance preset "
        "must be installed")


def declared_gates(gate_policy: dict) -> dict[str, list[str] | None]:
    """Every declared gate, mapped to the conditions it applies under.

    An `always` gate maps to None. A conditional gate maps to its `when:` list,
    which is a property of a change rather than of a project -- so it is
    reported beside the outcome and never evaluated here, and never copied into
    the record, where it would be a second copy of the condition vocabulary
    that nothing regenerates.
    """
    gates: dict[str, list[str] | None] = {
        name: None for name in gate_policy.get("always") or []}
    for name, spec in (gate_policy.get("conditional") or {}).items():
        gates[name] = list((spec or {}).get("when") or [])
    return gates


def declared_commands(policy: dict) -> list[str]:
    """Every framework command an overlay is allowed to satisfy."""
    return list(policy["required"]) + list(policy["release"])


def script_name(command: str) -> str:
    """`devbox run verify` -> `verify`."""
    return command.rsplit(" ", 1)[-1]


@dataclass
class Report:
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    overlaid: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    wrote: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        # A report that could not be produced is not a clean one. Without the
        # problems clause an unreadable devbox.json reports nothing missing and
        # therefore resolved, which is the "absent evidence reads as success"
        # mistake in a second place.
        return not self.missing and not self.problems

    def to_dict(self) -> dict:
        return {
            "present": self.present,
            "missing": self.missing,
            "overlaid": self.overlaid,
            "problems": self.problems,
            "wrote": self.wrote,
            "resolved": self.resolved,
        }


def defined_scripts(root: Path, policy: dict) -> set[str]:
    source = policy["definition_source"]
    path = root / source["file"]
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # An unparseable devbox.json is not a project without scripts. Say so
        # rather than reporting every command missing and sending the user to
        # add what is already there.
        raise
    for key in source["scripts_at"]:
        data = (data or {}).get(key, {})
    return set(data) if isinstance(data, dict) else set()


def load_overlay(root: Path, policy: dict) -> list[dict]:
    path = root / policy["overlay"]["file"]
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("mappings") or []


def detect(root: Path, policy: dict) -> Report:
    report = Report()
    try:
        scripts = defined_scripts(root, policy)
    except (OSError, json.JSONDecodeError) as exc:
        report.problems.append(
            f"{policy['definition_source']['file']} could not be read "
            f"({exc.__class__.__name__}); no command can be reported present or "
            f"missing from it")
        return report

    satisfied = {m.get("framework_command") for m in load_overlay(root, policy)}
    for command in declared_commands(policy):
        if script_name(command) in scripts:
            report.present.append(command)
        elif command in satisfied:
            report.overlaid.append(command)
        else:
            report.missing.append(command)
    return report


def check_overlay(root: Path, policy: dict) -> list[str]:
    """Refuse an overlay that satisfies a command the framework never runs."""
    declared = set(declared_commands(policy))
    problems = []
    for mapping in load_overlay(root, policy):
        target = mapping.get("framework_command")
        if target not in declared:
            problems.append(
                f"overlay maps {target!r}, which is not a framework command. "
                f"An overlay may satisfy only {sorted(declared)}; naming any "
                f"other command would add to what a workflow may execute.")
        if not mapping.get("project_command"):
            problems.append(
                f"overlay for {target!r} names no project command to run.")
    return problems


def load_item_types(root: Path) -> dict:
    for rel in ITEM_TYPE_CANDIDATES:
        path = root / rel
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"none of {list(ITEM_TYPE_CANDIDATES)} found; the governance preset "
        "must be installed")


def required_sections(item_types: dict, item_type: str) -> list[str]:
    """The section labels `item_type` must carry, from item-types.yml."""
    entry = (item_types.get("types") or {}).get(item_type) or {}
    return [s["label"] for s in entry.get("sections") or []
            if s.get("required")]


@dataclass
class GateReport:
    """Every declared gate, in exactly one bucket.

    Four buckets rather than three. `unexamined` is the one the story exists
    for: without it a gate nobody looked at is absent from the report, and an
    absent gate reads as a gate with nothing wrong.
    """
    resolved: list[dict] = field(default_factory=list)
    declined: list[dict] = field(default_factory=list)
    filed: list[dict] = field(default_factory=list)
    unexamined: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    wrote: list[str] = field(default_factory=list)

    @property
    def every_gate_answered(self) -> bool:
        return not self.unexamined and not self.problems

    unresolved_outcomes: tuple[str, ...] = ()

    @property
    def settled(self) -> bool:
        # A filed gate names work that has not been done. Counting it as
        # settled would let a project pass this check by filing sixteen items
        # and delivering none, which is the shape of the failure the record
        # exists to make visible.
        #
        # Which outcomes leave a gate unresolved comes from policy. Hardcoding
        # `not self.filed` would make `leaves_unresolved:` a switch that looks
        # like one and is not.
        outstanding = any(getattr(self, name)
                          for name in self.unresolved_outcomes)
        return self.every_gate_answered and not outstanding

    def to_dict(self) -> dict:
        return {
            "resolved": self.resolved,
            "declined": self.declined,
            "filed": self.filed,
            "unexamined": self.unexamined,
            "problems": self.problems,
            "wrote": self.wrote,
            "every_gate_answered": self.every_gate_answered,
            "settled": self.settled,
        }


EMPTY_RECORD = {"gates": {}, "pending_filings": {}}


def record_path(root: Path, policy: dict) -> Path:
    return root / policy["gate_resolution"]["file"]


def load_record(root: Path, policy: dict) -> dict:
    path = record_path(root, policy)
    if not path.is_file():
        return {"gates": {}, "pending_filings": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "gates": data.get("gates") or {},
        "pending_filings": data.get("pending_filings") or {},
    }


TYPES = {"str": str, "int": int}


def merge(record: dict, incoming: dict, gates: dict, policy: dict,
          item_types: dict | None = None) -> tuple[dict, list[str]]:
    """Fold `incoming` into `record`, or refuse the whole thing.

    All or nothing. A run is resumable only if a refused merge leaves the
    record exactly as it was: a half-applied merge leaves the file asserting
    something nobody decided, and the next run reads it as decided.
    """
    spec = policy["gate_resolution"]
    outcomes = spec["outcomes"]
    merged = {
        "gates": dict(record.get("gates") or {}),
        "pending_filings": dict(record.get("pending_filings") or {}),
    }
    problems: list[str] = []

    for name, entry in (incoming.get("gates") or {}).items():
        entry = dict(entry or {})
        if name not in gates:
            problems.append(
                f"{name!r} is not a declared gate. An outcome recorded against "
                f"a name nobody declared is invisible to the report, which is "
                f"the silence this record exists to end.")
            continue
        outcome = entry.get("outcome")
        if outcome not in outcomes:
            problems.append(
                f"{name}: {outcome!r} is not an outcome. A gate is exactly one "
                f"of {sorted(outcomes)}.")
            continue
        want = outcomes[outcome]
        value = entry.get(want["field"])
        expected = TYPES[want["type"]]
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(
                f"{name}: {outcome!r} carries no {want['field']}. An outcome "
                f"word with no content is indistinguishable from a gate nobody "
                f"looked at, which is what this record is for.")
            continue
        if not isinstance(value, expected) or isinstance(value, bool):
            problems.append(
                f"{name}: {want['field']} must be {want['type']}, not "
                f"{type(value).__name__}.")
            continue
        merged["gates"][name] = {"outcome": outcome, want["field"]: value}
        # Recording the filing answers the question the pending entry asked.
        merged["pending_filings"].pop(name, None)

    required = required_sections(item_types or {},
                                 spec["pending_filings_are"])
    for name, filing in (incoming.get("pending_filings") or {}).items():
        filing = dict(filing or {})
        if name not in gates:
            problems.append(
                f"{name!r} is not a declared gate, so nothing can be filed "
                f"for it.")
            continue
        if not (filing.get("title") or "").strip():
            problems.append(f"{name}: a proposed filing names no title.")
            continue
        body = filing.get("body") or ""
        absent = [s for s in required if s.lower() not in body.lower()]
        if absent:
            problems.append(
                f"{name}: a proposed {spec['pending_filings_are']} needs "
                f"{absent}. Approving a batch of filings that cannot be "
                f"created moves the refusal to after the person decided.")
            continue
        merged["pending_filings"][name] = {
            "title": filing["title"], "body": body}

    both = set(merged["gates"]) & set(merged["pending_filings"])
    for name in sorted(both):
        problems.append(
            f"{name} is both recorded and pending. That is two answers to one "
            f"question.")

    if problems:
        return record, problems
    return merged, []


def report_gates(record: dict, gates: dict, policy: dict) -> GateReport:
    """Every declared gate in one bucket, in declared order."""
    report = GateReport(unresolved_outcomes=tuple(
        policy["gate_resolution"].get("leaves_unresolved") or ()))
    recorded = record.get("gates") or {}
    pending = record.get("pending_filings") or {}
    outcomes = policy["gate_resolution"]["outcomes"]
    for name, when in gates.items():
        entry = dict(recorded.get(name) or {})
        row: dict = {"gate": name}
        if when:
            # Rendered from policy at report time. Storing it would be a second
            # copy that nothing regenerates when a `when:` list changes.
            row["applies_when"] = when
        outcome = entry.get("outcome")
        if outcome in outcomes:
            row[outcomes[outcome]["field"]] = entry.get(
                outcomes[outcome]["field"])
            getattr(report, outcome).append(row)
        else:
            proposed = pending.get(name) or {}
            row["pending_filing"] = proposed.get("title")
            report.unexamined.append(row)
    return report


def write_record(root: Path, policy: dict, record: dict) -> Path:
    path = record_path(root, policy)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False),
                    encoding="utf-8")
    return path


SECTION = re.compile(r"^(?:#{1,6}\s*|\*\*)\s*(.+?)\s*(?:\*\*)?\s*$")


def _records_a_decision(text: str, heading: str) -> bool:
    """Whether `heading` exists in `text` and has something under it.

    A heading with nothing beneath it is a heading, which is the same failure
    at one level down from the one this function was written for.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = SECTION.match(line.strip())
        if not match or match.group(1).strip().lower() != heading.lower():
            continue
        for following in lines[i + 1:]:
            stripped = following.strip()
            if not stripped:
                continue
            if SECTION.match(stripped) and stripped.startswith(("#", "**")):
                break        # next heading, nothing in between
            return True
    return False


def stack_decision(root: Path, policy: dict) -> Path | None:
    """The source that records a stack decision, or None.

    This tested that one of the sources existed and was non-empty. Every
    bootstrap writes a constitution, so the precondition cleared on every
    project and the guard against inventing a toolchain was satisfied by the
    document that was supposed to contain the answer (#136).

    Each source now names the section that records the decision, so the
    question asked is whether a decision is written down rather than whether a
    file is.
    """
    for source in policy["generation"]["stack_decision_sources"]:
        rel = source["path"] if isinstance(source, dict) else source
        heading = source.get("records_decision_in") if isinstance(source, dict) else None
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            continue
        if heading is None or _records_a_decision(text, heading):
            return path
    return None


def refuse_generation_without_a_stack(root: Path, policy: dict) -> list[str]:
    if not policy["generation"]["requires_stack_decision"]:
        return []
    if stack_decision(root, policy):
        return []
    sources = [
        f"{s['path']} (section {s['records_decision_in']!r})"
        if isinstance(s, dict) else s
        for s in policy["generation"]["stack_decision_sources"]]
    return [
        "cannot generate a verification script: no stack decision is recorded "
        f"in any of {sources}. The script has to run something, and what to run "
        "is that decision. Generating one anyway would invent the project's "
        "toolchain and call it a default."]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", type=Path, default=None,
                    help="Project to check. Defaults to the resolved project root.")
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
    ap.add_argument("--propose-generation", action="store_true",
                    help="Check whether a script may be generated. Writes nothing.")
    ap.add_argument("--resolve", type=Path, default=None,
                    help="A YAML file of gate outcomes and proposed filings to fold into the resolution record. Writes nothing without --write.")
    ap.add_argument("--write", action="store_true",
                    help="Persist the merged resolution record. Absent, the merge is reported and nothing is written.")
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

    project = args.path or args.policy_root

    report = detect(project, policy)
    report.problems.extend(check_overlay(project, policy))
    if args.propose_generation and report.missing:
        report.problems.extend(
            refuse_generation_without_a_stack(project, policy))

    # The gate half runs separately from the command half, so an unreadable
    # devbox.json -- which stops detection early -- cannot suppress the gate
    # report as well.
    try:
        gates = declared_gates(load_gate_policy(args.policy_root))
        item_types = load_item_types(args.policy_root)
    except (FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    record = load_record(project, policy)
    merge_problems: list[str] = []
    if args.resolve is not None:
        try:
            incoming = yaml.safe_load(
                args.resolve.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            print(f"error: {args.resolve} could not be read ({exc})",
                  file=sys.stderr)
            return 2
        record, merge_problems = merge(record, incoming, gates, policy,
                                       item_types)

    gate_report = report_gates(record, gates, policy)
    gate_report.problems.extend(merge_problems)
    if args.write and args.resolve is not None and not merge_problems:
        gate_report.wrote.append(str(write_record(project, policy, record)))

    if args.format == "json":
        print(json.dumps({"commands": report.to_dict(),
                          "gates": gate_report.to_dict()}, indent=2))
    else:
        for command in report.present:
            print(f"present  {command}")
        for command in report.overlaid:
            print(f"overlaid {command}")
        for command in report.missing:
            print(f"MISSING  {command}")
        for problem in report.problems:
            print(f"\n{problem}")
        print()
        for outcome in policy["gate_resolution"]["outcomes"]:
            for row in getattr(gate_report, outcome):
                print(f"{outcome:9} {row['gate']}")
        for row in gate_report.unexamined:
            proposed = row.get("pending_filing")
            print(f"{'UNEXAMINED':9} {row['gate']}"
                  + (f"  (proposed: {proposed})" if proposed else ""))
        for problem in gate_report.problems:
            print(f"\n{problem}")
        for path in gate_report.wrote:
            print(f"\nwrote {path}")
        print(f"\n{'Resolved' if report.resolved else 'Not resolved'}. "
              f"{len(gate_report.unexamined)} of {len(gates)} gates "
              f"unexamined, {len(gate_report.filed)} filed and so still "
              f"unresolved.")
        if not gate_report.wrote:
            print("This run wrote nothing.")
    return 0 if report.resolved and gate_report.settled else 1


if __name__ == "__main__":
    sys.exit(main())
