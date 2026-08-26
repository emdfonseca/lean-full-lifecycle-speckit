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

# A baseline says what it measured. `conditions` is that annotation, and a
# baseline without it is refused rather than compared against.
LINT_SCOPE = "eslint, src/**"
COVER_SCOPE = "vitest v8, include=src/shared/store*"

BASELINES = {
    LINT: {"value": 41, "recorded_at": "2026-08-01", "produced_by": "b700f30",
           "conditions": LINT_SCOPE},
    COVER: {"value": 84.0, "recorded_at": "2026-08-01",
            "produced_by": "b700f30", "conditions": COVER_SCOPE},
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
    out = rt.assess(LINT, 48, BASELINES, POLICY, produced_by="c1",
                    conditions=LINT_SCOPE)
    assert out.verdict == rt.REFUSED
    assert not out.passed


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_regression_on_a_higher_is_better_gate_is_refused():
    # Direction has to be read from policy, or coverage falling reads as a win.
    out = rt.assess(COVER, 79, BASELINES, POLICY, produced_by="c1",
                    conditions=COVER_SCOPE)
    assert out.verdict == rt.REFUSED


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_the_refusal_names_the_gate_the_baseline_and_the_measurement():
    out = rt.assess(LINT, 48, BASELINES, POLICY, produced_by="c1",
                    conditions=LINT_SCOPE)
    assert LINT in out.message
    assert "41" in out.message and "48" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_refused_measurement_never_moves_the_baseline():
    out = rt.assess(LINT, 48, BASELINES, POLICY, produced_by="c1",
                    conditions=LINT_SCOPE)
    assert rt.record(LINT, out, BASELINES, "c1", TODAY,
                     conditions=LINT_SCOPE, policy=POLICY) == BASELINES


# --- AC2: an improvement moves the baseline -----------------------------------

@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_improvement_moves_the_baseline():
    out = rt.assess(LINT, 30, BASELINES, POLICY, produced_by="PR #62",
                    conditions=LINT_SCOPE)
    assert out.verdict == rt.IMPROVED
    updated = rt.record(LINT, out, BASELINES, "PR #62", TODAY,
                        conditions=LINT_SCOPE, policy=POLICY)
    assert updated[LINT]["value"] == 30


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_the_moved_baseline_records_what_produced_it():
    out = rt.assess(LINT, 30, BASELINES, POLICY, produced_by="PR #62",
                    conditions=LINT_SCOPE)
    updated = rt.record(LINT, out, BASELINES, "PR #62", TODAY,
                        conditions=LINT_SCOPE, policy=POLICY)
    for name in POLICY["baseline_fields"]:
        assert updated[LINT][name], name
    assert updated[LINT]["produced_by"] == "PR #62"


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_improvement_with_no_provenance_is_refused():
    # A baseline with no provenance cannot be argued with later.
    out = rt.assess(LINT, 30, BASELINES, POLICY, produced_by="",
                    conditions=LINT_SCOPE)
    assert out.verdict == rt.REFUSED
    assert "what produced it" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_unchanged_measurement_holds():
    out = rt.assess(LINT, 41, BASELINES, POLICY, produced_by="c1",
                    conditions=LINT_SCOPE)
    assert out.verdict == rt.HELD
    assert out.passed


# --- AC3: loosening requires an approved exception ----------------------------

@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_loosening_without_an_exception_is_refused():
    out = rt.loosen(LINT, 60, BASELINES, POLICY, exception=None,
                    conditions=LINT_SCOPE)
    assert out.verdict == rt.REFUSED
    assert "only way to loosen" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_loosening_under_an_exception_naming_the_gate_is_permitted():
    out = rt.loosen(LINT, 60, BASELINES, POLICY, exception=valid_exception(),
                    conditions=LINT_SCOPE)
    assert out.verdict != rt.REFUSED
    assert out.new_baseline == 60


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_exception_for_another_gate_does_not_loosen_this_one():
    out = rt.loosen(LINT, 60, BASELINES, POLICY,
                    exception=valid_exception(policy_rule=COVER),
                    conditions=LINT_SCOPE)
    assert out.verdict == rt.REFUSED
    assert "not " + repr(LINT) in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_invalid_exception_does_not_loosen_anything():
    # Naming the gate is not enough; exception.py still has to accept it.
    out = rt.loosen(LINT, 60, BASELINES, POLICY,
                    exception=valid_exception(owner=""),
                    conditions=LINT_SCOPE)
    assert out.verdict == rt.REFUSED
    assert "is not valid" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_expired_exception_does_not_loosen_anything():
    out = rt.loosen(LINT, 60, BASELINES, POLICY,
                    exception=valid_exception(review_or_expiry_at="2026-01-01"),
                    conditions=LINT_SCOPE)
    assert out.verdict == rt.REFUSED


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_tightening_is_not_a_loosening():
    out = rt.loosen(LINT, 20, BASELINES, POLICY, exception=None,
                    conditions=LINT_SCOPE)
    assert out.verdict != rt.REFUSED


# --- AC4: a first run establishes, and does not pass --------------------------

@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_first_run_establishes_a_baseline():
    out = rt.assess("secret_detection", 0, BASELINES, POLICY, produced_by="c1",
                    conditions="gitleaks, whole tree")
    assert out.verdict == rt.ESTABLISHED
    assert out.new_baseline == 0


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_first_run_does_not_report_a_pass():
    # The baseline it silently recorded was never reviewed, so every later
    # comparison would rest on an unreviewed number.
    out = rt.assess("secret_detection", 0, BASELINES, POLICY, produced_by="c1",
                    conditions="gitleaks, whole tree")
    assert out.passed is False
    assert "not a pass" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_an_entry_with_no_value_is_treated_as_no_baseline():
    baselines = dict(BASELINES, secret_detection={
        "recorded_at": "2026-08-01", "conditions": "gitleaks, whole tree"})
    out = rt.assess("secret_detection", 3, baselines, POLICY, produced_by="c1",
                    conditions="gitleaks, whole tree")
    assert out.verdict == rt.ESTABLISHED


# --- AC5: a gate without a measure cannot ratchet -----------------------------

@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_gate_declared_ratcheted_with_no_measure_is_refused():
    policy = copy.deepcopy(POLICY)
    policy["gates"]["specification_convergence_for_promoted_work"] = {}
    out = rt.assess("specification_convergence_for_promoted_work", 1,
                    BASELINES, policy, produced_by="c1",
                    conditions="whole tree")
    assert out.verdict == rt.REFUSED
    assert "no usable measure" in out.message
    assert "specification_convergence_for_promoted_work" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_gate_with_an_unknown_direction_is_refused():
    policy = copy.deepcopy(POLICY)
    policy["gates"][LINT]["direction"] = "fewer_is_nicer"
    out = rt.assess(LINT, 30, BASELINES, policy, produced_by="c1",
                    conditions=LINT_SCOPE)
    assert out.verdict == rt.REFUSED


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_refusing_is_not_skipping():
    # A gate that silently opts out of the ratchet is the one that regresses.
    policy = copy.deepcopy(POLICY)
    policy["gates"]["accessibility"] = {"measure": None}
    out = rt.assess("accessibility", 1, BASELINES, policy, produced_by="c1",
                    conditions="axe, all views")
    assert out.verdict == rt.REFUSED
    assert out.passed is False


@pytest.mark.req("REQ-CORE-RATCHET-001")
def test_a_gate_that_does_not_ratchet_says_which_ones_do():
    out = rt.assess("accessibility", 1, BASELINES, POLICY, produced_by="c1",
                    conditions="axe, all views")
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


# --- AC6: a baseline says what it measured ------------------------------------

WIDER = "vitest v8, include=src/**"
UNSCOPED = {LINT: {"value": 41, "recorded_at": "2026-08-01",
                   "produced_by": "b700f30"}}


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_a_baseline_recording_no_scope_is_refused_rather_than_compared():
    # Not grandfathered. A number nobody can say what it covered is a number
    # nobody can argue with, and this repository refuses those.
    out = rt.assess(LINT, 41, UNSCOPED, POLICY, produced_by="c1",
                    conditions=LINT_SCOPE)
    assert out.verdict == rt.REFUSED
    assert "records no conditions" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_an_unscoped_baseline_is_not_silently_treated_as_no_baseline():
    # Reading it as "no baseline" would overwrite it with this run's number.
    out = rt.assess(LINT, 12, UNSCOPED, POLICY, produced_by="c1",
                    conditions=LINT_SCOPE)
    assert out.verdict != rt.ESTABLISHED
    assert rt.record(LINT, out, UNSCOPED, "c1", TODAY,
                     conditions=LINT_SCOPE, policy=POLICY) == UNSCOPED


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_a_run_that_states_no_conditions_is_refused():
    out = rt.assess(LINT, 41, BASELINES, POLICY, produced_by="c1")
    assert out.verdict == rt.REFUSED
    assert "no conditions" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_widening_what_is_measured_is_not_a_regression():
    # The denominator grew. The project started measuring more of itself, and
    # a refusal here would block that loudly and wrongly.
    out = rt.assess(COVER, 62.0, BASELINES, POLICY, produced_by="c1",
                    conditions=WIDER)
    assert out.verdict == rt.ESTABLISHED
    assert out.passed is False


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_a_run_under_other_conditions_says_what_it_did_not_compare_against():
    out = rt.assess(COVER, 62.0, BASELINES, POLICY, produced_by="c1",
                    conditions=WIDER)
    assert COVER_SCOPE in out.message
    assert "not compared" in out.message


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_narrowing_what_is_measured_does_not_move_the_wider_baseline():
    # 99% of one well-tested file must not become the number the project is
    # held to. The old baseline stays exactly where it was.
    narrow = "vitest v8, include=src/shared/store/index.ts"
    out = rt.assess(COVER, 99.0, BASELINES, POLICY, produced_by="c1",
                    conditions=narrow)
    updated = rt.record(COVER, out, BASELINES, "c1", TODAY,
                        conditions=narrow, policy=POLICY)
    held = {e["conditions"]: e["value"] for e in updated[COVER]}
    assert held[COVER_SCOPE] == 84.0
    assert held[narrow] == 99.0


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_two_conditions_for_one_gate_are_held_separately():
    out = rt.assess(COVER, 62.0, BASELINES, POLICY, produced_by="c1",
                    conditions=WIDER)
    updated = rt.record(COVER, out, BASELINES, "c1", TODAY,
                        conditions=WIDER, policy=POLICY)
    assert len(updated[COVER]) == 2
    assert updated[LINT] == BASELINES[LINT]


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_a_run_is_compared_against_the_baseline_for_its_own_conditions():
    both = dict(BASELINES, **{COVER: [
        dict(BASELINES[COVER]),
        {"value": 62.0, "recorded_at": "2026-08-02", "produced_by": "c2",
         "conditions": WIDER},
    ]})
    assert rt.assess(COVER, 70.0, both, POLICY, produced_by="c1",
                     conditions=WIDER).verdict == rt.IMPROVED
    # The same 70.0 is a regression against the narrow baseline of 84.
    assert rt.assess(COVER, 70.0, both, POLICY, produced_by="c1",
                     conditions=COVER_SCOPE).verdict == rt.REFUSED


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_loosening_names_which_baseline_it_loosens():
    out = rt.loosen(LINT, 60, BASELINES, POLICY, exception=valid_exception(),
                    conditions="eslint, src/parser/**")
    assert out.verdict == rt.REFUSED
    assert "no baseline under" in out.message


# --- the policy and the checker stay in agreement -----------------------------

@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_the_policy_declares_that_a_baseline_records_its_scope():
    assert rt.CONDITIONS in POLICY["baseline_fields"]


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_the_recorder_writes_exactly_the_fields_the_policy_declares():
    out = rt.assess(LINT, 30, BASELINES, POLICY, produced_by="PR #62",
                    conditions=LINT_SCOPE)
    entry = rt.record(LINT, out, BASELINES, "PR #62", TODAY,
                      conditions=LINT_SCOPE, policy=POLICY)[LINT]
    assert sorted(entry) == sorted(POLICY["baseline_fields"])
    assert entry[rt.CONDITIONS] == LINT_SCOPE


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_a_declared_field_the_recorder_cannot_produce_is_refused():
    # Adding a field to the policy must not leave the checker writing the old
    # set and calling the result a baseline.
    policy = copy.deepcopy(POLICY)
    policy["baseline_fields"].append("database_backend")
    out = rt.assess(LINT, 30, BASELINES, policy, produced_by="PR #62",
                    conditions=LINT_SCOPE)
    with pytest.raises(ValueError, match="database_backend"):
        rt.record(LINT, out, BASELINES, "PR #62", TODAY,
                  conditions=LINT_SCOPE, policy=policy)


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_the_command_line_records_the_conditions_it_measured(tmp_path):
    import shutil
    import subprocess

    # The recorder refuses to write outside its project, so the run gets a
    # project of its own with the same policy in it.
    (tmp_path / "policy").mkdir()
    shutil.copy(ROOT / "policy/quality-gates.yml",
                tmp_path / "policy/quality-gates.yml")
    path = tmp_path / "ratchet-baselines.yml"
    run = subprocess.run(
        [sys.executable, str(SCRIPTS / "ratchet.py"), "--gate", LINT,
         "--measurement", "41", "--produced-by", "c1",
         "--conditions", LINT_SCOPE, "--baselines", str(path),
         "--policy-root", str(tmp_path), "--write", "--format", "json"],
        text=True, capture_output=True, cwd=str(ROOT))
    assert run.returncode == 0, run.stderr
    written = load_yaml(path)
    assert written[LINT][rt.CONDITIONS] == LINT_SCOPE


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_the_command_line_refuses_a_run_that_states_no_conditions(tmp_path):
    import shutil
    import subprocess

    # The recorder refuses to write outside its project, so the run gets a
    # project of its own with the same policy in it.
    (tmp_path / "policy").mkdir()
    shutil.copy(ROOT / "policy/quality-gates.yml",
                tmp_path / "policy/quality-gates.yml")
    path = tmp_path / "ratchet-baselines.yml"
    run = subprocess.run(
        [sys.executable, str(SCRIPTS / "ratchet.py"), "--gate", LINT,
         "--measurement", "41", "--produced-by", "c1",
         "--baselines", str(path), "--policy-root", str(tmp_path), "--write"],
        text=True, capture_output=True, cwd=str(ROOT))
    assert run.returncode == 1
    assert "REFUSED" in run.stdout
    assert not path.exists()


@pytest.mark.req("REQ-CORE-RATCHET-002")
def test_the_command_documents_what_a_baseline_must_say_it_measured():
    doc = (ROOT / "bundle/components/extensions/github-lifecycle/commands"
                  "/ratchet.md").read_text(encoding="utf-8")
    assert "--conditions" in doc
