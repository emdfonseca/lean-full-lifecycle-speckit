"""The outcome review, and the two verdicts it must keep apart.

Delivery asks whether the work met the standard; outcome asks whether it did
what it was for. A team whose finished work is reopened because a metric moved
learns to pick safe metrics, and the measurement stops being worth taking. Most
of these tests exist to hold that separation against a workflow that writes a
status field.
"""
from __future__ import annotations

import pytest

from lib.inventory import ROOT, load_yaml

WORKFLOW = load_yaml(
    ROOT / "bundle/components/workflows/lifecycle-outcome-review/workflow.yml")
STEPS = WORKFLOW["steps"]
PLAN = "speckit.github-lifecycle.plan"
TRANSITION = "speckit.github-lifecycle.transition"
CAPTURE = "speckit.github-lifecycle.capture"
WRITE_EFFECT = {TRANSITION, CAPTURE}

INVARIANTS = load_yaml(ROOT / "tooling/invariants.yml")
# Steps declared read-only in invariants.yml. Inferring this from the args prose
# is the mistake of reading a rule and its violation the same way; a named step
# is checkable.
EXEMPT = {d["step"] for d in INVARIANTS.get("read_only_invocations", [])
          if d["workflow"] == WORKFLOW["workflow"]["id"]}


def flatten(steps):
    """Every step in order, descending into switch cases.

    The gate-precedes-write rule has to hold inside a branch, not just at the
    top level, so a checker that only walks the outer list proves nothing.
    """
    for step in steps:
        if step.get("type") == "switch":
            for case in step["cases"].values():
                yield from flatten(case)
        else:
            yield step


def branch(name):
    for step in STEPS:
        if step.get("type") == "switch":
            return list(flatten(step["cases"][name]))
    raise AssertionError("no switch step")


def text(step) -> str:
    return " ".join(str(v) for v in (
        step.get("prompt", ""), step.get("message", ""),
        (step.get("input") or {}).get("args", "")))


ALL = list(flatten(STEPS))


# --- AC1: delivery is not disturbed -------------------------------------------

@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_no_step_plans_or_applies_a_delivery_status_change():
    for step in ALL:
        if step.get("command") in {PLAN, TRANSITION}:
            args = (step["input"]["args"])
            assert "Outcome Status" in args, step["id"]
            # "Delivery Status" may appear only in a refusal to change it.
            for phrase in ("Delivery Status →", "Delivery Status ->"):
                assert phrase not in args, step["id"]


@pytest.mark.req("REQ-STATE-OUTCOME-003")
@pytest.mark.parametrize("case", ["measuring", "validated", "missed"])
def test_every_branch_says_delivery_is_untouched(case):
    assert any("Delivery Status untouched" in text(s)
               or "untouched" in text(s) for s in branch(case)), case


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_report_gives_the_delivery_state_rather_than_asserting_it_is_unchanged():
    report = [s for s in ALL if s["id"] == "report"][0]
    body = text(report)
    assert "unchanged" in body
    # Naming the value is what lets a reader check rather than trust.
    assert "give its value" in body or "give the value" in body


# --- AC2: only an authority validates -----------------------------------------

@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_validated_gate_names_the_two_authorities():
    steps = branch("validated")
    gate = [s for s in steps if s.get("type") == "gate"][0]
    assert "product owner" in gate["message"]
    assert "analytics owner" in gate["message"]
    assert gate["on_reject"] == "abort"


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_agent_is_told_it_is_not_an_authority():
    joined = " ".join(text(s) for s in branch("validated"))
    assert "You are not one of them" in joined


# --- AC3: insufficient evidence -----------------------------------------------

@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_measuring_branch_transitions_to_measuring_not_missed():
    args = [s["input"]["args"] for s in branch("measuring")
            if s.get("command") == TRANSITION]
    assert args and "Measuring" in args[0]
    assert "Missed" not in args[0]


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_measuring_branch_demands_a_date_or_a_number():
    joined = " ".join(text(s) for s in branch("measuring"))
    assert 'not "more data"' in joined, (
        "an outcome held open without a condition for closing it is one nobody "
        "returns to")
    assert "not failure" in joined


# --- AC4: a missed outcome produces a searched-for finding --------------------

@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_missed_branch_searches_before_it_creates():
    ids = [s["id"] for s in branch("missed") if s.get("command") == CAPTURE]
    assert ids == ["search-for-an-existing-finding", "capture-the-finding"]


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_search_step_writes_nothing():
    search = [s for s in branch("missed")
              if s["id"] == "search-for-an-existing-finding"][0]
    assert "Write nothing" in text(search)


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_a_regressed_guardrail_may_not_be_softened():
    joined = " ".join(text(s) for s in branch("missed"))
    assert "do not soften either" in joined
    assert "Do not renegotiate" in joined


# --- AC5: recommend, never decide ---------------------------------------------

@pytest.mark.req("REQ-STATE-OUTCOME-003")
@pytest.mark.parametrize("case", ["measuring", "validated", "missed"])
def test_every_write_effect_step_is_preceded_by_a_gate(case):
    steps = branch(case)
    for i, step in enumerate(steps):
        if step.get("command") in WRITE_EFFECT and step["id"] not in EXEMPT:
            prior = steps[:i]
            gates = [j for j, s in enumerate(prior) if s.get("type") == "gate"]
            assert gates, f"{step['id']} has no prior gate"
            # No write-effect step may sit between the gate and this one.
            between = prior[gates[-1] + 1:]
            assert not [s for s in between
                        if s.get("command") in WRITE_EFFECT
                        and s["id"] not in EXEMPT], (
                f"{step['id']} is separated from its gate by another write")


@pytest.mark.req("REQ-STATE-OUTCOME-003")
@pytest.mark.parametrize("case", ["measuring", "validated", "missed"])
def test_each_transition_names_the_plan_it_applies(case):
    for step in branch(case):
        if step.get("command") == TRANSITION:
            args = step["input"]["args"]
            assert "Approved plan:" in args
            slug = f"outcome-{'missed' if case == 'missed' else case}.md"
            assert slug in args, (case, step["id"])


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_assessment_is_reported_as_a_recommendation():
    first = ALL[0]
    assert first["command"] == "speckit.github-lifecycle.outcome"
    assert "does not decide" in text(first)


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_status_is_set_from_the_assessment_not_from_hope():
    assert "not set it from what" in text(ALL[0]).replace("\n", " ")


def test_the_run_states_which_question_it_is_answering():
    step = [s for s in ALL if s["id"] == "state-what-is-not-changing"][0]
    assert "measures less" in text(step)


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_every_exemption_names_a_step_that_exists():
    ids = {s["id"] for s in ALL}
    for declared in EXEMPT:
        assert declared in ids, (
            f"{declared!r} is exempted from the gate rule but no such step "
            "exists; a stale exemption silently widens the rule")


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_exempt_step_is_the_search_and_not_the_creation():
    assert EXEMPT == {"search-for-an-existing-finding"}


# --- the inconclusive route ---------------------------------------------------

@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_workflow_can_carry_an_inconclusive_assessment():
    # Without this case the assessment's own distinction had nowhere to go:
    # an open question was routed down the missed branch and reported as a
    # failure.
    assert "inconclusive" in WORKFLOW["inputs"]["assessed_status"]["enum"]
    assert "inconclusive" in [s for s in STEPS
                              if s.get("type") == "switch"][0]["cases"]


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_inconclusive_branch_refuses_to_call_it_a_failure():
    joined = " ".join(text(s) for s in branch("inconclusive"))
    assert "do not say the work failed" in joined
    assert "open question" in joined


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_inconclusive_branch_asks_what_would_settle_it():
    joined = " ".join(text(s) for s in branch("inconclusive"))
    assert "Name what would settle it" in joined


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_inconclusive_branch_reaches_the_same_status_by_its_own_route():
    # One board option covers both findings, so the route is what preserves
    # the difference.
    args = [s["input"]["args"] for s in branch("inconclusive")
            if s.get("command") == TRANSITION]
    assert args and "Outcome Missed / Inconclusive" in args[0]
    assert "inconclusive rather than missed" in args[0]


@pytest.mark.req("REQ-STATE-OUTCOME-003")
def test_the_inconclusive_branch_creates_no_follow_up_finding():
    # A missed outcome proposes a finding about the product. An inconclusive
    # one is about the measurement, and filing a product bug for it would be
    # the same misreading in a new place.
    assert CAPTURE not in [s.get("command") for s in branch("inconclusive")]
