#!/usr/bin/env python3
"""Search for duplicates, then create a backlog item only when asked.

Capture exists because findings arrive mid-flight — during delivery, review, or
an incident — and the cost of losing them is silent. The cost of recording them
carelessly is a backlog nobody trusts, so this searches first and creates second.

Distinct from upstream `speckit.taskstoissues`, which converts a feature's
tasks.md into dependency-ordered issues. That is implementation decomposition
inside a feature; this is capture of a finding into the backlog, with the
duplicate search that makes a backlog survivable.

Searching is the default. Creation requires --create and an explicit type, so
the safe operation is the one that happens by accident.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

from github_api import GitHub, GitHubError, NotFound  # noqa: E402

# Words carrying no signal for similarity.
STOPWORDS = frozenset("""
a an the and or but if then than that this these those for from with without
to of in on at by is are was were be been being do does did not no as it its
""".split())

DEFAULT_THRESHOLD = 0.45


@dataclass(frozen=True)
class Candidate:
    number: int
    title: str
    state: str
    score: float


# Crude suffix stripping, not a stemmer. Exact token matching missed
# "type"/"types" and "contract"/"contracts", which is the commonest way one
# person rewords another's title.
_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ies")
# "es" is only a plural after a sibilant. Stripping it unconditionally turned
# "types" into "typ" while "type" stayed whole, so the two stopped matching --
# which is the exact case the stemmer was added for.
_SIBILANTS = ("ch", "sh", "ss", "x", "z", "s")


def stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            base = word[: -len(suffix)]
            return base + "y" if suffix == "ies" else base
    if len(word) > 3 and word.endswith("es") and word[:-2].endswith(_SIBILANTS):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    return {stem(w) for w in words if w not in STOPWORDS and len(w) > 2}


def similarity(a: str, b: str) -> float:
    """Jaccard over meaningful words.

    Deliberately crude and explainable. A cleverer measure would be harder to
    argue with when it is wrong, and this only has to raise candidates for a
    human, never to decide.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def search_duplicates(gh: GitHub, repo: str, title: str,
                      threshold: float = DEFAULT_THRESHOLD,
                      include_closed: bool = True) -> list[Candidate]:
    """Open and closed issues resembling the proposed title.

    Closed issues are included: something already decided, rejected, or fixed
    is exactly what a duplicate report needs to surface.
    """
    state = "all" if include_closed else "open"
    rows = gh.rest("GET", f"repos/{repo}/issues?state={state}", paginate=True) or []
    if isinstance(rows, dict):
        rows = [rows]
    found = []
    for row in rows:
        if row.get("pull_request") or row.get("number") is None:
            continue
        score = similarity(title, row.get("title", ""))
        if score >= threshold:
            found.append(Candidate(int(row["number"]), str(row.get("title", "")),
                                   str(row.get("state", "")), round(score, 3)))
    return sorted(found, key=lambda c: -c.score)


def has_evidence(body: str, item_type: str) -> list[str]:
    """Sections a type requires that this body does not have.

    A finding with no reproduction and no stated outcome is an observation,
    and filing it as work makes the backlog less trustworthy rather than more
    complete.
    """
    required = {
        "bug": ["reproduction", "expected", "actual"],
        "story": ["acceptance"],
        "spike": ["question", "exit criteria"],
    }.get(item_type, [])
    lowered = body.lower()
    return [name for name in required if name not in lowered]


def unconsidered(candidates: list["Candidate"], considered: list[int]) -> list[int]:
    """Candidates the caller has not said anything about.

    Every candidate, not any candidate. A flag that cleared the whole report
    once one item was named would let the second duplicate through unseen,
    which is the failure the report exists to prevent.
    """
    seen = set(considered or [])
    return [c.number for c in candidates if c.number not in seen]


def phantom_considerations(candidates: list["Candidate"], considered: list[int]) -> list[int]:
    """Numbers named as considered that the search never raised.

    Refused rather than ignored. A decision recorded against an item the
    search did not surface is either a typo or a claim about something the
    author never actually compared, and both should be corrected before the
    record is written.
    """
    raised = {c.number for c in candidates}
    return [n for n in (considered or []) if n not in raised]


PROVENANCE = "Found during "


def with_provenance(body: str, found_in: int | None) -> str:
    """Record where a finding came from, in the body, as a real reference.

    A cross-reference rather than a field: GitHub renders `#12` as a link from
    both ends, so the source issue shows the finding without anything here
    writing to it. A `found_in` stored only in this command's JSON output
    would be provenance nobody reading the backlog ever sees.
    """
    if found_in is None:
        return body
    line = f"{PROVENANCE}#{found_in}."
    if line in body:
        return body
    return f"{body.rstrip()}\n\n{line}\n"


def create_item(gh: GitHub, repo: str, title: str, body: str, item_type: str,
                parent: int | None = None, operation_id: str | None = None,
                project: int | None = None,
                policy_root: Path | None = None,
                considered: list[int] | None = None,
                found_in: int | None = None) -> dict:
    body = with_provenance(body, found_in)
    created = gh.rest("POST", f"repos/{repo}/issues",
                      body={"title": title, "body": body, "labels": [item_type]},
                      operation_id=operation_id)
    if getattr(gh, "dry_run", False):
        # Nothing was created, so there is nothing to read back or link.
        # Reporting the intent is the whole point of a dry run.
        return {"number": None, "type": item_type, "parent": parent,
                "dry_run": True, "title": title}
    if not created or created.get("number") is None:
        raise GitHubError("issue creation returned no number")
    number = int(created["number"])

    # Read back rather than trusting the response.
    check = gh.rest("GET", f"repos/{repo}/issues/{number}") or {}
    labels = {str(l.get("name", "")) for l in check.get("labels") or []}
    if item_type not in labels:
        raise GitHubError(
            f"created #{number} but its type label {item_type!r} is absent on "
            f"read-back; the item exists without a type")

    if parent is not None:
        import relationships

        relationships.link_child(gh, repo, parent, number)

    result = {"number": number, "type": item_type, "parent": parent}
    if found_in is not None:
        result["found_in"] = found_in
    if considered:
        # The decision travels with the creation it authorized. Without this
        # the record is a flag someone passed and nothing anyone can read back.
        result["considered"] = sorted(considered)
    result.update(place_on_board(gh, repo, number, check, project,
                                 operation_id=operation_id,
                                 policy_root=policy_root))
    return result


def initial_delivery_state(policy_root: Path | None = None) -> str:
    """The state a new item enters, read from the installed state machine.

    Not hardcoded here. `state-machine.yml` defines exactly one edge from no
    state, and a second copy of its target living in this file is the copy
    that drifts.
    """
    import project_root
    import transition_plan

    root = project_root.resolve(policy_root, required=False) or Path.cwd()
    machine = transition_plan.load_state_machine(root)
    entries = [e["to"] for e in machine["delivery_status"]["transitions"]
               if e.get("from") is None]
    if len(entries) != 1:
        raise GitHubError(
            f"state-machine.yml defines {len(entries)} entry states {entries}; "
            f"capture cannot choose which one a new item enters")
    return entries[0]


def place_on_board(gh: GitHub, repo: str, number: int, issue: dict,
                   project: int | None,
                   operation_id: str | None = None,
                   policy_root: Path | None = None) -> dict:
    """Put the new item on the board and give it the state a new item has.

    Every transition, the audit, and the refinement queue read delivery state
    from the project. An item created off the board exists and cannot be moved,
    which is a worse outcome than not creating it: it looks done.

    Placing the row is only half of that. A row with no delivery state is
    reported by the audit, skipped by the refinement queue, and cannot be
    planned from -- so capture writes the entry state too. It is entitled to:
    `state-machine.yml` gives the edge from no state the evidence
    `issue_exists`, and this function has just created and read back the issue.

    A capture that cannot place the item, or cannot set the state after
    placing it, reports that plainly. Returning a clean creation would hand
    back an item nobody can transition and let the caller believe otherwise.
    """
    import inspect_target
    import field_backend

    owner, _, name = repo.partition("/")
    try:
        inspection = inspect_target.inspect(gh, owner, name, project)
        backend = field_backend.for_inspection(gh, inspection)
        place = getattr(backend, "place", None)
        if place is None:
            return {"on_board": False,
                    "board_note": f"the {inspection.backend} backend has no "
                                  f"board; delivery state is carried on the "
                                  f"issue itself"}
        item = place(number, int(issue["id"]), operation_id=operation_id)
    except Exception as exc:  # noqa: BLE001
        return {
            "on_board": False,
            "board_note": (
                f"created #{number} but could not place it on the board "
                f"({exc.__class__.__name__}: {exc}). It has no delivery state, "
                f"so no transition can be planned for it until it is added."),
        }

    try:
        state = initial_delivery_state(policy_root)
        backend.write(number, "delivery_state", state,
                      operation_id=f"{operation_id}-state" if operation_id else None)
    except Exception as exc:  # noqa: BLE001
        return {
            "on_board": True, "project_item_id": item, "delivery_state": None,
            "board_note": (
                f"placed #{number} on the board but could not set its delivery "
                f"state ({exc.__class__.__name__}: {exc}). The audit will "
                f"report it and the refinement queue will skip it until the "
                f"state is set."),
        }
    return {"on_board": True, "project_item_id": item, "delivery_state": state}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None,
                    help="owner/name. Defaults to the repository the extension config declares.")
    ap.add_argument("--title", required=True)
    ap.add_argument("--body", default="")
    ap.add_argument("--type", dest="item_type", choices=["story", "bug", "spike", "epic"])
    ap.add_argument("--parent", type=int, default=None)
    ap.add_argument("--project", type=int, default=None,
                    help="Project to place the item on. Omit to let inspection choose,\n"
                         "which fails when the owner has more than one.")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--found-in", type=int, default=None, metavar="N",
                    help="Issue this finding was discovered during. Recorded "
                         "in the body as a cross-reference, so the source "
                         "shows it too.")
    ap.add_argument("--considered", type=int, action="append", default=[],
                    metavar="N",
                    help="Issue number a person compared this against and "
                         "judged different. Repeatable. Every candidate the "
                         "search raises must be named before --create "
                         "proceeds.")
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, "
                         "then the nearest ancestor with a .specify/ directory.")
    ap.add_argument("--create", action="store_true",
                    help="Create the item. Without this, only searches.")
    ap.add_argument("--audit", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        target = config.resolve_target(args.repo, getattr(args, "project", None))
        args.repo = target.repo
        if hasattr(args, "project"):
            args.project = target.project
    except config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    gh = GitHub(audit_path=args.audit, dry_run=args.dry_run)
    try:
        candidates = search_duplicates(gh, args.repo, args.title, args.threshold)
        report = {
            "title": args.title,
            "duplicate_candidates": [c.__dict__ for c in candidates],
        }

        if not args.create:
            report["action"] = "searched only"
            print(json.dumps(report, indent=2))
            return 0

        if not args.item_type:
            print("--type is required with --create", file=sys.stderr)
            return 2

        missing = has_evidence(args.body, args.item_type)
        if missing:
            report["action"] = "refused"
            report["reason"] = (
                f"a {args.item_type} needs {missing}; without them this is a "
                f"discovery note rather than a backlog item")
            print(json.dumps(report, indent=2))
            return 1

        invented = phantom_considerations(candidates, args.considered)
        if invented:
            report["action"] = "refused"
            report["reason"] = (
                f"--considered names {invented}, which the search did not "
                f"raise. Either the number is wrong or the comparison was "
                f"against something else; correct it rather than recording "
                f"a decision nobody can check.")
            print(json.dumps(report, indent=2))
            return 1

        outstanding = unconsidered(candidates, args.considered)
        if outstanding:
            report["action"] = "refused"
            report["reason"] = (
                f"{len(candidates)} candidate duplicate(s) found and "
                f"{len(outstanding)} not yet decided: {outstanding}. Look at "
                f"each, then either link to it, or record the decision: "
                + " ".join(f"--considered {n}" for n in outstanding)
                + ". Raising --threshold hides the report instead of "
                  "answering it.")
            print(json.dumps(report, indent=2))
            return 1

        if args.considered:
            report["considered"] = sorted(args.considered)

        report.update(create_item(gh, args.repo, args.title, args.body,
                                  args.item_type, args.parent,
                                  project=args.project,
                                  policy_root=args.policy_root,
                                  considered=args.considered,
                                  found_in=args.found_in))
        report["action"] = "created"
        print(json.dumps(report, indent=2))
        return 0
    except (GitHubError, NotFound) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
