"""The pilot record contract, offline.

A pilot report that looks complete because its hard fields defaulted is worse
than one that is visibly incomplete: the first ends the phase, the second
prompts someone to finish it. These tests concentrate on that refusal.

Every entry answers with a verdict and the evidence behind it. The verdict is
the part that invites a shrug; the evidence is what stops it.
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
        "metrics": {m["id"]: {"verdict": "observed", "evidence": "nothing occurred"}
                    for m in CONTRACT["metrics"]},
        "failures": [],
    }
    for m in CONTRACT["metrics"]:
        allowed = m.get("verdicts")
        if allowed:
            record["metrics"][m["id"]]["verdict"] = allowed[0]
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
@pytest.mark.parametrize("metric", [m["id"] for m in CONTRACT["metrics"]])
def test_a_verdict_without_evidence_is_refused(metric):
    # The whole point. `held` on its own says a property held; it does not say
    # how anyone knows, and three streams once reported `0` three different
    # ad-hoc ways.
    record = filled()
    record["metrics"][metric]["evidence"] = ""
    assert any(metric in p and "evidence" in p
               for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
@pytest.mark.parametrize("metric", [m["id"] for m in CONTRACT["metrics"]])
def test_unrecorded_is_always_refused(metric):
    # It is what the template ships with, so a record nobody filled in cannot
    # be signed off.
    record = filled()
    record["metrics"][metric] = {"verdict": "unrecorded", "evidence": "n/a"}
    assert any(metric in p and "unrecorded" in p
               for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_unmeasured_is_distinct_from_not_applicable_and_from_unrecorded():
    # The three the old schema conflated as `null`. model_cost read null with
    # "not instrumented in this run" in every record: a gap in the framework
    # recorded as a gap in the pilot.
    assert {"unmeasured", "not_applicable", "unrecorded"} <= set(CONTRACT["verdicts"])
    for verdict in ("unmeasured", "not_applicable"):
        record = filled()
        record["metrics"]["model_cost"] = {
            "verdict": verdict, "evidence": "no instrument exists"}
        assert pr.check(record, CONTRACT) == [], verdict


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_a_verdict_outside_the_vocabulary_is_refused():
    record = filled()
    record["metrics"]["model_cost"] = {"verdict": "fine", "evidence": "seemed ok"}
    assert any("does not declare" in p for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_a_quantity_is_not_a_verdict():
    # The shape this replaces. A number in the verdict field records nothing
    # and reads as though it recorded something.
    record = filled()
    record["metrics"]["human_interventions"] = {"verdict": 7, "evidence": "seven"}
    assert any("human_interventions" in p for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
@pytest.mark.parametrize("metric", [m["id"] for m in CONTRACT["metrics"]
                                    if m.get("verdicts")])
def test_a_declared_binary_cannot_be_answered_with_a_shrug(metric):
    # Whether anything was written outside scope, and whether any GitHub
    # operation failed. These the run either upheld or did not.
    record = filled()
    record["metrics"][metric] = {"verdict": "observed", "evidence": "some stuff"}
    assert any(metric in p and "judgement" in p
               for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_a_missing_metric_is_not_read_as_an_answer():
    record = filled()
    del record["metrics"]["human_interventions"]
    assert any("Absent is not a verdict" in p for p in pr.check(record, CONTRACT))


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_an_invented_metric_is_refused():
    record = filled()
    record["metrics"]["vibes"] = {"verdict": "held", "evidence": "felt good"}
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
def test_the_contract_declares_its_vocabulary_and_its_sources():
    ids = {m["id"] for m in CONTRACT["metrics"]}
    assert len(ids) == len(CONTRACT["metrics"]), "duplicate metric id"
    assert {m["source"] for m in CONTRACT["metrics"]} <= {"observed", "operator"}
    assert set(CONTRACT["sources"]) == {"observed", "operator"}
    # Every restriction a metric declares must name verdicts the vocabulary has.
    for m in CONTRACT["metrics"]:
        assert set(m.get("verdicts") or []) <= set(CONTRACT["verdicts"]), m["id"]


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_no_entry_asks_for_a_self_rated_score():
    # developer_satisfaction gated nothing, was not comparable across streams,
    # and nobody acted on it. The 0.9.0 gate gets its human accountability from
    # `owner:`, a named person signing off.
    assert "developer_satisfaction" not in {m["id"] for m in CONTRACT["metrics"]}


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_no_source_is_declared_without_a_member():
    # The dead-vocabulary case. `human` existed for one entry; with that entry
    # gone the source guarded nothing, and a declared source no metric uses
    # reads as a capability the contract does not have.
    used = {m["source"] for m in CONTRACT["metrics"]}
    assert set(CONTRACT["sources"]) == used, (
        f"declared but unused: {sorted(set(CONTRACT['sources']) - used)}")


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
def test_an_operator_verdict_may_be_recorded_by_an_agent():
    # An agent driving a pilot watches its own interventions.
    record = filled()
    record["metrics"]["human_interventions"] = {
        "verdict": "observed", "evidence": "re-ran twice", "recorded_by": "agent"}
    assert pr.check(record, CONTRACT) == []


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
@pytest.mark.parametrize("stream", ["greenfield", "brownfield", "monorepo"])
def test_each_written_record_is_complete(stream):
    # Zero problems, not one. The single outstanding verdict in every stream was
    # developer_satisfaction, which no longer exists -- so the records are
    # finished rather than waiting on a value nobody would act on.
    record = yaml.safe_load(
        (ROOT / f"docs/evidence/pilot-{stream}.md").read_text(encoding="utf-8"))
    assert pr.check(record, CONTRACT) == []


@pytest.mark.req("REQ-PILOT-EVIDENCE-001")
@pytest.mark.parametrize("stream", ["greenfield", "brownfield", "monorepo"])
def test_migration_kept_the_prose_that_always_carried_the_meaning(stream):
    # The numbers were dropped; the sentences beside them were the content.
    record = yaml.safe_load(
        (ROOT / f"docs/evidence/pilot-{stream}.md").read_text(encoding="utf-8"))
    for name, entry in record["metrics"].items():
        assert entry.get("evidence", "").strip(), name
        assert "value" not in entry, f"{name} still carries a quantity"
