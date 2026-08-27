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


# --- gate resolution: resolved, declined, or filed -----------------------------
#
# The contract before this produced no outcome for any gate at once, so nothing
# distinguished a gate the owner rejected from one nobody looked at. Every test
# below drives the property that ends that: sixteen declared gates, each in
# exactly one bucket, and `unexamined` is a bucket rather than an absence.

GATES = vb.declared_gates(vb.load_gate_policy(ROOT))
ITEM_TYPES = vb.load_item_types(ROOT)
REQUIRED = vb.required_sections(ITEM_TYPES, "story")
FILING_BODY = "\n".join(f"## {s}\n\nsomething" for s in REQUIRED)


def resolve(record, incoming):
    return vb.merge(record, incoming, GATES, POLICY, ITEM_TYPES)


def run(monkeypatch, *argv):
    """Through the CLI, because writing and the exit code live only there."""
    monkeypatch.setattr(sys, "argv", ["verify_bootstrap.py",
                                      "--policy-root", str(ROOT)] + list(argv))
    return vb.main()


def resolution(tmp_path, incoming):
    path = tmp_path / "resolve.yml"
    path.write_text(vb.yaml.safe_dump(incoming), encoding="utf-8")
    return path


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_resolved_gate_records_the_command_that_satisfies_it():
    record, problems = resolve(vb.EMPTY_RECORD, {"gates": {
        "secret_detection": {"outcome": "resolved",
                             "command": "gitleaks detect"}}})
    assert problems == []
    row = vb.report_gates(record, GATES, POLICY).resolved[0]
    assert row == {"gate": "secret_detection", "command": "gitleaks detect"}


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_resolved_gate_naming_no_command_is_refused():
    # An outcome with no command leaves the gate satisfied by nothing nameable.
    record, problems = resolve(vb.EMPTY_RECORD, {"gates": {
        "secret_detection": {"outcome": "resolved", "command": "  "}}})
    assert problems and "secret_detection" in problems[0]
    assert record["gates"] == {}


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_declined_gate_records_its_reason_and_the_run_proceeds():
    record, problems = resolve(vb.EMPTY_RECORD, {"gates": {
        "accessibility": {"outcome": "declined", "reason": "no user surface"}}})
    assert problems == []
    report = vb.report_gates(record, GATES, POLICY)
    assert report.declined[0]["reason"] == "no user surface"
    assert "accessibility" not in [r["gate"] for r in report.unexamined]


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_declined_gate_is_distinguishable_from_one_nobody_looked_at():
    # The story exists for this line. Both gates are unsatisfied; only one was
    # decided, and a report that cannot tell them apart is the defect.
    record, _ = resolve(vb.EMPTY_RECORD, {"gates": {
        "accessibility": {"outcome": "declined", "reason": "no user surface"}}})
    report = vb.report_gates(record, GATES, POLICY)
    assert [r["gate"] for r in report.declined] == ["accessibility"]
    assert "security_review" in [r["gate"] for r in report.unexamined]


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_declined_gate_with_no_reason_is_refused():
    # A decline with no reason is silence wearing a word.
    record, problems = resolve(vb.EMPTY_RECORD, {"gates": {
        "accessibility": {"outcome": "declined", "reason": ""}}})
    assert problems
    assert record["gates"] == {}


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_gate_the_owner_wants_becomes_a_pending_filing_and_stays_unexamined():
    record, problems = resolve(vb.EMPTY_RECORD, {"pending_filings": {
        "performance_tests": {"title": "Add a performance gate",
                              "body": FILING_BODY}}})
    assert problems == []
    report = vb.report_gates(record, GATES, POLICY)
    row = [r for r in report.unexamined if r["gate"] == "performance_tests"][0]
    assert row["pending_filing"] == "Add a performance gate"
    assert report.filed == []


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_proposed_filing_that_could_not_be_created_is_refused():
    # Approving a batch containing an item capture would refuse moves the
    # refusal to after the person decided.
    record, problems = resolve(vb.EMPTY_RECORD, {"pending_filings": {
        "performance_tests": {"title": "Add a performance gate",
                              "body": "## Scope\n\nonly this"}}})
    assert problems and "Acceptance criteria" in problems[0]
    assert record["pending_filings"] == {}


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_filed_gate_names_its_backlog_item():
    record, problems = resolve(vb.EMPTY_RECORD, {"gates": {
        "end_to_end_tests": {"outcome": "filed", "item": 171}}})
    assert problems == []
    assert vb.report_gates(record, GATES, POLICY).filed[0]["item"] == 171


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_filed_gate_leaves_the_project_unsettled():
    # The issue's own words: the gate is recorded unresolved pending that item.
    # Filing sixteen items and delivering none is not a resolved project.
    record, _ = resolve(vb.EMPTY_RECORD, {"gates": {
        name: {"outcome": "declined", "reason": "no"} for name in GATES}})
    assert vb.report_gates(record, GATES, POLICY).settled
    record, _ = resolve(record, {"gates": {
        "end_to_end_tests": {"outcome": "filed", "item": 171}}})
    report = vb.report_gates(record, GATES, POLICY)
    assert report.every_gate_answered
    assert not report.settled


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_filed_gate_naming_no_item_is_refused():
    record, problems = resolve(vb.EMPTY_RECORD, {"gates": {
        "end_to_end_tests": {"outcome": "filed", "item": None}}})
    assert problems
    assert record["gates"] == {}


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_recording_a_filing_clears_its_pending_entry():
    # A gate both pending and recorded is two answers to one question.
    record, _ = resolve(vb.EMPTY_RECORD, {"pending_filings": {
        "performance_tests": {"title": "Add one", "body": FILING_BODY}}})
    record, problems = resolve(record, {"gates": {
        "performance_tests": {"outcome": "filed", "item": 200}}})
    assert problems == []
    assert record["pending_filings"] == {}
    assert record["gates"]["performance_tests"]["item"] == 200


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_every_declared_gate_appears_in_the_report():
    # Derived from quality-gates.yml, not listed here: a gate added to policy
    # and forgotten by the report is the absence this record exists to end.
    report = vb.report_gates(vb.EMPTY_RECORD, GATES, POLICY)
    seen = {r["gate"] for bucket in ("resolved", "declined", "filed",
                                     "unexamined")
            for r in getattr(report, bucket)}
    assert seen == set(GATES)


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_conditional_gates_outcome_carries_the_condition_it_applies_under():
    report = vb.report_gates(vb.EMPTY_RECORD, GATES, POLICY)
    rows = {r["gate"]: r for r in report.unexamined}
    assert rows["end_to_end_tests"]["applies_when"] == [
        "critical_user_journey_changed"]
    assert "applies_when" not in rows["secret_detection"]


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_an_outcome_for_an_undeclared_gate_is_refused():
    record, problems = resolve(vb.EMPTY_RECORD, {"gates": {
        "gate_nobody_declared": {"outcome": "resolved", "command": "true"}}})
    assert problems
    assert record["gates"] == {}


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_an_outcome_outside_the_three_words_is_refused():
    record, problems = resolve(vb.EMPTY_RECORD, {"gates": {
        "secret_detection": {"outcome": "skipped", "command": "true"}}})
    assert problems
    assert record["gates"] == {}


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_refused_entry_writes_no_part_of_the_record(tmp_path, monkeypatch):
    # All or nothing. A half-applied merge leaves the record asserting
    # something nobody decided, and the next run reads it as decided.
    path = resolution(tmp_path, {"gates": {
        "secret_detection": {"outcome": "resolved", "command": "gitleaks"},
        "accessibility": {"outcome": "declined", "reason": ""}}})
    run(monkeypatch, "--path", str(tmp_path), "--resolve", str(path), "--write")
    assert not vb.record_path(tmp_path, POLICY).exists()


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_resolution_writes_nothing_without_write(tmp_path, monkeypatch):
    path = resolution(tmp_path, {"gates": {
        "secret_detection": {"outcome": "resolved", "command": "gitleaks"}}})
    run(monkeypatch, "--path", str(tmp_path), "--resolve", str(path))
    assert not vb.record_path(tmp_path, POLICY).exists()


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_the_record_survives_a_second_merge_and_keeps_earlier_outcomes(
        tmp_path, monkeypatch):
    # Resumability. A refused `capture` leaves the record on disk, and the next
    # run has to keep every outcome already established.
    first = resolution(tmp_path, {"gates": {
        "secret_detection": {"outcome": "resolved", "command": "gitleaks"}}})
    run(monkeypatch, "--path", str(tmp_path), "--resolve", str(first), "--write")
    second = tmp_path / "second.yml"
    second.write_text(vb.yaml.safe_dump({"gates": {
        "accessibility": {"outcome": "declined", "reason": "no surface"}}}),
        encoding="utf-8")
    run(monkeypatch, "--path", str(tmp_path), "--resolve", str(second),
        "--write")
    record = vb.load_record(tmp_path, POLICY)
    assert record["gates"]["secret_detection"]["command"] == "gitleaks"
    assert record["gates"]["accessibility"]["reason"] == "no surface"


@pytest.mark.req("REQ-CORE-GATERES-001")
def test_a_gate_with_no_outcome_keeps_the_command_from_passing(
        tmp_path, monkeypatch):
    # Decision 5, enforced where it can be: a record with a gate missing is
    # impossible to pass, rather than impossible to hold.
    (tmp_path / "devbox.json").write_text(json.dumps({"shell": {"scripts": {
        "verify": ["pytest"], "release-verify": ["pytest"]}}}),
        encoding="utf-8")
    settled = {name: {"outcome": "declined", "reason": "not for this project"}
               for name in GATES}
    one_short = dict(settled)
    one_short.pop("secret_detection")

    path = resolution(tmp_path, {"gates": one_short})
    assert run(monkeypatch, "--path", str(tmp_path), "--resolve", str(path),
               "--write") == 1

    path = resolution(tmp_path, {"gates": settled})
    assert run(monkeypatch, "--path", str(tmp_path), "--resolve", str(path),
               "--write") == 0


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


# --- an approval that performs nothing, and a report nobody has to read -------
#
# `approve-verification-resolution` promised that approving decided how the
# missing commands "are resolved", and no step consumes its verdict: not a scan
# run, not a targeted one. The run then reached `completed` while its own
# validation report named the commands as an outstanding blocker.
#
# Two properties follow, and neither is the blanket "every gate's verdict is
# consumed by a later step" the issue first proposed. That one fires on
# `adoption_verdict` and `discovery_verdict`, where approve legitimately means
# proceed and `on_reject: abort` is the whole consumption.

#: Phrases by which a gate message tells the reader that approving *applies*
#: something, rather than that it lets the run proceed. A message using one of
#: these is making a promise a later step has to keep.
APPLICATION_PHRASES = (
    "are resolved", "is resolved", "are applied", "is applied",
    "applies the", "will be applied", "will apply",
)

#: The last step of each bootstrap workflow, and the report it shows.
FINAL_GATE = {
    "lifecycle-brownfield-adoption":
        ("accept-the-adoption-report", "brownfield-adoption-report.md"),
    "lifecycle-greenfield-bootstrap":
        ("accept-the-bootstrap-report", "greenfield-bootstrap-report.md"),
}


def all_gates(steps):
    for step in steps:
        if step.get("type") == "gate":
            yield step
        for case in (step.get("cases") or {}).values():
            yield from all_gates(case)


@pytest.mark.req("REQ-WORKFLOW-VERDICT-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_a_gate_promising_application_has_a_step_reading_its_verdict(name):
    source = (ROOT / f"bundle/components/workflows/{name}/workflow.yml").read_text(
        encoding="utf-8")
    for gate in all_gates(WORKFLOWS[name]["steps"]):
        message = str(gate.get("message", "")).lower()
        promised = [p for p in APPLICATION_PHRASES if p in message]
        if not promised:
            continue
        verdict = gate.get("verdict_input")
        assert f"inputs.{verdict}" in source, (
            f"{name}:{gate['id']} says approving {promised[0]!r}, but no step "
            f"reads inputs.{verdict}, so approving performs nothing")


@pytest.mark.wording
@pytest.mark.req("REQ-WORKFLOW-VERDICT-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_resolution_gate_says_approving_applies_nothing(name):
    gate = [s for s in WORKFLOWS[name]["steps"]
            if s["id"] == "approve-verification-resolution"][0]
    assert "applies nothing" in gate["message"]


@pytest.mark.req("REQ-WORKFLOW-VERDICT-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_run_cannot_reach_its_end_without_a_verdict_on_the_report(name):
    # The engine marks a run `completed` whenever no step raised, so a prompt
    # step writing a blocker into its report cannot stop it. A gate can: it is
    # the last step, so the run reaches its end only through an approve.
    gate_id, report = FINAL_GATE[name]
    steps = WORKFLOWS[name]["steps"]
    assert [s["id"] for s in steps][-1] == gate_id, "the gate is not the last step"
    gate = steps[-1]
    assert gate["type"] == "gate"
    assert gate["on_reject"] == "abort"
    assert gate["show_file"].endswith(report), gate["show_file"]


@pytest.mark.req("REQ-WORKFLOW-VERDICT-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_final_gate_shows_the_report_the_step_before_it_writes(name):
    # A gate over a stale or absent file would be a rubber stamp.
    gate_id, report = FINAL_GATE[name]
    steps = WORKFLOWS[name]["steps"]
    writer = steps[-2]
    assert writer["type"] == "prompt"
    assert report in writer["prompt"], f"{writer['id']} does not write {report}"
    assert "Unresolved blockers" in writer["prompt"], (
        f"{writer['id']} does not tell the report to record its blockers, so "
        f"the gate has nothing to read")


@pytest.mark.req("REQ-WORKFLOW-VERDICT-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_final_gates_verdict_is_a_declared_input_that_starts_unanswered(name):
    gate = WORKFLOWS[name]["steps"][-1]
    spec = WORKFLOWS[name]["inputs"][gate["verdict_input"]]
    assert spec["default"] == ""
    assert "" in spec["enum"], "the gate would default to a verdict nobody gave"
