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


def decision_records(root: Path, contract: dict) -> dict:
    """Which directory this project keeps its decision records in.

    The contract named docs/decisions/ in prose, which is this repository's own
    directory. A target keeping five Nygard ADRs in docs/adr/ was invisible to
    it, so the architecture document would have delegated arc42 section 9 to a
    directory the project does not have while the records it does have sat
    unread beside it (#141).

    Shaped like `inspect_target`: candidates declared in preference order, and
    ambiguity refused rather than resolved. Two directories holding records is
    reported, because which set of decisions is authoritative is a person's
    call. The order only answers the empty case -- a project with no records
    is told where new ones go, which a greenfield project needs by definition.
    """
    candidates = [str(c) for c in
                  ((contract.get("decision_records") or {}).get("candidates") or [])]
    holding = [c for c in candidates if _holds_records(root / c)]
    result = {"candidates": candidates, "found": holding,
              "resolved": None, "problem": None, "note": ""}
    if len(holding) == 1:
        result["resolved"] = holding[0]
    elif len(holding) > 1:
        result["problem"] = (
            "decision records are in more than one place: "
            + ", ".join(holding)
            + ". Which set is authoritative is a decision for a person, so "
              "this is reported rather than resolved by preference order.")
    elif candidates:
        result["resolved"] = candidates[0]
        result["note"] = (
            f"No decision records found. New ones go in {candidates[0]}, the "
            f"first declared candidate.")
    return result


def _holds_records(path: Path) -> bool:
    """A candidate directory holds records when it has a Markdown file in it.

    Existence alone is not enough: an empty docs/adr/ is a directory somebody
    made, not a set of decisions the project keeps.
    """
    return path.is_dir() and any(path.glob("*.md"))


def entries_of(form: str, body: str) -> list[str]:
    """The claim-bearing entries of a section, by its declared form.

    A table row's claim is its first cell; a list item's is its text. Prose
    holds no per-entry claim and yields none, which is why `Context and scope`
    carries no provenance rather than being exempted by name.
    """
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if form == "table":
        rows = [ln for ln in lines if ln.startswith("|")]
        out = []
        for row in rows[2:]:                     # header and separator first
            cells = [c.strip() for c in row.strip("|").split("|")]
            if cells:
                out.append(cells[0])
        return out
    if form == "list":
        return [re.sub(r"^([-*]|\d+\.)\s*", "", ln) for ln in lines
                if re.match(r"^([-*]|\d+\.)\s", ln)]
    return []


def provenance_of(entry: str, markers: dict) -> str | None:
    """Which marker an entry opens with, or None.

    Opens with, not contains. An entry that mentions what was observed
    elsewhere in its own sentence has not classified itself, and accepting that
    would make the marker decorative.
    """
    text = entry.lstrip("*_ ").lstrip()
    for key, word in markers.items():
        if text.lower().startswith(str(word).lower()):
            return key
    return None


def provenance_problems(name: str, spec: dict, found: dict) -> list[str]:
    """Entries that do not say whether they describe the code or propose a change.

    Two findings, and the second is the one that only shows up in a project
    with code: a proposed change filed under the decisions heading is a fix,
    and a fix belongs where fixes are tracked. A project that observes nothing
    has nothing to remediate, so everything there is legitimately intended.
    """
    rules = spec.get("provenance") or {}
    markers = rules.get("markers") or {}
    if not markers:
        return []

    problems: list[str] = []
    forms = {s["name"]: s.get("form", "") for s in spec.get("sections") or []}
    classified: dict[str, list[tuple[str, str]]] = {}

    for title in rules.get("applies_to") or []:
        body = found.get(title.lower())
        if body is None:
            continue                      # a missing section is already reported
        for entry in entries_of(forms.get(title, ""), body):
            kind = provenance_of(entry, markers)
            if kind is None:
                problems.append(
                    f"{name}: {title!r} entry {entry[:60]!r} declares neither "
                    f"{' nor '.join(str(w) for w in markers.values())}. "
                    f"Unmarked reads as observed, and a reader who takes a "
                    f"proposal for a description acts on a false statement "
                    f"about the code.")
                continue
            classified.setdefault(title, []).append((kind, entry))

    remediation = rules.get("remediation") or {}
    section = remediation.get("section")
    if section and any(kind == "observed"
                       for entries in classified.values()
                       for kind, _ in entries):
        for kind, entry in classified.get(section, []):
            if kind == "intended":
                problems.append(
                    f"{name}: {section!r} entry {entry[:60]!r} is "
                    f"{markers['intended']}, which in a document that observes "
                    f"anything is a fix rather than a decision. It belongs "
                    f"under {remediation.get('belongs')!r}.")
    return problems


def check(root: Path, contract: dict, today: date | None = None) -> list[str]:
    problems: list[str] = []
    ambiguity = decision_records(root, contract)["problem"]
    if ambiguity:
        problems.append(ambiguity)
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
        problems.extend(provenance_problems(name, spec, found))
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
    records = decision_records(root, contract)
    if args.format == "json":
        print(json.dumps({"problems": problems, "complete": not problems,
                          "style": contract.get("style", []),
                          "decision_records": records}, indent=2))
    else:
        for problem in problems:
            print(f"MISSING {problem}")
        if not problems:
            print("Every declared section is present and in the form the "
                  "contract asks for.")
        if records["resolved"]:
            print(f"\nDecision records: {records['resolved']}"
                  + (f" -- {records['note']}" if records["note"] else ""))
        print(f"\n{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
