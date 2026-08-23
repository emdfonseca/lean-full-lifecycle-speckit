"""Holding each measurable gate to the best it has ever done.

`quality-gates.yml` named sixteen gates and recorded what none of them
measured, so "do not make it worse" had no referent.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from datetime import date

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("exception")
rt = _load("ratchet")

POLICY = rt.load_policy(ROOT)
LINT = "lint_or_static_analysis"
COVER = "deterministic_change_appropriate_tests"
TODAY = date(2026, 8, 23)

BASELINES = {
    LINT: {"value": 41, "recorded_at": "2026-08-01", "produced_by": "b700f30"},
    COVER: {"value": 84.0, "recorded_at": "2026-08-01", "produced_by": "b700f30"},
}

WORKFLOWS = {
    n: load_yaml(ROOT / f"bundle/components/workflows/{n}/workflow.yml")
    for n in ("lifecycle-story-delivery", "lifecycle-bugfix")
}


def valid_exception(**over):
    base = {
        "id": "EX-009", "scope": "src/legacy/parser/**", "policy_rule": LINT,
        "reason": "The parser predates the rule; the grammar work is #77.",
        "owner": "platform-team", "approver": "emdfonseca",
        "created_at": "2026-08-01", "review_or_expiry_at": "2026-12-01",
        "compensating_controls": ["characterization tests"],
        "disposition": "active", "baseline": "41 at b700f30",
    }
    base.update(over)
    return base


# --- AC1: a regression is refused ---------------------------------------------

@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_regression_on_a_lower_is_better_gate_is_refused():
    out = rt.assess(LINT, 48, BASELINES, POLICY, produced_by="c1")
    assert out.verdict == rt.REFUSED
    assert not out.passed


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_regression_on_a_higher_is_better_gate_is_refused():
    # Direction has to be read from policy, or coverage falling reads as a win.
    out = rt.assess(COVER, 79, BASELINES, POLICY, produced_by="c1")
    assert out.verdict == rt.REFUSED


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_the_refusal_names_the_gate_the_baseline_and_the_measurement():
    out = rt.assess(LINT, 48, BASELINES, POLICY, produced_by="c1")
    assert LINT in out.message
    assert "41" in out.message and "48" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_refused_measurement_never_moves_the_baseline():
    out = rt.assess(LINT, 48, BASELINES, POLICY, produced_by="c1")
    assert rt.record(LINT, out, BASELINES, "c1", TODAY) == BASELINES


# --- AC2: an improvement moves the baseline -----------------------------------

@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_improvement_moves_the_baseline():
    out = rt.assess(LINT, 30, BASELINES, POLICY, produced_by="PR #62")
    assert out.verdict == rt.IMPROVED
    updated = rt.record(LINT, out, BASELINES, "PR #62", TODAY)
    assert updated[LINT]["value"] == 30


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_the_moved_baseline_records_what_produced_it():
    out = rt.assess(LINT, 30, BASELINES, POLICY, produced_by="PR #62")
    updated = rt.record(LINT, out, BASELINES, "PR #62", TODAY)
    for name in POLICY["baseline_fields"]:
        assert updated[LINT][name], name
    assert updated[LINT]["produced_by"] == "PR #62"


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_improvement_with_no_provenance_is_refused():
    # A baseline with no provenance cannot be argued with later.
    out = rt.assess(LINT, 30, BASELINES, POLICY, produced_by="")
    assert out.verdict == rt.REFUSED
    assert "what produced it" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_unchanged_measurement_holds():
    out = rt.assess(LINT, 41, BASELINES, POLICY, produced_by="c1")
    assert out.verdict == rt.HELD
    assert out.passed


# --- AC3: loosening requires an approved exception ----------------------------

@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_loosening_without_an_exception_is_refused():
    out = rt.loosen(LINT, 60, BASELINES, POLICY, exception=None)
    assert out.verdict == rt.REFUSED
    assert "only way to loosen" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_loosening_under_an_exception_naming_the_gate_is_permitted():
    out = rt.loosen(LINT, 60, BASELINES, POLICY, exception=valid_exception())
    assert out.verdict != rt.REFUSED
    assert out.new_baseline == 60


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_exception_for_another_gate_does_not_loosen_this_one():
    out = rt.loosen(LINT, 60, BASELINES, POLICY,
                    exception=valid_exception(policy_rule=COVER))
    assert out.verdict == rt.REFUSED
    assert "not " + repr(LINT) in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_invalid_exception_does_not_loosen_anything():
    # Naming the gate is not enough; exception.py still has to accept it.
    out = rt.loosen(LINT, 60, BASELINES, POLICY,
                    exception=valid_exception(owner=""))
    assert out.verdict == rt.REFUSED
    assert "is not valid" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_expired_exception_does_not_loosen_anything():
    out = rt.loosen(LINT, 60, BASELINES, POLICY,
                    exception=valid_exception(review_or_expiry_at="2026-01-01"))
    assert out.verdict == rt.REFUSED


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_tightening_is_not_a_loosening():
    out = rt.loosen(LINT, 20, BASELINES, POLICY, exception=None)
    assert out.verdict != rt.REFUSED


# --- AC4: a first run establishes, and does not pass --------------------------

@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_first_run_establishes_a_baseline():
    out = rt.assess("secret_detection", 0, BASELINES, POLICY, produced_by="c1")
    assert out.verdict == rt.ESTABLISHED
    assert out.new_baseline == 0


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_first_run_does_not_report_a_pass():
    # The baseline it silently recorded was never reviewed, so every later
    # comparison would rest on an unreviewed number.
    out = rt.assess("secret_detection", 0, BASELINES, POLICY, produced_by="c1")
    assert out.passed is False
    assert "not a pass" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_entry_with_no_value_is_treated_as_no_baseline():
    baselines = dict(BASELINES, secret_detection={"recorded_at": "2026-08-01"})
    out = rt.assess("secret_detection", 3, baselines, POLICY, produced_by="c1")
    assert out.verdict == rt.ESTABLISHED


# --- AC5: a gate without a measure cannot ratchet -----------------------------

@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_gate_declared_ratcheted_with_no_measure_is_refused():
    policy = copy.deepcopy(POLICY)
    policy["gates"]["specification_convergence_for_promoted_work"] = {}
    out = rt.assess("specification_convergence_for_promoted_work", 1,
                    BASELINES, policy, produced_by="c1")
    assert out.verdict == rt.REFUSED
    assert "no usable measure" in out.message
    assert "specification_convergence_for_promoted_work" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_gate_with_an_unknown_direction_is_refused():
    policy = copy.deepcopy(POLICY)
    policy["gates"][LINT]["direction"] = "fewer_is_nicer"
    out = rt.assess(LINT, 30, BASELINES, policy, produced_by="c1")
    assert out.verdict == rt.REFUSED


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_refusing_is_not_skipping():
    # A gate that silently opts out of the ratchet is the one that regresses.
    policy = copy.deepcopy(POLICY)
    policy["gates"]["accessibility"] = {"measure": None}
    out = rt.assess("accessibility", 1, BASELINES, policy, produced_by="c1")
    assert out.verdict == rt.REFUSED
    assert out.passed is False


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_gate_that_does_not_ratchet_says_which_ones_do():
    out = rt.assess("accessibility", 1, BASELINES, POLICY, produced_by="c1")
    assert out.verdict == rt.REFUSED
    assert LINT in out.message


# --- policy is the source, and the check is wired -----------------------------

@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_every_ratcheted_gate_is_a_gate_quality_gates_declares():
    gates = load_yaml(ROOT / "policy/quality-gates.yml")
    known = set(gates["always"]) | set(gates["conditional"])
    for name in POLICY["gates"]:
        assert name in known, f"{name} ratchets but is not a gate"


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_the_gate_names_are_not_hardcoded_in_the_script():
    source = (SCRIPTS / "ratchet.py").read_text(encoding="utf-8")
    assert LINT not in source
    assert "coverage_percent" not in source


@pytest.mark.req("REQ-CORE-RATCHET-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_ratchet_runs_after_verification(name):
    ids = [s["id"] for s in WORKFLOWS[name]["steps"]]
    assert ids.index("check-quality-ratchet") == ids.index("verify") + 1


@pytest.mark.req("REQ-CORE-RATCHET-001")
@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_step_forbids_reporting_a_baseline_as_a_pass(name):
    step = [s for s in WORKFLOWS[name]["steps"]
            if s["id"] == "check-quality-ratchet"][0]
    args = step["input"]["args"]
    assert "never as a pass" in args
    assert "do not re-run hoping" in args
