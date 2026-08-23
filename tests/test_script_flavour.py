"""Which script flavour the extension provides, and whether it says so.

`specify init --script py|sh` records the project's choice, and Spec Kit
installs both flavours of its own scripts regardless. This extension provides
one and every command invokes it, while `requires.tools` declared only `gh` —
so a project that chose shell learned the dependency when a command failed.

The fix is to declare it. Upstream's `git` extension ships three flavours
because its scripts are a few lines of `git init`; `transition_plan.py` does
schema validation, read-back verification, and dependency resolution, and a
shell reimplementation would be a second copy that drifts.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
EXTENSION = ROOT / "bundle/components/extensions/github-lifecycle"
POLICY = load_yaml(ROOT / "policy/bootstrap-policy.yml")["script_flavours"]

spec = importlib.util.spec_from_file_location("doctor", SCRIPTS / "doctor.py")
doctor = importlib.util.module_from_spec(spec)
sys.modules["doctor"] = doctor
spec.loader.exec_module(doctor)


def project(tmp_path, chosen=None, with_policy=True):
    (tmp_path / ".specify").mkdir(parents=True, exist_ok=True)
    if with_policy:
        dest = tmp_path / ".specify/presets/lean-full-lifecycle-governance/policy"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "bootstrap-policy.yml").write_text(
            (ROOT / "policy/bootstrap-policy.yml").read_text(encoding="utf-8"),
            encoding="utf-8")
    if chosen is not None:
        (tmp_path / ".specify/init-options.json").write_text(
            json.dumps({"script": chosen, "integration": "claude"}),
            encoding="utf-8")
    return tmp_path


# --- the manifest declares what the commands need -----------------------------

@pytest.mark.req("REQ-CORE-FLAVOUR-001")
def test_the_extension_declares_the_interpreter_its_commands_invoke():
    manifest = load_yaml(EXTENSION / "extension.yml")
    tools = {t["name"] for t in manifest["requires"]["tools"]}
    assert tools & {"python", "python3"}


@pytest.mark.req("REQ-CORE-FLAVOUR-001")
def test_every_command_invokes_only_a_shipped_script():
    manifest = load_yaml(EXTENSION / "extension.yml")
    shipped = {p.name for p in SCRIPTS.glob("*")}
    for entry in manifest["provides"]["commands"]:
        text = (EXTENSION / entry["file"]).read_text(encoding="utf-8")
        for name in re.findall(r"scripts/([A-Za-z0-9_.-]+\.(?:py|sh|ps1))", text):
            assert name in shipped, f"{entry['name']} invokes {name}"


@pytest.mark.req("REQ-CORE-FLAVOUR-001")
def test_no_command_invokes_a_flavour_the_extension_does_not_ship():
    manifest = load_yaml(EXTENSION / "extension.yml")
    allowed = {"py": ".py", "sh": ".sh", "ps1": ".ps1"}
    permitted = {allowed[f] for f in POLICY["provided"]}
    for entry in manifest["provides"]["commands"]:
        text = (EXTENSION / entry["file"]).read_text(encoding="utf-8")
        for name in re.findall(r"scripts/([A-Za-z0-9_.-]+\.(?:py|sh|ps1))", text):
            assert name[name.rindex("."):] in permitted, name


@pytest.mark.req("REQ-CORE-FLAVOUR-001")
def test_a_registered_check_enforces_it():
    from lib import checks  # noqa: F401  (registers them)
    from lib import registry

    assert "INV-SCRIPT-FLAVOUR" in registry.REGISTRY


# --- doctor tells the operator before a command does --------------------------

@pytest.mark.req("REQ-CORE-FLAVOUR-001")
def test_a_matching_project_is_reported_ok(tmp_path):
    result = doctor.script_flavour(project(tmp_path, chosen="py"))
    assert result["status"] == "ok"
    assert result["chosen"] == "py"


@pytest.mark.req("REQ-CORE-FLAVOUR-001")
def test_a_shell_project_is_reported_as_a_mismatch(tmp_path):
    result = doctor.script_flavour(project(tmp_path, chosen="sh"))
    assert result["status"] == "mismatch"
    assert result["chosen"] == "sh"
    assert result["provided"] == POLICY["provided"]


@pytest.mark.req("REQ-CORE-FLAVOUR-001")
def test_the_mismatch_says_what_it_does_and_does_not_mean(tmp_path):
    # Not a broken install: the scripts are installed and run wherever python3
    # is. What it means is that nothing here honours the project's choice.
    detail = doctor.script_flavour(project(tmp_path, chosen="sh"))["detail"]
    assert "asked for shell" in detail
    assert "before a command fails" in detail


@pytest.mark.req("REQ-CORE-FLAVOUR-001")
def test_a_project_with_no_recorded_choice_is_unknown_not_ok(tmp_path):
    # Absent evidence is not agreement.
    result = doctor.script_flavour(project(tmp_path, chosen=None))
    assert result["status"] == "unknown"


@pytest.mark.req("REQ-CORE-FLAVOUR-001")
def test_an_unreadable_choice_is_unknown_not_ok(tmp_path):
    root = project(tmp_path, chosen="py")
    (root / ".specify/init-options.json").write_text("{ not json",
                                                     encoding="utf-8")
    assert doctor.script_flavour(root)["status"] == "unknown"


@pytest.mark.req("REQ-CORE-FLAVOUR-001")
def test_without_the_preset_the_provided_flavour_is_not_asserted(tmp_path):
    result = doctor.script_flavour(project(tmp_path, chosen="sh",
                                           with_policy=False))
    assert result["status"] == "unknown"
    assert "not declared" in result["detail"]
