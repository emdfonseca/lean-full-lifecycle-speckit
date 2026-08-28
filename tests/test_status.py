"""One composed status report, and what it refuses to claim.

The interesting property is not that the sections are present. It is that no
section is a second implementation: the queue buckets come from
`classify_queue`, the audit from `audit_board`, the wiring from
`doctor.report`, and the drift sentence from `working_tree_disagreement`. So
these tests drive the real modules behind a fake GitHub runner, and the only
things stubbed are the two subprocesses doctor shells out to.

The refusals matter more than the composition. A status command that answered
"0 startable" because it could not reach GitHub would be worse than one that
failed, so the unread-board cases assert the *absence* of the queue and audit
sections rather than their emptiness.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"

sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gh_api = _load("github_api")
it = _load("inspect_target")
fb = _load("field_backend")
tp = _load("transition_plan")
cfg = _load("config")
doctor = _load("doctor")
status = _load("status")

STATES = list(it.DELIVERY_STATES)
OPT = {s: f"{i + 1:08x}" for i, s in enumerate(STATES)}


def inspection():
    return it.Inspection(
        owner="acme", repo="widgets", owner_type="User",
        backend=it.BACKEND_PROJECT, issue_fields_available=False,
        issue_types_available=False, sub_issues_available=True,
        dependencies_available=True, project_number=3,
        fields={"Status": it.FieldRef("Status", "403", "single_select",
                                      options=dict(OPT))},
        roles={"delivery_state": "Status"},
    )


class BoardRunner:
    """Issues, their delivery states, labels and blockers. Reads only."""

    def __init__(self, issues, states, labels=None, blocked=None):
        self.issues = issues                  # number -> open | closed
        self.labels = labels or {}
        self.blocked = blocked or {}
        self.calls: list[list[str]] = []
        self.item_of, self.values = {}, {}
        item = 900
        for number, st in states.items():
            self.item_of[number] = item
            self.values[item] = {"403": OPT[st]} if st else {}
            item += 1

    def _ok(self, payload):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    def __call__(self, args, stdin):
        self.calls.append(list(args))
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        assert method == "GET", "status must never write"
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        if url.endswith("/sub_issues"):
            return self._ok([])
        if url.endswith("/blocked_by"):
            n = int(url.split("/issues/")[1].split("/")[0])
            return self._ok([
                {"number": num, "state": st, "repository": {"full_name": repo}}
                for repo, num, st in self.blocked.get(n, [])])
        if url.endswith("/issues"):
            return self._ok([
                {"number": n, "state": s,
                 "state_reason": "completed" if s == "closed" else None,
                 "labels": [{"name": lbl} for lbl in self.labels.get(n, [])]}
                for n, s in self.issues.items()])
        if url.endswith("/items"):
            return self._ok([{"id": i, "content": {"number": n}}
                             for n, i in self.item_of.items()])
        if "/items/" in url:
            item = int(url.rsplit("/", 1)[-1])
            rendered = [
                {"id": int(fid), "name": "Status",
                 "value": {"id": stored,
                           "name": {"raw": next((n for n, o in OPT.items()
                                                 if o == stored), None)}}}
                for fid, stored in self.values.get(item, {}).items()]
            return self._ok({"id": item, "fields": rendered})
        return self._ok("User")


def project(tmp_path):
    """A tree status will accept as a Spec Kit project, with the policy it reads."""
    (tmp_path / ".specify").mkdir()
    policy = tmp_path / "policy"
    policy.mkdir()
    (policy / "state-machine.yml").write_text(
        (ROOT / "policy/state-machine.yml").read_text(encoding="utf-8"),
        encoding="utf-8")
    ext = tmp_path / ".specify/extensions/github-lifecycle"
    ext.mkdir(parents=True)
    (ext / "github-lifecycle-config.yml").write_text(
        "organization: acme\nrepository: widgets\nproject_number: 3\n",
        encoding="utf-8")
    return tmp_path


@pytest.fixture
def quiet_doctor(monkeypatch):
    """Doctor without its two subprocesses; everything else it does runs."""
    monkeypatch.setattr(doctor, "run",
                        lambda command, timeout=20: {"status": "ok",
                                                     "command": command})


@pytest.fixture
def board(monkeypatch):
    """Install a fake board and hand back the runner that recorded the calls."""
    def install(issues, states, labels=None, blocked=None):
        runner = BoardRunner(issues, states, labels, blocked)
        gh = gh_api.GitHub(runner=runner, sleep=lambda _: None, max_attempts=1)
        insp = inspection()
        monkeypatch.setattr(
            tp, "open_target",
            lambda repo, project, audit=None, dry_run=False: (
                gh, insp, fb.ProjectFieldBackend(gh, insp)))
        return runner
    return install


# --- the composed report -----------------------------------------------------

@pytest.mark.req("REQ-CORE-STATUS-001")
def test_one_run_carries_target_queue_audit_and_working_tree(
        tmp_path, quiet_doctor, board):
    root = project(tmp_path)
    board({1: "open", 2: "open", 3: "closed"},
          {1: "Ready", 2: "Inbox", 3: "In Progress"},
          labels={1: ["story"], 2: ["epic"]})
    report, code = status.collect(root)

    assert code == 0
    assert report["target"]["repo"] == "acme/widgets"
    assert report["target"]["project"] == 3
    assert report["queue"]["startable"] == [{"issue": 1, "item_type": "story"}]
    assert report["queue"]["awaiting_decomposition"][0]["issue"] == 2
    # #3 is closed and left claiming somebody is working on it.
    assert report["audit"]["count"] == 1
    assert report["audit"]["findings"][0]["issue"] == 3
    assert report["working_tree"]["status"] in {"clean", "drift", "unknown"}
    assert report["doctor"]["config_source"] == "scaffolded"


@pytest.mark.req("REQ-CORE-STATUS-001")
def test_the_queue_buckets_are_the_ones_the_queue_command_produces(
        tmp_path, quiet_doctor, board):
    # Not a second classification: the same call, so a rule cannot mean one
    # thing here and another in `transition_plan queue`.
    root = project(tmp_path)
    runner = board({1: "open", 2: "open"}, {1: "Ready", 2: "Refining"},
                   labels={1: ["story"], 2: ["bug"]},
                   blocked={1: [("acme/other", 9, "open")]})
    report, _ = status.collect(root)
    entries = tp.ready_queue(
        gh_api.GitHub(runner=runner, sleep=lambda _: None, max_attempts=1),
        fb.ProjectFieldBackend(
            gh_api.GitHub(runner=runner, sleep=lambda _: None, max_attempts=1),
            inspection()),
        inspection())
    expected = tp.classify_queue(entries)
    assert [e["issue"] for e in report["queue"]["blocked"]] == \
        [e.issue for e in expected.blocked]
    assert report["queue"]["advice"] == expected.advice


@pytest.mark.req("REQ-CORE-STATUS-001")
def test_the_report_writes_nothing(tmp_path, quiet_doctor, board):
    root = project(tmp_path)
    runner = board({1: "open"}, {1: "Ready"}, labels={1: ["story"]})
    status.collect(root)
    # BoardRunner asserts GET on every call; this pins that it was exercised.
    assert runner.calls
    assert not any("--method" in c and c[c.index("--method") + 1] != "GET"
                   for c in runner.calls)


# --- what it refuses to claim ------------------------------------------------

@pytest.mark.req("REQ-CORE-STATUS-001")
def test_an_unconfigured_project_gets_the_doctor_and_no_board_state(
        tmp_path, quiet_doctor):
    root = tmp_path
    (root / ".specify").mkdir()
    report, code = status.collect(root)

    assert code == 2
    assert report["board"]["status"] == "unread"
    assert "no repository" in report["board"]["reason"]
    assert report["target"] is None
    assert "queue" not in report and "audit" not in report
    assert report["doctor"]["config_source"] == "missing"


@pytest.mark.req("REQ-CORE-STATUS-001")
def test_an_unusable_target_reports_why_rather_than_an_empty_queue(
        tmp_path, quiet_doctor, monkeypatch):
    root = project(tmp_path)

    def refuse(repo, project, audit=None, dry_run=False):
        raise tp.PlanError("target is not usable: missing=['delivery_state']")

    monkeypatch.setattr(tp, "open_target", refuse)
    report, code = status.collect(root)

    assert code == 2
    assert "queue" not in report and "audit" not in report
    assert "delivery_state" in report["board"]["reason"]
    # The target resolved; only the board did not. Saying so is the difference
    # between "not configured" and "configured at something unusable".
    assert report["target"]["repo"] == "acme/widgets"


@pytest.mark.req("REQ-CORE-STATUS-001")
def test_an_unread_board_leaves_the_tree_unattributed_rather_than_drifting(
        tmp_path, quiet_doctor, monkeypatch):
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: ["a.py"])
    root = tmp_path
    (root / ".specify").mkdir()
    report, code = status.collect(root)

    assert code == 2
    assert report["working_tree"]["status"] == "unattributed"
    assert report["working_tree"]["modified"] == ["a.py"]


@pytest.mark.req("REQ-CORE-STATUS-001")
def test_the_text_form_says_no_queue_follows_and_why(tmp_path, quiet_doctor):
    root = tmp_path
    (root / ".specify").mkdir()
    report, _ = status.collect(root)
    text = status.render(report)

    assert "Board: not read" in text
    assert "Startable now" not in text
    assert "empty board" in text


# --- the working tree section ------------------------------------------------

@pytest.mark.req("REQ-CORE-STATUS-001")
def test_a_tree_no_item_accounts_for_is_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: ["a.py"])
    tree = status.working_tree(tmp_path, [])
    assert tree["status"] == "drift"
    assert "In Progress" in tree["detail"]


@pytest.mark.req("REQ-CORE-STATUS-001")
def test_a_tree_an_item_accounts_for_names_that_item(tmp_path, monkeypatch):
    # The case the audit is silent on, and the one a resuming agent needs.
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: ["a.py"])
    tree = status.working_tree(tmp_path, [178])
    assert tree["status"] == "accounted"
    assert "#178" in tree["detail"]


@pytest.mark.req("REQ-CORE-STATUS-001")
def test_a_tree_git_could_not_read_is_unknown_not_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: None)
    tree = status.working_tree(tmp_path, [])
    assert tree["status"] == "unknown"
    assert tree["modified"] is None


@pytest.mark.req("REQ-CORE-STATUS-001")
def test_a_clean_tree_is_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: [])
    assert status.working_tree(tmp_path, [])["status"] == "clean"


# --- the two forms carry the same answer --------------------------------------

@pytest.mark.req("REQ-CORE-STATUS-001")
def test_the_json_form_parses_and_carries_the_text_form_fields(
        tmp_path, quiet_doctor, board):
    root = project(tmp_path)
    board({1: "open", 2: "open"}, {1: "Ready", 2: "Refining"},
          labels={1: ["story"], 2: ["bug"]})
    report, _ = status.collect(root)
    parsed = json.loads(json.dumps(report))

    assert set(parsed) == {"root", "doctor", "target", "board", "queue",
                           "audit", "working_tree"}
    text = status.render(report)
    assert "acme/widgets" in text
    assert "#1 [story]" in text
    assert parsed["queue"]["advice"] in text
    assert f"Audit ({parsed['audit']['count']} inconsistencies)" in text


@pytest.mark.req("REQ-CORE-STATUS-001")
def test_the_command_line_emits_json_on_request(tmp_path, quiet_doctor, board,
                                                monkeypatch, capsys):
    root = project(tmp_path)
    board({1: "open"}, {1: "Ready"}, labels={1: ["story"]})
    monkeypatch.setattr(sys, "argv",
                        ["status.py", "--format", "json",
                         "--policy-root", str(root)])
    assert status.main() == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["target"]["repo"] == "acme/widgets"


# --- the contract the command documents ---------------------------------------

@pytest.mark.req("REQ-CORE-STATUS-001")
def test_the_command_documents_that_it_never_transitions():
    text = (ROOT / "bundle/components/extensions/github-lifecycle/commands"
            / "status.md").read_text(encoding="utf-8")
    assert "Transition anything" in text
    assert "read-only" in text


@pytest.mark.req("REQ-CORE-STATUS-001")
def test_the_command_documents_the_exit_status_that_means_unread():
    text = (ROOT / "bundle/components/extensions/github-lifecycle/commands"
            / "status.md").read_text(encoding="utf-8")
    assert "`2` when the board could not be read" in text
