"""The documented recovery, and the timeouts that set its exposure.

A run killed without a signal Python can catch is left at `status: running` and
`specify workflow resume` refuses it (#123, upstream). Nothing here repairs
that: `specify_cli` owns run state, and a script that edited it on our behalf
would make the workaround permanent and would eventually do it while a run was
genuinely alive.

So the deliverable is a page a person follows and a rule that keeps the longest
tier from being spent by default. These tests hold both to what they claim.
"""
from __future__ import annotations

import collections
import pathlib

import pytest
import yaml

from lib.inventory import ROOT

PAGE = ROOT / "docs/recovering-a-run.md"
POLICY = yaml.safe_load((ROOT / "policy/bootstrap-policy.yml").read_text(encoding="utf-8"))
TIERS = POLICY["step_timeouts"]
WORKFLOWS = ROOT / "bundle/components/workflows"


def steps():
    def walk(items):
        for step in items or []:
            if not isinstance(step, dict):
                continue
            yield step
            for case in (step.get("cases") or {}).values():
                yield from walk(case)
            yield from walk(step.get("steps"))

    for path in sorted(WORKFLOWS.glob("*/workflow.yml")):
        for step in walk(yaml.safe_load(path.read_text(encoding="utf-8")).get("steps")):
            yield path.parent.name, step


# --- the recovery a person follows --------------------------------------------

@pytest.mark.req("REQ-WORKFLOW-RECOVERY-001")
def test_the_page_says_which_deaths_produce_the_state():
    """`^C` is not this, and a page that let a reader assume it was would send
    them editing state for a run that would have resumed on its own."""
    text = PAGE.read_text(encoding="utf-8")
    assert "SIGINT" in text and "paused" in text
    assert "is **not** this" in text


@pytest.mark.req("REQ-WORKFLOW-RECOVERY-001")
def test_the_page_makes_the_reader_check_for_a_live_run_first():
    # The one case the flag exists to prevent. Editing it while a run is alive
    # lets two runs write the same state.
    text = PAGE.read_text(encoding="utf-8")
    assert "If a process really is running that workflow, stop here" in text


@pytest.mark.req("REQ-WORKFLOW-RECOVERY-001")
def test_the_page_states_that_the_manual_step_is_deliberate():
    text = PAGE.read_text(encoding="utf-8")
    assert "editing another component's state file" in text
    assert "make a workaround permanent" in text


@pytest.mark.req("REQ-WORKFLOW-RECOVERY-001")
def test_the_page_names_the_upstream_item_and_what_removes_it():
    # A workaround with no removal condition outlives the defect it works
    # around, and nobody can tell whether it is still needed.
    text = PAGE.read_text(encoding="utf-8")
    assert "#123" in text
    assert "Removing this page" in text


@pytest.mark.req("REQ-WORKFLOW-RECOVERY-001")
def test_nothing_shipped_repairs_the_state_file():
    """The out-of-scope clause, held rather than stated.

    A script under bundle/ that wrote `paused` into a run's state would be the
    automation this deliberately does not provide.
    """
    for path in (ROOT / "bundle").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "workflows/runs" not in text, path
    for path in (ROOT / "scripts").rglob("*.py"):
        assert "workflows/runs" not in path.read_text(encoding="utf-8"), path


# --- the timeouts that set the exposure ---------------------------------------

@pytest.mark.req("REQ-WORKFLOW-RECOVERY-001")
def test_every_declared_timeout_is_a_tier():
    allowed = {v for v in TIERS.values() if isinstance(v, int)}
    off = [(w, s.get("id"), s.get("timeout")) for w, s in steps()
           if s.get("timeout") is not None and s["timeout"] not in allowed]
    assert not off, f"timeouts that are not a tier: {off}"


@pytest.mark.req("REQ-WORKFLOW-RECOVERY-001")
def test_the_check_holds_command_steps_too():
    """Twenty-two of the thirty steps at the longest tier were command steps.

    Both timeout checks skipped anything that was not a prompt, so the largest
    tier was being spent with nothing holding it to what the tier means.
    """
    source = (ROOT / "scripts/lib/checks.py").read_text(encoding="utf-8")
    body = source[source.index('@check("INV-STEP-TIMEOUT-TIER"'):]
    body = body[:body.index("\n@check(")]
    assert 'kind not in ("prompt", "command")' in body


@pytest.mark.req("REQ-WORKFLOW-RECOVERY-001")
def test_a_reporting_command_does_not_sit_on_the_synthesis_tier():
    """`Reads and reports` is a tier of its own, and these are that.

    `speckit.analyze` produces a cross-artifact report, `speckit.converge`
    reconciles what already exists, and
    `speckit.github-lifecycle.documents` reads markdown and prints findings --
    measured at well under a second.
    """
    reporting = {"speckit.analyze", "speckit.converge",
                 "speckit.github-lifecycle.documents"}
    synthesis = TIERS["artifact_synthesis"]
    off = [(w, s.get("id")) for w, s in steps()
           if s.get("command") in reporting and s.get("timeout") == synthesis]
    assert not off, f"reporting steps still on the synthesis tier: {off}"


@pytest.mark.req("REQ-WORKFLOW-RECOVERY-001")
def test_the_steps_that_build_an_artifact_keep_the_longest_tier():
    # The review was not a blanket reduction. #116 and #117 established these
    # genuinely need it, and cutting them would trade one failure for another.
    building = {"speckit.specify", "speckit.plan", "speckit.tasks",
                "speckit.implement", "speckit.checklist"}
    synthesis = TIERS["artifact_synthesis"]
    found = [(w, s.get("id")) for w, s in steps()
             if s.get("command") in building]
    assert found
    for w, step_id in found:
        step = next(s for ww, s in steps()
                    if ww == w and s.get("id") == step_id)
        assert step.get("timeout") == synthesis, (w, step_id)


@pytest.mark.req("REQ-WORKFLOW-RECOVERY-001")
def test_the_review_actually_moved_something():
    """A review that changed nothing and said so is a review; one that changed
    nothing and did not say so is a claim. This pins that it moved."""
    tally = collections.Counter(
        s["timeout"] for _, s in steps() if s.get("timeout"))
    assert tally[TIERS["artifact_synthesis"]] < 30
    assert tally[TIERS["inspection"]] > 0
