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


def carriable_fields(root: Path, backend: str = "projects-v2") -> list[dict]:
    """Fields this backend should carry, from the schema and the matrix.

    `board` created only the delivery field, so every board it made lacked the
    four roles the matrix records this backend as carrying -- and inspection
    then reported their absence as harmless (#124). The names and option sets
    come from `github-schema.yml`; a list here would be a second copy.

    A field the schema leaves to a strategy rather than declaring values for
    is skipped: `Priority` is reused from GitHub's own, and `Capability` is an
    organization choice. Inventing options for either would decide something
    the policy deliberately left open.
    """
    import yaml

    schema = _load(root, SCHEMA_CANDIDATES)
    matrix = _load_matrix(root).get(backend) or {}
    carries = set(matrix.get("carries") or [])
    machine = _load(root, MACHINE_CANDIDATES)

    out = []
    for name, spec in (schema.get("issue_fields") or {}).items():
        if not isinstance(spec, dict) or spec.get("strategy"):
            continue
        role = _role_of(name)
        if role and carries and role not in carries:
            continue
        values = list(spec.get("values") or [])
        if role == "delivery_state":
            # The states come from the machine, which is authoritative for
            # what a delivery state is.
            values = list(machine["delivery_status"]["values"])
        if spec.get("type") == "single_select" and values:
            out.append({"name": name, "role": role, "options": values})
    return out


def _role_of(field_name: str) -> str | None:
    for role, names in inspect_target.ROLE_CANDIDATES.items():
        if field_name in names:
            return role
    return None


def _load_matrix(root: Path) -> dict:
    import yaml

    for rel in ("tooling/compatibility.yml", ".specify/tooling/compatibility.yml"):
        path = root / rel
        if path.is_file():
            return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    ).get("backends") or {}
    return {}


def delivery_field(root: Path, backend: str = "projects-v2") -> tuple[str, list[str]]:
    """The field name and its options, both from policy.

    The name is per backend, because the two genuinely differ: a Projects v2
    board carries GitHub's reserved `Status`, and an organization Issue Field is
    `Delivery Status`. The values come from `state-machine.yml`, in the order
    the policy lists them, so a board this creates cannot disagree with the
    machine about what a state is.

    This used to read `schema.get("fields")` for an entry carrying
    `role: delivery_state`. The schema declares `issue_fields:` and no entry has
    ever carried a role, so the lookup found nothing and the function returned a
    `"Status"` default on every call -- right by accident for the only backend
    that creates boards, and silently wrong for the other (#125). Reading the
    name through `ROLE_CANDIDATES` instead would not have fixed it: those are
    ordered candidates for *discovery*, `Delivery Status` first, so creation
    would have named a project board's field after the other backend's
    vocabulary.
    """
    schema = _load(root, SCHEMA_CANDIDATES)
    machine = _load(root, MACHINE_CANDIDATES)
    name = _declared_delivery_field(schema, backend)
    return name, list(machine["delivery_status"]["values"])


def _declared_delivery_field(schema: dict, backend: str) -> str:
    """The `delivery_field` the schema declares for this backend.

    Backends are keyed one way in `github-schema.yml` (`project`,
    `issue_fields`) and another in `tooling/compatibility.yml` (`projects-v2`,
    `issue-fields`); each schema entry carries `matrix_key` so either spelling
    resolves. Raising rather than defaulting is the point of the change: a
    default here is what let an undeclared name look declared.
    """
    backends = schema.get("backends") or {}
    for key, spec in backends.items():
        if not isinstance(spec, dict):
            continue
        if backend in (key, spec.get("matrix_key")):
            name = spec.get("delivery_field")
            if name:
                return str(name)
            raise KeyError(
                f"github-schema.yml declares backend {key!r} with no "
                f"`delivery_field`; the name a backend gives the delivery "
                f"field is policy, not a default this code may choose")
    known = sorted(
        {k for k in backends} | {
            s.get("matrix_key") for s in backends.values()
            if isinstance(s, dict) and s.get("matrix_key")})
    raise KeyError(
        f"github-schema.yml declares no backend {backend!r}; it declares "
        f"{known}")


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

    # Boards this repository is linked to, not boards the owner has. Asking
    # the owner meant nobody with an existing project could ever create one
    # for a second repository -- the same confusion #120 fixed in inspection,
    # reached from the other side.
    existing = inspect_target.discover_projects(
        gh, owner, "org" if _is_org(gh, owner) else "user", repo)
    if existing:
        listed = ", ".join(f"#{p['number']} {p['title']!r}" for p in existing)
        return {"action": "refused", "problems": [
            f"{owner}/{repo} is already linked to {len(existing)} board(s): "
            f"{listed}. This creates the first one only. To give an existing "
            f"board the states the policy declares, pass "
            f"--project <number>."]}

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
    # Every other field the backend carries. The delivery field is done above
    # because it is the reserved one that must be reshaped; these are created.
    extra, failed = [], []
    for spec in carriable_fields(root):
        if spec["role"] == "delivery_state":
            continue
        made = run(["gh", "project", "field-create", str(number), "--owner", owner,
                    "--name", spec["name"], "--data-type", "SINGLE_SELECT",
                    "--single-select-options", ",".join(spec["options"]),
                    "--format", "json"], runner)
        (extra if made.returncode == 0 else failed).append(spec["name"])
    if failed:
        raise GitHubError(
            f"board #{number} carries {name!r} but these could not be added: "
            f"{failed}. A workflow that writes one of them cannot complete, "
            f"and a board missing them reads as finished.")

    orphans = _unplaced_issues(gh, owner, repo, number, runner)
    result = {"action": "created", "project_number": number, "field": name,
              "options": got, "linked_to": f"{owner}/{repo}",
              "reshaped_existing_field": existing_field is not None,
              "fields_created": extra,
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
    """Give a single-select the policy's states, keeping the ids it already has.

    GraphQL rather than `gh project field-edit`, which does not exist. The
    mutation replaces the whole option set, which is what is wanted for the
    names: a board left carrying Todo/In Progress/Done alongside the real states
    would let an item hold a value the state machine does not know.

    But an option carries an **id**, and an item's stored value is that id, not
    the name. Sending a name-only list makes GitHub mint new ids and discard the
    old ones, so every item's value dangles and reads as empty. That is not
    theoretical: adding one state to a live board this way cleared the delivery
    state of 160 items (#163).

    So each surviving state is sent with the id, colour and description it
    already has, and only a genuinely new state is sent without one. On a fresh
    board nothing matches and the behaviour is unchanged.
    """
    present = {o.get("name"): o for o in (field.get("options") or [])}
    entries = []
    for state in options:
        prior = present.get(state)
        if prior and prior.get("id"):
            entries.append(
                '{id: "%s", name: "%s", color: %s, description: "%s"}' % (
                    prior["id"], state, prior.get("color") or "GRAY",
                    (prior.get("description") or "").replace('"', "'")))
        else:
            entries.append('{name: "%s", color: GRAY, description: ""}' % state)
    mutation = (
        'mutation { updateProjectV2Field(input: {fieldId: "%s", '
        'singleSelectOptions: [%s]}) { projectV2Field { ... on '
        'ProjectV2SingleSelectField { id name options { id name } } } } }'
        % (field["id"], ", ".join(entries)))
    return run(["gh", "api", "graphql", "-f", f"query={mutation}"], runner)


def reshape(owner: str, repo: str, number: int, root: Path,
            runner=None, gh: GitHub | None = None, dry_run: bool = False) -> dict:
    """Give an existing board the states the policy declares.

    `create` refuses when a board already exists and told the caller to pass
    `--project`, which was not a flag. So adding a state to `state-machine.yml`
    had no supported path onto a board already in use, and doing it by hand is
    what cost 160 items their delivery state (#163).
    """
    gh = gh or GitHub()
    name, options = delivery_field(root)
    field = _find_field(owner, number, name, runner)
    if field is None:
        return {"action": "refused", "problems": [
            f"board #{number} carries no {name!r} field. This reshapes an "
            f"existing field; it does not create one."]}

    before = [o.get("name") for o in (field.get("options") or [])]
    losing = [state for state in before if state not in options]
    if losing:
        return {"action": "refused", "problems": [
            f"board #{number} carries {losing}, which "
            f"state-machine.yml does not declare. Removing an option clears it "
            f"from every item holding it; decide what those items should be "
            f"first."]}
    if before == options:
        return {"action": "unchanged", "project": number,
                "field": name, "options": options}
    if dry_run:
        return {"action": "dry-run", "project": number, "field": name,
                "adding": [s for s in options if s not in before],
                "keeping": before}

    applied = _set_options(field, options, runner)
    if applied.returncode != 0:
        raise GitHubError(
            f"could not give {name!r} the states the policy declares: "
            f"{applied.stderr.strip()[:200]}")

    after = _find_field(owner, number, name, runner)
    got = [o.get("name") for o in (after.get("options") or [])] if after else []
    if got != options:
        raise GitHubError(
            f"board #{number} carries {name!r} with {got}, not the states "
            f"state-machine.yml declares: {options}.")

    kept = {o.get("name"): o.get("id") for o in (field.get("options") or [])}
    now = {o.get("name"): o.get("id") for o in (after.get("options") or [])}
    moved = [n for n, i in kept.items() if now.get(n) != i]
    if moved:
        raise GitHubError(
            f"board #{number}: {moved} kept their names and were given new "
            f"ids, so every item holding one has lost its value. This is the "
            f"failure the id pass-through exists to prevent.")
    return {"action": "reshaped", "project": number, "field": name,
            "added": [s for s in options if s not in before], "options": options}


def _is_org(gh: GitHub, owner: str) -> bool:
    payload = gh.rest("GET", f"users/{owner}") or {}
    return str(payload.get("type", "")).lower() == "organization"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--title", default=None,
                    help="Board title. Defaults to the repository name.")
    ap.add_argument("--policy-root", type=Path, default=None)
    ap.add_argument("--project", type=int, default=None,
                    help="Reshape this existing board's delivery field to the "
                         "states state-machine.yml declares, instead of "
                         "creating a board. Options already present keep their "
                         "ids, so no item loses its value.")
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
        if args.project is not None:
            result = reshape(owner, name, args.project, args.policy_root,
                             dry_run=args.dry_run)
        else:
            result = create(owner, name, args.title or name, args.policy_root,
                            dry_run=args.dry_run, adopt=args.adopt)
    except (GitHubError, FileNotFoundError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 1 if result.get("action") == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
