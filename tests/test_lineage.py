"""What an item was derived from, and the three answers a check can give.

The failure this guards against is quiet: a spec edited after an item was built
against it, so Output Done asserts acceptance criteria that have since moved.
Nothing recorded the derivation, so nothing could notice.

Two properties carry most of these tests. Drift must be *detected* -- content
changed, artifact deleted, artifact appeared late. And an absent record must
never read as a passing one, because "we never looked" and "nothing moved" are
the two answers that must not be confused here.

The third is quieter and is the story's stated risk: this record must never
become a second answer to what an item's delivery state is.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest
import yaml

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lineage = _load("lineage")

WORKFLOW = "lifecycle-story-delivery"


def project(tmp_path, produces=("spec.md", "plan.md", "checklists/")):
    """A source-shaped tree carrying one workflow that declares what it makes."""
    (tmp_path / ".specify").mkdir()
    d = tmp_path / "bundle/components/workflows" / WORKFLOW
    d.mkdir(parents=True)
    steps = [{"id": f"step-{i}", "command": "speckit.x", "produces": p}
             for i, p in enumerate(produces)]
    (d / "workflow.yml").write_text(
        yaml.safe_dump({"workflow": {"id": WORKFLOW}, "steps": steps},
                       sort_keys=False), encoding="utf-8")
    feature = tmp_path / "specs/001"
    (feature / "checklists").mkdir(parents=True)
    (feature / "spec.md").write_text("spec\n", encoding="utf-8")
    (feature / "plan.md").write_text("plan\n", encoding="utf-8")
    (feature / "checklists/req.md").write_text("c\n", encoding="utf-8")
    return tmp_path, feature


def record(root, feature, issue=1):
    lineage.write(root, lineage.build(root, issue, feature, WORKFLOW))


# --- the three answers --------------------------------------------------------

@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_a_changed_artifact_is_reported_and_named(tmp_path):
    root, feature = project(tmp_path)
    record(root, feature)
    (feature / "spec.md").write_text("changed\n", encoding="utf-8")

    findings = lineage.check(root, 1)
    assert [f["finding"] for f in findings] == [lineage.OUT_OF_BAND]
    assert findings[0]["path"] == "spec.md"


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_matching_hashes_report_no_drift(tmp_path):
    root, feature = project(tmp_path)
    record(root, feature)
    assert lineage.check(root, 1) == []


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_an_absent_record_is_a_finding_not_a_pass(tmp_path):
    # The one that matters most: returning "no drift" for a comparison that
    # never happened is the failure this module exists to prevent.
    root, _ = project(tmp_path)
    findings = lineage.check(root, 1)
    assert [f["finding"] for f in findings] == [lineage.ABSENT]
    assert "not an unchanged one" in findings[0]["detail"]


# --- the other two ways an artifact drifts ------------------------------------

@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_a_deleted_artifact_is_drift(tmp_path):
    root, feature = project(tmp_path)
    record(root, feature)
    (feature / "plan.md").unlink()
    findings = lineage.check(root, 1)
    assert [f["path"] for f in findings] == ["plan.md"]
    assert "now gone" in findings[0]["detail"]


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_an_artifact_that_appeared_after_recording_is_drift(tmp_path):
    # The item was derived without it, which is exactly as interesting as an
    # edit. A record that omitted absent artifacts could not tell.
    root, feature = project(tmp_path, produces=("spec.md", "tasks.md"))
    record(root, feature)
    (feature / "tasks.md").write_text("late\n", encoding="utf-8")
    findings = lineage.check(root, 1)
    assert [f["path"] for f in findings] == ["tasks.md"]
    assert "derived without it" in findings[0]["detail"]


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_a_file_added_to_a_directory_artifact_is_drift(tmp_path):
    root, feature = project(tmp_path)
    record(root, feature)
    (feature / "checklists/second.md").write_text("x\n", encoding="utf-8")
    assert [f["path"] for f in lineage.check(root, 1)] == ["checklists/"]


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_a_renamed_file_in_a_directory_artifact_is_drift(tmp_path):
    # Same bytes, different name. Hashing contents alone would miss it.
    root, feature = project(tmp_path)
    record(root, feature)
    (feature / "checklists/req.md").rename(feature / "checklists/other.md")
    assert [f["path"] for f in lineage.check(root, 1)] == ["checklists/"]


# --- what it records, and what it refuses to ----------------------------------

@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_the_artifacts_come_from_what_the_workflow_declares(tmp_path):
    # No list of artifact names lives in lineage.py: a step added to a workflow
    # extends the record with nothing to change there.
    root, feature = project(tmp_path, produces=("spec.md", "invented.md"))
    record(root, feature)
    stored = yaml.safe_load(lineage.record_path(root, 1).read_text())
    assert [a["path"] for a in stored["artifacts"]] == ["spec.md", "invented.md"]


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_a_workflow_declaring_nothing_is_refused_rather_than_recorded(tmp_path):
    root, feature = project(tmp_path, produces=())
    with pytest.raises(lineage.LineageError):
        lineage.build(root, 1, feature, WORKFLOW)


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_an_uninstalled_workflow_is_refused(tmp_path):
    root, feature = project(tmp_path)
    with pytest.raises(lineage.LineageError):
        lineage.build(root, 1, feature, "lifecycle-not-installed")


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_an_unreadable_record_is_not_read_as_absent(tmp_path):
    root, _ = project(tmp_path)
    path = lineage.record_path(root, 1)
    path.parent.mkdir(parents=True)
    path.write_text("::not yaml::\n:", encoding="utf-8")
    with pytest.raises(lineage.LineageError):
        lineage.check(root, 1)


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_the_record_carries_no_delivery_state(tmp_path):
    # The story's stated risk. A record that mentioned a state would sooner or
    # later be consulted for one, and the board owns that answer.
    root, feature = project(tmp_path)
    record(root, feature)
    machine = yaml.safe_load(
        (ROOT / "policy/state-machine.yml").read_text(encoding="utf-8"))
    stored = yaml.safe_load(lineage.record_path(root, 1).read_text())
    # No delivery state value anywhere in it, and no field that could be read
    # as one. The workflow id is recorded and happens to contain the word;
    # that is a component name, not a state.
    flat = yaml.safe_dump(stored)
    for state in machine["delivery_status"]["values"]:
        assert state not in flat
    assert set(stored) == {"issue", "workflow", "feature_dir", "revision",
                           "artifacts"}


# --- the command line ---------------------------------------------------------

@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_drift_exits_non_zero_so_a_gate_can_act_on_it(tmp_path):
    root, feature = project(tmp_path)
    record(root, feature)
    (feature / "spec.md").write_text("changed\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "lineage.py"), "--policy-root", str(root),
         "check", "--issue", "1"], capture_output=True, text=True)
    assert result.returncode == 1
    assert lineage.OUT_OF_BAND in result.stdout


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_a_clean_item_exits_zero(tmp_path):
    root, feature = project(tmp_path)
    record(root, feature)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "lineage.py"), "--policy-root", str(root),
         "check", "--issue", "1"], capture_output=True, text=True)
    assert result.returncode == 0


# --- the command's own contract -----------------------------------------------

@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_the_command_refuses_to_reconcile_or_re_record():
    text = (ROOT / "bundle/components/extensions/github-lifecycle/commands"
            / "lineage.md").read_text(encoding="utf-8")
    assert "Reconcile a stale artifact" in text
    assert "Re-record to clear a finding" in text
    assert "Treat an absent record as a passing one" in text


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_the_delivery_workflows_record_lineage_before_the_delivery_record():
    for wid in ("lifecycle-story-delivery", "lifecycle-bugfix"):
        steps = yaml.safe_load(
            (ROOT / "bundle/components/workflows" / wid / "workflow.yml")
            .read_text(encoding="utf-8"))["steps"]
        ids = [s["id"] for s in steps]
        assert ids.index("record-lineage") < ids.index("write-delivery-record")
        assert ids.index("converge") < ids.index("record-lineage")


@pytest.mark.req("REQ-TOOLING-LINEAGE-001")
def test_the_audit_asks_only_the_state_whose_artifacts_exist():
    """Refining and Ready have no feature directory to compare against.

    Scoping the audit to every state that "asserts work" reported six items
    that could not possibly have lineage, because `speckit.specify` creates the
    feature directory on the way into the delivering state. A rule that fires
    where nothing can be done is how the whole audit gets ignored.
    """
    source = (SCRIPTS / "transition_plan.py").read_text(encoding="utf-8")
    guard = source[source.index("lineage_findings(number") - 700:
                   source.index("lineage_findings(number")]
    assert "if value == START_STATE:" in guard
    # `asserts_work` still guards the closed-item rule; it must not guard this
    # one, which is the distinction the real board exposed.
    assert "asserts_work" not in guard
