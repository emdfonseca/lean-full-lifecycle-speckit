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


# --- the linter knows what kind of item it is looking at ----------------------
#
# It did not, so a bug's Reproduction and a spike's Exit criteria were split
# into pseudo-criteria and asked for Then clauses item-types.yml never
# requires of them.

POLICY = lint_mod.load_policy(ROOT)

BUG_BODY = """**Reproduction**

Run the thing.

**Expected**

It works.

**Actual**

It does not.

**Regression test**

tests/test_x.py::test_y
"""

STORY_BODY = """**Scope**

A change.

**Acceptance criteria**

AC1 — the happy path
  Given a thing
  When it runs
  Then it reports success

AC2 — the refusal
  Given a thing with no name
  When it runs
  Then it exits non-zero and names the missing field

**Risk**

Low.
"""


@pytest.mark.req("REQ-BACKLOG-CRITERIA-001")
def test_only_types_with_an_acceptance_section_carry_criteria():
    carries = lint_mod.acceptance_types(POLICY)
    assert "story" in carries
    assert not carries & {"bug", "spike", "epic"}, (
        "a type without an acceptance section is being treated as though it "
        "had one")


@pytest.mark.req("REQ-BACKLOG-CRITERIA-001")
def test_a_bug_is_not_linted_and_the_report_says_so():
    findings, account = lint_mod.lint_issue(BUG_BODY, "bug", CONTRACT, POLICY)
    assert findings == []
    assert "not linted" in account and "bug" in account


@pytest.mark.req("REQ-BACKLOG-CRITERIA-001")
def test_a_spike_is_not_linted():
    findings, account = lint_mod.lint_issue(
        "**Question**\n\nWhat?\n\n**Exit criteria**\n\nAn answer.\n",
        "spike", CONTRACT, POLICY)
    assert findings == []
    assert "not linted" in account


@pytest.mark.req("REQ-BACKLOG-CRITERIA-001")
def test_a_story_is_still_linted():
    findings, account = lint_mod.lint_issue(STORY_BODY, "story", CONTRACT, POLICY)
    assert findings == [], f"a conforming story produced {findings}"
    assert "linted" in account and "not linted" not in account


@pytest.mark.req("REQ-BACKLOG-CRITERIA-001")
def test_a_story_with_a_bad_criterion_still_reports():
    # The fix must not silence the findings that were the point.
    # Strip AC1's outcome entirely: "And" also satisfies the Then check, so
    # rewording it would not have broken anything.
    body = STORY_BODY.replace("  Then it reports success\n", "")
    findings, _ = lint_mod.lint_issue(body, "story", CONTRACT, POLICY)
    assert findings, "a story with no observable outcome was not reported"


@pytest.mark.req("REQ-BACKLOG-CRITERIA-001")
def test_a_story_with_no_acceptance_section_is_reported():
    findings, account = lint_mod.lint_issue(
        "**Scope**\n\nA change.\n", "story", CONTRACT, POLICY)
    assert findings and "no Acceptance criteria section" in str(findings[0])
    assert "requires acceptance criteria" in account


@pytest.mark.req("REQ-BACKLOG-CRITERIA-001")
def test_a_missing_section_is_none_rather_than_the_whole_body():
    # The fallback to the whole body is the defect. Returning the body meant
    # every non-story was linted as though its prose were criteria.
    assert lint_mod.extract_section(BUG_BODY) is None
    assert lint_mod.extract_section(STORY_BODY) is not None


@pytest.mark.req("REQ-BACKLOG-CRITERIA-001")
def test_the_types_come_from_policy_not_from_this_script():
    source = (SCRIPTS / "lint_acceptance.py").read_text(encoding="utf-8")
    body = source.split("def acceptance_types(")[1].split("\ndef ")[0]
    for name in ("story", "bug", "spike", "epic"):
        assert f'"{name}"' not in body, f"{name} is hardcoded in acceptance_types"


# --- emphasis must not hide a criterion --------------------------------------
#
# Bold Given/When/Then is the natural Markdown form and the one real issue
# bodies use. It defeated the linter twice over: the section terminator ended
# at any line opening `**` and a capital, so `**Given**` closed the section it
# was inside; and the clause patterns anchored to the start of a line, so a
# one-line criterion had its When and Then mid-sentence where nothing looked.

BOLD_CRITERIA = (
    "**Acceptance criteria**\n\n"
    "**Given** a stale extension, **When** update runs, **Then** it refuses.\n\n"
    "**Risk**\n\nLow.\n"
)


@pytest.mark.req("REQ-BACKLOG-CRITERIA-002")
def test_a_bold_criterion_does_not_end_the_section_it_is_inside():
    section = lint_mod.extract_section(BOLD_CRITERIA)
    assert section is not None and section.strip(), "the section came back empty"
    assert "refuses" in section
    assert lint_mod.split_criteria(section), "no criteria found in a section with one"


@pytest.mark.req("REQ-BACKLOG-CRITERIA-002")
def test_a_bold_heading_still_ends_the_section():
    # What the terminator was for. Real bodies close with `**Risk**`, and the
    # fix must not swallow it into the criteria.
    section = lint_mod.extract_section(BOLD_CRITERIA)
    assert "**Risk**" not in section and "Low." not in section


@pytest.mark.req("REQ-BACKLOG-CRITERIA-002")
def test_emphasised_clause_markers_are_recognised_mid_line():
    one_line = "**Given** a thing, **When** it runs, **Then** it refuses."
    assert lint_mod.GIVEN.search(one_line)
    assert lint_mod.WHEN.search(one_line)
    assert lint_mod.THEN.search(one_line)


@pytest.mark.req("REQ-BACKLOG-CRITERIA-002")
def test_a_bare_then_in_prose_is_not_a_clause_marker():
    # Only the emphasised form is recognised away from the start of a line.
    # `then` is too common a word to treat as a marker wherever it appears.
    assert not lint_mod.THEN.search("The system does a thing and then it stops.")


@pytest.mark.req("REQ-BACKLOG-CRITERIA-002")
def test_a_bold_criterion_reaches_lint_rather_than_merely_being_captured():
    # Capturing the section is not enough: the criteria must arrive at the
    # content checks. A banned phrase inside a bold criterion proves they did.
    body = ("**Acceptance criteria**\n\n"
            "**Given** a thing, **When** it runs, **Then** it works correctly.\n\n"
            "**Risk**\n\nLow.\n")
    findings, account = lint_mod.lint_issue(body, "story", CONTRACT, POLICY)
    assert "linted the acceptance section" in account
    assert any("works correctly" in str(f) for f in findings), findings
