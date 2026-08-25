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


def load_policy(root: Path) -> dict:
    for rel in POLICY_CANDIDATES:
        path = root / rel
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data["verification_commands"]
    raise FileNotFoundError(
        f"none of {list(POLICY_CANDIDATES)} found; the governance preset must "
        "be installed")


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

    report = detect(args.path or args.policy_root, policy)
    report.problems.extend(check_overlay(args.path or args.policy_root,
                                         policy))
    if args.propose_generation and report.missing:
        report.problems.extend(
            refuse_generation_without_a_stack(
                args.path or args.policy_root, policy))

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for command in report.present:
            print(f"present  {command}")
        for command in report.overlaid:
            print(f"overlaid {command}")
        for command in report.missing:
            print(f"MISSING  {command}")
        for problem in report.problems:
            print(f"\n{problem}")
        print(f"\n{'Resolved' if report.resolved else 'Not resolved'}. "
              "This command writes nothing.")
    return 0 if report.resolved and not report.problems else 1


if __name__ == "__main__":
    sys.exit(main())
