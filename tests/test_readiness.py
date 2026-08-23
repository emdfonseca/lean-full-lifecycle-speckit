"""The readiness verdict is evidence, not an assertion.

`state-machine.yml` requires `readiness_verdict_ready` for Refining to Ready.
Without validation that requirement is satisfied by writing the word "ready",
which is why the verdict is checked rather than read.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
spec = importlib.util.spec_from_file_location("readiness", SCRIPTS / "readiness.py")
rd = importlib.util.module_from_spec(spec)
sys.modules["readiness"] = rd
spec.loader.exec_module(rd)

SCHEMA = rd.load_schema(ROOT)

READY = {
    "readiness": "ready",
    "blocking_questions": [],
    "risk": "medium",
    "spec_impact": "create",
    "material_uncertainty": "none",
    "next_engineering_action": "Author the workflow.",
}


@pytest.mark.req("REQ-BACKLOG-READINESS-001")
def test_a_valid_ready_verdict_passes():
    assert rd.check(READY, SCHEMA) == []


@pytest.mark.req("REQ-BACKLOG-READINESS-001")
def test_ready_with_an_open_question_is_a_contradiction():
    verdict = {**READY, "blocking_questions": ["Which board is authoritative?"]}
    problems = rd.check(verdict, SCHEMA)
    assert problems and "blocking question" in problems[0]


@pytest.mark.req("REQ-BACKLOG-READINESS-001")
def test_not_ready_without_a_reason_is_refused():
    # Nothing says what would make it ready, so nobody can act on it.
    verdict = {**READY, "readiness": "not_ready", "blocking_questions": []}
    problems = rd.check(verdict, SCHEMA)
    assert problems and "nothing says what would make it ready" in problems[0]


@pytest.mark.req("REQ-BACKLOG-READINESS-001")
@pytest.mark.parametrize("field,value", [
    ("risk", "catastrophic"),
    ("readiness", "maybe"),
    ("material_uncertainty", "vibes"),
])
def test_a_value_outside_the_vocabulary_is_refused(field, value):
    assert rd.check({**READY, field: value}, SCHEMA)


def test_a_missing_field_is_refused():
    verdict = {k: v for k, v in READY.items() if k != "risk"}
    assert rd.check(verdict, SCHEMA)


def test_a_verdict_may_be_fenced_or_bare(tmp_path):
    bare = tmp_path / "bare.yml"
    bare.write_text("readiness: ready\nblocking_questions: []\n", encoding="utf-8")
    assert rd.load_verdict(bare)["readiness"] == "ready"

    fenced = tmp_path / "fenced.md"
    fenced.write_text("# Verdict\n\n```yaml\nreadiness: ready\n```\n", encoding="utf-8")
    assert rd.load_verdict(fenced)["readiness"] == "ready"


def test_a_verdict_that_is_not_a_mapping_is_refused(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        rd.load_verdict(path)


def test_the_schema_comes_from_installed_policy():
    # Not compiled in: changing the policy changes what is enforced.
    source = (SCRIPTS / "readiness.py").read_text(encoding="utf-8")
    assert "readiness-verdict.schema.json" in source
    assert '"enum"' not in source


# --- the path that was never executed ----------------------------------------

@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_a_not_ready_verdict_exits_non_zero(tmp_path):
    # `main()`'s `return 0 if readiness == "ready" else 1` had never run with
    # a not-ready verdict, so an item could pass Refining to Ready with the
    # gate reporting success.
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps({
        "readiness": "not_ready",
        "blocking_questions": ["Which of the two APIs is authoritative?"],
        "risk": "medium", "spec_impact": "update",
        "material_uncertainty": "discovery",
        "next_engineering_action": "Answer the blocking question first."}),
        encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "readiness.py"), "--verdict",
         str(verdict)],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0, result.stdout


@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_a_ready_verdict_exits_zero(tmp_path):
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps({
        "readiness": "ready", "blocking_questions": [], "risk": "low",
        "spec_impact": "none", "material_uncertainty": "none",
        "next_engineering_action": "Write the failing test first."}),
        encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "readiness.py"), "--verdict",
         str(verdict)],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_a_not_ready_verdict_with_no_blocking_question_is_still_not_ready(
        tmp_path):
    # Not-ready is the verdict, not a consequence of having questions.
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps({
        "readiness": "not_ready", "blocking_questions": [], "risk": "low",
        "spec_impact": "none", "material_uncertainty": "none",
        "next_engineering_action": "Split it; it is two stories."}),
        encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "readiness.py"), "--verdict",
         str(verdict)],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
