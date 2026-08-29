"""Whether the project can run the workflows, asked at bootstrap.

Five workflow steps run `.specify/lifecycle/verify` and one runs
`.specify/lifecycle/release-verify`, and nothing had ever checked the target
project provides them. The roadmap states the requirement as a
user-experience one: do not let the user discover this only after the first
workflow failure.

They used to read `devbox run verify`, and detection parsed `devbox.json` for a
`scripts` key. That named a vendor and asked a question about a manifest rather
than about the project: #104's pilot target has a devbox.json whose every script
shims to pnpm, and its real gate -- `pnpm verify` -- was invisible, so a project
with working verification was reported as having none (#156, #166).
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest
import yaml

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
spec = importlib.util.spec_from_file_location("verify_bootstrap",
                                              SCRIPTS / "verify_bootstrap.py")
vb = importlib.util.module_from_spec(spec)
sys.modules["verify_bootstrap"] = vb
spec.loader.exec_module(vb)

POLICY = vb.load_policy(ROOT)
VERIFY, RELEASE = vb.declared_commands(POLICY)
WORKFLOWS = {
    n: load_yaml(ROOT / f"bundle/components/workflows/{n}/workflow.yml")
    for n in ("lifecycle-greenfield-bootstrap", "lifecycle-brownfield-adoption")
}


def project(tmp_path, entry_points=(), executable=True, stack=None):
    """A project providing the named entry points.

    `executable` is a parameter because present-and-not-runnable is its own
    finding: the workflow step runs the path directly, so a file without the
    bit fails at the shell with a permission error rather than a verification
    failure.
    """
    for command in entry_points:
        path = tmp_path / command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755 if executable else 0o644)
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
def test_both_entry_points_present_is_resolved(tmp_path):
    root = project(tmp_path, [VERIFY, RELEASE])
    report = vb.detect(root, POLICY)
    assert report.present == [VERIFY, RELEASE]
    assert report.missing == []
    assert report.resolved


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_detection_writes_nothing(tmp_path):
    root = project(tmp_path, [VERIFY])
    before = {p.name for p in root.rglob("*")}
    vb.detect(root, POLICY)
    assert {p.name for p in root.rglob("*")} == before


# --- AC2: missing is named, and distinguished from present --------------------

@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_a_partial_project_reports_each_entry_point_separately(tmp_path):
    root = project(tmp_path, [VERIFY])
    report = vb.detect(root, POLICY)
    # The point of the story: not one verdict for both.
    assert report.present == [VERIFY]
    assert report.missing == [RELEASE]


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_neither_entry_point_present_names_both(tmp_path):
    report = vb.detect(project(tmp_path), POLICY)
    assert report.missing == [VERIFY, RELEASE]
    assert report.present == []


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_a_project_that_provides_neither_is_a_finding_not_a_failure(tmp_path):
    # An empty project provides neither. That is a finding, not a failure to
    # look, and there is no manifest whose absence could confuse the two.
    report = vb.detect(tmp_path, POLICY)
    assert report.missing == [VERIFY, RELEASE]
    assert report.problems == []


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_a_present_but_unrunnable_entry_point_resolves_nothing(tmp_path):
    root = project(tmp_path, [VERIFY, RELEASE], executable=False)
    report = vb.detect(root, POLICY)
    assert report.problems
    assert not report.resolved, (
        "a file the step cannot execute reporting nothing missing would read "
        "as success")
    assert report.missing == [], (
        "reporting it missing would send the user to write a file that is "
        "already there")
    assert all("not executable" in p for p in report.problems)


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


# --- AC4: what a workflow may execute, and where that is decided -------------

@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_no_declared_entry_point_names_a_binary():
    # The whole item. A path under .specify/ is something the project fills; a
    # command is something the project must have installed, which is what made
    # five of the fourteen workflows unrunnable without devbox.
    for command in vb.declared_commands(POLICY):
        assert command.startswith(".specify/"), command
        assert " " not in command, (
            f"{command!r} has arguments, so it is a command line rather than a "
            f"path, and something has to supply the program that runs it")


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_the_policy_offers_no_discovery_to_privilege_a_vendor():
    # The failure mode #156 named: adding package.json beside devbox.json
    # reproduces the defect for every project using make, just, or cargo. A
    # longer list of files to sniff is still a list of vendors.
    assert "definition_source" not in POLICY


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_the_shell_surface_is_exactly_the_declared_entry_points():
    # This replaced `allowed_shell` in tooling/invariants.yml, two literals the
    # validator compared each step's run: against. The list is now derived from
    # the policy, so the two cannot disagree -- but every shell step in every
    # shipped workflow must still resolve to one, which is the property the
    # literals were holding.
    declared = set(vb.declared_commands(POLICY))
    seen = set()
    for path in sorted((ROOT / "bundle/components/workflows").glob("*/workflow.yml")):
        for step in load_yaml(path).get("steps") or []:
            if step.get("type") != "shell":
                continue
            run = str(step.get("run", "")).strip()
            assert run in declared, f"{path.parent.name}:{step.get('id')} runs {run!r}"
            seen.add(run)
    assert seen == declared, (
        f"declared but never run: {sorted(declared - seen)}. An entry point no "
        f"workflow runs is one a project is asked to provide for nothing")


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
def test_the_overlay_is_gone_rather_than_carried():
    # #144 established it was inert: `load_overlay` needed a `mappings` list the
    # proposed shape never produced, and Spec Kit's ShellStep runs
    # `config["run"]` verbatim. Keeping an inert mechanism is how it comes back.
    assert "overlay" not in POLICY
    assert not hasattr(vb, "load_overlay")
    assert not hasattr(vb, "check_overlay")
    resolutions = POLICY["resolution"]
    assert not any("overlay" in r for r in resolutions), resolutions


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
    # Two claims, and the second is not "writes nothing". The resolution record
    # is written here, because it is what the gate reads and what the step after
    # it generates from; a gate over a file nobody wrote approves nothing. What
    # must not be written before the gate is an entry point (#192).
    step = [s for s in WORKFLOWS[name]["steps"]
            if s["id"] == "check-verification-commands"][0]
    args = step["input"]["args"]
    assert "Write no entry point here" in args
    assert "Propose, then wait" in args
    assert "separately" in args
    assert "Persist that record" in args


@pytest.mark.req("REQ-CORE-VERIFYCMD-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_gate_says_what_rejecting_costs(name):
    # It used to be "the first delivery will fail", because approving wrote
    # nothing either way and the cost was the same on both sides. Now the two
    # sides differ, so the message has to say what the reject side loses (#192).
    gate = [s for s in WORKFLOWS[name]["steps"]
            if s["id"] == "approve-verification-resolution"][0]
    assert "Rejecting stops the run here and writes neither." in gate["message"]


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
    # Which outcomes leave a gate unresolved is policy, not a literal here.
    assert report.unresolved_outcomes == tuple(
        POLICY["gate_resolution"]["leaves_unresolved"])


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
    project(tmp_path, [VERIFY, RELEASE])
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
# --- generation: the entry points the workflows run ----------------------------
#
# #166 declared the paths and #192 is what writes the files behind them. Until
# it, `resolution: [generate_entry_point_when_stack_decided]` named a resolution
# no step performed, so every bootstrapped project had two entry points named by
# six workflow steps and no file behind either.

SPEC = vb.entry_point_spec(POLICY)
STACK = "# S\n\n## Decision\n\n| Chose | Rejected | Why |\n|---|---|---|\n| py | go | team |\n"


def resolved_project(tmp_path, gates, stack=STACK):
    """A project with a gate-resolution record and, by default, a stack decision."""
    root = project(tmp_path, stack=stack)
    (root / ".specify/lifecycle").mkdir(parents=True, exist_ok=True)
    (root / POLICY["gate_resolution"]["file"]).write_text(
        yaml.safe_dump({"gates": gates, "pending_filings": {}}),
        encoding="utf-8")
    return root


def generate(root):
    record = vb.load_record(root, POLICY)
    report = vb.report_gates(record, GATES, POLICY)
    return vb.generate_entry_points(root, POLICY, report)


THREE = {
    "format_or_style_validation": {"outcome": "resolved", "command": "make fmt"},
    "lint_or_static_analysis": {"outcome": "resolved", "command": "make lint"},
    "secret_detection": {"outcome": "resolved", "command": "make secrets"},
}


@pytest.mark.req("REQ-CORE-VERIFYCMD-003")
def test_a_resolved_project_gets_an_executable_entry_point(tmp_path):
    root = resolved_project(tmp_path, THREE)
    wrote, problems = generate(root)
    assert problems == []
    path = root / VERIFY
    assert path.is_file() and os.access(path, os.X_OK)
    assert VERIFY in wrote


@pytest.mark.req("REQ-CORE-VERIFYCMD-003")
def test_the_lines_run_the_recorded_commands_in_declared_order(tmp_path):
    root = resolved_project(tmp_path, THREE)
    generate(root)
    body = (root / VERIFY).read_text(encoding="utf-8")
    commands = [ln for ln in body.splitlines()
                if ln and not ln.startswith(("#", "set "))]
    # quality-gates.yml order, not the record's: the record is a mapping and
    # the policy is the thing that declares a sequence.
    assert commands == ["make fmt", "make lint", "make secrets"]


@pytest.mark.req("REQ-CORE-VERIFYCMD-003")
def test_every_line_names_the_gate_it_runs(tmp_path):
    # The step reports a failure of the whole set, so the file's comments are
    # the only way back from a failed line to a gate.
    root = resolved_project(tmp_path, THREE)
    generate(root)
    body = (root / VERIFY).read_text(encoding="utf-8")
    for gate in THREE:
        assert f"# {gate}" in body


@pytest.mark.req("REQ-CORE-VERIFYCMD-003")
def test_a_declined_or_filed_gate_contributes_no_line(tmp_path):
    root = resolved_project(tmp_path, dict(
        THREE,
        dependency_hygiene={"outcome": "declined", "reason": "vendored"},
        build_or_package_validation={"outcome": "filed", "item": 7}))
    generate(root)
    body = (root / VERIFY).read_text(encoding="utf-8")
    assert "dependency_hygiene" not in body
    assert "build_or_package_validation" not in body


@pytest.mark.req("REQ-CORE-VERIFYCMD-003")
def test_a_resolved_conditional_gate_carries_its_condition(tmp_path):
    # `when:` is a property of a change and there is none at bootstrap, so the
    # line runs and the condition is a comment rather than a filter.
    root = resolved_project(tmp_path, dict(
        THREE, end_to_end_tests={"outcome": "resolved", "command": "pnpm e2e"}))
    generate(root)
    body = (root / VERIFY).read_text(encoding="utf-8")
    assert "pnpm e2e" in body
    assert "critical_user_journey_changed" in body


@pytest.mark.req("REQ-CORE-VERIFYCMD-003")
def test_both_declared_entry_points_are_written(tmp_path):
    # Generating only `verify` leaves `release-verify` missing, so detect still
    # reports one absent and the run still cannot reach completed.
    root = resolved_project(tmp_path, THREE)
    wrote, _ = generate(root)
    assert sorted(wrote) == sorted([VERIFY, RELEASE])
    assert vb.detect(root, POLICY).resolved


@pytest.mark.req("REQ-CORE-VERIFYCMD-003")
def test_each_file_says_it_shares_the_release_set(tmp_path):
    root = resolved_project(tmp_path, THREE)
    generate(root)
    for command in (VERIFY, RELEASE):
        body = (root / command).read_text(encoding="utf-8")
        assert "release-only" in body, command
        assert command in body.splitlines()[1], command


@pytest.mark.req("REQ-CORE-VERIFYCMD-003")
def test_a_file_with_no_gate_to_run_exits_nonzero(tmp_path):
    # An entry point that exits 0 having run nothing is a green verification
    # step over no gates, which is worse than a missing file: the missing one
    # fails the shell step loudly and this one passes.
    root = resolved_project(tmp_path, {
        "format_or_style_validation": {"outcome": "declined", "reason": "none yet"}})
    wrote, problems = generate(root)
    assert wrote
    body = (root / VERIFY).read_text(encoding="utf-8")
    assert "exit 1" in body
    assert any("verifies nothing" in p for p in problems)


@pytest.mark.req("REQ-CORE-VERIFYCMD-003")
def test_generation_without_a_stack_decision_writes_nothing(tmp_path):
    # The refusal existed and was reachable only from --propose-generation, so
    # it guarded the proposal and not the write.
    root = resolved_project(tmp_path, THREE, stack=None)
    wrote, problems = generate(root)
    assert wrote == []
    assert not (root / VERIFY).exists()
    assert any("no stack decision is recorded" in p for p in problems)


@pytest.mark.req("REQ-CORE-VERIFYCMD-003")
def test_generation_is_idempotent(tmp_path):
    root = resolved_project(tmp_path, THREE)
    generate(root)
    first = (root / VERIFY).read_text(encoding="utf-8")
    generate(root)
    assert (root / VERIFY).read_text(encoding="utf-8") == first


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
def test_the_resolution_gate_says_approving_writes_the_entry_points(name):
    # The inverse of what this asserted until #192, and it is the same
    # requirement: the message must match what the run does. It said "applies
    # nothing" while nothing applied it, and says it writes them now that a
    # step does.
    gate = [s for s in WORKFLOWS[name]["steps"]
            if s["id"] == "approve-verification-resolution"][0]
    assert "applies nothing" not in gate["message"]
    assert "Approving writes" in gate["message"]


@pytest.mark.req("REQ-WORKFLOW-VERDICT-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_gate_that_promises_generation_is_followed_by_the_step_that_does_it(name):
    # The promise and the step that keeps it are in two files, and #144 is what
    # happens when they drift: a gate approving a mechanism nothing performed.
    ids = [s["id"] for s in WORKFLOWS[name]["steps"]]
    i = ids.index("approve-verification-resolution")
    assert ids[i + 1] == "generate-verification-entry-points", ids
    step = WORKFLOWS[name]["steps"][i + 1]
    assert step["command"] == "speckit.github-lifecycle.verify-bootstrap"


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
