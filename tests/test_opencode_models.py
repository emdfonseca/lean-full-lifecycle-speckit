"""Whether the model a role names actually exists.

`model-routing.yml` named seven roles and left every primary null since 0.1.0,
and nothing read the file. A mapping written by hand would name models nobody
had verified against the CLI that has to run them.
"""
from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys

import pytest

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("project_root")
om = _load("opencode_models")

POLICY = om.load_policy(ROOT)
INVENTORY = {"anthropic/claude-opus-5", "anthropic/claude-sonnet-5",
             "openai/gpt-5", "opencode/big-pickle"}


def policy(roles, approved=None):
    out = copy.deepcopy(POLICY)
    out["roles"] = roles
    out["approved_providers"] = approved if approved is not None else []
    return out


def runner(stdout="", returncode=0, stderr="", raises=None):
    def run(_args):
        if raises:
            raise raises
        return subprocess.CompletedProcess([], returncode, stdout, stderr)
    return run


# --- AC1: an id outside the inventory -----------------------------------------

@pytest.mark.req("REQ-CORE-MODELS-001")
def test_a_model_not_in_the_inventory_is_refused():
    report = om.verify(
        policy({"builder": {"primary": "anthropic/claude-nonexistent"}}),
        INVENTORY)
    assert not report.ok
    assert "builder" in report.problems[0]
    assert "claude-nonexistent" in report.problems[0]
    assert "not in the installed inventory" in report.problems[0]


@pytest.mark.req("REQ-CORE-MODELS-001")
def test_a_model_in_the_inventory_is_verified():
    report = om.verify(policy({"builder": {"primary": "openai/gpt-5"}}),
                       INVENTORY)
    assert report.ok
    assert report.verified["builder"] == ["openai/gpt-5"]


# --- AC2: an unapproved provider ----------------------------------------------

@pytest.mark.req("REQ-CORE-MODELS-001")
def test_a_model_from_an_unapproved_provider_is_refused():
    report = om.verify(
        policy({"builder": {"primary": "openai/gpt-5"}},
               approved=["anthropic"]),
        INVENTORY)
    assert not report.ok
    assert "'openai'" in report.problems[0]
    assert "['anthropic']" in report.problems[0]


@pytest.mark.req("REQ-CORE-MODELS-001")
def test_an_empty_approved_list_does_not_reject_everything():
    # The policy shipped `require_approved_provider: true` with nothing to
    # check against. An empty list means unset, not "approve nothing".
    report = om.verify(policy({"builder": {"primary": "openai/gpt-5"}},
                              approved=[]), INVENTORY)
    assert report.ok


@pytest.mark.req("REQ-CORE-MODELS-001")
def test_a_real_model_from_an_unapproved_provider_still_fails():
    # Both checks run: existing is not the same as permitted.
    report = om.verify(
        policy({"builder": {"primary": "opencode/big-pickle"}},
               approved=["anthropic", "openai"]),
        INVENTORY)
    assert not report.ok


# --- AC3: fallbacks are verified like primaries -------------------------------

@pytest.mark.req("REQ-CORE-MODELS-001")
def test_a_bad_fallback_is_refused_and_identified_as_a_fallback():
    # A fallback runs when the primary is unavailable, which is exactly when
    # nobody is in a position to discover it was never real.
    report = om.verify(
        policy({"builder": {"primary": "openai/gpt-5",
                            "fallbacks": ["openai/gpt-nonexistent"]}}),
        INVENTORY)
    assert not report.ok
    assert "fallback" in report.problems[0]
    assert "primary" not in report.problems[0]


@pytest.mark.req("REQ-CORE-MODELS-001")
def test_good_fallbacks_are_reported_with_the_primary():
    report = om.verify(
        policy({"builder": {"primary": "openai/gpt-5",
                            "fallbacks": ["anthropic/claude-sonnet-5"]}}),
        INVENTORY)
    assert report.verified["builder"] == ["openai/gpt-5",
                                          "anthropic/claude-sonnet-5"]


@pytest.mark.req("REQ-CORE-MODELS-001")
def test_a_fallback_with_no_primary_is_refused():
    report = om.verify(
        policy({"builder": {"primary": None,
                            "fallbacks": ["openai/gpt-5"]}}), INVENTORY)
    assert not report.ok
    assert "nothing to fall back from" in report.problems[0]


# --- AC4: an unresolved role is reported, not filled in -----------------------

@pytest.mark.req("REQ-CORE-MODELS-001")
def test_a_null_primary_is_reported_unresolved():
    report = om.verify(policy({"planner": {"primary": None}}), INVENTORY)
    assert report.unresolved == ["planner"]
    assert report.verified == {}


@pytest.mark.req("REQ-CORE-MODELS-001")
def test_an_unresolved_role_is_not_a_problem_to_be_fixed_by_choosing_one():
    # A null primary is a decision deferred until there is evidence. Reporting
    # it clean is right; picking something to make it green is not.
    report = om.verify(policy({"planner": {"primary": None}}), INVENTORY)
    assert report.ok
    assert report.to_dict()["fully_resolved"] is False


@pytest.mark.req("REQ-CORE-MODELS-001")
def test_the_shipped_policy_resolves_no_roles_and_that_is_clean():
    report = om.verify(POLICY, INVENTORY)
    assert sorted(report.unresolved) == sorted(POLICY["roles"])
    assert report.ok


# --- AC5: an unreadable inventory ---------------------------------------------

@pytest.mark.req("REQ-CORE-MODELS-001")
def test_a_failing_inventory_command_refuses():
    with pytest.raises(om.InventoryError) as exc:
        om.read_inventory(POLICY, runner(returncode=1, stderr="boom"))
    assert "exited 1" in str(exc.value)


@pytest.mark.req("REQ-CORE-MODELS-001")
def test_a_missing_inventory_command_refuses():
    with pytest.raises(om.InventoryError) as exc:
        om.read_inventory(POLICY, runner(raises=FileNotFoundError("opencode")))
    assert "could not be read" in str(exc.value)


@pytest.mark.req("REQ-CORE-MODELS-001")
def test_an_empty_inventory_refuses_rather_than_verifying_everything():
    with pytest.raises(om.InventoryError) as exc:
        om.read_inventory(POLICY, runner(stdout="\n\n"))
    assert "verify every id while appearing to" in str(exc.value)


@pytest.mark.req("REQ-CORE-MODELS-001")
def test_a_readable_inventory_is_parsed_into_provider_model_ids():
    models = om.read_inventory(
        POLICY, runner(stdout="anthropic/claude-opus-5\nopenai/gpt-5\n"
                              "not a model line\n"))
    assert models == {"anthropic/claude-opus-5", "openai/gpt-5"}


# --- the inventory is asked for, not maintained here --------------------------

@pytest.mark.req("REQ-CORE-MODELS-001")
def test_the_inventory_command_comes_from_policy():
    assert POLICY["resolution"]["inventory_command"] == ["opencode", "models"]
    source = (SCRIPTS / "opencode_models.py").read_text(encoding="utf-8")
    # A model list maintained in this repository would be a second copy that
    # drifts, and the copy that drifts is the one nobody is testing.
    assert '"opencode", "models"' not in source


@pytest.mark.req("REQ-CORE-MODELS-001")
@pytest.mark.requires_opencode
def test_the_real_cli_reports_a_usable_inventory():
    models = om.read_inventory(POLICY)
    assert models
    assert all("/" in m for m in models)


# --- recording a resolution ---------------------------------------------------

from datetime import date  # noqa: E402

TODAY = date(2026, 8, 23)
GOOD = {"builder": {"primary": "openai/gpt-5",
                    "fallbacks": ["anthropic/claude-sonnet-5"]}}


def verified_report():
    return om.verify(policy(GOOD), INVENTORY)


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_a_record_carries_each_role_its_model_and_both_dates():
    written = om.record(POLICY, verified_report(), "2026-08-23", "2026-11-23",
                        ROOT)
    assert written["evaluated_at"] == "2026-08-23"
    assert written["expires_at"] == "2026-11-23"
    assert written["roles"]["builder"]["primary"] == "openai/gpt-5"
    assert written["roles"]["builder"]["fallbacks"] == \
        ["anthropic/claude-sonnet-5"]


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_the_record_carries_the_roles_that_stayed_unresolved():
    report = om.verify(policy(dict(GOOD, planner={"primary": None})), INVENTORY)
    written = om.record(POLICY, report, "2026-08-23", "2026-11-23", ROOT)
    assert written["unresolved"] == ["planner"]


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_an_expired_record_is_reported_expired(tmp_path):
    path = tmp_path / "resolved.yml"
    path.write_text(om.yaml.safe_dump(
        {"evaluated_at": "2026-01-01", "expires_at": "2026-04-01",
         "roles": GOOD}), encoding="utf-8")
    read = om.read_record(path, as_of=TODAY)
    assert read["expired"] is True
    assert read["current"] is False
    assert "not the mapping in force" in read["note"]


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_a_current_record_is_reported_current(tmp_path):
    path = tmp_path / "resolved.yml"
    path.write_text(om.yaml.safe_dump(
        {"evaluated_at": "2026-08-01", "expires_at": "2026-12-01",
         "roles": GOOD}), encoding="utf-8")
    assert om.read_record(path, as_of=TODAY)["current"] is True


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_a_record_with_no_usable_expiry_cannot_be_shown_current(tmp_path):
    # A resolution with no visible expiry is trusted indefinitely, which is how
    # a withdrawn model stays in a config.
    path = tmp_path / "resolved.yml"
    path.write_text(om.yaml.safe_dump({"roles": GOOD}), encoding="utf-8")
    read = om.read_record(path, as_of=TODAY)
    assert read["current"] is False
    assert "cannot be shown to be current" in read["note"]


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_recording_a_failed_verification_is_refused():
    report = om.verify(policy({"builder": {"primary": "openai/nope"}}),
                       INVENTORY)
    with pytest.raises(om.RecordError) as exc:
        om.record(POLICY, report, "2026-08-23", "2026-11-23", ROOT)
    assert "failed verification" in str(exc.value)


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_recording_nothing_verified_is_refused():
    # An empty mapping recorded as current is indistinguishable from a
    # resolved one, which is exactly the confusion this file exists to end.
    report = om.verify(POLICY, INVENTORY)
    assert report.ok and not report.verified
    with pytest.raises(om.RecordError) as exc:
        om.record(POLICY, report, "2026-08-23", "2026-11-23", ROOT)
    assert "nothing was verified" in str(exc.value)


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_recording_without_an_expiry_is_refused():
    with pytest.raises(om.RecordError) as exc:
        om.record(POLICY, verified_report(), "2026-08-23", "", ROOT)
    assert "no expiry" in str(exc.value)


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
@pytest.mark.parametrize("bad", ["soon", "2026-13-01", None])
def test_a_date_that_is_not_a_date_is_refused(bad):
    with pytest.raises(om.RecordError):
        om.record(POLICY, verified_report(), "2026-08-23", bad, ROOT)


# --- the mapping is replaceable, and unused roles are visible -----------------

@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_no_workflow_names_a_role():
    # The exit gate asks that the mapping be replaceable without changing
    # lifecycle workflows. It is currently true by accident; this makes it true
    # by test, before anything starts referencing roles.
    import re

    # "Names a role" means uses it as a value. A bare-word search reports
    # `architect` because a prompt says "architecture", and `reviewer` because
    # a gate message describes the person at it -- neither is a reference the
    # mapping could break.
    workflows = ROOT / "bundle/components/workflows"
    named = [(path.parent.name, role)
             for path in workflows.rglob("workflow.yml")
             for role in POLICY["roles"]
             if re.search(rf"""(?:role|agent)\s*:\s*["']?{role}\b""",
                          path.read_text(encoding="utf-8"))]
    assert named == [], named


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_every_role_is_currently_reported_unused():
    # Reported, not removed: deleting somebody's role because nothing
    # references it yet is a decision, not tidying.
    unused = om.unused_roles(POLICY, [ROOT / "bundle/components/workflows"])
    assert sorted(unused) == sorted(POLICY["roles"])


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_a_role_a_consumer_names_is_not_reported_unused(tmp_path):
    consumer = tmp_path / "workflow.yml"
    consumer.write_text("steps:\n  - id: x\n    role: reviewer\n",
                        encoding="utf-8")
    unused = om.unused_roles(POLICY, [tmp_path])
    assert "reviewer" not in unused
    assert "builder" in unused


@pytest.mark.req("REQ-CORE-MODELRECORD-001")
def test_the_record_path_comes_from_policy():
    assert POLICY["resolution"]["record_path"].startswith(".specify/")
    source = (SCRIPTS / "opencode_models.py").read_text(encoding="utf-8")
    assert POLICY["resolution"]["record_path"] not in source
