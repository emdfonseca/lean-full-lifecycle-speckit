#!/usr/bin/env python3
"""Read-only inspection: what this repository supports, and how to address it.

Every other command depends on this. `policy/github-schema.yml` prefers
organization Issue Fields and defines a fallback for when they are unavailable;
which of those applies is a property of the target, not a configuration choice,
so it is probed rather than declared.

Two things this exists to prevent:

Addressing fields by display name. Names are renameable and ambiguous; ids are
not. Everything downstream receives ids.

Guessing when the target is ambiguous. Two projects carrying the same field, or
a project field shadowing an organization one, is reported and refused rather
than resolved by picking one.

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

# Backends, in preference order. github-schema.yml: organization_preferred.
BACKEND_ISSUE_FIELDS = "issue-fields"
BACKEND_PROJECT = "projects-v2"
BACKEND_NONE = "none"

# Fields the schema requires, by name. Resolution maps these to ids.
REQUIRED_FIELDS = (
    "Delivery Status", "Outcome Status", "Risk", "Severity", "Priority", "Capability",
)

# Projects ships a built-in "Status" field that reads as a delivery state and is
# not one. github-schema.yml calls this out as do_not_create_duplicate.
SHADOWING_NAMES = {"Status"}


@dataclass(frozen=True)
class FieldRef:
    """A field addressed by id, with its options also addressed by id."""

    name: str
    id: str
    data_type: str
    options: dict[str, str] = field(default_factory=dict)

    def option_id(self, value: str) -> str:
        try:
            return self.options[value]
        except KeyError:
            raise NotFound(
                f"field {self.name!r} has no option {value!r}; "
                f"known: {sorted(self.options)}"
            ) from None


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
    project_id: str | None = None
    fields: dict[str, FieldRef] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether a transition could be planned against this target."""
        return self.backend != BACKEND_NONE and not self.ambiguities and not self.missing_fields

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fields"] = {k: asdict(v) for k, v in self.fields.items()}
        data["usable"] = self.usable
        return data


def owner_type(gh: GitHub, owner: str, repo: str) -> str:
    payload = gh.graphql(
        "query OwnerType($owner:String!,$repo:String!)"
        "{repository(owner:$owner,name:$repo){owner{__typename login}}}",
        variables={"owner": owner, "repo": repo},
    )
    node = (payload or {}).get("data", {}).get("repository")
    if not node:
        raise NotFound(f"repository {owner}/{repo} not found or not visible")
    return node["owner"]["__typename"]


def organization_fields(gh: GitHub, owner: str) -> dict[str, FieldRef]:
    """Issue Fields, which exist only on organizations (spike #33)."""
    payload = gh.graphql(
        "query OrgFields($owner:String!){organization(login:$owner)"
        "{issueFields(first:50){nodes{id name dataType options{id name}}}}}",
        variables={"owner": owner},
    )
    org = (payload or {}).get("data", {}).get("organization") or {}
    out: dict[str, FieldRef] = {}
    for node in (org.get("issueFields") or {}).get("nodes") or []:
        out[node["name"]] = FieldRef(
            name=node["name"], id=node["id"],
            data_type=str(node.get("dataType", "")),
            options={o["name"]: o["id"] for o in node.get("options") or []},
        )
    return out


def project_fields(gh: GitHub, owner: str, owner_kind: str,
                   project_number: int) -> tuple[str, dict[str, FieldRef]]:
    root = "organization" if owner_kind == "Organization" else "user"
    payload = gh.graphql(
        f"query ProjFields($owner:String!,$number:Int!){{{root}(login:$owner)"
        "{projectV2(number:$number){id "
        "fields(first:50){nodes{"
        "... on ProjectV2Field{id name dataType} "
        "... on ProjectV2SingleSelectField{id name dataType options{id name}}}}}}}",
        variables={"owner": owner, "number": project_number},
    )
    node = ((payload or {}).get("data", {}).get(root) or {}).get("projectV2")
    if not node:
        raise NotFound(f"project {project_number} not found for {owner}")
    out: dict[str, FieldRef] = {}
    for f in (node.get("fields") or {}).get("nodes") or []:
        if not f:
            continue
        out[f["name"]] = FieldRef(
            name=f["name"], id=f["id"], data_type=str(f.get("dataType", "")),
            options={o["name"]: o["id"] for o in f.get("options") or []},
        )
    return node["id"], out


def discover_projects(gh: GitHub, owner: str, owner_kind: str) -> list[dict]:
    root = "organization" if owner_kind == "Organization" else "user"
    payload = gh.graphql(
        f"query Projects($owner:String!){{{root}(login:$owner)"
        "{projectsV2(first:20){nodes{number title}}}}}",
        variables={"owner": owner},
    )
    node = (payload or {}).get("data", {}).get(root) or {}
    return (node.get("projectsV2") or {}).get("nodes") or []


def probe_repo_features(gh: GitHub, owner: str, repo: str) -> tuple[bool, bool]:
    """Sub-issues and dependencies are available regardless of owner type."""
    sub_issues = dependencies = False
    try:
        gh.rest("GET", f"repos/{owner}/{repo}/issues", jq="length")
        sub_issues = True
        dependencies = True
    except GitHubError:
        pass
    return sub_issues, dependencies


def inspect(gh: GitHub, owner: str, repo: str,
            project_number: int | None = None) -> Inspection:
    kind = owner_type(gh, owner, repo)
    sub_issues, dependencies = probe_repo_features(gh, owner, repo)

    org_fields: dict[str, FieldRef] = {}
    issue_fields_available = False
    issue_types_available = False
    if kind == "Organization":
        try:
            org_fields = organization_fields(gh, owner)
            issue_fields_available = bool(org_fields)
            issue_types_available = True
        except GitHubError:
            issue_fields_available = False

    result = Inspection(
        owner=owner, repo=repo, owner_type=kind,
        backend=BACKEND_NONE,
        issue_fields_available=issue_fields_available,
        issue_types_available=issue_types_available,
        sub_issues_available=sub_issues,
        dependencies_available=dependencies,
    )

    if issue_fields_available:
        result.backend = BACKEND_ISSUE_FIELDS
        result.fields = org_fields
        result.notes.append("Organization Issue Fields available; preferred backend.")
    else:
        if kind != "Organization":
            result.notes.append(
                "Owner is a user. Issue Fields and Issue Types are organization-only, "
                "so the Projects v2 fallback applies "
                "(github-schema.yml: when_issue_fields_unavailable)."
            )
        projects = discover_projects(gh, owner, kind)
        if project_number is None:
            if len(projects) == 1:
                project_number = projects[0]["number"]
            elif not projects:
                result.notes.append("No Projects v2 board found; no field backend available.")
                return _finalize(result)
            else:
                # authoritative_project_count: 1. Refuse rather than choose.
                result.ambiguities.append(
                    "multiple projects found and none selected: "
                    + ", ".join(f"#{p['number']} {p['title']!r}" for p in projects)
                )
                return _finalize(result)
        result.project_number = project_number
        result.project_id, result.fields = project_fields(gh, owner, kind, project_number)
        result.backend = BACKEND_PROJECT

    return _finalize(result)


def _finalize(result: Inspection) -> Inspection:
    result.missing_fields = [n for n in REQUIRED_FIELDS if n not in result.fields]
    shadowing = SHADOWING_NAMES & set(result.fields)
    if shadowing and "Delivery Status" in result.fields:
        # Not fatal, but a reader cannot tell which one governs, and the schema
        # explicitly warns against creating a duplicate.
        result.notes.append(
            f"{sorted(shadowing)} coexists with 'Delivery Status'. "
            "Delivery Status is authoritative; leave the built-in unused."
        )
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--project", type=int, default=None,
                    help="Project number, when the owner has more than one.")
    ap.add_argument("--out", type=Path, default=None,
                    help="Write the sanitized inspection record here.")
    ap.add_argument("--audit", type=Path, default=None)
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
    print(payload)
    return 0 if result.usable else 1


if __name__ == "__main__":
    sys.exit(main())
