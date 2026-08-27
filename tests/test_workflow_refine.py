"""The refine workflow's structure, which is what makes its guarantees real.

A workflow is data. What stops it writing without approval is not the prose in
its prompts but the order of its steps, so that order is asserted here.
"""
from __future__ import annotations

import pytest

from lib.inventory import load_yaml, load_inventory

WF = load_inventory().by_id("workflow", "lifecycle-refine")
STEPS = WF.manifest["steps"]
IDS = [s["id"] for s in STEPS]


def index(step_id):
    return IDS.index(step_id)


@pytest.mark.req("REQ-BACKLOG-REFINE-001")
def test_the_workflow_gates_before_every_write():
    writes = {"speckit.github-lifecycle.transition"}
    for i, step in enumerate(STEPS):
        if step.get("command") in writes:
            assert any(s.get("type") == "gate" for s in STEPS[:i]), \
                f"{step['id']} writes with no prior gate"


@pytest.mark.req("REQ-BACKLOG-REFINE-001")
def test_the_transition_applies_a_plan_a_prior_step_wrote():
    plan_step = next(s for s in STEPS
                     if s.get("command") == "speckit.github-lifecycle.plan")
    trans_step = next(s for s in STEPS
                      if s.get("command") == "speckit.github-lifecycle.transition")
    assert index(plan_step["id"]) < index(trans_step["id"])
    written = plan_step["input"]["args"].split("Write exactly")[1].split(".md")[0].strip()
    applied = trans_step["input"]["args"].split("Approved plan:")[1].split(".md")[0].strip()
    assert written == applied, "the transition applies a plan nothing wrote"


@pytest.mark.req("REQ-BACKLOG-REFINE-001")
def test_rejecting_a_gate_aborts_the_run():
    gates = [s for s in STEPS if s.get("type") == "gate"]
    assert gates, "a workflow that writes to the board with no gate writes unapproved"
    for gate in gates:
        assert gate["on_reject"] == "abort"
        assert set(gate["options"]) == {"approve", "reject"}
        assert gate.get("show_file"), f"{gate['id']} asks for approval of nothing visible"


def test_the_verdict_is_validated_before_the_readiness_gate():
    # Approving an unvalidated verdict would make the gate the only check.
    assert index("validate-readiness") < index("approve-readiness")


def test_each_gate_shows_the_artifact_a_prior_step_wrote():
    for gate in (s for s in STEPS if s.get("type") == "gate"):
        shown = gate["show_file"]
        earlier = " ".join(
            str(s.get("prompt", "")) + str((s.get("input") or {}).get("args", ""))
            for s in STEPS[:index(gate["id"])])
        stem = shown.split("}}")[-1].split(".md")[0]
        assert stem in earlier, f"{gate['id']} shows {shown}, which nothing writes"


@pytest.mark.req("REQ-BACKLOG-REFINE-001")
def test_the_workflow_is_registered_by_generation():
    from lib.inventory import ROOT

    bundle = load_yaml(ROOT / "bundle/bundle.yml")
    ids = [w["id"] for w in bundle["provides"]["workflows"]]
    assert "lifecycle-refine" in ids

    import json
    catalog = json.loads((ROOT / "catalogs/workflows.json").read_text(encoding="utf-8"))
    assert "lifecycle-refine" in catalog["workflows"]


def test_the_workflow_reads_before_it_decides():
    assert index("inspect-item") == 0
