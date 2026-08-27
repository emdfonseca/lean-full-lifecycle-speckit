#!/usr/bin/env python3
"""Validate a readiness verdict, and lint the criteria it claims are met.

`state-machine.yml` requires `readiness_verdict_ready` as evidence for
Refining to Ready. This is what checks that evidence is real rather than
asserted: the verdict must match its schema, hold no blocking questions, and
the item's acceptance criteria must be criteria rather than opinions.

Refuses rather than warns. Unlike the acceptance linter, whose findings are
advisory, a verdict either satisfies the schema or does not, and Ready is a
gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

SCHEMA_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/schemas/readiness-verdict.schema.json",
    "tooling/schemas/readiness-verdict.schema.json",
)


def load_schema(root: Path) -> dict:
    for rel in SCHEMA_CANDIDATES:
        path = root / rel
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        "readiness-verdict.schema.json not found; the governance preset must "
        "be installed"
    )


def load_verdict(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    # Verdicts are written inside a fenced block so they read as part of the
    # item; accept either that or a bare document.
    if "```" in text:
        import re

        match = re.search(r"```(?:yaml)?\n(.*?)\n```", text, re.DOTALL)
        if match:
            text = match.group(1)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("verdict is not a mapping")
    return data


def check(verdict: dict, schema: dict) -> list[str]:
    problems: list[str] = []
    try:
        import jsonschema

        jsonschema.validate(verdict, schema)
    except ImportError:
        problems.append("jsonschema is not installed; schema not enforced")
    except Exception as exc:  # noqa: BLE001 - message is the useful part
        problems.append(f"schema: {getattr(exc, 'message', exc)}")

    blocking = verdict.get("blocking_questions") or []
    if verdict.get("readiness") == "ready" and blocking:
        problems.append(
            f"readiness is 'ready' with {len(blocking)} blocking question(s) "
            f"open: {blocking}. An item cannot be Ready with an open question "
            f"about what it is."
        )
    if verdict.get("readiness") == "not_ready" and not blocking:
        problems.append(
            "readiness is 'not_ready' with no blocking questions, so nothing "
            "says what would make it ready"
        )
    return problems


# One current readiness judgement per item. Keyed by issue rather than by run,
# because the judgement is about the item and outlives the run that made it --
# which is why a second workflow used to re-derive it rather than read it.
RECORD_DIR = ".specify/github-lifecycle/verdicts"


def record_path(root: Path, issue: int) -> Path:
    return root / RECORD_DIR / f"{issue}.yml"


def render(verdict: dict, issue: int | None) -> str:
    """The verdict as a person reads it at a gate."""
    questions = verdict.get("blocking_questions") or []
    lines = [
        f"# Readiness verdict{f' for #{issue}' if issue else ''}",
        "",
        "## What you are approving",
        "",
        f"- Readiness: **{verdict.get('readiness')}**",
        f"- Risk: {verdict.get('risk')}",
        f"- Spec impact: {verdict.get('spec_impact')}",
        f"- Material uncertainty: {verdict.get('material_uncertainty')}",
        "",
        "## Blocking questions",
        "",
    ]
    lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)] or ["None."]
    lines += ["", "## Next engineering action", "",
              str(verdict.get("next_engineering_action") or "").strip(), ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verdict", type=Path, default=None,
                    help="The verdict file to validate. Omit with --from-record.")
    ap.add_argument("--issue", type=int, help="Also lint this issue's criteria.")
    ap.add_argument("--record", action="store_true",
                    help="Store the validated verdict against the issue, so a later run can read the judgement instead of making a second one.")
    ap.add_argument("--from-record", action="store_true",
                    help="Read the stored verdict for --issue rather than a file. Refuses when none was recorded.")
    ap.add_argument("--emit", type=Path, default=None,
                    help="Write the verdict where a gate can show it. A gate needs a path in this run; the record is keyed by issue and outlives it.")
    ap.add_argument("--repo", help="owner/name, required with --issue")
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
    args = ap.parse_args()
    try:
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.from_record and not args.issue:
        print("--from-record needs --issue: the record is keyed by issue",
              file=sys.stderr)
        return 2
    if not args.from_record and args.verdict is None:
        print("--verdict is required without --from-record", file=sys.stderr)
        return 2

    try:
        schema = load_schema(args.policy_root)
        source = (record_path(args.policy_root, args.issue) if args.from_record
                  else args.verdict)
        if args.from_record and not source.is_file():
            # An item reaching delivery with no recorded verdict is exactly
            # what this refuses. A missing file must not read as an approved
            # one, which is the failure a per-run path never had to consider.
            print(f"error: no readiness verdict recorded for #{args.issue} at "
                  f"{source}. Refine the item before delivering it; an absent "
                  f"verdict is not a passing one.", file=sys.stderr)
            return 2
        verdict = load_verdict(source)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problems = check(verdict, schema)
    lint_account = ""
    advisories: list[str] = []

    # `--issue` identifies the item; `--repo` opts into fetching and linting
    # it. Requiring both meant recording a verdict against an item needed a
    # network call to say which item.
    if args.issue and args.repo:
        import lint_acceptance
        from github_api import GitHub

        issue = GitHub().rest(
            "GET", f"repos/{args.repo}/issues/{args.issue}") or {}
        labels = {str(l.get("name", "")).lower()
                  for l in issue.get("labels") or []}
        item_type = next((t for t in ("epic", "story", "bug", "spike")
                          if t in labels), None)
        contract = lint_acceptance.load_contract(args.policy_root)
        # Only types whose contract has acceptance criteria are linted. A bug
        # has a Reproduction and a spike has Exit criteria, and asking either
        # for a Then clause invents an advisory about prose that was never
        # criteria.
        findings, lint_account = lint_acceptance.lint_issue(
            str(issue.get("body") or ""), item_type, contract,
            lint_acceptance.load_policy(args.policy_root))
        advisories = [str(f) for f in findings]

    for problem in problems:
        print(f"BLOCKING {problem}")
    if lint_account:
        # "No findings" and "not applicable" are different results, and a
        # report that renders them identically is why this went unnoticed.
        print(f"CRITERIA {lint_account}")
    for advisory in advisories:
        print(f"ADVISORY {advisory}")

    if problems:
        print(f"\nNot ready: {len(problems)} blocking problem(s).")
        return 1

    if args.record:
        if not args.issue:
            print("--record needs --issue", file=sys.stderr)
            return 2
        stored = record_path(args.policy_root, args.issue)
        stored.parent.mkdir(parents=True, exist_ok=True)
        stored.write_text(yaml.safe_dump(verdict, sort_keys=False),
                          encoding="utf-8")
        print(f"recorded {stored}")
    if args.emit is not None:
        args.emit.parent.mkdir(parents=True, exist_ok=True)
        args.emit.write_text(render(verdict, args.issue), encoding="utf-8")
        print(f"emitted {args.emit}")
    print(f"\nVerdict is valid. readiness={verdict.get('readiness')!r}"
          + (f", {len(advisories)} advisory finding(s) on the criteria."
             if advisories else "."))
    return 0 if verdict.get("readiness") == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
