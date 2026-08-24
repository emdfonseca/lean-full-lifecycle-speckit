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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verdict", type=Path, required=True)
    ap.add_argument("--issue", type=int, help="Also lint this issue's criteria.")
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

    try:
        schema = load_schema(args.policy_root)
        verdict = load_verdict(args.verdict)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problems = check(verdict, schema)
    lint_account = ""
    advisories: list[str] = []

    if args.issue:
        if not args.repo:
            print("--repo is required with --issue", file=sys.stderr)
            return 2
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
    print(f"\nVerdict is valid. readiness={verdict.get('readiness')!r}"
          + (f", {len(advisories)} advisory finding(s) on the criteria."
             if advisories else "."))
    return 0 if verdict.get("readiness") == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
