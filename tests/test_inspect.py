"""Capability probing, offline.

`inspect_target` decides which field backend every later command uses, so the
cases that matter are the ones where it could plausibly guess: an owner that is
not an organization, more than one candidate project, a field named `Status`
that is not the delivery state.

All REST. Issue types, issue fields, and Projects v2 each have routes; an
earlier revision used GraphQL on the mistaken belief that they did not.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest
import yaml

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    # Registered so @dataclass resolves annotations. The module is named
    # inspect_target precisely so this cannot overwrite stdlib `inspect`.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(SCRIPTS))
gh_api = _load("github_api")
it = _load("inspect_target")

STATES = list(it.DELIVERY_STATES)


def router(**routes):
    """Answer by matching the request URL.

    Matching is by suffix before substring: `/projectsV2/3/fields` contains
    both `projectsV2` and `fields`, and either a plain substring scan or a
    longest-needle scan answers with the wrong one.
    """
    calls: list[list[str]] = []

    def url_of(args) -> str:
        for i, a in enumerate(args):
            if a == "api" and i + 1 < len(args):
                nxt = args[i + 1]
                return args[i + 3] if nxt == "--method" else nxt
        return ""

    def runner(args, stdin):
        calls.append(list(args))
        url = url_of(args)
        for needle, payload in routes.items():
            if url.endswith(needle.replace("__", "/")):
                body = payload if isinstance(payload, str) else json.dumps(payload)
                return subprocess.CompletedProcess(args, 0, body, "")
        for needle, payload in routes.items():
            if needle.replace("__", "/") in url:
                body = payload if isinstance(payload, str) else json.dumps(payload)
                return subprocess.CompletedProcess(args, 0, body, "")
        return subprocess.CompletedProcess(args, 1, "", "gh: Not Found (HTTP 404)")

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def client(runner):
    return gh_api.GitHub(runner=runner, sleep=lambda _: None, max_attempts=1)


def sel(name, options, fid=None):
    return {"id": fid or f"F_{name}", "name": name, "data_type": "single_select",
            "node_id": f"N_{name}",
            "options": [{"id": f"O_{name}_{o}", "name": {"raw": o}} for o in options]}


def org_sel(name, options):
    """Organization issue fields serialize option names plainly."""
    return {"id": f"IF_{name}", "name": name, "data_type": "single_select",
            "node_id": f"IFN_{name}",
            "options": [{"id": f"IFO_{name}_{o}", "name": o} for o in options]}


FULL_PROJECT = [sel("Status", STATES), sel("Risk", ["Low"]), sel("Priority", ["P0"]),
                sel("Severity", ["High"]), sel("Outcome Status", ["Measuring"]),
                sel("Capability", [])]


# --- the delivery state, wherever it lives -----------------------------------

@pytest.mark.req("REQ-GITHUB-INSPECT-001")
def test_delivery_state_is_found_in_the_builtin_status_field():
    # On a project board the state is carried by the built-in Status field,
    # which GitHub does not permit renaming.
    r = router(repos__acme__widgets="User", issues="[]",
               projectsV2=[{"number": 3, "title": "R"}], fields=FULL_PROJECT)
    result = it.inspect(client(r), "acme", "widgets")
    assert result.roles["delivery_state"] == "Status"
    assert result.usable


@pytest.mark.req("REQ-GITHUB-INSPECT-001")
def test_a_status_field_holding_the_wrong_options_is_not_the_delivery_state():
    # A default board still holding Todo/In Progress/Done is not our state
    # machine, whatever the field is called.
    r = router(repos__acme__widgets="User", issues="[]",
               projectsV2=[{"number": 3, "title": "R"}],
               fields=[sel("Status", ["Todo", "In Progress", "Done"])])
    result = it.inspect(client(r), "acme", "widgets")
    assert "delivery_state" in result.missing_roles
    assert not result.usable


def test_a_named_delivery_status_field_is_preferred_over_status():
    r = router(repos__acme__widgets="User", issues="[]",
               projectsV2=[{"number": 3, "title": "R"}],
               fields=[sel("Delivery Status", STATES), sel("Status", STATES)])
    result = it.inspect(client(r), "acme", "widgets")
    assert result.roles["delivery_state"] == "Delivery Status"
    # Both could carry it, so a reader cannot tell which governs.
    assert result.ambiguities


def test_delivery_states_match_the_policy():
    policy = yaml.safe_load((ROOT / "policy/state-machine.yml").read_text(encoding="utf-8"))
    assert list(it.DELIVERY_STATES) == policy["delivery_status"]["values"]


# --- backend selection --------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-INSPECT-001")
def test_user_owner_uses_the_project_backend():
    # Not a fallback: project-scoped is the default (ADR 0003).
    r = router(repos__acme__widgets="User", issues="[]",
               projectsV2=[{"number": 3, "title": "R"}], fields=FULL_PROJECT)
    result = it.inspect(client(r), "acme", "widgets")
    assert result.backend == it.BACKEND_PROJECT
    assert result.issue_fields_available is False
    assert any("default" in n for n in result.notes)


@pytest.mark.req("REQ-GITHUB-INSPECT-001")
def test_organization_issue_fields_win_when_they_carry_the_state():
    r = router(**{"repos__acme__widgets": "Organization",
                  "issues": "[]",
                  "issue-fields": [org_sel("Delivery Status", STATES)],
                  "issue-types": [{"name": "Task"}]})
    result = it.inspect(client(r), "acme", "widgets")
    assert result.backend == it.BACKEND_ISSUE_FIELDS
    assert result.issue_types_available is True
    assert result.roles["delivery_state"] == "Delivery Status"


def test_organization_without_a_delivery_field_falls_back_to_its_board():
    # Real case: an organization carrying GitHub's default issue fields
    # (Effort, Priority, dates) but nothing describing delivery state.
    r = router(**{"repos__acme__widgets": "Organization",
                  "issues": "[]",
                  "issue-fields": [org_sel("Effort", ["High"])],
                  "issue-types": [{"name": "Task"}],
                  "projectsV2": [{"number": 1, "title": "B"}],
                  "fields": FULL_PROJECT})
    result = it.inspect(client(r), "acme", "widgets")
    assert result.backend == it.BACKEND_PROJECT
    assert result.issue_fields_available is True
    assert any("none carries the delivery state" in n for n in result.notes)


# --- refusing to guess --------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-INSPECT-001")
def test_multiple_projects_are_an_ambiguity_not_a_choice():
    r = router(repos__acme__widgets="User", issues="[]",
               projectsV2=[{"number": 2, "title": "Money"}, {"number": 3, "title": "R"}])
    result = it.inspect(client(r), "acme", "widgets")
    assert result.ambiguities and not result.usable
    assert "#2" in result.ambiguities[0] and "#3" in result.ambiguities[0]


def test_an_explicit_project_resolves_the_ambiguity():
    r = router(repos__acme__widgets="User", issues="[]",
               projectsV2=[{"number": 2, "title": "M"}, {"number": 3, "title": "R"}],
               fields=FULL_PROJECT)
    result = it.inspect(client(r), "acme", "widgets", project_number=3)
    assert result.usable and result.project_number == 3


def test_no_project_means_no_backend():
    r = router(repos__acme__widgets="User", issues="[]", projectsV2=[])
    result = it.inspect(client(r), "acme", "widgets")
    assert result.backend == it.BACKEND_NONE and not result.usable


def test_unknown_repository_is_reported_not_guessed():
    with pytest.raises(gh_api.NotFound):
        it.inspect(client(router(issues="[]")), "acme", "nope")


# --- addressing by id ---------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-INSPECT-001")
def test_fields_and_options_resolve_to_ids_not_names():
    r = router(repos__acme__widgets="User", issues="[]",
               projectsV2=[{"number": 3, "title": "R"}], fields=FULL_PROJECT)
    result = it.inspect(client(r), "acme", "widgets")
    ref = result.field_for("delivery_state")
    assert ref.id == "F_Status"
    assert ref.option_id("Ready") == "O_Status_Ready"
    assert ref.node_id == "N_Status"


def test_an_unknown_option_names_what_is_available():
    ref = it.FieldRef("Status", "F_1", "single_select", options={"Inbox": "O_1"})
    with pytest.raises(gh_api.NotFound) as exc:
        ref.option_id("Shipped")
    assert "Inbox" in str(exc.value)


def test_option_names_parse_from_both_serializations():
    assert it._option_name({"name": {"raw": "Ready"}}) == "Ready"   # project field
    assert it._option_name({"name": "Ready"}) == "Ready"            # issue field


# --- read-only ----------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-INSPECT-001")
def test_inspection_never_mutates():
    r = router(repos__acme__widgets="User", issues="[]",
               projectsV2=[{"number": 3, "title": "R"}], fields=FULL_PROJECT)
    it.inspect(client(r), "acme", "widgets")
    for call in r.calls:
        blob = " ".join(call)
        assert "mutation" not in blob
        for verb in ("POST", "PATCH", "PUT", "DELETE"):
            assert f"--method {verb}" not in blob


def test_the_record_serializes():
    r = router(repos__acme__widgets="User", issues="[]",
               projectsV2=[{"number": 3, "title": "R"}], fields=FULL_PROJECT)
    payload = json.loads(json.dumps(it.inspect(client(r), "acme", "widgets").to_dict()))
    assert payload["usable"] is True
    assert payload["roles"]["delivery_state"] == "Status"


# --- what a backend cannot carry --------------------------------------------

@pytest.mark.req("REQ-GITHUB-BACKENDS-001")
def test_every_backend_accounts_for_the_same_roles():
    # A role added to one backend and forgotten in another is the drift this
    # prevents. Silence about a role reads as support for it.
    import yaml
    matrix = yaml.safe_load((ROOT / "tooling/compatibility.yml").read_text())
    backends = matrix["backends"]
    accounted = {name: set(spec.get("carries") or [])
                 | set(spec.get("unavailable") or {})
                 for name, spec in backends.items()}
    assert len(set(map(frozenset, accounted.values()))) == 1, accounted


@pytest.mark.req("REQ-GITHUB-BACKENDS-001")
def test_the_organization_backend_records_what_it_cannot_carry():
    import yaml
    matrix = yaml.safe_load((ROOT / "tooling/compatibility.yml").read_text())
    org = matrix["backends"]["issue-fields"]
    assert set(org["unavailable"]) == {
        "outcome_status", "risk", "severity", "capability"}
    for role, reason in org["unavailable"].items():
        assert reason.strip(), role
    assert org["remedy"].strip()


@pytest.mark.req("REQ-GITHUB-BACKENDS-001")
def test_a_missing_role_says_what_the_project_loses():
    # "optional role has no field" said nothing actionable. On the
    # organization backend it cannot be created at all, and a workflow needing
    # it cannot complete.
    said = it._role_consequence("issue-fields", "outcome_status")
    assert "cannot be created by this bundle" in said
    assert "lifecycle-release-outcome" in said
    assert "Remedy:" in said


@pytest.mark.req("REQ-GITHUB-BACKENDS-001")
def test_a_role_nothing_writes_says_nothing_is_blocked():
    said = it._role_consequence("projects-v2", "capability")
    assert "nothing is blocked" in said.lower()


@pytest.mark.req("REQ-GITHUB-BACKENDS-001")
def test_an_older_preset_loses_the_explanation_not_the_inspection(monkeypatch):
    monkeypatch.setattr(it, "_backend_matrix", lambda: {})
    said = it._role_consequence("issue-fields", "outcome_status")
    assert said and "nothing is blocked" in said.lower()
