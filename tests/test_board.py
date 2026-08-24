"""Creating the board the default deployment shape needs, offline.

ADR 0003 makes project-scoped fields the default and nothing created one. A
greenfield bootstrap produced a backlog nothing could transition, because
delivery_state lives on a board that did not exist.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from lib.inventory import ROOT

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
board = _load("board")


class Calls:
    """Records the gh invocations, and what each returned.

    Models what a real new board looks like: GitHub pre-creates a reserved
    single-select named Status carrying Todo/In Progress/Done. A fake without
    it would test a board GitHub does not make.
    """

    def __init__(self, fail_at=None, options=None, has_status=True):
        self.args: list[list[str]] = []
        self.fail_at = fail_at
        self.has_status = has_status
        self.options = list(options) if options is not None else [
            "Inbox", "Refining", "Ready", "In Progress", "Output Done"]
        self.reshaped = False
        self.on_board: list[int] = []

    def __call__(self, args):
        self.args.append(list(args))
        verb = args[2] if len(args) > 2 else ""
        if self.fail_at and verb == self.fail_at:
            return subprocess.CompletedProcess(args, 1, "", f"gh: {verb} refused")
        if verb == "graphql":
            self.reshaped = True
            return subprocess.CompletedProcess(args, 0, "{}", "")
        if verb == "create":
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"number": 7, "title": "t"}), "")
        if verb == "item-list":
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"items": [
                    {"content": {"number": n}} for n in self.on_board]}), "")
        if verb == "item-add":
            url = args[args.index("--url") + 1]
            self.on_board.append(int(url.rsplit("/", 1)[-1]))
            return subprocess.CompletedProcess(args, 0, "{}", "")
        if verb == "field-list":
            fields = []
            if self.has_status:
                opts = self.options if self.reshaped else [
                    "Todo", "In Progress", "Done"]
                fields.append({"id": "F1", "name": "Status",
                               "options": [{"name": o} for o in opts]})
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"fields": fields}), "")
        return subprocess.CompletedProcess(args, 0, "{}", "")


def wire(monkeypatch, existing=(), accepted=True):
    monkeypatch.setattr(board, "_is_org", lambda gh, owner: False)
    monkeypatch.setattr(it, "discover_projects", lambda gh, o, k: list(existing))
    monkeypatch.setattr(board.inspect_target, "discover_projects",
                        lambda gh, o, k: list(existing))
    result = type("I", (), {
        "backend": it.BACKEND_PROJECT if accepted else None,
        "roles": {"delivery_state": "Status"} if accepted else {},
    })()
    monkeypatch.setattr(board.inspect_target, "inspect",
                        lambda gh, o, r, n: result)


def _repo_issues(monkeypatch, numbers):
    class Fake:
        def rest(self, method, url, **kw):
            return [{"number": n} for n in numbers]
    return Fake()


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_the_field_and_its_options_come_from_policy():
    # A board that disagreed with the state machine about what a state is
    # would be worse than no board.
    import yaml
    name, options = board.delivery_field(ROOT)
    machine = yaml.safe_load((ROOT / "policy/state-machine.yml").read_text())
    assert options == machine["delivery_status"]["values"]
    assert options[0] == "Inbox"
    source = (SCRIPTS / "board.py").read_text()
    for state in options:
        assert f'"{state}"' not in source, f"{state} is hardcoded in board.py"


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_creating_makes_the_field_and_links_the_repo(monkeypatch):
    wire(monkeypatch)
    calls = Calls()
    result = board.create("acme", "widgets", "Widgets", ROOT,
                          runner=calls, gh=_repo_issues(None, []))
    assert result["action"] == "created"
    assert result["project_number"] == 7
    verbs = [a[2] for a in calls.args]
    # GitHub pre-creates a reserved Status field, so the existing one is
    # reshaped by GraphQL rather than a new one created.
    assert "graphql" in verbs and "field-create" not in verbs
    assert "link" in verbs
    assert result["reshaped_existing_field"] is True
    assert any("acme/widgets" in " ".join(a) for a in calls.args)


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_an_existing_board_is_not_joined_by_a_second(monkeypatch):
    # authoritative_project_count is 1. Choosing between two is not this
    # command's decision.
    wire(monkeypatch, existing=[{"number": 3, "title": "Existing"}])
    calls = Calls()
    result = board.create("acme", "widgets", "Widgets", ROOT,
                          runner=calls, gh=_repo_issues(None, []))
    assert result["action"] == "refused"
    assert "#3" in result["problems"][0]
    assert calls.args == [], "a refusal still wrote"


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_a_board_without_its_field_is_reported_not_left_silently(monkeypatch):
    # The worst outcome is a board that exists and cannot carry a state.
    wire(monkeypatch)
    with pytest.raises(gh_api.GitHubError, match="unusable until"):
        board.create("acme", "widgets", "Widgets", ROOT,
                     runner=Calls(fail_at="graphql"), gh=_repo_issues(None, []))


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_a_board_that_cannot_be_linked_is_reported(monkeypatch):
    wire(monkeypatch)
    with pytest.raises(gh_api.GitHubError, match="could not link"):
        board.create("acme", "widgets", "Widgets", ROOT,
                     runner=Calls(fail_at="link"), gh=_repo_issues(None, []))


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_the_board_is_read_back_not_the_repositorys_chosen_backend(monkeypatch):
    # Three writes that each returned zero are not a working board. The field
    # is fetched again and its options compared to the policy.
    #
    # The board is read, not `inspect()`: an organization carrying Issue Fields
    # resolves to that backend whatever boards exist, so asking which backend
    # would be chosen reports a correct board as a failure. That is what a live
    # run did.
    wire(monkeypatch)
    calls = Calls()
    calls.options = ["Todo", "In Progress", "Done"]   # reshape silently no-ops
    with pytest.raises(gh_api.GitHubError, match="not the states"):
        board.create("acme", "widgets", "Widgets", ROOT,
                     runner=calls, gh=_repo_issues(None, []))


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_a_board_with_no_status_field_creates_one(monkeypatch):
    # Not every board carries the reserved field; if it is absent, create it.
    wire(monkeypatch)
    calls = Calls(has_status=False)
    with pytest.raises(gh_api.GitHubError, match="not on it when read back"):
        board.create("acme", "widgets", "Widgets", ROOT,
                     runner=calls, gh=_repo_issues(None, []))
    assert "field-create" in [a[2] for a in calls.args]


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_a_dry_run_writes_nothing(monkeypatch):
    wire(monkeypatch)
    calls = Calls()
    result = board.create("acme", "widgets", "Widgets", ROOT,
                          runner=calls, gh=_repo_issues(None, []), dry_run=True)
    assert result["action"] == "dry-run"
    assert calls.args == []


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_no_board_is_a_refusal_not_a_note():
    # It was a note, which reads as information. With no board there is
    # nowhere for delivery_state to live and nothing can be transitioned.
    source = (SCRIPTS / "inspect_target.py").read_text()
    branch = source.split("if not projects:")[1].split("return None")[0]
    assert "ambiguities.append" in branch
    assert "notes.append" not in branch


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_existing_issues_are_reported_as_not_on_the_board(monkeypatch):
    # Linking a project to a repository does not put its issues on it. A board
    # created after the backlog leaves every item off, and an empty board
    # reads as a working one.
    wire(monkeypatch)
    calls = Calls()
    result = board.create("acme", "widgets", "Widgets", ROOT,
                          runner=calls, gh=_repo_issues(monkeypatch, [1, 2, 3]))
    assert result["issues_not_on_the_board"] == [1, 2, 3]
    assert "invisible to the queue and the audit" in result["note"]
    assert "item-add" not in [a[2] for a in calls.args], "adopted without --adopt"


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_adopt_places_them_and_reports_what_landed(monkeypatch):
    wire(monkeypatch)
    calls = Calls()
    result = board.create("acme", "widgets", "Widgets", ROOT, runner=calls,
                          gh=_repo_issues(monkeypatch, [1, 2, 3]), adopt=True)
    assert result["adopted"] == [1, 2, 3]
    assert result["issues_not_on_the_board"] == []


@pytest.mark.req("REQ-GITHUB-BOARD-003")
def test_a_board_whose_items_cannot_be_listed_reports_every_issue(monkeypatch):
    # "Could not look" is reported as "none on the board" rather than as
    # "all on the board": the conservative direction for a rule whose job is
    # noticing items nothing can see.
    wire(monkeypatch)
    calls = Calls(fail_at="item-list")
    orphans = board._unplaced_issues(
        _repo_issues(monkeypatch, [1, 2]), "acme", "widgets", 7, calls)
    assert orphans == [1, 2]
