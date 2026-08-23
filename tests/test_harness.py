"""Running a workflow, rather than reading it.

Every workflow test before this asserted a step existed or a prompt contained a
sentence. The P12 coverage map refuted claim after claim with one line: delete
that clause and the test still passes. These tests walk the steps.
"""
from __future__ import annotations

import json

import pytest

import harness
from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
REFINE = "lifecycle-refine"


def gates(workflow_id: str, verdict: str = harness.APPROVE) -> dict:
    workflow = harness.load(workflow_id)

    def collect(steps):
        out = {}
        for step in steps:
            if step.get("type") == "gate":
                out[step["id"]] = verdict
            for case in (step.get("cases") or {}).values():
                out.update(collect(case))
        return out

    return collect(workflow["steps"])


def ready_verdict(tmp_path):
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps({
        "readiness": "ready", "blocking_questions": [], "risk": "low",
        "spec_impact": "none", "material_uncertainty": "none",
        "next_engineering_action": "Write the failing test first."}),
        encoding="utf-8")
    return path


# --- AC1: a workflow runs end to end, with no model --------------------------

@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_a_workflow_runs_end_to_end(): 
    run = harness.run(REFINE, inputs={"issue_ref": "#142"},
                      verdicts=gates(REFINE))
    assert run.completed
    assert run.step_ids == [s["id"] for s in harness.load(REFINE)["steps"]]


@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_steps_are_visited_in_order():
    run = harness.run(REFINE, inputs={"issue_ref": "#142"},
                      verdicts=gates(REFINE))
    declared = [s["id"] for s in harness.load(REFINE)["steps"]]
    assert run.step_ids == declared


@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_a_switch_descends_into_the_case_its_input_selects():
    run = harness.run("lifecycle-outcome-review",
                      inputs={"issue_ref": "#1", "record_path": "r.md",
                              "assessed_status": "measuring"},
                      verdicts=gates("lifecycle-outcome-review"))
    assert "measuring-state-the-gap" in run.step_ids
    assert "validated-name-the-authority" not in run.step_ids


@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_an_input_outside_its_enum_is_refused():
    with pytest.raises(harness.WorkflowError):
        harness.run("lifecycle-outcome-review",
                    inputs={"issue_ref": "#1", "record_path": "r.md",
                            "assessed_status": "nonsense"},
                    verdicts={})


# --- AC2: a rejected gate stops the run --------------------------------------

@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_a_rejected_gate_aborts_the_run():
    verdicts = gates(REFINE)
    first_gate = next(s["id"] for s in harness.load(REFINE)["steps"]
                      if s.get("type") == "gate")
    verdicts[first_gate] = harness.REJECT

    run = harness.run(REFINE, inputs={"issue_ref": "#142"}, verdicts=verdicts)
    assert not run.completed
    assert run.aborted_at == first_gate


@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_no_step_after_a_rejected_gate_executes():
    verdicts = gates(REFINE)
    declared = [s["id"] for s in harness.load(REFINE)["steps"]]
    first_gate = next(s["id"] for s in harness.load(REFINE)["steps"]
                      if s.get("type") == "gate")
    verdicts[first_gate] = harness.REJECT

    run = harness.run(REFINE, inputs={"issue_ref": "#142"}, verdicts=verdicts)
    after = declared[declared.index(first_gate) + 1:]
    assert not set(after) & set(run.step_ids), run.step_ids


@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_an_unscripted_gate_is_not_an_approval():
    # Defaulting to approve would make every gate invisible to the test that
    # forgot it, which is the failure this whole harness exists to stop.
    with pytest.raises(harness.WorkflowError) as exc:
        harness.run(REFINE, inputs={"issue_ref": "#142"}, verdicts={})
    assert "no verdict was scripted" in str(exc.value)


# --- AC3: command steps really execute ---------------------------------------

@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_a_command_step_runs_the_real_script(tmp_path):
    run = harness.run(
        REFINE, inputs={"issue_ref": "#142"}, verdicts=gates(REFINE),
        invocations={"speckit.github-lifecycle.readiness": [
            str(SCRIPTS / "readiness.py"), "--verdict",
            str(ready_verdict(tmp_path))]})
    assert run.completed
    assert "validate-readiness" in run.executed()
    assert "Verdict is valid" in run.asked_for("validate-readiness")


@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_a_refusing_command_stops_the_run(tmp_path):
    bad = tmp_path / "verdict.json"
    bad.write_text(json.dumps({"readiness": "ready"}), encoding="utf-8")

    run = harness.run(
        REFINE, inputs={"issue_ref": "#142"}, verdicts=gates(REFINE),
        invocations={"speckit.github-lifecycle.readiness": [
            str(SCRIPTS / "readiness.py"), "--verdict", str(bad)]})
    assert not run.completed
    assert run.aborted_at == "validate-readiness"
    assert "refused" in run.reason


@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_a_command_with_no_invocation_is_recorded_not_invented():
    # The args are prose for an agent. A harness that derived a command line
    # from them would be manufacturing the confidence the coverage map exposed.
    run = harness.run(REFINE, inputs={"issue_ref": "#142"},
                      verdicts=gates(REFINE))
    assert "validate-readiness" in run.recorded()
    assert "validate-readiness" not in run.executed()


# --- AC4: prompts are recorded, not simulated --------------------------------

@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_a_prompt_step_records_what_it_asked_for():
    run = harness.run(REFINE, inputs={"issue_ref": "#142"},
                      verdicts=gates(REFINE))
    asked = run.asked_for("assess-readiness")
    assert asked
    assert "#142" in asked, "the input should have been substituted"


@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_no_prompt_step_is_ever_reported_as_executed():
    run = harness.run(REFINE, inputs={"issue_ref": "#142"},
                      verdicts=gates(REFINE))
    prompts = [s["id"] for s in harness.load(REFINE)["steps"]
               if s.get("type") == "prompt"]
    assert prompts
    assert not set(prompts) & set(run.executed())


# --- AC5: a workflow that changed shape fails the run ------------------------

@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_an_expected_step_that_no_longer_exists_fails_the_run():
    with pytest.raises(harness.WorkflowError) as exc:
        harness.run(REFINE, inputs={"issue_ref": "#142"},
                    verdicts=gates(REFINE),
                    expect_steps=["assess-readiness", "step-that-was-renamed"])
    assert "step-that-was-renamed" in str(exc.value)


@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_expected_steps_that_exist_do_not_fail_the_run():
    run = harness.run(REFINE, inputs={"issue_ref": "#142"},
                      verdicts=gates(REFINE),
                      expect_steps=["assess-readiness", "transition-ready"])
    assert run.completed


@pytest.mark.req("REQ-TOOLING-HARNESS-001")
def test_a_step_inside_a_switch_case_counts_as_present():
    run = harness.run("lifecycle-outcome-review",
                      inputs={"issue_ref": "#1", "record_path": "r.md",
                              "assessed_status": "missed"},
                      verdicts=gates("lifecycle-outcome-review"),
                      expect_steps=["capture-the-finding"])
    assert run.completed


# --- every shipped workflow can be walked ------------------------------------

@pytest.mark.req("REQ-TOOLING-HARNESS-001")
@pytest.mark.parametrize("workflow_id", sorted(
    p.parent.name for p in (ROOT / "bundle/components/workflows").rglob("workflow.yml")))
def test_every_workflow_walks_without_a_model(workflow_id):
    # Not an assertion about correctness: an assertion that each one is
    # runnable at all, which nothing established before.
    workflow = harness.load(workflow_id)
    required = {name: f"<{name}>"
                for name, spec in (workflow.get("inputs") or {}).items()
                if (spec or {}).get("required")}
    run = harness.run(workflow_id, inputs=required,
                      verdicts=gates(workflow_id))
    assert run.step_ids
