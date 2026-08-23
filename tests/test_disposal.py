"""A prototype or spike must say what becomes of what it produced.

The failure this prevents is quiet. Nobody decides to ship prototype code; it
stays because deleting it needs a reason and keeping it needs none. Requiring
the decision inverts that, so most of these tests are about the refusals.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from lib.inventory import ROOT, load_inventory, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(SCRIPTS))
gh_api = _load("github_api")
it = _load("inspect_target")
_load("field_backend")
_load("relationships")
_load("capture")
tp = _load("transition_plan")
dsp = _load("disposal")

SCHEMA = dsp.load_schema(ROOT)
CONTRACT = dsp.load_contract(ROOT)


def record(**over):
    base = {
        "kind": "prototype",
        "questions": ["Can the panel show three states without a modal?"],
        "findings": ["Yes, with a split pane."],
        "decision": "delete",
        "artifacts": ["prototypes/panel/"],
    }
    base.update(over)
    return base


def spike(**over):
    base = record(kind="spike", question="Which queue survives a restart?",
                  permitted_scope="two libraries, local broker",
                  required_evidence="a restart under load",
                  time_box="one day", exit_criteria="either survives, or neither")
    base.update(over)
    return base


# --- the record ---------------------------------------------------------------

@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
def test_a_complete_prototype_record_validates():
    assert dsp.check(record(), SCHEMA, CONTRACT) == []


@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
def test_promotion_requires_an_approver_and_a_reason():
    problems = dsp.check(record(decision="promote"), SCHEMA, CONTRACT)
    assert problems and "approver" in problems[0] and "reason" in problems[0]


def test_promotion_with_both_is_accepted():
    assert dsp.check(record(decision="promote", approver="a reviewer",
                            reason="the interaction is the product"),
                     SCHEMA, CONTRACT) == []


@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
@pytest.mark.parametrize("decision", ["delete", "archive"])
def test_disposal_must_name_the_artifacts(decision):
    problems = dsp.check(record(decision=decision, artifacts=[]), SCHEMA, CONTRACT)
    assert any("artifacts are named" in p or "check the disposal" in p
               for p in problems)


@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
def test_a_spike_must_state_its_boundary():
    bare = record(kind="spike")
    problems = dsp.check(bare, SCHEMA, CONTRACT)
    assert problems and "boundary before it starts" in problems[0]


def test_a_bounded_spike_validates():
    assert dsp.check(spike(), SCHEMA, CONTRACT) == []


@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
def test_unresolved_is_a_legitimate_finding():
    # A prototype that answered nothing has still told you something.
    assert dsp.check(record(findings=["unresolved: ran out of time box"]),
                     SCHEMA, CONTRACT) == []


def test_silence_is_not_a_finding():
    problems = dsp.check(record(findings=[]), SCHEMA, CONTRACT)
    assert any("silence is not" in p for p in problems)


@pytest.mark.parametrize("decision", ["keep", "maybe", "later"])
def test_a_decision_outside_the_vocabulary_is_refused(decision):
    assert dsp.check(record(decision=decision), SCHEMA, CONTRACT)


def test_the_vocabulary_comes_from_policy():
    policy = load_yaml(ROOT / "policy/artifact-policy.yml")
    decisions = policy["artifacts"]["prototype"]["disposal_record"]["decisions"]
    assert set(SCHEMA["properties"]["decision"]["enum"]) == set(decisions)


# --- the guard on completion --------------------------------------------------

class Repo:
    def __init__(self, labels):
        self.labels = labels

    def __call__(self, args, stdin):
        return subprocess.CompletedProcess(
            [], 0, json.dumps({"number": 1,
                               "labels": [{"name": l} for l in self.labels]}), "")


def inspection():
    return it.Inspection(
        owner="o", repo="r", owner_type="User", backend=it.BACKEND_PROJECT,
        issue_fields_available=False, issue_types_available=False,
        sub_issues_available=True, dependencies_available=True, project_number=3,
        fields={}, roles={"delivery_state": "Status"})


@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
@pytest.mark.parametrize("label", ["prototype", "spike"])
def test_completion_requires_a_disposal_record(label, tmp_path):
    gh = gh_api.GitHub(runner=Repo([label, "story"]), sleep=lambda _: None)
    assert tp.disposal_required("In Progress", 1, inspection(), gh, root=tmp_path)


@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
def test_an_ordinary_item_is_unaffected(tmp_path):
    gh = gh_api.GitHub(runner=Repo(["story"]), sleep=lambda _: None)
    assert not tp.disposal_required("In Progress", 1, inspection(), gh, root=tmp_path)


@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
def test_a_present_record_satisfies_the_guard(tmp_path):
    directory = tmp_path / tp.DISPOSAL_DIR
    directory.mkdir(parents=True)
    (directory / "1-abc.md").write_text("kind: spike\n", encoding="utf-8")
    gh = gh_api.GitHub(runner=Repo(["spike"]), sleep=lambda _: None)
    assert not tp.disposal_required("In Progress", 1, inspection(), gh, root=tmp_path)


# --- the workflows ------------------------------------------------------------

@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
@pytest.mark.parametrize("wf_id", ["lifecycle-prototype", "lifecycle-spike"])
def test_each_uncertainty_workflow_ends_in_a_disposal_decision(wf_id):
    wf = load_inventory().by_id("workflow", wf_id)
    ids = [s["id"] for s in wf.manifest["steps"]]
    assert "record-disposal" in ids
    assert ids.index("record-disposal") < ids.index("validate-disposal")
    assert ids.index("validate-disposal") < ids.index("approve-disposal")


@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
@pytest.mark.parametrize("wf_id", ["lifecycle-prototype", "lifecycle-spike"])
def test_neither_workflow_uses_production_data(wf_id):
    """Any mention of production must be a prohibition, not an instruction.

    Asserted this way because the prototype workflow legitimately says
    production data is out of scope, and a test searching for the phrase
    cannot tell a rule from its violation.
    """
    import re

    wf = load_inventory().by_id("workflow", wf_id)
    text = " ".join(json.dumps(wf.manifest).lower().split())
    # Only data access counts. "production code" and "carried into production"
    # are prose about the destination, not instructions to reach into it.
    access = (r"production (?:data|credential|credentials|database|secrets)"
              r"|live data|prod credentials")
    for match in re.finditer(access, text):
        window = text[max(0, match.start() - 90):match.end() + 90]
        assert any(word in window for word in
                   ("out of scope", "not ", "never", "avoid", "no ")), (
            f"{wf_id} mentions {match.group(0)!r} without forbidding it")


@pytest.mark.req("REQ-UNCERTAINTY-DISPOSAL-001")
def test_the_prototype_workflow_explicitly_excludes_production_data():
    # Stated rather than merely absent: a prototype touching real data is the
    # failure worth naming, not one to leave to inference.
    wf = load_inventory().by_id("workflow", "lifecycle-prototype")
    text = json.dumps(wf.manifest).lower()
    assert "production credentials and production data are out of scope" in text
    assert "fake or local data" in text


def test_the_spike_states_its_boundary_before_investigating():
    wf = load_inventory().by_id("workflow", "lifecycle-spike")
    ids = [s["id"] for s in wf.manifest["steps"]]
    assert ids.index("bound-the-spike") < ids.index("investigate")
