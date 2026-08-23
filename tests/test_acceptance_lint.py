"""Acceptance criteria that cannot be verified are reported.

`state-machine.yml` requires `acceptance_criteria_satisfied` as evidence for
Output Done. Against "works correctly", satisfaction is an opinion, and the
evidence is a checkbox rather than a fact.

The linter reports and does not block. Prose has judgement in it, and one
confident enough to reject text is one people route around by rewording.
"""
from __future__ import annotations

import importlib.util
import sys

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
spec = importlib.util.spec_from_file_location("lint_acceptance", SCRIPTS / "lint_acceptance.py")
lint_mod = importlib.util.module_from_spec(spec)
sys.modules["lint_acceptance"] = lint_mod
spec.loader.exec_module(lint_mod)

CONTRACT = load_yaml(ROOT / "policy/item-types.yml")["acceptance_criteria"]

WELL_FORMED = """
AC1 — Value is written
  Given an issue in Ready
  When a valid plan is applied
  Then the delivery state reads In Progress
   And the operation id is reported

AC2 — A stale plan is refused
  Given a plan whose observed value no longer holds
  When it is applied
  Then the command exits non-zero
   And no value is written
"""


def lint(text):
    return lint_mod.lint(text, CONTRACT)


@pytest.mark.req("REQ-BACKLOG-AC-001")
def test_well_formed_criteria_pass():
    assert lint(WELL_FORMED) == []


@pytest.mark.req("REQ-BACKLOG-AC-001")
@pytest.mark.parametrize("phrase", [
    "works correctly", "as expected", "user-friendly", "handles gracefully",
])
def test_an_unobservable_phrase_is_reported(phrase):
    text = WELL_FORMED.replace("the delivery state reads In Progress", phrase)
    problems = [f for f in lint(text) if phrase in f.problem]
    assert problems, f"{phrase!r} not reported"
    assert "AC1" in problems[0].criterion


@pytest.mark.req("REQ-BACKLOG-AC-001")
def test_a_set_describing_only_success_is_reported():
    happy = """
AC1 — Value is written
  Given an issue in Ready
  When a valid plan is applied
  Then the delivery state reads In Progress
"""
    problems = [f for f in lint(happy) if f.criterion == "set"]
    assert problems and "failure" in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-AC-001")
def test_an_assertion_without_a_then_clause_is_reported():
    # The shape this repository used before the contract existed.
    bullets = """
- Each of the three commands invokes its script.
- A check asserts no command mutates state without invoking a script.
"""
    problems = lint(bullets)
    assert any("nothing observable" in f.problem for f in problems)


def test_criteria_missing_context_or_action_are_reported():
    only_then = """
AC1 — Something
  Then the value is written
"""
    assert any("cannot be executed" in f.problem for f in lint(only_then))


def test_empty_criteria_are_reported():
    assert lint("   ")[0].problem == "no acceptance criteria given"


def test_each_criterion_is_reported_separately():
    text = WELL_FORMED.replace("the command exits non-zero", "it works correctly")
    labels = {f.criterion for f in lint(text)}
    assert "AC2" in labels and "AC1" not in labels


# --- the contract itself ------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-AC-001")
def test_the_contract_reaches_the_author_through_the_template():
    template = load_yaml(ROOT / ".github/ISSUE_TEMPLATE/story.yml")
    field = next(b for b in template["body"] if b.get("id") == "acceptance")
    description = field["attributes"]["description"]
    assert "Given" in description and "When" in description and "Then" in description
    for entry in CONTRACT["banned_phrases"][:3]:
        assert entry["phrase"] in description


def test_the_linter_reads_the_contract_rather_than_carrying_one():
    source = (SCRIPTS / "lint_acceptance.py").read_text(encoding="utf-8")
    for entry in CONTRACT["banned_phrases"]:
        assert f'"{entry["phrase"]}"' not in source, (
            f"{entry['phrase']!r} is hardcoded; changing policy would not change "
            "the linter")


def test_section_extraction_handles_both_heading_styles():
    for heading in ("## Acceptance criteria", "**Acceptance criteria**"):
        body = f"# Story\n\nSome scope.\n\n{heading}\n\nAC1 — x\n  Then y\n\n## Risk\n\nlow"
        section = lint_mod.extract_section(body)
        assert "AC1" in section and "low" not in section
