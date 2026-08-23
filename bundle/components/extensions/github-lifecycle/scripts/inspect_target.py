#!/usr/bin/env python3
"""Read-only inspection: what this repository supports, and how to address it.

Every other command depends on this. `policy/github-schema.yml` prefers
organization Issue Fields and defines a fallback for when they are unavailable;
which applies is a property of the target, not a configuration choice, so it is
probed rather than declared.

REST throughout. Issue types, issue fields, and Projects v2 all have REST
routes; an earlier revision used GraphQL on the mistaken belief that they did
not. GraphQL remains available in the adapter for anything that genuinely lacks
a route.

Two things this exists to prevent:

Addressing fields by display name. Names are renameable and, for the delivery
state, differ between backends. Everything downstream receives ids.

Guessing when the target is ambiguous. Two candidate projects, or a field whose
options do not match the state machine, is reported and refused rather than
resolved by picking one.

Named `inspect_target` rather than `inspect`: a module named `inspect.py` first
on `sys.path` shadows the standard library module that `dataclasses` imports,
and the script fails on a circular import before its own code runs.

Mutates nothing. Ever.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_api import GitHub, GitHubError, NotFound  # noqa: E402

BACKEND_ISSUE_FIELDS = "issue-fields"
BACKEND_PROJECT = "projects-v2"
BACKEND_NONE = "none"

# Semantic roles, and the field names that may carry them, in preference order.
# The delivery state has two spellings: an organization may name an Issue Field
# "Delivery Status", while on a project board it is carried by the built-in
# "Status" field, which cannot be renamed.
ROLE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "delivery_state": ("Delivery Status", "Status"),
    "outcome_status": ("Outcome Status",),
    "risk": ("Risk",),
    "severity": ("Severity",),
    "priority": ("Priority",),
    "capability": ("Capability",),
}

# Must agree with policy/state-machine.yml. tests/test_inspect.py enforces that.
DELIVERY_STATES = ("Inbox", "Refining", "Ready", "In Progress", "Output Done")

REQUIRED_ROLES = ("delivery_state",)


@dataclass(frozen=True)
class FieldRef:
    """A field addressed by id, with its options also addressed by id."""

    name: str
    id: str
    data_type: str
    node_id: str = ""
    options: dict[str, str] = field(default_factory=dict)

    def option_id(self, value: str) -> str:
        try:
            return self.options[value]
        except KeyError:
            raise NotFound(
                f"field {self.name!r} has no option {value!r}; "
                f"known: {sorted(self.options)}"
            ) from None


def _option_name(option: dict) -> str:
    """Option names are plain on issue fields and structured on project fields."""
    name = option.get("name")
    if isinstance(name, dict):
        return str(name.get("raw", ""))
    return str(name or "")


def _to_ref(payload: dict) -> FieldRef:
    return FieldRef(
        name=str(payload.get("name", "")),
        id=str(payload.get("id", "")),
        data_type=str(payload.get("data_type", "")),
        node_id=str(payload.get("node_id", "")),
        options={_option_name(o): str(o.get("id", "")) for o in payload.get("options") or []},
    )


@dataclass
class Inspection:
    owner: str
    repo: str
    owner_type: str
    backend: str
    issue_fields_available: bool
    issue_types_available: bool
    sub_issues_available: bool
    dependencies_available: bool
    project_number: int | None = None
    fields: dict[str, FieldRef] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    missing_roles: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def field_for(self, role: str) -> FieldRef:
        name = self.roles.get(role)
        if not name:
            raise NotFound(f"no field carries the {role!r} role on this target")
        return self.fields[name]

    @property
    def usable(self) -> bool:
        return (self.backend != BACKEND_NONE
                and not self.ambiguities
                and not self.missing_roles)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fields"] = {k: asdict(v) for k, v in self.fields.items()}
        data["usable"] = self.usable
        return data


def owner_type(gh: GitHub, owner: str, repo: str) -> str:
    payload = gh.rest("GET", f"repos/{owner}/{repo}", jq=".owner.type")
    if not payload:
        raise NotFound(f"repository {owner}/{repo} not found or not visible")
    return str(payload)


def organization_issue_fields(gh: GitHub, owner: str) -> dict[str, FieldRef]:
    """Issue Fields are organization-only; a user account 404s here."""
    rows = gh.rest("GET", f"orgs/{owner}/issue-fields") or []
    return {r["name"]: _to_ref(r) for r in rows}


def organization_issue_types(gh: GitHub, owner: str) -> list[str]:
    rows = gh.rest("GET", f"orgs/{owner}/issue-types") or []
    return [r["name"] for r in rows]


def discover_projects(gh: GitHub, owner: str, owner_kind: str) -> list[dict]:
    root = "orgs" if owner_kind == "Organization" else "users"
    rows = gh.rest("GET", f"{root}/{owner}/projectsV2") or []
    return [{"number": r["number"], "title": r.get("title", "")} for r in rows]


def project_fields(gh: GitHub, owner: str, owner_kind: str,
                   project_number: int) -> dict[str, FieldRef]:
    root = "orgs" if owner_kind == "Organization" else "users"
    rows = gh.rest("GET", f"{root}/{owner}/projectsV2/{project_number}/fields") or []
    return {r["name"]: _to_ref(r) for r in rows}


def probe_repo_features(gh: GitHub, owner: str, repo: str) -> tuple[bool, bool]:
    try:
        gh.rest("GET", f"repos/{owner}/{repo}/issues", jq="length")
        return True, True
    except GitHubError:
        return False, False


def inspect(gh: GitHub, owner: str, repo: str,
            project_number: int | None = None) -> Inspection:
    kind = owner_type(gh, owner, repo)
    sub_issues, dependencies = probe_repo_features(gh, owner, repo)

    org_fields: dict[str, FieldRef] = {}
    issue_types: list[str] = []
    if kind == "Organization":
        try:
            org_fields = organization_issue_fields(gh, owner)
            issue_types = organization_issue_types(gh, owner)
        except GitHubError:
            org_fields, issue_types = {}, []

    result = Inspection(
        owner=owner, repo=repo, owner_type=kind, backend=BACKEND_NONE,
        issue_fields_available=bool(org_fields),
        issue_types_available=bool(issue_types),
        sub_issues_available=sub_issues,
        dependencies_available=dependencies,
    )

    # An organization only wins if its Issue Fields can actually carry the
    # delivery state. Otherwise the project board is the real source.
    if org_fields and _resolve_roles(org_fields).get("delivery_state"):
        result.backend = BACKEND_ISSUE_FIELDS
        result.fields = org_fields
        result.notes.append("Organization Issue Fields carry the delivery state.")
    else:
        if kind != "Organization":
            result.notes.append(
                "Owner is a user, so the project backend applies. This is the "
                "default (ADR 0003); Issue Fields are an organization opt-in."
            )
        elif org_fields:
            result.notes.append(
                "Organization Issue Fields exist but none carries the delivery "
                "state; falling back to the project board."
            )
        project_number = _select_project(gh, owner, kind, project_number, result)
        if project_number is None:
            return _finalize(result)
        result.project_number = project_number
        result.fields = project_fields(gh, owner, kind, project_number)
        result.backend = BACKEND_PROJECT

    return _finalize(result)


def _select_project(gh: GitHub, owner: str, kind: str,
                    chosen: int | None, result: Inspection) -> int | None:
    if chosen is not None:
        return chosen
    projects = discover_projects(gh, owner, kind)
    if not projects:
        result.notes.append("No Projects v2 board found; no field backend available.")
        return None
    if len(projects) == 1:
        return projects[0]["number"]
    # authoritative_project_count: 1. Refuse rather than choose.
    result.ambiguities.append(
        "multiple projects found and none selected: "
        + ", ".join(f"#{p['number']} {p['title']!r}" for p in projects)
    )
    return None


def _resolve_roles(fields: dict[str, FieldRef]) -> dict[str, str]:
    """Map each semantic role onto the field name that carries it."""
    roles: dict[str, str] = {}
    for role, candidates in ROLE_CANDIDATES.items():
        for name in candidates:
            ref = fields.get(name)
            if ref is None:
                continue
            if role == "delivery_state" and not set(DELIVERY_STATES) <= set(ref.options):
                # A field named Status that still holds Todo/Done is not the
                # delivery state, whatever it is called.
                continue
            roles[role] = name
            break
    return roles


def _finalize(result: Inspection) -> Inspection:
    result.roles = _resolve_roles(result.fields)
    result.missing_roles = [r for r in REQUIRED_ROLES if r not in result.roles]

    delivery = result.roles.get("delivery_state")
    if delivery:
        result.notes.append(f"Delivery state is carried by the {delivery!r} field.")
        others = [n for n in ROLE_CANDIDATES["delivery_state"]
                  if n != delivery and n in result.fields]
        if others:
            result.ambiguities.append(
                f"more than one field could carry the delivery state: "
                f"{delivery!r} selected, {others} also present"
            )
    elif result.fields:
        result.notes.append(
            "No field carries the delivery state. Expected one of "
            f"{list(ROLE_CANDIDATES['delivery_state'])} with options "
            f"{list(DELIVERY_STATES)}."
        )
    for role in ROLE_CANDIDATES:
        if role not in result.roles and role not in REQUIRED_ROLES:
            result.notes.append(f"optional role {role!r} has no field")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--project", type=int, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--audit", type=Path, default=None)
    ap.add_argument("--quiet", action="store_true", help="Print a summary, not the record.")
    args = ap.parse_args()

    owner, _, repo = args.repo.partition("/")
    if not owner or not repo:
        print("--repo must be owner/name", file=sys.stderr)
        return 2

    gh = GitHub(audit_path=args.audit)
    try:
        result = inspect(gh, owner, repo, args.project)
    except GitHubError as exc:
        print(f"inspection failed: {exc}", file=sys.stderr)
        return 1

    payload = json.dumps(result.to_dict(), indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    if args.quiet:
        print(f"backend={result.backend} usable={result.usable} "
              f"roles={sorted(result.roles)} ambiguities={len(result.ambiguities)}")
    else:
        print(payload)
    return 0 if result.usable else 1


if __name__ == "__main__":
    sys.exit(main())
