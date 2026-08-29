"""The interview a bootstrap runs before it writes the documents.

Greenfield bootstrap wrote seven documents defining a project's direction from
one input string -- `product_context`, prompted as "Product idea and
constraints" -- and asked no question. Its four gates are all approve/reject on
content already written, which is worse than no gate: a person who approves an
artifact reads it afterwards as agreed, and downstream work treats it as the
project's stated intent (#186).

What is asserted here is the property that failed, in both halves. The
questions exist and reach a person (`--plan`, and the ordering check), and the
silences stay visible (`--check`, `--unresolved`). A decline is a first-class
outcome: blocking on a question nobody can answer yet would make greenfield
unusable, which is the failure this must not trade for.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import date, timedelta

import pytest
import yaml

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
WORKFLOW = ROOT / "bundle/components/workflows/lifecycle-greenfield-bootstrap/workflow.yml"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(SCRIPTS))
_load("project_root")
elicit = _load("elicit")
CONTRACT = elicit.load_contract(ROOT)
POLICY = yaml.safe_load((ROOT / "policy/bootstrap-policy.yml").read_text(encoding="utf-8"))
STEPS = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["steps"]


def _complete_record(**overrides) -> dict:
    answers = [{"id": q["id"], "status": "answered", "answer": "something",
                "basis": "typed"} for q in CONTRACT["questions"]]
    record = {"asked_on": date.today(), "answers": answers}
    record.update(overrides)
    return record


# --- the questions reach a person ---------------------------------------------

@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_the_bootstrap_asks_before_it_writes():
    # The whole item in one assertion: the workflow that writes the seven
    # documents now invokes an interview, where it previously invoked none.
    assert any(str(s.get("command") or "").endswith(".elicit") for s in STEPS)


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_the_interview_precedes_the_step_that_chooses():
    # Presence alone is cheap. `apply-greenfield-bootstrap` selects the stack,
    # draws the product boundary and creates the Epic set, so an interview
    # after it answers questions already decided.
    ids = [s.get("id") for s in STEPS]
    commands = [str(s.get("command") or "") for s in STEPS]
    elicit_at = next(i for i, c in enumerate(commands) if c.endswith(".elicit"))
    assert elicit_at < ids.index(CONTRACT["runs_before"]["step"])


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_every_question_names_the_section_its_answer_feeds():
    # A question feeding nothing is one whose answer has nowhere to go, which
    # from the transcript is indistinguishable from an interview that worked.
    for question in CONTRACT["questions"]:
        assert question.get("feeds"), question["id"]


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_the_plan_preserves_the_declared_order():
    # `form.ordered` is a property of the sequence as written: each question is
    # answerable given the ones before it. Sorting would look tidier and
    # destroy it.
    assert [q["id"] for q in elicit.plan(CONTRACT)] == \
        [q["id"] for q in CONTRACT["questions"]]


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_most_of_the_interview_is_answerable_by_choosing():
    # `prefer_closed` is the difference between an interview and a form. Open
    # questions are the exception, and the two that are open are the two where
    # offering options would mean inventing the product.
    forms = [q.get("form") for q in CONTRACT["questions"]]
    assert forms.count("closed") > forms.count("open")
    open_ids = {q["id"] for q in CONTRACT["questions"] if q.get("form") == "open"}
    fed = {f["section"] for q in CONTRACT["questions"] if q["id"] in open_ids
           for f in q["feeds"]}
    assert fed == {"Intent", "Vocabulary"}


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_the_asker_is_given_the_rules_that_make_it_an_interview():
    # The agent conducts the interview; nothing else can. So the rules travel
    # with the questions rather than sitting in a file it might not read. The
    # one that closes the loophole -- everything derived from the product
    # context, nothing asked -- is named here because it is the rule whose
    # absence reinstates the old behaviour with an extra step.
    import json
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "elicit.py"), "--plan",
         "--policy-root", str(ROOT), "--format", "json"],
        text=True, capture_output=True, timeout=60)
    emitted = json.loads(r.stdout)["form"]
    assert emitted == CONTRACT["form"]
    assert "derivation_never_skips_a_question" in emitted
    assert "one_at_a_time" in emitted
    assert "prefer_closed" in emitted


# --- the silences stay visible ------------------------------------------------

@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_a_declared_question_missing_from_the_record_is_reported():
    # Not asked and asked-then-declined are different facts, and the item turns
    # on the difference.
    record = _complete_record()
    record["answers"] = [a for a in record["answers"] if a["id"] != "Q9"]
    assert any("Q9" in p for p in elicit.validate(CONTRACT, record))


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_a_decline_without_a_reason_is_reported():
    # A `declined` carrying nothing is indistinguishable from a question nobody
    # reached, which is the failure `gate_resolution` already had once.
    record = _complete_record()
    record["answers"][2] = {"id": "Q3", "status": "declined"}
    assert any("Q3" in p and "reason" in p
               for p in elicit.validate(CONTRACT, record))


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_a_decline_with_a_reason_does_not_block():
    # Blocking on a question nobody can answer yet would make greenfield
    # unusable. What is guaranteed is that the question was asked.
    record = _complete_record()
    record["answers"][2] = {"id": "Q3", "status": "declined",
                            "reason": "No launch criteria agreed yet."}
    assert elicit.validate(CONTRACT, record) == []
    assert CONTRACT["decline"]["blocks_the_run"] is False


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_every_decline_reaches_the_final_gate():
    # One decline buried in one document is a decline nobody sees. The report's
    # blockers line is where a person gets the total.
    record = _complete_record()
    record["answers"][2] = {"id": "Q3", "status": "declined",
                            "reason": "No launch criteria agreed yet."}
    unresolved = elicit.unresolved(CONTRACT, record)
    assert [u["id"] for u in unresolved] == ["Q3"]
    assert unresolved[0]["ask"] == CONTRACT["questions"][2]["ask"]


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_a_question_dropped_without_naming_what_dropped_it_is_reported():
    # `settled_by` is how an earlier answer removes a later question visibly.
    # Unnamed, it is a skip.
    record = _complete_record()
    record["answers"][3] = {"id": "Q4", "status": "settled_by"}
    assert any("Q4" in p for p in elicit.validate(CONTRACT, record))


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_a_question_settled_by_an_answer_nobody_gave_is_reported():
    # Found by writing a realistic record rather than by reasoning about the
    # code: Q11 dropped as settled by Q3, and Q3 declined. `settled_by` is the
    # one word that makes a drop look deliberate, so pointing it at a decline
    # removes a question with no answer behind it.
    record = _complete_record()
    record["answers"][2] = {"id": "Q3", "status": "declined",
                            "reason": "No launch criteria agreed yet."}
    record["answers"][10] = {"id": "Q11", "status": "settled_by",
                             "settled_by": "Q3"}
    problems = elicit.validate(CONTRACT, record)
    assert any("Q11" in p and "Q3" in p for p in problems), problems


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_an_undated_record_is_reported():
    # Without a date the answers cannot be placed in time, so a later
    # contradiction cannot be told from a later decision.
    record = _complete_record()
    record.pop("asked_on")
    assert any("asked_on" in p for p in elicit.validate(CONTRACT, record))


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_a_future_dated_record_is_reported():
    # The rule `product_documents.freshness` already holds for documents. A
    # stamp nobody can contradict is worse than no stamp.
    record = _complete_record(asked_on=date.today() + timedelta(days=1))
    assert any("future" in p for p in elicit.validate(CONTRACT, record))


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_a_complete_record_passes():
    assert elicit.validate(CONTRACT, _complete_record()) == []


# --- the answers are traceable ------------------------------------------------

@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_every_fed_section_exists_in_the_document_contract():
    # Two contracts naming each other's parts. Renaming a section in one leaves
    # the other pointing at nothing while the interview still asks.
    declared = {spec["path"]: {s["name"] for s in spec.get("sections") or []}
                for spec in POLICY["product_documents"]["required"]}
    for question in CONTRACT["questions"]:
        for fed in question["feeds"]:
            assert fed["section"] in declared[fed["document"]], question["id"]


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_a_document_section_cites_the_answer_it_encodes():
    # Criterion four: a later contradiction traces to the answer rather than to
    # the paragraph that encoded it.
    assert CONTRACT["citation"]["required_in_sections_fed_by_a_question"] is True


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_the_record_outlives_the_run_that_collected_it():
    # Keyed by project, not by run. A readiness verdict was keyed by run once
    # and a second unvalidated one got made because the first could not be
    # named.
    path = CONTRACT["record"]["path"]
    assert "{{" not in path and "run_id" not in path


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_the_document_step_is_told_to_write_from_the_record():
    step = next(s for s in STEPS
                if str(s.get("command") or "").endswith(".documents"))
    args = " ".join(str(step["input"]["args"]).split())
    assert CONTRACT["record"]["path"] in args
    assert "cites the answer id" in args


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_the_apply_step_is_told_to_choose_from_the_record():
    # The step that picks the stack, the boundary and the Epic set is the one
    # whose choices previously derived from the single paragraph.
    step = next(s for s in STEPS if s.get("id") == CONTRACT["runs_before"]["step"])
    prompt = " ".join(str(step["prompt"]).split())
    assert CONTRACT["record"]["path"] in prompt


# --- the reason clarify is not the instrument ---------------------------------

@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_no_workflow_calls_clarify_and_the_reason_is_written_down():
    # The issue asked for one or the other: either calling it is the fix, or
    # the reason none of the fourteen do is recorded. It is a feature-spec
    # command -- it aborts on `check-prerequisites.sh` with "Feature directory
    # not found" and writes into that spec's `## Clarifications` -- and
    # bootstrap has no feature and no spec.
    for path in (ROOT / "bundle/components/workflows").glob("*/workflow.yml"):
        assert "speckit.clarify" not in path.read_text(encoding="utf-8"), path
    policy_text = (ROOT / "policy/bootstrap-policy.yml").read_text(encoding="utf-8")
    assert "check-prerequisites.sh" in policy_text
    assert "FEATURE_SPEC" in policy_text


# --- the command runs -----------------------------------------------------------

@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_the_plan_runs_and_asks_nothing(tmp_path):
    # A script that claimed to put a question to a person would report an
    # interview it never ran.
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "elicit.py"), "--plan",
         "--policy-root", str(ROOT), "--format", "json"],
        text=True, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert len(__import__("json").loads(r.stdout)["questions"]) == \
        len(CONTRACT["questions"])


@pytest.mark.req("REQ-PRODUCT-ELICITATION-001")
def test_an_absent_record_refuses_rather_than_passing(tmp_path):
    # A missing record is an interview that did not happen, and every document
    # written after it would encode answers nobody gave.
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "elicit.py"), "--check",
         "--policy-root", str(ROOT), "--record", str(tmp_path / "absent.yml")],
        text=True, capture_output=True, timeout=60)
    assert r.returncode == 2
    assert "does not exist" in r.stderr
