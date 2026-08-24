#!/usr/bin/env python3
"""Report acceptance criteria that cannot be verified.

`state-machine.yml` requires `acceptance_criteria_satisfied` as evidence for
Output Done. That evidence is only as good as the criteria: against "works
correctly", satisfaction is an opinion.

Reports rather than blocks. Prose has judgement in it, and a linter confident
enough to reject text is a linter people route around by rewording. What it can
do reliably is name the phrases nobody can observe, and notice when a set
describes only success.

Reads the contract from installed policy rather than carrying its own copy, so
changing the rules changes the linter.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

# A criterion header: "AC1 — name", "AC1: name", or a bare numbered line.
AC_HEADER = re.compile(r"^\s*(?:AC\s*\d+|\d+[.)])\s*[—\-:]?\s*(.*)$", re.IGNORECASE)
GIVEN = re.compile(r"^\s*given\b", re.IGNORECASE | re.MULTILINE)
WHEN = re.compile(r"^\s*when\b", re.IGNORECASE | re.MULTILINE)
THEN = re.compile(r"^\s*(?:then|and)\b", re.IGNORECASE | re.MULTILINE)

# Words that signal a criterion covering something other than the happy path.
NEGATIVE_SIGNALS = (
    "not ", "no ", "refus", "reject", "fail", "error", "invalid", "missing",
    "absent", "denied", "empty", "unknown", "stale", "conflict", "boundary",
    "without", "cannot", "exceeds", "unauthorized", "unauthorised",
)


@dataclass(frozen=True)
class Finding:
    criterion: str
    problem: str

    def __str__(self) -> str:
        return f"{self.criterion}: {self.problem}"


def load_policy(root: Path) -> dict:
    """The whole item-types policy, not only the acceptance contract.

    Which types carry acceptance criteria is a fact about the policy, and the
    linter needs it to know whether an item has criteria to lint at all.
    """
    for candidate in (
        root / ".specify/presets/lean-full-lifecycle-governance/policy/item-types.yml",
        root / "policy/item-types.yml",
    ):
        if candidate.is_file():
            return yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    raise FileNotFoundError(
        "item-types.yml not found; the governance preset must be installed"
    )


def load_contract(root: Path) -> dict:
    for candidate in (
        root / ".specify/presets/lean-full-lifecycle-governance/policy/item-types.yml",
        root / "policy/item-types.yml",
    ):
        if candidate.is_file():
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            contract = data.get("acceptance_criteria")
            if contract:
                return contract
    raise FileNotFoundError(
        "acceptance contract not found; the governance preset must be installed"
    )


def split_criteria(text: str) -> list[tuple[str, str]]:
    """Split into (label, body). Untitled text is treated as one criterion."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if AC_HEADER.match(ln) and ln.strip()]
    if not starts:
        return [("criteria", text)] if text.strip() else []
    out = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        label = lines[start].strip().split("—")[0].split(":")[0].strip()
        out.append((label or f"AC{n + 1}", "\n".join(lines[start:end])))
    return out


def lint(text: str, contract: dict) -> list[Finding]:
    findings: list[Finding] = []
    criteria = split_criteria(text)
    if not criteria:
        return [Finding("criteria", "no acceptance criteria given")]

    banned = contract.get("banned_phrases") or []
    for label, body in criteria:
        lowered = body.lower()
        for entry in banned:
            phrase = str(entry["phrase"]).lower()
            if re.search(rf"\b{re.escape(phrase)}\b", lowered):
                findings.append(Finding(
                    label, f"contains {entry['phrase']!r}: {entry['because']}"))
        if not THEN.search(body):
            findings.append(Finding(
                label, "no Then clause, so nothing observable is asserted"))
        elif not (GIVEN.search(body) and WHEN.search(body)):
            findings.append(Finding(
                label, "not in Given/When/Then form: the context or the action "
                       "is missing, so it cannot be executed"))

    joined = " ".join(b for _, b in criteria).lower()
    if not any(signal in joined for signal in NEGATIVE_SIGNALS):
        findings.append(Finding(
            "set", "every criterion describes success; none covers a failure, "
                   "refusal, or boundary"))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", type=Path, help="Read criteria from a file.")
    src.add_argument("--issue", type=int, help="Read the acceptance section of an issue.")
    ap.add_argument("--repo", help="owner/name, required with --issue")
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()
    try:
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    contract = load_contract(args.policy_root)

    if args.file:
        text = args.file.read_text(encoding="utf-8")
    else:
        if not args.repo:
            print("--repo is required with --issue", file=sys.stderr)
            return 2
        from github_api import GitHub

        issue = GitHub().rest(
            "GET", f"repos/{args.repo}/issues/{args.issue}") or {}
        labels = {str(l.get("name", "")).lower()
                  for l in issue.get("labels") or []}
        item_type = next((t for t in ("epic", "story", "bug", "spike")
                          if t in labels), None)
        findings, account = lint_issue(
            str(issue.get("body") or ""), item_type, contract,
            load_policy(args.policy_root))
        if args.format != "json":
            print(account)
        return _report(findings, args.format)

    findings = lint(text, contract)
    return _report(findings, args.format)


def _report(findings: list["Finding"], fmt: str) -> int:
    if fmt == "json":
        print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        for finding in findings:
            print(finding)
        print(f"\n{len(findings)} findings")
    return 1 if findings else 0


# A section heading, written either as markdown heading or as a bold line.
# Both occur in practice, and matching only the first silently linted the whole
# issue body instead of its criteria.
_SECTION = re.compile(
    r"^(?:#{1,6}\s*|\*\*)\s*Acceptance criteria\s*(?:\*\*)?\s*$"
    r"(.*?)"
    r"(?=^(?:#{1,6}\s|\*\*[A-Z]).*$|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def extract_section(body: str) -> str | None:
    """The acceptance section of an issue body, or None when there is none.

    None rather than the whole body. Falling back meant a bug's Reproduction
    and a spike's Exit criteria were split into pseudo-criteria and asked for
    Given/When/Then clauses `item-types.yml` never requires of them, so every
    refinement of a non-story produced advisories about prose that was never
    criteria. Advisories that always fire teach a reader to skip them.
    """
    match = _SECTION.search(body)
    if not match:
        return None
    # Criteria are usually fenced so they render as written; the fences are not
    # part of them.
    return re.sub(r"^```\w*$", "", match.group(1), flags=re.MULTILINE)


def acceptance_types(policy: dict) -> set[str]:
    """Item types whose contract includes an acceptance section.

    Read from the policy rather than listed here: `item-types.yml` decides
    which types carry criteria, and a second copy in this file is the copy
    that drifts when a type gains or loses the section.
    """
    out = set()
    for name, spec in (policy.get("types") or {}).items():
        for section in (spec or {}).get("sections") or []:
            if section.get("id") == "acceptance":
                out.add(name)
    return out


def lint_issue(body: str, item_type: str | None, contract: dict,
               policy: dict) -> tuple[list[Finding], str]:
    """Lint an issue's criteria if its type has any, and say what was done.

    Returns the findings and a one-line account of the decision, because
    "no findings" and "not applicable" are different results and a report that
    renders them identically is why this was not noticed sooner.
    """
    carries = acceptance_types(policy)
    if item_type and item_type not in carries:
        return [], (f"not linted: {item_type} has no acceptance section in "
                    f"item-types.yml; {sorted(carries)} do")
    section = extract_section(body)
    if section is None:
        if item_type in carries:
            return ([Finding("criteria", "no Acceptance criteria section")],
                    f"{item_type} requires acceptance criteria and has none")
        return [], "no acceptance section, and the type is unknown; not linted"
    return lint(section, contract), f"linted the acceptance section of a {item_type or 'item'}"


if __name__ == "__main__":
    sys.exit(main())
