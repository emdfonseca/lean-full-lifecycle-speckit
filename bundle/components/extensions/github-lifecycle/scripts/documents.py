#!/usr/bin/env python3
"""Check a project's core documents against the contract that declares them.

`bootstrap-policy.yml` names the documents a bootstrapped project must have,
what each answers, the sections it carries, and how long it may be. This checks
a project against that.

Form is what is checked, not length. A line budget is wrong for somebody: the
first version set the constitution at 200 lines, which would have meant deleting
principles from a real one to fit. What scales instead is shape -- a table with
one row per fact cannot ramble however large the project, and a section declared
as a list shows how many entries it has.

Three refusals:

A missing document is a failure, not a warning. A project without a product
definition cannot have a spec written against it, and reporting that as advice
lets the gap survive.

An empty section is a heading. A declared section with nothing under it claims
an answer nobody wrote.

A section in the wrong form is a failure. Prose where the contract asked for a
table is how a section of facts grows without a shape to hold it -- which is
what this command was written after seeing.

`per_principle` is enforced: a principle states something normative and states
it first. Applied to a real constitution it found 11 of 23 principles with no
MUST, SHOULD, or MAY anywhere in them -- headings over opinions.

Not yet enforced: `per_entry`, for the decision log. An entry's four ADR fields
are read by a person until something checks them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
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


def sections_of(text: str) -> dict[str, str]:
    """Each heading and the body under it.

    Both heading styles are matched. Recognising only one would report a
    present section as absent, which teaches an author to ignore the check.
    """
    out: dict[str, str] = {}
    current = None
    body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        name = None
        if stripped.startswith("#"):
            name = stripped.lstrip("#").strip()
        elif stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            name = stripped.strip("*").strip()
        if name is not None:
            if current:
                out[current.lower()] = "\n".join(body)
            current, body = name, []
        else:
            body.append(line)
    if current:
        out[current.lower()] = "\n".join(body)
    return out


def form_problem(name: str, form: str, body: str) -> str | None:
    """Whether the section's shape matches what the contract asked for.

    Form is what makes terseness scale. A table with one row per fact cannot
    ramble however large the project; a line budget can only be wrong for
    somebody. This checks the shape and leaves the judgement to a reader.
    """
    content = [ln for ln in body.splitlines() if ln.strip()]
    if not content:
        return f"{name!r} is empty. A declared section with nothing in it is a heading."

    if form == "table":
        rows = [ln for ln in content if ln.strip().startswith("|")]
        if len(rows) < 3:            # header, separator, and at least one row
            return (f"{name!r} is declared as a table and has none. Facts go in "
                    f"tables, one row each; prose here will grow without a shape "
                    f"to hold it.")
    elif form == "list":
        if not any(ln.strip().startswith(("-", "*", "1.")) for ln in content):
            return (f"{name!r} is declared as a list and has no items. A list "
                    f"makes each entry stand alone; a paragraph hides how many "
                    f"there are.")
    elif form == "prose":
        sentences = sum(body.count(c) for c in ".!?")
        if sentences > 6:
            return (f"{name!r} is prose and runs to about {sentences} sentences. "
                    f"Prose is for the one thing a table cannot hold; if this is "
                    f"a list of facts, it is a table.")
    return None


NORMATIVE = ("MUST NOT", "MUST", "SHOULD NOT", "SHOULD", "MAY")


def principles_of(text: str) -> list[tuple[str, list[str]]]:
    """Each `###` heading and its body.

    Third level because the constitutions in use put sections at `##` and
    principles beneath them. A document with no third level has no principles
    to check, which is reported rather than passed.
    """
    out: list[tuple[str, list[str]]] = []
    name, body = None, []
    for line in text.splitlines():
        if line.startswith("### "):
            if name:
                out.append((name, body))
            name, body = line[4:].strip(), []
        elif name is not None:
            body.append(line)
    if name:
        out.append((name, body))
    return out


# A list item, table row, or block quote -- the structures the preamble count
# exempts. Any ordinal is a list item: exempting `1.` alone made the second and
# third steps of a numbered cycle read as prose.
STRUCTURE = re.compile(r"^(?:[-*+>|]|\d+[.)](?:\s|$))")


def blocks_of(lines: list[str]) -> list[str]:
    """Each structure or prose line, with the lines it wraps onto.

    A bullet that wraps is one bullet. Counting its continuation lines as prose
    made the passing shape depend on the wrap column, so a principle in exactly
    the form the contract asks for was reported whenever its rule ran past the
    margin.

    Prose lines are not joined to each other. Three consecutive prose lines are
    three, which is what the preamble count is there to catch; only a
    continuation of a structure is folded into it.
    """
    out: list[list[str]] = []
    for line in lines:
        continues = (out and line[:1].isspace()
                     and STRUCTURE.match(out[-1][0].strip()))
        if continues and not STRUCTURE.match(line.strip()):
            out[-1].append(line)
        else:
            out.append([line])
    return ["\n".join(block) for block in out]


def principle_problems(path_name: str, text: str) -> list[str]:
    """Whether each principle is a rule or an essay with a rule in it.

    Two properties, both checkable. A principle states something normative --
    without an RFC 2119 keyword it is an opinion, however well argued. And the
    rule comes first: at most one line before it, which is the rule statement
    itself. An explanatory paragraph in front means the rule is not yet
    written, and the reader has to extract it.
    """
    found = principles_of(text)
    if not found:
        return [f"{path_name} declares per-principle rules and has no `###` "
                f"principles to apply them to."]

    problems = []
    for name, body in found:
        blocks = blocks_of([ln for ln in body if ln.strip()])
        first = next((i for i, block in enumerate(blocks)
                      if any(k in block for k in NORMATIVE)), None)
        if first is None:
            problems.append(
                f"{path_name}: {name!r} states no MUST, SHOULD, or MAY. "
                f"Without one it is an opinion, however well argued.")
            continue
        preamble = [block for block in blocks[:first]
                    if not STRUCTURE.match(block.strip())]
        if len(preamble) > 1:
            problems.append(
                f"{path_name}: {name!r} has {len(preamble)} lines of prose "
                f"before its first rule. One line states the rule; more than "
                f"that means the rule is not yet written and the reader has "
                f"to extract it.")
    return problems


FRESHNESS = re.compile(
    r"^Last verified:\s*(\d{4}-\d{2}-\d{2})\s*\(change:\s*([^)]+)\)\s*$",
    re.MULTILINE)


def freshness_problems(path_name: str, text: str, rule: dict,
                       today: date) -> list[str]:
    """Whether a document says when it was last checked, and by what.

    Nothing here made a stale document visible: one that stopped being true
    read exactly like one that is. The date is evidence of when the claim was
    checked, which is why it carries a change id -- a date alone says somebody
    typed a date.

    A future date is refused rather than reported. It cannot be contradicted by
    anything, so it is a stamp that permanently claims freshness, which is
    worse than no stamp at all.
    """
    if not rule.get("required"):
        return []
    match = FRESHNESS.search(text)
    if not match:
        return [f"{path_name} carries no `{rule['line']}` line. Without it a "
                f"document that stopped being true reads exactly like one "
                f"that is."]
    if not rule.get("refuse_future_dates"):
        return []
    try:
        stamped = date.fromisoformat(match.group(1))
    except ValueError:
        return [f"{path_name}: {match.group(1)!r} is not a date."]
    if stamped > today:
        return [f"{path_name} is verified {stamped.isoformat()}, which is in "
                f"the future. Nothing can contradict it, so it claims "
                f"freshness permanently."]
    return []


def check(root: Path, contract: dict, today: date | None = None) -> list[str]:
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
        problems.extend(freshness_problems(
            name, text, contract.get("freshness") or {},
            today or date.today()))
        if spec.get("per_principle"):
            problems.extend(principle_problems(name, text))

        found = sections_of(text)
        for section in spec.get("sections") or []:
            title = section["name"]
            body = found.get(title.lower())
            if body is None:
                problems.append(
                    f"{name}: section {title!r} is missing. It answers: "
                    f"{section.get('answers', '').strip()}")
                continue
            issue = form_problem(f"{name}: {title}", section.get("form", ""), body)
            if issue:
                problems.append(issue)
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
            print("Every declared section is present and in the form the "
                  "contract asks for.")
        print(f"\n{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
