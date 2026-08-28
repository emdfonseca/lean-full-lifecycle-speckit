"""Which binaries doctor reports, and under what condition.

The bundle executes three binaries and `doctor.py` probed one: `gh`, at its
own call sites. `git` and the model-inventory binary were executed from
shipped code and named nowhere, so a machine missing either passed `doctor`
cleanly and failed later inside a workflow run.

A flat list would have been the wrong fix. The three are not alike: `gh` is
unconditional, `git`'s absence costs one audit rule and nothing else, and the
model-inventory binary is required only by an integration that declares an
inventory command. `model-routing.yml` states `claude: null` precisely so a
Claude Code project is not asked for one, and reporting `opencode` missing to
that project would be a false prerequisite.

These tests assert nothing about `requires.tools`. Declaring a binary there
changes no behaviour in specify 1.0.1 -- it is read for display and for shape
validation only -- which is the premise this issue (#159) was reshaped to
drop.
"""
from __future__ import annotations

import importlib.util
import json
import sys

import pytest

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"

spec = importlib.util.spec_from_file_location(
    "doctor_binaries_subject", SCRIPTS / "doctor.py")
doctor = importlib.util.module_from_spec(spec)
sys.modules["doctor_binaries_subject"] = doctor
spec.loader.exec_module(doctor)


def project(tmp_path, with_policy=True):
    """A project tree carrying the preset's model-routing policy."""
    (tmp_path / ".specify").mkdir(parents=True, exist_ok=True)
    if with_policy:
        dest = tmp_path / ".specify/presets/lean-full-lifecycle-governance/policy"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "model-routing.yml").write_text(
            (ROOT / "policy/model-routing.yml").read_text(encoding="utf-8"),
            encoding="utf-8")
    return tmp_path


def absent(*names):
    """A `which` that answers no for these binaries and yes for the rest.

    Injected rather than stubbing PATH: `gh`, `git` and `opencode` are all
    installed on the machines this suite runs on, so no local environment
    observes the missing-binary path on its own.
    """
    return lambda name: None if name in names else f"/usr/bin/{name}"


def by_binary(reports):
    return {r["binary"]: r for r in reports if "binary" in r}


# --- the binary an integration needs, when that integration needs it ---------

@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_a_missing_inventory_binary_is_reported_for_the_integration_that_runs_it(
        tmp_path):
    reports = doctor.binary_dependencies(
        project(tmp_path), integration="opencode", which=absent("opencode"))
    assert by_binary(reports)["opencode"]["status"] == "missing"


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_the_missing_inventory_binary_names_what_fails(tmp_path):
    reports = doctor.binary_dependencies(
        project(tmp_path), integration="opencode", which=absent("opencode"))
    entry = by_binary(reports)["opencode"]
    assert "InventoryError" in entry["on_absence"]
    assert "read_inventory" in entry["on_absence"]


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_an_integration_with_no_inventory_command_is_not_told_to_install_one(
        tmp_path):
    reports = doctor.binary_dependencies(
        project(tmp_path), integration="claude", which=absent("opencode"))
    assert "opencode" not in json.dumps(reports)


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_that_integration_is_still_accounted_for_rather_than_omitted(tmp_path):
    reports = doctor.binary_dependencies(
        project(tmp_path), integration="claude", which=absent())
    stated = [r for r in reports if r.get("integration") == "claude"]
    assert [r["status"] for r in stated] == ["not_applicable"]


# --- the two every project runs ----------------------------------------------

@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_a_missing_git_is_reported_as_optional_and_names_the_rule_it_costs(
        tmp_path):
    entry = by_binary(doctor.binary_dependencies(
        project(tmp_path), which=absent("git")))["git"]
    assert entry["status"] == "missing"
    assert entry["condition"] == "optional"
    assert "working_tree_disagreement" in entry["on_absence"]


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_a_missing_gh_is_reported_as_unconditional(tmp_path):
    entry = by_binary(doctor.binary_dependencies(
        project(tmp_path), which=absent("gh")))["gh"]
    assert entry["status"] == "missing"
    assert entry["condition"] == "unconditional"


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_a_present_binary_is_reported_present(tmp_path):
    reports = by_binary(doctor.binary_dependencies(
        project(tmp_path), integration="opencode", which=absent()))
    assert [reports[b]["status"] for b in ("gh", "git", "opencode")] == \
        ["ok", "ok", "ok"]


# --- which integration, and never a guess ------------------------------------

@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_an_undeclared_integration_is_unknown_rather_than_assumed(tmp_path):
    # The bundle is agent-neutral. Defaulting to one meant a project using a
    # different agent was told about a binary it never executes.
    reports = doctor.binary_dependencies(project(tmp_path), which=absent())
    assert "opencode" not in by_binary(reports)
    conditional = [r for r in reports if "binary" not in r]
    assert [r["status"] for r in conditional] == ["unknown"]
    assert conditional[0]["integration"] is None


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_the_integration_is_read_from_the_project(tmp_path):
    root = project(tmp_path)
    (root / ".specify/integration.json").write_text(
        json.dumps({"default_integration": "claude"}), encoding="utf-8")
    assert doctor.resolve_integration(root) == {
        "integration": "claude", "source": ".specify/integration.json"}


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_the_older_integration_key_is_still_read(tmp_path):
    root = project(tmp_path)
    (root / ".specify/integration.json").write_text(
        json.dumps({"integration": "opencode"}), encoding="utf-8")
    assert doctor.resolve_integration(root)["integration"] == "opencode"


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_an_absent_integration_file_names_what_was_missing(tmp_path):
    resolved = doctor.resolve_integration(project(tmp_path))
    assert resolved["integration"] is None
    assert ".specify/integration.json" in resolved["detail"]


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_an_unreadable_integration_file_is_not_read_as_absent(tmp_path):
    root = project(tmp_path)
    (root / ".specify/integration.json").write_text("{not json", encoding="utf-8")
    resolved = doctor.resolve_integration(root)
    assert resolved["integration"] is None
    assert "could not be read" in resolved["detail"]


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_the_flag_overrides_what_the_project_declares(tmp_path):
    root = project(tmp_path)
    (root / ".specify/integration.json").write_text(
        json.dumps({"default_integration": "claude"}), encoding="utf-8")
    assert doctor.resolve_integration(root, "opencode") == {
        "integration": "opencode", "source": "--integration"}


# --- what it does when the policy that carries the condition is absent -------

@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_without_the_preset_the_conditional_binary_is_unknown_not_guessed(
        tmp_path):
    reports = doctor.binary_dependencies(
        project(tmp_path, with_policy=False), which=absent())
    assert "opencode" not in by_binary(reports)
    assert [r["status"] for r in reports if "binary" not in r] == ["unknown"]


@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_the_unconditional_binaries_are_reported_without_the_preset(tmp_path):
    reports = by_binary(doctor.binary_dependencies(
        project(tmp_path, with_policy=False), which=absent("gh")))
    assert reports["gh"]["status"] == "missing"
    assert reports["git"]["status"] == "ok"


# --- doctor's own report carries it ------------------------------------------

@pytest.mark.req("REQ-CORE-BINARIES-001")
def test_the_doctor_report_carries_the_binaries_section(tmp_path, monkeypatch,
                                                        capsys):
    monkeypatch.chdir(project(tmp_path))
    monkeypatch.setattr(sys, "argv", ["doctor.py", "--integration", "claude"])
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("doctor must not be asked to run a command here")))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert doctor.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert {r.get("binary") for r in report["binaries"]} >= {"gh", "git"}
