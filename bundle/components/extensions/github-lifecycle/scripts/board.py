#!/usr/bin/env python3
"""Create the Projects v2 board the default deployment shape needs.

ADR 0003 makes project-scoped fields the default and organization Issue Fields
the opt-in. Nothing created the default. A greenfield bootstrap into an
ordinary repository produced a backlog nothing could transition, because
`delivery_state` lives on a board that did not exist and no command made one.

Explicitly invoked, never implicit. Creating a board is the first structural
write this bundle makes, and a bootstrap that quietly created one would be
deciding where a project's work is tracked on the project's behalf.

Two refusals:

It will not create a second board. If the owner already has one, or several,
the ambiguity is reported and nothing is written -- `authoritative_project_count`
is 1, and choosing between two boards is not this command's decision.

It will not invent the states. The single-select options come from
`state-machine.yml`, in its order, so the board and the policy cannot disagree
about what a delivery state is.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import inspect_target  # noqa: E402
import project_root  # noqa: E402
import yaml  # noqa: E402
from github_api import GitHub, GitHubError  # noqa: E402

MACHINE_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/state-machine.yml",
    "policy/state-machine.yml",
)
SCHEMA_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/github-schema.yml",
    "policy/github-schema.yml",
)


def _load(root: Path, candidates) -> dict:
    for rel in candidates:
        path = root / rel
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raise FileNotFoundError(
        f"none of {list(candidates)} found; the governance preset must be installed")


def delivery_field(root: Path) -> tuple[str, list[str]]:
    """The field name and its options, both from policy.

    The name comes from `github-schema.yml` and the values from
    `state-machine.yml`, in the order the policy lists them, so a board this
    creates cannot disagree with the machine about what a state is.
    """
    schema = _load(root, SCHEMA_CANDIDATES)
    machine = _load(root, MACHINE_CANDIDATES)
    name = next((n for n, spec in (schema.get("fields") or {}).items()
                 if isinstance(spec, dict)
                 and spec.get("role") == "delivery_state"), None) or "Status"
    return name, list(machine["delivery_status"]["values"])


def run(args: list[str], runner=None) -> subprocess.CompletedProcess:
    runner = runner or (lambda a: subprocess.run(
        a, capture_output=True, text=True, timeout=120))
    return runner(args)


def create(owner: str, repo: str, title: str, root: Path,
           runner=None, gh: GitHub | None = None,
           dry_run: bool = False, adopt: bool = False) -> dict:
    """Create a board, give it the delivery field, and link it to the repo."""
    gh = gh or GitHub()
    name, options = delivery_field(root)

    existing = inspect_target.discover_projects(
        gh, owner, "org" if _is_org(gh, owner) else "user")
    if existing:
        listed = ", ".join(f"#{p['number']} {p['title']!r}" for p in existing)
        return {"action": "refused", "problems": [
            f"{owner} already has {len(existing)} board(s): {listed}. This "
            f"creates the first one only; pass --project to use an existing "
            f"board, or say which is authoritative."]}

    if dry_run:
        return {"action": "dry-run", "would_create": title,
                "field": name, "options": options, "linked_to": repo}

    made = run(["gh", "project", "create", "--owner", owner,
                "--title", title, "--format", "json"], runner)
    if made.returncode != 0:
        raise GitHubError(f"gh project create failed: {made.stderr.strip()[:200]}")
    number = int(json.loads(made.stdout)["number"])

    # Every new board already carries a single-select the API calls Status,
    # with GitHub's own Todo/In Progress/Done. The name is reserved, so
    # creating one fails; the existing field is reshaped instead. Found by
    # running this against a real board -- `field-create` returned
    # "Name cannot have a reserved value, Name has already been taken".
    existing_field = _find_field(owner, number, name, runner)
    if existing_field is None:
        field = run(["gh", "project", "field-create", str(number), "--owner", owner,
                     "--name", name, "--data-type", "SINGLE_SELECT",
                     "--single-select-options", ",".join(options),
                     "--format", "json"], runner)
        if field.returncode != 0:
            raise GitHubError(
                f"created board #{number} but could not add {name!r}: "
                f"{field.stderr.strip()[:200]}. The board exists and is "
                f"unusable until the field is added.")
    else:
        reshaped = _set_options(existing_field, options, runner)
        if reshaped.returncode != 0:
            raise GitHubError(
                f"created board #{number} but could not give {name!r} the "
                f"states the policy declares: "
                f"{reshaped.stderr.strip()[:200]}. The board exists and is "
                f"unusable until its options match the state machine.")

    linked = run(["gh", "project", "link", str(number), "--owner", owner,
                  "--repo", f"{owner}/{repo}"], runner)
    if linked.returncode != 0:
        raise GitHubError(
            f"created board #{number} but could not link it to {repo}: "
            f"{linked.stderr.strip()[:200]}")

    # Read the board back, not the repository's chosen backend. Those are
    # different questions: an organization carrying Issue Fields resolves to
    # that backend whatever boards exist, so asking inspection which backend
    # it would pick reports a correct board as a failure.
    made_field = _find_field(owner, number, name, runner)
    if made_field is None:
        raise GitHubError(
            f"board #{number} created but {name!r} is not on it when read back")
    got = [o.get("name") for o in (made_field.get("options") or [])]
    if got != options:
        raise GitHubError(
            f"board #{number} carries {name!r} with {got}, not the states "
            f"state-machine.yml declares: {options}. An item could hold a "
            f"value the state machine does not know.")
    # Linking a project to a repository does not put its issues on it. A board
    # created after the backlog leaves every existing item off, and an empty
    # board reads as a working one -- the failure this whole issue is about,
    # one layer down.
    orphans = _unplaced_issues(gh, owner, repo, number, runner)
    result = {"action": "created", "project_number": number, "field": name,
              "options": got, "linked_to": f"{owner}/{repo}",
              "reshaped_existing_field": existing_field is not None,
              "issues_not_on_the_board": orphans}
    if orphans and adopt:
        placed = _adopt(gh, owner, repo, number, orphans, runner)
        result["adopted"] = placed
        result["issues_not_on_the_board"] = [
            n for n in orphans if n not in placed]
    elif orphans:
        result["note"] = (
            f"{len(orphans)} open issue(s) are not on this board and will be "
            f"invisible to the queue and the audit: {orphans[:10]}. Re-run "
            f"with --adopt to place them.")
    return result


def _unplaced_issues(gh: GitHub, owner: str, repo: str, number: int,
                     runner=None) -> list[int]:
    """Open issues in the repository that the board does not carry.

    Asks the project directly rather than going through the backend
    `inspect()` would choose. An organization carrying Issue Fields resolves
    to that backend whatever boards exist, and `ProjectFieldBackend` refuses
    to construct against it -- so routing this through inspection reports an
    error where the question is simply "what is on board N".
    """
    rows = gh.rest("GET", f"repos/{owner}/{repo}/issues?state=open",
                   paginate=True) or []
    if isinstance(rows, dict):
        rows = [rows]
    numbers = {int(r["number"]) for r in rows
               if r.get("number") is not None and not r.get("pull_request")}
    listed = run(["gh", "project", "item-list", str(number), "--owner", owner,
                  "--limit", "500", "--format", "json"], runner)
    if listed.returncode != 0:
        return sorted(numbers)
    try:
        items = json.loads(listed.stdout or "{}").get("items") or []
    except json.JSONDecodeError:
        return sorted(numbers)
    on_board = {int(i["content"]["number"]) for i in items
                if isinstance(i.get("content"), dict)
                and i["content"].get("number") is not None}
    return sorted(numbers - on_board)


def _adopt(gh: GitHub, owner: str, repo: str, number: int,
           issues: list[int], runner=None) -> list[int]:
    """Place existing issues on the board. Explicit, never automatic."""
    placed = []
    for issue in issues:
        added = run(["gh", "project", "item-add", str(number), "--owner", owner,
                     "--url", f"https://github.com/{owner}/{repo}/issues/{issue}",
                     "--format", "json"], runner)
        if added.returncode == 0:
            placed.append(issue)
    return placed


def _find_field(owner: str, number: int, name: str, runner=None) -> dict | None:
    """The board's existing field of that name, or None."""
    listed = run(["gh", "project", "field-list", str(number), "--owner", owner,
                  "--format", "json"], runner)
    if listed.returncode != 0:
        return None
    try:
        fields = json.loads(listed.stdout or "{}").get("fields") or []
    except json.JSONDecodeError:
        return None
    return next((f for f in fields if f.get("name") == name), None)


def _set_options(field: dict, options: list[str], runner=None):
    """Replace a single-select's options with the policy's states.

    GraphQL rather than `gh project field-edit`, which does not exist. The
    mutation replaces the whole option set, which is what is wanted: a board
    left carrying Todo/In Progress/Done alongside the real states would let an
    item hold a value the state machine does not know.
    """
    listing = ", ".join(
        '{name: "%s", color: GRAY, description: ""}' % state for state in options)
    mutation = (
        'mutation { updateProjectV2Field(input: {fieldId: "%s", '
        'singleSelectOptions: [%s]}) { projectV2Field { ... on '
        'ProjectV2SingleSelectField { id name options { name } } } } }'
        % (field["id"], listing))
    return run(["gh", "api", "graphql", "-f", f"query={mutation}"], runner)


def _is_org(gh: GitHub, owner: str) -> bool:
    payload = gh.rest("GET", f"users/{owner}") or {}
    return str(payload.get("type", "")).lower() == "organization"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--title", default=None,
                    help="Board title. Defaults to the repository name.")
    ap.add_argument("--policy-root", type=Path, default=None)
    ap.add_argument("--adopt", action="store_true",
                    help="Place the repository's existing open issues on the "
                         "new board. Without it they are reported and left.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--format", choices=["text", "json"], default="json")
    args = ap.parse_args()

    try:
        target = config.resolve_target(args.repo, None)
        args.repo = target.repo
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
    except (config.ConfigError, project_root.ProjectRootError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    owner, _, name = args.repo.partition("/")
    try:
        result = create(owner, name, args.title or name, args.policy_root,
                        dry_run=args.dry_run, adopt=args.adopt)
    except (GitHubError, FileNotFoundError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 1 if result.get("action") == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
