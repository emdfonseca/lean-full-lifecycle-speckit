"""An embedded branch must not drift from the workflow it mirrors.

Spec Kit has no sub-workflow step type, so a branch that does what a standalone
workflow does has to inline its steps. The sequence exists twice by necessity,
and the roadmap named the risk: the two diverge, and nobody notices until one
of them is wrong.

P0d chose this over generating both from shared fragments. A generator would
make drift impossible but hide the hand-written prompt prose behind a template
layer, doubling the review surface at fifteen workflows. The bet was that
comparing structure is enough, and this is where that bet is settled.

What is compared is the sequence of step kinds and commands. Prose is not: the
embedded branch addresses a story already in flight and the standalone one does
not, so identical wording would be wrong.
"""
from __future__ import annotations

import pytest

from lib.inventory import ROOT, load_inventory, load_yaml

INVARIANTS = load_yaml(ROOT / "tooling" / "invariants.yml")
PARITY = INVARIANTS.get("parity") or []
INV = load_inventory()


def signature(steps):
    """Step kinds and commands: what the branch does, not how it words it."""
    out = []
    for step in steps:
        if step.get("command"):
            out.append(("command", step["command"]))
        else:
            out.append((step.get("type", "prompt"), None))
    return out


def case_steps(workflow_id, case):
    wf = INV.by_id("workflow", workflow_id)
    for step in wf.manifest["steps"]:
        if step.get("type") == "switch":
            cases = step.get("cases") or {}
            if case in cases:
                return cases[case]
    raise AssertionError(f"{workflow_id} has no switch case {case!r}")


def test_parity_is_declared():
    # An empty declaration would make every test below vacuously pass.
    assert PARITY, "no parity pairs declared; embedded branches would drift unchecked"


@pytest.mark.req("REQ-UNCERTAINTY-PARITY-001")
@pytest.mark.parametrize("pair", PARITY, ids=lambda p: p["standalone"])
def test_an_embedded_branch_matches_its_standalone_workflow(pair):
    standalone = INV.by_id("workflow", pair["standalone"])
    assert standalone, f"{pair['standalone']} does not exist"

    trailing = pair.get("standalone_trailing_steps", 0)
    expected = signature(standalone.manifest["steps"])
    if trailing:
        expected = expected[:-trailing]
    actual = signature(case_steps(pair["embedded_in"], pair["case"]))

    if expected != actual:
        lines = ["embedded branch has drifted from its standalone workflow:"]
        for i in range(max(len(expected), len(actual))):
            want = expected[i] if i < len(expected) else None
            got = actual[i] if i < len(actual) else None
            mark = " " if want == got else "*"
            lines.append(f"  {mark} {i}: standalone={want}  embedded={got}")
        pytest.fail("\n".join(lines))


@pytest.mark.req("REQ-UNCERTAINTY-PARITY-001")
@pytest.mark.parametrize("pair", PARITY, ids=lambda p: p["standalone"])
def test_an_embedded_branch_keeps_its_gate(pair):
    # The gate is the point. A branch that dropped it would still match on
    # kinds if the standalone had none, so this is asserted directly.
    steps = case_steps(pair["embedded_in"], pair["case"])
    assert any(s.get("type") == "gate" for s in steps)
    for gate in (s for s in steps if s.get("type") == "gate"):
        assert gate["on_reject"] == "abort"


# --- the switch itself --------------------------------------------------------

def story_switch():
    wf = INV.by_id("workflow", "lifecycle-story-delivery")
    return next(s for s in wf.manifest["steps"] if s.get("type") == "switch")


@pytest.mark.req("REQ-UNCERTAINTY-MODE-001")
def test_every_declared_mode_has_a_case():
    wf = INV.by_id("workflow", "lifecycle-story-delivery")
    declared = set(wf.manifest["inputs"]["uncertainty_mode"]["enum"])
    cases = set(story_switch()["cases"])
    assert declared == cases, f"modes without a case: {declared - cases}"


@pytest.mark.req("REQ-UNCERTAINTY-MODE-001")
def test_reconciliation_runs_before_planning():
    # Planning against unreconciled findings is how a guess becomes a
    # requirement.
    wf = INV.by_id("workflow", "lifecycle-story-delivery")
    ids = [s["id"] for s in wf.manifest["steps"]]
    assert ids.index("resolve-uncertainty") < ids.index("reconcile-spec")
    assert ids.index("reconcile-spec") < ids.index("plan")


@pytest.mark.req("REQ-UNCERTAINTY-MODE-001")
def test_reconciliation_forbids_promoting_unconfirmed_observations():
    wf = INV.by_id("workflow", "lifecycle-story-delivery")
    step = next(s for s in wf.manifest["steps"] if s["id"] == "reconcile-spec")
    text = str(step["prompt"]).lower()
    assert "unconfirmed" in text
    assert "acceptance criterion" in text


def test_the_switch_uses_the_field_the_runner_reads():
    # The runner requires `expression`; `value` validates locally and fails to
    # install.
    switch = story_switch()
    assert "expression" in switch and "value" not in switch


def test_every_step_id_is_unique_including_inside_cases():
    wf = INV.by_id("workflow", "lifecycle-story-delivery")
    ids = []

    def collect(steps):
        for step in steps:
            ids.append(step["id"])
            for case in (step.get("cases") or {}).values():
                collect(case)
            collect(step.get("default") or [])

    collect(wf.manifest["steps"])
    assert len(ids) == len(set(ids))
