"""Retiring and superseding, offline.

Both close an item without delivering it. The value is in what they refuse:
a retirement with no reason, a supersession naming nothing, and either one
stranding live children.
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
_load("relationships")
rt = _load("retire")
MACHINE = rt.load_machine(ROOT)


class Repo:
    """Issues, their children, and what a PATCH did to them."""

    def __init__(self, issues=None, children=None):
        self.issues = issues or {1: "open", 2: "open"}
        self.kids = children or {}
        self.patched: dict[int, dict] = {}
        self.comments: list[tuple[int, str]] = []

    def __call__(self, args, stdin):
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        if url.endswith("/sub_issues"):
            n = int(url.split("/issues/")[1].split("/")[0])
            return self._ok([{"number": c} for c in self.kids.get(n, [])])
        if url.endswith("/comments") and method == "POST":
            n = int(url.split("/issues/")[1].split("/")[0])
            self.comments.append((n, json.loads(stdin or "{}").get("body", "")))
            return self._ok({"id": 1})
        if "/issues/" in url:
            n = int(url.rsplit("/", 1)[-1])
            if n not in self.issues:
                return subprocess.CompletedProcess([], 1, "", "gh: Not Found (HTTP 404)")
            if method == "PATCH":
                self.patched[n] = json.loads(stdin or "{}")
                self.issues[n] = "closed"
            state = self.issues[n]
            return self._ok({"number": n, "state": state, "id": 1000 + n,
                             "state_reason": self.patched.get(n, {}).get("state_reason")})
        return self._ok({})

    @staticmethod
    def _ok(payload):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")


def client(repo):
    return gh_api.GitHub(runner=repo, sleep=lambda _: None, max_attempts=1)


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_the_routes_come_from_policy():
    # A route added to state-machine.yml is available here without this file
    # changing.
    assert rt.undelivered_routes(MACHINE) == {
        "not_planned": "not_planned", "duplicate": "duplicate"}
    extended = {"closure": dict(MACHINE["closure"],
                                archived={"set_output_done": False,
                                          "close_reason": "archived"})}
    assert "archived" in rt.undelivered_routes(extended)


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_a_completed_route_is_not_offered():
    # Completing work is what transition is for. Offering it here would give
    # two ways to reach Output Done, one of them unaudited.
    assert "completed" not in rt.undelivered_routes(MACHINE)


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_retiring_records_the_reason_and_leaves_the_delivery_state():
    repo = Repo()
    result = rt.retire(client(repo), "o/r", 1, "overtaken by #2 and #3",
                       "not_planned", machine=MACHINE)
    assert result["action"] == "retired"
    assert repo.patched[1]["state_reason"] == "not_planned"
    assert result["delivery_state_unchanged"] is True
    assert "Status" not in json.dumps(repo.patched), \
        "retiring wrote a delivery state it was not entitled to set"
    assert any("overtaken by #2" in body for _, body in repo.comments)


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_a_retirement_with_no_reason_is_refused():
    repo = Repo()
    result = rt.retire(client(repo), "o/r", 1, "   ", "not_planned",
                       machine=MACHINE)
    assert result["action"] == "refused"
    assert any("no reason" in p for p in result["problems"])
    assert repo.patched == {}, "a refusal still wrote"


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_superseding_references_both_ends():
    repo = Repo()
    result = rt.retire(client(repo), "o/r", 1, "same work as #2", "duplicate",
                       superseded_by=2, machine=MACHINE)
    assert result["action"] == "retired"
    assert repo.patched[1]["state_reason"] == "duplicate"
    on_one = next(b for n, b in repo.comments if n == 1)
    on_two = next(b for n, b in repo.comments if n == 2)
    assert "Superseded by #2" in on_one
    assert "Supersedes #1" in on_two


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_superseding_without_naming_the_successor_is_refused():
    # Without the reference the work has been lost rather than moved.
    repo = Repo()
    result = rt.retire(client(repo), "o/r", 1, "duplicate of something",
                       "duplicate", machine=MACHINE)
    assert result["action"] == "refused"
    assert any("--superseded-by" in p for p in result["problems"])
    assert repo.patched == {}


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_an_item_cannot_supersede_itself():
    repo = Repo()
    result = rt.retire(client(repo), "o/r", 1, "x", "duplicate",
                       superseded_by=1, machine=MACHINE)
    assert result["action"] == "refused"
    assert any("supersede itself" in p for p in result["problems"])


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_open_children_are_not_stranded():
    # The case most likely to lose work.
    repo = Repo(issues={1: "open", 2: "open", 3: "open"}, children={1: [2, 3]})
    result = rt.retire(client(repo), "o/r", 1, "not needed", "not_planned",
                       machine=MACHINE)
    assert result["action"] == "refused"
    assert any("open children [2, 3]" in p for p in result["problems"])
    assert repo.patched == {}


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_closed_children_do_not_block_retirement():
    repo = Repo(issues={1: "open", 2: "closed"}, children={1: [2]})
    result = rt.retire(client(repo), "o/r", 1, "not needed", "not_planned",
                       machine=MACHINE)
    assert result["action"] == "retired"


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_an_undeclared_route_is_refused_without_touching_the_api():
    repo = Repo()
    result = rt.retire(client(repo), "o/r", 1, "x", "invented",
                       machine=MACHINE)
    assert result["action"] == "refused"
    assert repo.comments == [] and repo.patched == {}


@pytest.mark.req("REQ-BACKLOG-RETIRE-001")
def test_a_write_that_does_not_take_is_reported():
    # Same read-back guarantee the transition command gives: a write that
    # reports success while the read disagrees is not a success.
    class Stubborn(Repo):
        def __call__(self, args, stdin):
            method = args[args.index("--method") + 1] if "--method" in args else "GET"
            url = (args[args.index("--method") + 2] if "--method" in args
                   else args[args.index("api") + 1]).split("?")[0]
            if "/issues/" in url and method == "PATCH":
                return self._ok({"number": 1})          # accepted, changed nothing
            return super().__call__(args, stdin)

    repo = Stubborn()
    with pytest.raises(gh_api.GitHubError, match="did not take"):
        rt.retire(client(repo), "o/r", 1, "x", "not_planned", machine=MACHINE)
