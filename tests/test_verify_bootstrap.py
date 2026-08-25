"""Whether the project can run the workflows, asked at bootstrap.

Five workflows shell out to `devbox run verify` and one to
`devbox run release-verify`, and nothing has ever checked the target project
defines them. The roadmap states the requirement as a user-experience one: do
not let the user discover this only after the first workflow failure.
"""
from __future__ import annotations

import importlib.util
import json
import sys

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
spec = importlib.util.spec_from_file_location("verify_bootstrap",
                                              SCRIPTS / "verify_bootstrap.py")
vb = importlib.util.module_from_spec(spec)
sys.modules["verify_bootstrap"] = vb
spec.loader.exec_module(vb)

POLICY = vb.load_policy(ROOT)
VERIFY = "devbox run verify"
RELEASE = "devbox run release-verify"
WORKFLOWS = {
    n: load_yaml(ROOT / f"bundle/components/workflows/{n}/workflow.yml")
    for n in ("lifecycle-greenfield-bootstrap", "lifecycle-brownfield-adoption")
}


def project(tmp_path, scripts=None, overlay=None, stack=None, devbox="valid"):
    if devbox == "valid":
        (tmp_path / "devbox.json").write_text(
            json.dumps({"shell": {"scripts": scripts or {}}}), encoding="utf-8")
    elif devbox == "broken":
        (tmp_path / "devbox.json").write_text("not json", encoding="utf-8")
    if overlay is not None:
        path = tmp_path / POLICY["overlay"]["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(vb.yaml.safe_dump({"mappings": overlay}), encoding="utf-8")
    if stack:
        source = POLICY["generation"]["stack_decision_sources"][0]
        path = tmp_path / source["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        # A source records a decision under a declared heading. Writing the
        # body alone is what used to count, and is the defect (#136).
        if stack.strip() and "#" not in stack:
            stack = f"# S\n\n## {source['records_decision_in']}\n\n{stack}"
        path.write_text(stack, encoding="utf-8")
    return tmp_path


# --- AC1: both present, nothing written ---------------------------------------

@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_both_commands_present_is_resolved(tmp_path):
    root = project(tmp_path, {"verify": ["pytest"], "release-verify": ["pytest"]})
    report = vb.detect(root, POLICY)
    assert report.present == [VERIFY, RELEASE]
    assert report.missing == []
    assert report.resolved


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_detection_writes_nothing(tmp_path):
    root = project(tmp_path, {"verify": ["pytest"]})
    before = {p.name for p in root.rglob("*")}
    vb.detect(root, POLICY)
    vb.check_overlay(root, POLICY)
    assert {p.name for p in root.rglob("*")} == before


# --- AC2: missing is named, and distinguished from present --------------------

@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_a_partial_project_reports_each_command_separately(tmp_path):
    root = project(tmp_path, {"verify": ["pytest"]})
    report = vb.detect(root, POLICY)
    # The point of the story: not one verdict for both commands.
    assert report.present == [VERIFY]
    assert report.missing == [RELEASE]


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_neither_command_defined_names_both(tmp_path):
    report = vb.detect(project(tmp_path), POLICY)
    assert report.missing == [VERIFY, RELEASE]
    assert report.present == []


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_a_missing_devbox_file_is_not_an_error(tmp_path):
    # A project with no devbox.json defines neither command. That is a finding,
    # not a failure to look.
    report = vb.detect(tmp_path, POLICY)
    assert report.missing == [VERIFY, RELEASE]
    assert report.problems == []


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_an_unreadable_devbox_file_resolves_nothing(tmp_path):
    root = project(tmp_path, devbox="broken")
    report = vb.detect(root, POLICY)
    assert report.problems
    assert not report.resolved, (
        "an unreadable file reporting nothing missing would read as success")
    assert report.missing == [], (
        "reporting every command missing would send the user to add what is "
        "already there")


# --- AC3: generation requires a stack decision --------------------------------

@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_generation_without_a_stack_decision_is_refused(tmp_path):
    problems = vb.refuse_generation_without_a_stack(project(tmp_path), POLICY)
    assert problems
    assert "no stack decision is recorded" in problems[0]


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_the_refusal_names_the_missing_input(tmp_path):
    problems = vb.refuse_generation_without_a_stack(project(tmp_path), POLICY)
    for source in POLICY["generation"]["stack_decision_sources"]:
        assert source["path"] in problems[0]
        assert source["records_decision_in"] in problems[0]


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_an_empty_stack_decision_does_not_count(tmp_path):
    root = project(tmp_path, stack="   \n")
    assert vb.refuse_generation_without_a_stack(root, POLICY)


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_generation_is_permitted_once_a_stack_is_decided(tmp_path):
    root = project(tmp_path, stack="Python 3.13, pytest, ruff.")
    assert vb.refuse_generation_without_a_stack(root, POLICY) == []


# --- AC4: an overlay may satisfy only a declared framework command ------------

@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_an_overlay_to_a_framework_command_is_accepted(tmp_path):
    root = project(tmp_path, overlay=[
        {"framework_command": VERIFY, "project_command": "make check"}])
    assert vb.check_overlay(root, POLICY) == []
    assert vb.detect(root, POLICY).overlaid == [VERIFY]


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_an_overlay_to_any_other_command_is_refused(tmp_path):
    root = project(tmp_path, overlay=[
        {"framework_command": "devbox run deploy",
         "project_command": "kubectl apply -f prod/"}])
    problems = vb.check_overlay(root, POLICY)
    assert problems
    assert "not a framework command" in problems[0]


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_an_overlay_naming_no_project_command_is_refused(tmp_path):
    root = project(tmp_path, overlay=[{"framework_command": VERIFY}])
    assert any("names no project command" in p
               for p in vb.check_overlay(root, POLICY))


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_the_allowed_targets_match_the_source_repo_allowed_shell():
    # Two copies of the same fact: the shipped policy and the source-tree
    # invariant. They must agree, or an overlay could satisfy a command the
    # validator would reject in a workflow.
    invariants = load_yaml(ROOT / "tooling/invariants.yml")
    assert sorted(vb.declared_commands(POLICY)) == sorted(
        invariants["allowed_shell"])


# --- AC5: nothing is written without a gate -----------------------------------

@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_both_bootstrap_workflows_check_verification_commands(name):
    ids = [s["id"] for s in WORKFLOWS[name]["steps"]]
    assert "check-verification-commands" in ids
    assert ids.index("check-verification-commands") < \
        ids.index("approve-verification-resolution")


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_resolution_gate_aborts_on_reject(name):
    gate = [s for s in WORKFLOWS[name]["steps"]
            if s["id"] == "approve-verification-resolution"][0]
    assert gate["on_reject"] == "abort"
    assert gate["verdict_input"] == "verification_verdict"


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_check_step_says_it_writes_nothing_before_the_gate(name):
    step = [s for s in WORKFLOWS[name]["steps"]
            if s["id"] == "check-verification-commands"][0]
    args = step["input"]["args"]
    assert "stop at the gate before writing" in args
    assert "separately" in args


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_gate_says_what_rejecting_costs(name):
    gate = [s for s in WORKFLOWS[name]["steps"]
            if s["id"] == "approve-verification-resolution"][0]
    assert "first delivery will fail" in gate["message"]


# --- policy is the source -----------------------------------------------------

@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_the_commands_are_not_hardcoded_in_the_script():
    source = (SCRIPTS / "verify_bootstrap.py").read_text(encoding="utf-8")
    for literal in ('"devbox run verify"', '"devbox.json"'):
        assert literal not in source, f"{literal} is hardcoded"


# --- a file is not a decision -------------------------------------------------
#
# `stack_decision` tested that a source existed and was non-empty. Every
# bootstrap writes a constitution, so the guard against inventing a toolchain
# was cleared by the document meant to contain the answer (#136).

@pytest.mark.req("REQ-CORE-VERIFYCMD-002")
def test_a_constitution_naming_no_toolchain_is_not_a_stack_decision(tmp_path):
    # The pilot's constitution: 347 lines, no language, no runtime, no test
    # command. It satisfied the old check by existing.
    root = tmp_path
    path = root / ".specify/memory/constitution.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Constitution\n\n## Governance\n\n" + ("Rules.\n" * 50),
                    encoding="utf-8")
    assert vb.stack_decision(root, POLICY) is None


@pytest.mark.req("REQ-CORE-VERIFYCMD-002")
def test_a_constitution_that_records_its_tooling_does_count(tmp_path):
    # The fix must not simply refuse everything: a real constitution records
    # its stack, and the brownfield pilot's does under this heading.
    source = next(s for s in POLICY["generation"]["stack_decision_sources"]
                  if s["path"].endswith("constitution.md"))
    path = tmp_path / source["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Constitution\n\n### {source['records_decision_in']}\n\n"
        "| Concern | Decision |\n|---|---|\n| Lint | Ruff |\n", encoding="utf-8")
    assert vb.stack_decision(tmp_path, POLICY) == path


@pytest.mark.req("REQ-CORE-VERIFYCMD-002")
def test_a_declared_heading_with_nothing_under_it_is_not_a_decision(tmp_path):
    # The same failure one level down: a heading is not an answer.
    source = POLICY["generation"]["stack_decision_sources"][0]
    path = tmp_path / source["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# S\n\n## {source['records_decision_in']}\n\n"
                    "## Consequences\n\n- something\n", encoding="utf-8")
    assert vb.stack_decision(tmp_path, POLICY) is None


@pytest.mark.req("REQ-CORE-VERIFYCMD-002")
def test_every_source_declares_where_its_decision_is_recorded():
    for source in POLICY["generation"]["stack_decision_sources"]:
        assert source["records_decision_in"], (
            f"{source['path']} names no section, so any content would count")
