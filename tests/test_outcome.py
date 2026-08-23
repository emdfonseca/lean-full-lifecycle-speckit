"""What a measurement means, and what it does not.

Outcome Status had five values and no defined evidence, so validating one meant
asserting it. These tests hold the four judgements in outcome-policy.yml, each
of which exists because the opposite is tempting.
"""
from __future__ import annotations

import importlib.util
import sys

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
spec = importlib.util.spec_from_file_location("outcome", SCRIPTS / "outcome.py")
oc = importlib.util.module_from_spec(spec)
sys.modules["outcome"] = oc
spec.loader.exec_module(oc)

SCHEMA = oc.load_schema(ROOT)
POLICY = oc.load_policy(ROOT)


def record(**over):
    base = {
        "hypothesis": "faster review shortens delivery",
        "owner": "product", "baseline": "6 days", "target": "4 days",
        "guardrails": ["review quality"], "data_source": "analytics/cycle-time",
        "observation_window": "4 weeks", "decision_date": "2026-09-20",
        "result": "met", "decision": "pending",
        "sample_size": 120, "minimum_sample": 50, "window_elapsed": True,
        "guardrail_results": [{"name": "review quality", "held": True,
                               "measured": "unchanged"}],
        "measured_value": "3.8 days",
    }
    base.update(over)
    return base


def assess(rec, readable=True):
    return oc.assess(rec, SCHEMA, POLICY, data_source_readable=readable)


# --- completeness -------------------------------------------------------------

@pytest.mark.req("REQ-STATE-OUTCOME-002")
@pytest.mark.parametrize("missing", ["hypothesis", "guardrail_results",
                                     "window_elapsed", "data_source"])
def test_an_incomplete_record_cannot_be_judged(missing):
    incomplete = {k: v for k, v in record().items() if k != missing}
    result = assess(incomplete)
    assert result.blocking
    assert result.recommended_status is None


# --- the four judgements ------------------------------------------------------

@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_a_regressed_guardrail_defeats_a_met_target():
    rec = record(guardrail_results=[{"name": "review quality", "held": False,
                                     "measured": "defect escape up 30%"}])
    result = assess(rec)
    assert result.recommended_status == oc.MISSED
    assert "review quality" in " ".join(result.reasons)
    # Both facts reported: the target was met, and it does not change it.
    assert any("target was met" in r for r in result.reasons)


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_an_unelapsed_window_leaves_it_measuring():
    result = assess(record(window_elapsed=False))
    assert result.recommended_status == oc.MEASURING
    assert "not failure" in " ".join(result.reasons)


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_an_undersized_sample_leaves_it_measuring():
    result = assess(record(sample_size=12))
    assert result.recommended_status == oc.MEASURING
    assert result.recommended_status != oc.MISSED


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_an_unreadable_data_source_blocks_rather_than_concludes():
    result = assess(record(), readable=False)
    assert result.blocking and result.recommended_status is None
    assert "not evidence of absence" in " ".join(result.blocking)


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_evidence_sufficiency_is_checked_before_the_target():
    # A result computed from too little data is not a result, however good.
    result = assess(record(window_elapsed=False, result="met"))
    assert result.recommended_status == oc.MEASURING


def test_a_met_target_with_guardrails_intact_is_recommended_for_validation():
    result = assess(record())
    assert result.recommended_status == oc.VALIDATED


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_a_missed_target_with_sufficient_evidence_is_missed():
    result = assess(record(result="not_met"))
    assert result.recommended_status == oc.MISSED
    assert result.finding == oc.FINDING_NOT_MET


# --- authority ----------------------------------------------------------------

@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_validation_without_a_named_authority_is_refused():
    problems = oc.check_authority(record(), oc.VALIDATED, POLICY)
    assert problems and "never decide" in problems[0]


def test_validation_with_an_authority_is_permitted():
    assert oc.check_authority(record(validated_by="product_owner"),
                              oc.VALIDATED, POLICY) == []


def test_a_missed_outcome_needs_no_authority_to_report():
    # Only Validated is gated: refusing to report a miss would hide it.
    assert oc.check_authority(record(), oc.MISSED, POLICY) == []


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_the_output_states_that_it_is_only_a_recommendation():
    payload = assess(record()).to_dict()
    assert payload["is_recommendation_only"] is True
    assert payload["validation_requires_authority"] is True


# --- policy is the source -----------------------------------------------------

@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_the_required_fields_come_from_policy():
    policy = load_yaml(ROOT / "policy/outcome-policy.yml")
    for name in policy["required"]:
        assert name in SCHEMA["required"], name


def test_the_authorities_come_from_policy():
    policy = load_yaml(ROOT / "policy/outcome-policy.yml")
    source = (SCRIPTS / "outcome.py").read_text(encoding="utf-8")
    for authority in policy["validation_authority"]:
        assert f'"{authority}"' not in source, (
            f"{authority!r} is hardcoded; changing policy would not change the "
            "script")


# --- a missed target and an open question are different findings --------------

@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_an_inconclusive_result_is_not_reported_as_missed():
    # They share one Outcome Status -- the board field is named for both -- so
    # the finding and the reason are what preserve the difference.
    result = assess(record(result="inconclusive"))
    assert result.recommended_status == oc.MISSED
    assert result.finding == oc.FINDING_INCONCLUSIVE
    assert "did not settle the question" in " ".join(result.reasons)
    assert "not a missed target" in " ".join(result.reasons)


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_a_missed_target_says_the_evidence_supports_it():
    result = assess(record(result="not_met"))
    assert "sufficient evidence to say so" in " ".join(result.reasons)
    assert "still open" not in " ".join(result.reasons)


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_a_record_with_nothing_measured_never_reaches_a_finding():
    # Caught by the schema rather than by the branch: a record with no
    # measured value is incomplete, not inconclusive, and the two refusals
    # should not be confused.
    rec = {k: v for k, v in record(result="not_met").items()
           if k != "measured_value"}
    result = assess(rec)
    assert result.finding is None
    assert "measured_value" in result.blocking[0]


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_an_unrecognised_result_is_refused_rather_than_guessed():
    # The old free-text form. Guessing which reading it meant is how an open
    # question becomes a verdict.
    result = assess(record(result="not met"))
    assert result.blocking
    assert result.recommended_status is None
    assert "not one of" in result.blocking[0]


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_the_result_vocabulary_comes_from_policy():
    assert set(POLICY["assessment"]["result_values"]) == {
        "met", "not_met", "inconclusive"}
    assert SCHEMA["properties"]["result"]["enum"] == [
        "inconclusive", "met", "not_met"]


@pytest.mark.req("REQ-STATE-OUTCOME-002")
def test_a_validated_outcome_carries_the_met_finding():
    assert assess(record()).finding == oc.FINDING_MET
