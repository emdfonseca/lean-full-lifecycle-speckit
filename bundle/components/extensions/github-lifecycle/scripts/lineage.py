#!/usr/bin/env python3
"""What revision of which artifacts a delivered item was derived from.

Nothing recorded it. A spec edited out of band left no trace, so an item could
reach the terminal delivery state asserting acceptance criteria that had since
changed underneath it, and no check anywhere could tell.

This records the artifacts and detects the drift. It does not reconcile it:
deciding what a changed spec means is a person's judgement, and a tool that
quietly re-derived an item from an edited spec would be making that judgement
without saying so.

**It never answers what state an item is in.** That is the board's, and the risk
this story names is precisely that a second record starts being consulted for
it. A lineage record holds file paths, hashes and a git revision -- nothing that
could be mistaken for a delivery state.

**It carries no list of artifact names.** The workflow steps declare what they
`produce`, and that declaration is what is hashed, so a step added to a workflow
extends lineage without a line changing here. A list here would be the copy that
drifts from the workflows it describes.

Keyed by issue, under `.specify/github-lifecycle/lineage/<n>.yml`, which is
where `readiness.py` keeps a verdict and for the same reason: the record is
about the item and outlives the run that wrote it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

RECORD_DIR = ".specify/github-lifecycle/lineage"

WORKFLOW_DIRS = (
    ".specify/workflows",
    "bundle/components/workflows",
)

# What a finding is called, so the audit and this command say the same word.
OUT_OF_BAND = "OUT_OF_BAND_CHANGE"
ABSENT = "ABSENT_LINEAGE"


class LineageError(Exception):
    """Lineage could not be recorded or read, and was not guessed at."""


def record_path(root: Path, issue: int) -> Path:
    return root / RECORD_DIR / f"{issue}.yml"


def _load_workflow(root: Path, workflow_id: str) -> dict:
    for rel in WORKFLOW_DIRS:
        path = root / rel / workflow_id / "workflow.yml"
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raise LineageError(
        f"workflow {workflow_id!r} is not installed, so what it produces "
        f"could not be read")


def declared_artifacts(workflow: dict) -> list[str]:
    """Every `produces` value a workflow's steps declare, in step order.

    Walks nested cases too: a step inside a switch produces its artifact just
    as surely as one at the top level, and a lineage record that skipped those
    would be silently partial.
    """
    found: list[str] = []

    def walk(steps):
        for step in steps or []:
            if not isinstance(step, dict):
                continue
            produces = step.get("produces")
            if produces and produces not in found:
                found.append(str(produces))
            for case in (step.get("cases") or {}).values():
                walk(case)
            walk(step.get("steps"))

    walk(workflow.get("steps") or [])
    return found


def digest(path: Path) -> str:
    """A file's content hash, or a directory's hash of its files' hashes.

    A directory artifact -- `checklists/` -- is one step's output and is
    recorded as one entry. Hashing the names alongside the contents is what
    makes a deleted checklist drift rather than a file nobody notices is gone.
    """
    if path.is_dir():
        rolling = hashlib.sha256()
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            rolling.update(str(child.relative_to(path)).encode("utf-8"))
            rolling.update(child.read_bytes())
        return rolling.hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_revision(root: Path) -> str | None:
    """HEAD at record time, or None when git cannot answer.

    None rather than a placeholder: "this was recorded outside a repository"
    and "this was recorded at revision unknown" are different, and only one of
    them is true.
    """
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def build(root: Path, issue: int, feature_dir: Path, workflow_id: str) -> dict:
    """The lineage record for one item, from what its workflow declares."""
    workflow = _load_workflow(root, workflow_id)
    declared = declared_artifacts(workflow)
    if not declared:
        raise LineageError(
            f"{workflow_id!r} declares no `produces` on any step, so there is "
            f"nothing to record. Declare what a step leaves behind first.")

    artifacts = []
    for relative in declared:
        target = feature_dir / relative
        if not target.exists():
            # Recorded as absent rather than omitted. A step that had not run
            # yet and a step whose output was deleted look identical in a
            # record that simply leaves the entry out.
            artifacts.append({"path": relative, "sha256": None,
                              "present": False})
            continue
        artifacts.append({"path": relative, "sha256": digest(target),
                          "present": True})
    return {
        "issue": issue,
        "workflow": workflow_id,
        "feature_dir": str(feature_dir.relative_to(root)
                           if feature_dir.is_relative_to(root) else feature_dir),
        "revision": git_revision(root),
        "artifacts": artifacts,
    }


def write(root: Path, record: dict) -> Path:
    path = record_path(root, int(record["issue"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    return path


def read(root: Path, issue: int) -> dict | None:
    path = record_path(root, issue)
    if not path.is_file():
        return None
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LineageError(
            f"{path} could not be parsed ({exc.__class__.__name__}). An "
            f"unreadable record is not an absent one.") from None
    if not isinstance(loaded, dict):
        raise LineageError(f"{path} is not a lineage record")
    return loaded


def check(root: Path, issue: int) -> list[dict]:
    """Every artifact whose content no longer matches what was recorded.

    An absent record is itself a finding. Returning an empty list for an item
    nobody ever recorded would report "no drift" about a comparison that never
    happened, which is the failure mode this whole module exists to prevent.
    """
    record = read(root, issue)
    if record is None:
        return [{"finding": ABSENT, "issue": issue, "path": None,
                 "detail": f"no lineage was recorded for #{issue}, so no "
                           f"artifact could be compared. An unrecorded item is "
                           f"not an unchanged one."}]

    feature_dir = root / str(record.get("feature_dir") or "")
    findings = []
    for entry in record.get("artifacts") or []:
        relative = str(entry.get("path"))
        target = feature_dir / relative
        was_present = bool(entry.get("present"))
        if not target.exists():
            if was_present:
                findings.append({
                    "finding": OUT_OF_BAND, "issue": issue, "path": relative,
                    "detail": f"{relative} was recorded and is now gone."})
            continue
        if not was_present:
            findings.append({
                "finding": OUT_OF_BAND, "issue": issue, "path": relative,
                "detail": f"{relative} appeared after lineage was recorded, so "
                          f"the item was derived without it."})
            continue
        if digest(target) != entry.get("sha256"):
            findings.append({
                "finding": OUT_OF_BAND, "issue": issue, "path": relative,
                "detail": f"{relative} has changed since lineage was recorded "
                          f"at {record.get('revision') or 'an unknown revision'}."})
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_record = sub.add_parser(
        "record", help="Record what this item was derived from. Writes one file.")
    p_record.add_argument("--issue", type=int, required=True)
    p_record.add_argument("--feature-dir", type=Path, required=True)
    p_record.add_argument("--workflow", required=True,
                          help="The workflow whose `produces` declarations say what to hash.")

    p_check = sub.add_parser(
        "check", help="Compare the recorded artifacts to what is on disk. Reads only.")
    p_check.add_argument("--issue", type=int, required=True)
    p_check.add_argument("--format", choices=("text", "json"), default="text")

    args = ap.parse_args()
    try:
        root = project_root.resolve(args.policy_root, required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.cmd == "record":
            written = write(root, build(root, args.issue, args.feature_dir,
                                        args.workflow))
            print(f"recorded {written}")
            return 0

        findings = check(root, args.issue)
    except LineageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(findings, indent=2))
    else:
        for item in findings:
            where = f" {item['path']}" if item.get("path") else ""
            print(f"{item['finding']}{where}: {item['detail']}")
        if not findings:
            print(f"#{args.issue}: every recorded artifact still matches.")
    # Drift is a finding to report, and a non-zero exit is what makes it one a
    # gate can act on.
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
