#!/usr/bin/env python3
"""Bound the interview a bootstrap must run before it writes product documents.

`bootstrap-policy.yml` declares under `product_elicitation` the questions whose
answers the seven product documents encode, the order they are asked in, and
the shape of the record that holds them. This emits that plan and validates
that record.

The asking itself is the agent's. Nothing here can put a question to a person,
and pretending otherwise would produce a script that reports an interview it
never ran. What it can do is make the interview checkable: the plan is derived
from the contract rather than composed, so a question cannot quietly leave the
set, and the record is validated against the same contract, so an answer cannot
quietly arrive without one.

Three refusals, and the third is the one this exists for.

A record missing a declared question is refused. Not asked and asked-then-
declined are different facts and the whole item turns on the difference: a
decline is recorded with a reason, put under `Open` in the decision log, named
as unanswered in the section that wanted it, and carried to the final gate. An
omission is a question nobody reached.

A decline with no reason is refused. A `declined` carrying nothing is
indistinguishable from a question that was skipped, which is the same defect
`gate_resolution` above records having already had once.

A question dropped as `settled_by` an answer that does not exist is refused.
`settled_by` is how an earlier answer removes a later question visibly;
pointing it at a decline drops the question with the one word that makes the
drop look deliberate.

An answer that is a value where a decline belongs is not something this can
detect, and it is not claimed. What is checked is that every question was put.

Nothing here blocks a run. `--unresolved` reports the declines for the
bootstrap report's `Unresolved blockers:` line, because a person deciding at
`accept-the-bootstrap-report` should see the total rather than one decline at a
time.
"""
from __future__ import annotations

import argparse
import json
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


class ContractError(Exception):
    """The contract is absent or declares no questions."""


def load_contract(root: Path | None = None) -> dict:
    base = root or project_root.resolve(required=False) or Path.cwd()
    for rel in POLICY_CANDIDATES:
        path = base / rel
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            contract = data.get("product_elicitation")
            if contract:
                return contract
    raise ContractError(
        "bootstrap-policy.yml declares no product_elicitation; the governance "
        "preset must be installed")


def record_path(root: Path, contract: dict) -> Path:
    rel = (contract.get("record") or {}).get("path")
    if not rel:
        raise ContractError(
            "product_elicitation declares no record path, so there is nowhere "
            "for an answer to live")
    return root / rel


def plan(contract: dict) -> list[dict]:
    """The questions, in declared order, each carrying what the asker needs.

    Order is the contract's, not this function's. `form.ordered` says each
    question must be answerable given the ones before it, and that property is
    a property of the sequence as written -- sorting or grouping here would
    destroy it while looking tidier.
    """
    out = []
    for question in contract.get("questions") or []:
        out.append({
            "id": question["id"],
            "ask": question["ask"],
            "form": question.get("form", "closed"),
            "changes": question.get("changes", ""),
            "feeds": question.get("feeds") or [],
        })
    return out


def _declared_ids(contract: dict) -> list[str]:
    return [q["id"] for q in contract.get("questions") or []]


def validate(contract: dict, record: dict) -> list[str]:
    """Findings against the record. Empty means the interview is accounted for."""
    problems: list[str] = []
    spec = contract.get("record") or {}
    per = spec.get("per_answer") or {}
    statuses = list((per.get("status") or {}).get("values") or [])

    if not record.get("asked_on"):
        problems.append(
            "the record carries no `asked_on`. Without a date the answers "
            "cannot be placed in time, so a later contradiction cannot be "
            "told from a later decision.")
    else:
        try:
            when = date.fromisoformat(str(record["asked_on"])) \
                if not isinstance(record["asked_on"], date) else record["asked_on"]
            if when > date.today():
                problems.append(
                    f"`asked_on` is {when.isoformat()}, which is in the "
                    f"future. A date nobody can contradict is worse than no "
                    f"date.")
        except ValueError:
            problems.append(
                f"`asked_on` is {record['asked_on']!r}, which is not a date.")

    answers = record.get("answers")
    if not isinstance(answers, list):
        problems.append(
            "the record carries no `answers` list. An interview with no "
            "answers recorded is one that cannot be shown to have happened.")
        answers = []

    seen: dict[str, dict] = {}
    for entry in answers:
        if not isinstance(entry, dict) or not entry.get("id"):
            problems.append(f"an answer entry has no id: {entry!r}")
            continue
        if entry["id"] in seen:
            problems.append(
                f"{entry['id']} is recorded twice. One question has one "
                f"current answer, not one per attempt.")
        seen[entry["id"]] = entry

    declared = _declared_ids(contract)
    for qid in declared:
        entry = seen.get(qid)
        if entry is None:
            problems.append(
                f"{qid} is declared and absent from the record. Not asked and "
                f"asked-then-declined are different facts: a decline is "
                f"recorded with a reason and carried to the final gate, and an "
                f"omission is a question nobody reached.")
            continue
        status = entry.get("status")
        if status not in statuses:
            problems.append(
                f"{qid} has status {status!r}, which is not one of "
                f"{', '.join(statuses)}.")
            continue
        if status == "answered" and not str(entry.get("answer") or "").strip():
            problems.append(
                f"{qid} is `answered` and carries no answer. A status word "
                f"with no content is the failure this record exists to end.")
        if status == "declined" and not str(entry.get("reason") or "").strip():
            problems.append(
                f"{qid} is `declined` and carries no reason. A decline with no "
                f"reason is indistinguishable from a question that was skipped.")
        if status == "settled_by":
            by = str(entry.get("settled_by") or "").strip()
            if not by:
                problems.append(
                    f"{qid} is `settled_by` and names nothing. A question "
                    f"dropped without naming what dropped it was skipped.")
            elif by not in declared:
                problems.append(
                    f"{qid} says it was settled by {by!r}, which is not a "
                    f"declared question.")
            elif (seen.get(by) or {}).get("status") != "answered":
                # A question dropped by an answer that does not exist is a
                # question nobody asked, wearing the one word that makes it
                # look deliberate.
                problems.append(
                    f"{qid} says it was settled by {by}, which is "
                    f"{(seen.get(by) or {}).get('status', 'absent')!r} rather "
                    f"than answered. A question dropped by an answer nobody "
                    f"gave was not settled; it was skipped.")

    for qid in seen:
        if qid not in declared:
            problems.append(
                f"{qid} is recorded and not declared. An answer to a question "
                f"the contract does not ask is not traceable to a document "
                f"section.")
    return problems


def unresolved(contract: dict, record: dict) -> list[dict]:
    """The declines, for the bootstrap report's blockers line."""
    by_id = {q["id"]: q for q in contract.get("questions") or []}
    out = []
    for entry in record.get("answers") or []:
        if isinstance(entry, dict) and entry.get("status") == "declined":
            question = by_id.get(entry.get("id"), {})
            out.append({
                "id": entry.get("id"),
                "ask": question.get("ask", ""),
                "reason": entry.get("reason", ""),
                "feeds": question.get("feeds") or [],
            })
    return out


def load_record(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} does not exist. The interview has not run, and every "
            f"document written now would encode answers nobody gave.")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true",
                    help="Emit the ordered question plan and stop. Asks nothing.")
    ap.add_argument("--check", action="store_true",
                    help="Validate the recorded answers against the contract.")
    ap.add_argument("--unresolved", action="store_true",
                    help="List the declines, for the report's blockers line.")
    ap.add_argument("--record", type=Path, default=None,
                    help="The answer record. Defaults to the contract's path.")
    ap.add_argument("--policy-root", type=Path, default=None)
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    if not (args.plan or args.check or args.unresolved):
        ap.error("choose --plan, --check, or --unresolved")

    try:
        root = project_root.resolve(args.policy_root, required=False) or Path.cwd()
        contract = load_contract(root)
    except (project_root.ProjectRootError, ContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.plan:
        questions = plan(contract)
        if args.format == "json":
            print(json.dumps({"form": contract.get("form", {}),
                              "decline": contract.get("decline", {}),
                              "citation": contract.get("citation", {}),
                              "record": (contract.get("record") or {}).get("path"),
                              "questions": questions}, indent=2))
        else:
            rules = contract.get("form") or {}
            print("How to ask:")
            for name, rule in rules.items():
                print(f"  {name}: {' '.join(str(rule).split())}")
            print(f"\n{len(questions)} question(s), in this order. "
                  f"Ask one, wait, then ask the next.\n")
            for question in questions:
                fed = ", ".join(f"{f['document']} > {f['section']}"
                                for f in question["feeds"])
                print(f"  {question['id']} [{question['form']}] {question['ask']}")
                print(f"       changes: {' '.join(question['changes'].split())}")
                print(f"       feeds:   {fed}")
        return 0

    path = args.record or record_path(root, contract)
    try:
        record = load_record(path)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.unresolved:
        items = unresolved(contract, record)
        if args.format == "json":
            print(json.dumps({"unresolved": items}, indent=2))
        else:
            if not items:
                print("Unresolved blockers: none")
            else:
                print("Unresolved blockers:")
                for item in items:
                    print(f"  {item['id']} unanswered: {item['ask']} "
                          f"-- {item['reason']}")
        return 0

    problems = validate(contract, record)
    if args.format == "json":
        print(json.dumps({"problems": problems, "complete": not problems,
                          "record": str(path)}, indent=2))
    else:
        for problem in problems:
            print(f"MISSING {problem}")
        if not problems:
            print(f"Every declared question is accounted for in {path}.")
        print(f"\n{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
