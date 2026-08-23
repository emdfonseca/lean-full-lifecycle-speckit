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
    ap.add_argument("--policy-root", type=Path, default=Path.cwd())
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    contract = load_contract(args.policy_root)

    if args.file:
        text = args.file.read_text(encoding="utf-8")
    else:
        if not args.repo:
            print("--repo is required with --issue", file=sys.stderr)
            return 2
        from github_api import GitHub

        body = GitHub().rest("GET", f"repos/{args.repo}/issues/{args.issue}",
                             jq=".body") or ""
        text = extract_section(str(body))

    findings = lint(text, contract)
    if args.format == "json":
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


def extract_section(body: str) -> str:
    """The acceptance section of an issue body, or the whole body."""
    match = _SECTION.search(body)
    text = match.group(1) if match else body
    # Criteria are usually fenced so they render as written; the fences are not
    # part of them.
    return re.sub(r"^```\w*$", "", text, flags=re.MULTILINE)


if __name__ == "__main__":
    sys.exit(main())
