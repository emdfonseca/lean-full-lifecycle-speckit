#!/usr/bin/env python3
"""Check a project's core documents against the contract that declares them.

`bootstrap-policy.yml` names the documents a bootstrapped project must have,
what each answers, the sections it carries, and how long it may be. This checks
a project against that.

The budgets are the point. A brownfield adoption produced four artefacts
averaging 234 lines -- accurate, well-reasoned, and too long to read before
writing a spec. Length is the one quality property a script can judge, so it is
the one this enforces; the rest is stated in the style rules for a person to
apply.

Two refusals:

A missing document is a failure, not a warning. A project without a product
definition cannot have a spec written against it, and reporting that as advice
lets the gap survive.

A document over budget is a failure with the overage named. Not truncated, not
warned about: the budget is a maximum somebody chose, and a document that needs
more room usually needs less content.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/bootstrap-policy.yml",
    "policy/bootstrap-policy.yml",
)


def load_contract(root: Path | None = None) -> dict:
    base = root or project_root.resolve(required=False) or Path.cwd()
    for rel in POLICY_CANDIDATES:
        path = base / rel
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            contract = data.get("product_documents")
            if contract:
                return contract
    raise FileNotFoundError(
        "bootstrap-policy.yml declares no product_documents; the governance "
        "preset must be installed")


def headings(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            out.add(stripped.lstrip("#").strip().lower())
        elif stripped.startswith("**") and stripped.endswith("**"):
            out.add(stripped.strip("*").strip().lower())
    return out


def check(root: Path, contract: dict) -> list[str]:
    problems: list[str] = []
    for spec in contract.get("required") or []:
        path = root / spec["path"]
        name = spec["path"]
        if not path.is_file():
            problems.append(
                f"{name} is missing. It answers: {spec.get('answers', '')} "
                f"Without it nothing downstream has a product to refer to.")
            continue

        text = path.read_text(encoding="utf-8")
        budget = int(spec.get("max_lines") or 0)
        lines = len(text.splitlines())
        if budget and lines > budget:
            problems.append(
                f"{name} is {lines} lines against a budget of {budget}. "
                f"A document that needs more room usually needs less content; "
                f"evidence belongs in an evidence record.")

        present = headings(text)
        missing = [s for s in (spec.get("sections") or [])
                   if s.lower() not in present]
        if missing:
            problems.append(
                f"{name} is missing the section(s) {missing}. The contract "
                f"names them because a reader looks for them by name.")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy-root", type=Path, default=None)
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    try:
        root = project_root.resolve(args.policy_root, required=False) or Path.cwd()
        contract = load_contract(root)
    except (project_root.ProjectRootError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problems = check(root, contract)
    if args.format == "json":
        print(json.dumps({"problems": problems, "complete": not problems,
                          "style": contract.get("style", [])}, indent=2))
    else:
        for problem in problems:
            print(f"MISSING {problem}")
        if not problems:
            print("Every declared document is present and within budget.")
        print(f"\n{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
