"""The pilot record contract, offline.

A pilot report that looks complete because its hard fields defaulted is worse
than one that is visibly incomplete: the first ends the phase, the second
prompts someone to finish it. These tests concentrate on that refusal.
"""
from __future__ import annotations

import importlib.util
import sys

import pytest
import yaml

from lib.inventory import ROOT

PILOTS = ROOT / "tooling/pilots"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pr = _load("pilot_record", PILOTS / "pilot_record.py")
CONTRACT = pr.load_contract()


def filled(**over):
    record = {
        "stream": "monorepo", "owner": "someone", "target": "/tmp/x",
        "started": "2026-08-24T14:00", "finished": "2026-08-24T15:00",
        "metrics": {m["id"]: {"value": 0, "why": "none occurred"}
                    for m in CONTRACT["metrics"]},
        "failures": [],
    }
    record.update(over)
    return record


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_a_complete_record_passes():
    assert pr.check(filled(), CONTRACT) == []


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_no_failures_is_an_explicit_claim_not_an_omission():
    # `[]` is the record shape this asks for. A falsy check would reject it.
    assert pr.check(filled(failures=[]), CONTRACT) == []
    record = filled()
    del record["failures"]
    assert any("failures" in p for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
@pytest.mark.parametrize("metric", [m["id"] for m in CONTRACT["metrics"]
                                    if m["source"] in ("operator", "human")])
def test_an_operator_or_human_metric_cannot_be_null(metric):
    # Nobody can reconstruct it afterwards, so a null is a gap in the pilot
    # rather than a gap in the data.
    record = filled()
    record["metrics"][metric] = {"value": None, "why": "forgot"}
    problems = pr.check(record, CONTRACT)
    assert any(metric in p and "recorded" in p for p in problems)


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_an_observed_metric_may_be_null_with_a_reason():
    observed = next(m["id"] for m in CONTRACT["metrics"]
                    if m["source"] == "observed")
    record = filled()
    record["metrics"][observed] = {"value": None, "why": "no audit file written"}
    assert pr.check(record, CONTRACT) == []


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_a_null_with_no_reason_is_refused():
    observed = next(m["id"] for m in CONTRACT["metrics"]
                    if m["source"] == "observed")
    record = filled()
    record["metrics"][observed] = {"value": None, "why": ""}
    assert any("not measured and zero are different" in p.lower()
               for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_a_missing_metric_is_not_read_as_zero():
    record = filled()
    del record["metrics"]["human_interventions"]
    assert any("Absent is not zero" in p for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_an_invented_metric_is_refused():
    record = filled()
    record["metrics"]["vibes"] = {"value": 5}
    assert any("vibes" in p for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_the_owner_is_required_because_the_gate_asks_for_one():
    assert any("owner" in p for p in pr.check(filled(owner=""), CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_a_failure_must_name_the_item_tracking_it():
    record = filled(failures=[{"what": "something broke"}])
    assert any("tracked_by" in p for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_the_shipped_template_does_not_pass_as_written():
    # A template that validated clean would let a pilot be signed off without
    # anybody filling it in.
    template = yaml.safe_load((PILOTS / "template.yml").read_text(encoding="utf-8"))
    assert pr.check(template, CONTRACT), "the blank template validates clean"


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_every_roadmap_metric_is_declared():
    # Phase 10 names twelve; the contract adds nothing silently and drops
    # nothing silently.
    ids = {m["id"] for m in CONTRACT["metrics"]}
    assert len(ids) == len(CONTRACT["metrics"]), "duplicate metric id"
    assert {m["source"] for m in CONTRACT["metrics"]} <= {
        "observed", "operator", "human"}
    assert set(CONTRACT["sources"]) == {"observed", "operator", "human"}


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_an_agent_may_not_supply_a_human_metric():
    # Categorically different from the rest: a judgement about the experience
    # of doing the work. An agent reporting one invents a reading nobody had.
    human = [m["id"] for m in CONTRACT["metrics"] if m["source"] == "human"]
    assert human == ["developer_satisfaction"], human
    record = filled()
    record["metrics"]["developer_satisfaction"] = {
        "value": 4, "why": "went fine", "recorded_by": "agent"}
    assert any("needs a person" in p for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_an_operator_metric_may_be_recorded_by_an_agent():
    # The distinction the first version got wrong: an agent driving a pilot
    # observes its own interventions and can count them.
    record = filled()
    record["metrics"]["human_interventions"] = {
        "value": 2, "why": "re-ran twice", "recorded_by": "agent"}
    assert pr.check(record, CONTRACT) == []


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_not_applicable_is_a_third_state():
    # Distinct from a value and from null. A bootstrap pilot stops before
    # anything reaches Ready, so readiness accuracy has nothing to be right
    # or wrong about. Found by using this contract on the first pilot.
    record = filled()
    record["metrics"]["readiness_accuracy"] = {
        "value": "not_applicable", "why": "bootstrap stops before Ready"}
    assert pr.check(record, CONTRACT) == []


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_not_applicable_still_needs_a_reason():
    record = filled()
    record["metrics"]["readiness_accuracy"] = {"value": "not_applicable"}
    assert any("not_applicable with no reason" in p
               for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_not_applicable_does_not_excuse_a_human_metric_silently():
    # It is still a claim someone made, and it still needs the reason.
    record = filled()
    record["metrics"]["developer_satisfaction"] = {
        "value": "not_applicable", "why": "no person drove this run"}
    assert pr.check(record, CONTRACT) == []


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_the_greenfield_pilot_record_is_complete_but_for_the_human_metric():
    # The shipped record is real evidence, not a fixture. It should be
    # complete except for the one value an agent may not supply.
    import yaml
    record = yaml.safe_load(
        (ROOT / "docs/evidence/pilot-greenfield.md").read_text(encoding="utf-8"))
    problems = pr.check(record, CONTRACT)
    assert len(problems) == 1, problems
    assert "developer_satisfaction" in problems[0]
