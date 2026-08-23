"""The discovery record is evidence, and must be consumable as a whole.

Three workflows read it. A consumer that reads nine of eleven sections and
proceeds is worse than one that stops: it produces a confident answer from an
incomplete picture. So an incomplete record is blocking rather than advisory.
"""
from __future__ import annotations

import importlib.util
import sys

import pytest

from lib.inventory import ROOT, load_inventory, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
spec = importlib.util.spec_from_file_location("discover", SCRIPTS / "discover.py")
dis = importlib.util.module_from_spec(spec)
sys.modules["discover"] = dis
spec.loader.exec_module(dis)

SCHEMA = dis.load_schema(ROOT)
SECTIONS = SCHEMA["required"]


def record(**over):
    base = {s: ["something worth saying"] for s in SECTIONS}
    base["scope"] = ["examined the parser; did not examine the CLI"]
    base["current_behaviour"] = [
        {"statement": "rejects an empty payload", "source": "specified"}]
    base["open_uncertainty"] = ["why the retry count is three"]
    base.update(over)
    return base


# --- completeness -------------------------------------------------------------

@pytest.mark.req("REQ-UNCERTAINTY-DISCOVER-001")
def test_a_complete_record_validates():
    assert dis.check(record(), SCHEMA) == []


@pytest.mark.req("REQ-UNCERTAINTY-DISCOVER-001")
@pytest.mark.parametrize("section", SECTIONS)
def test_a_missing_section_is_blocking(section):
    incomplete = {k: v for k, v in record().items() if k != section}
    assert dis.check(incomplete, SCHEMA)


@pytest.mark.req("REQ-UNCERTAINTY-DISCOVER-001")
def test_an_empty_section_is_blocking_not_ignored():
    # An absent finding and an uninvestigated area look identical afterwards,
    # and only one is safe to build on.
    problems = dis.check(record(safe_seams=[]), SCHEMA)
    assert problems and "does not distinguish" in problems[0]


def test_an_unknown_section_is_rejected():
    assert dis.check(record(vibes=["good"]), SCHEMA)


# --- evidence, not intent -----------------------------------------------------

@pytest.mark.req("REQ-UNCERTAINTY-DISCOVER-001")
def test_a_behaviour_observation_must_declare_its_source():
    bad = record(current_behaviour=[{"statement": "does a thing"}])
    assert dis.check(bad, SCHEMA)


@pytest.mark.req("REQ-UNCERTAINTY-DISCOVER-001")
@pytest.mark.parametrize("source", ["assumed", "obvious", "probably"])
def test_a_source_outside_the_vocabulary_is_rejected(source):
    bad = record(current_behaviour=[{"statement": "x", "source": source}])
    assert dis.check(bad, SCHEMA)


@pytest.mark.req("REQ-UNCERTAINTY-DISCOVER-001")
def test_inferred_observations_are_surfaced_for_reconciliation():
    rec = record(current_behaviour=[
        {"statement": "retries three times", "source": "inferred"},
        {"statement": "rejects empty input", "source": "specified"}])
    notes = " ".join(dis.advisories(rec))
    assert "1 of 2" in notes and "reconciled" in notes


def test_the_vocabulary_comes_from_policy():
    policy = load_yaml(ROOT / "policy/artifact-policy.yml")
    sources = policy["artifacts"]["discovery_notes"]["record"]["behaviour_sources"]
    assert set(SCHEMA["properties"]["current_behaviour"]["items"]
               ["properties"]["source"]["enum"]) == set(sources)


# --- advisories ---------------------------------------------------------------

def test_a_record_with_no_open_uncertainty_is_questioned():
    # Bounded discovery that answered everything is unusual.
    notes = dis.advisories(record(open_uncertainty=[]))
    assert any("resolved by guessing" in n for n in notes)


def test_a_scope_that_does_not_say_what_was_excluded_is_questioned():
    notes = dis.advisories(record(scope=["looked at the parser"]))
    assert any("deliberately not examined" in n for n in notes)


def test_advisories_are_not_raised_for_a_good_record():
    assert dis.advisories(record()) == []


# --- loading ------------------------------------------------------------------

def test_a_record_may_be_fenced(tmp_path):
    path = tmp_path / "d.md"
    path.write_text("# Discovery\n\n```yaml\nscope:\n  - a\n```\n", encoding="utf-8")
    assert dis.load_record(path)["scope"] == ["a"]


def test_a_record_that_is_not_a_mapping_is_refused(tmp_path):
    path = tmp_path / "d.md"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        dis.load_record(path)


# --- the workflow -------------------------------------------------------------

@pytest.mark.req("REQ-UNCERTAINTY-DISCOVER-001")
def test_the_workflow_states_scope_before_investigating():
    wf = load_inventory().by_id("workflow", "lifecycle-discover")
    ids = [s["id"] for s in wf.manifest["steps"]]
    assert ids.index("state-scope") < ids.index("investigate")


def test_the_workflow_validates_before_the_gate():
    wf = load_inventory().by_id("workflow", "lifecycle-discover")
    ids = [s["id"] for s in wf.manifest["steps"]]
    assert ids.index("validate-record") < ids.index("approve-record")


@pytest.mark.req("REQ-UNCERTAINTY-DISCOVER-001")
def test_the_workflow_writes_nothing_to_github():
    # Discovery is read-only. A transition here would make evidence into intent.
    wf = load_inventory().by_id("workflow", "lifecycle-discover")
    commands = {s.get("command") for s in wf.manifest["steps"] if s.get("command")}
    assert "speckit.github-lifecycle.transition" not in commands
    assert "speckit.github-lifecycle.capture" not in commands
