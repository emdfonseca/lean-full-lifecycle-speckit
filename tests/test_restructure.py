"""Split and merge, offline.

Both end the original, and the question the backlog usually loses is what
became of it. These tests concentrate on that, and on the one rule that is easy
to violate by writing the obvious implementation: a split must not make the new
Stories children of the old one.
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
_load("capture")
rt = _load("retire")
rs = _load("restructure")
MACHINE = rt.load_machine(ROOT)

GOOD = ("**Scope**\nx\n\n**Acceptance criteria**\n\nAC1 — a\n  Given a\n"
        "  When b\n  Then c\n\n**Risk**\nLow.")


class Repo:
    def __init__(self, issues=None, children=None, parents=None):
        self.issues = issues or {1: "open"}
        self.kids = children or {}
        self.parents = parents or {}
        self.created: list[dict] = []
        self.patched: dict[int, dict] = {}
        self.sub_issue_posts: list[tuple[int, int]] = []
        self.next = 50

    def __call__(self, args, stdin):
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        body = json.loads(stdin or "{}")
        if url.endswith("/sub_issues") and method == "POST":
            n = int(url.split("/issues/")[1].split("/")[0])
            child_id = body.get("sub_issue_id")
            child = int(child_id) - 1000        # ids are 1000 + number here
            self.sub_issue_posts.append((n, child))
            self.kids.setdefault(n, []).append(child)
            return self._ok({})
        if url.endswith("/sub_issues"):
            n = int(url.split("/issues/")[1].split("/")[0])
            return self._ok([{"number": c} for c in self.kids.get(n, [])])
        if url.endswith("/comments"):
            return self._ok({"id": 1})
        if url.endswith("/issues") and method == "POST":
            n = self.next
            self.next += 1
            self.issues[n] = "open"
            self.created.append({"number": n, **body})
            return self._ok({"number": n})
        if "/issues/" in url:
            n = int(url.rsplit("/", 1)[-1])
            if n not in self.issues:
                return subprocess.CompletedProcess([], 1, "", "gh: Not Found (HTTP 404)")
            if method == "PATCH":
                self.patched[n] = body
                self.issues[n] = "closed"
            payload = {"number": n, "id": 1000 + n, "state": self.issues[n],
                       "state_reason": self.patched.get(n, {}).get("state_reason"),
                       "labels": [{"name": "story"}]}
            if n in self.parents:
                payload["parent_issue_url"] = f"https://api.github.com/repos/o/r/issues/{self.parents[n]}"
            return self._ok(payload, args)
        return self._ok({})

    @staticmethod
    def _ok(payload, args=None):
        # Honour --jq the way the real gh does. A fake that ignores it returns
        # a whole payload where the caller asked for one field, and the caller
        # then compares a dict to a string and quietly takes the wrong branch.
        if args and "--jq" in args:
            expr = args[args.index("--jq") + 1]
            if expr.startswith(".") and isinstance(payload, dict):
                payload = payload.get(expr[1:])
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")


def client(repo):
    return gh_api.GitHub(runner=repo, sleep=lambda _: None, max_attempts=1)


def wire(monkeypatch):
    """Board placement is capture's job and has its own tests."""
    import capture
    monkeypatch.setattr(capture, "place_on_board",
                        lambda *a, **k: {"on_board": True, "delivery_state": "Inbox"})


TWO = [{"title": "First half", "body": GOOD}, {"title": "Second half", "body": GOOD}]


@pytest.mark.req("REQ-BACKLOG-RESTRUCTURE-001")
def test_a_split_creates_siblings_never_children(monkeypatch):
    # item-types.yml declares only Epics decomposable. Making the new Stories
    # children of the old one is the obvious implementation and the wrong one.
    wire(monkeypatch)
    repo = Repo(issues={1: "open", 9: "open"}, parents={1: 9})
    result = rs.split(client(repo), "o/r", 1, TWO, "too large to start", MACHINE)
    assert result["action"] == "split"
    assert result["parent"] == 9
    assert all(parent != 1 for parent, _ in repo.sub_issue_posts), \
        "a new Story was made a child of the Story being split"


@pytest.mark.req("REQ-BACKLOG-RESTRUCTURE-001")
def test_a_split_ends_the_original_naming_its_successors(monkeypatch):
    wire(monkeypatch)
    repo = Repo(issues={1: "open"})
    result = rs.split(client(repo), "o/r", 1, TWO, "too large", MACHINE)
    assert repo.patched[1]["state_reason"] == "not_planned"
    assert result["original"]["action"] == "retired"
    assert "Split into" in result["original"]["reason"]
    for number in result["created"]:
        assert f"#{number}" in result["original"]["reason"]


@pytest.mark.req("REQ-BACKLOG-RESTRUCTURE-001")
def test_a_split_into_one_is_refused(monkeypatch):
    wire(monkeypatch)
    repo = Repo()
    result = rs.split(client(repo), "o/r", 1, TWO[:1], "x", MACHINE)
    assert result["action"] == "refused"
    assert repo.created == []


@pytest.mark.req("REQ-BACKLOG-RESTRUCTURE-001")
def test_a_split_with_no_reason_is_refused(monkeypatch):
    wire(monkeypatch)
    repo = Repo()
    result = rs.split(client(repo), "o/r", 1, TWO, "  ", MACHINE)
    assert result["action"] == "refused"
    assert repo.created == []


@pytest.mark.req("REQ-BACKLOG-RESTRUCTURE-001")
def test_a_split_that_would_strand_children_is_refused(monkeypatch):
    wire(monkeypatch)
    repo = Repo(issues={1: "open", 2: "open"}, children={1: [2]})
    result = rs.split(client(repo), "o/r", 1, TWO, "too large", MACHINE)
    assert result["action"] == "refused"
    assert "open children [2]" in result["problems"][0]
    assert repo.created == [], "children were stranded and Stories created anyway"


@pytest.mark.req("REQ-BACKLOG-RESTRUCTURE-001")
def test_merging_supersedes_the_dropped_item():
    repo = Repo(issues={1: "open", 2: "open"})
    result = rs.merge(client(repo), "o/r", keep=1, drop=2,
                      reason="same work as #1", machine=MACHINE)
    assert result["action"] == "merged"
    assert repo.patched[2]["state_reason"] == "duplicate"
    assert 1 not in repo.patched, "the kept item was modified"


@pytest.mark.req("REQ-BACKLOG-RESTRUCTURE-001")
def test_merging_an_item_with_itself_is_refused():
    repo = Repo()
    result = rs.merge(client(repo), "o/r", keep=1, drop=1, reason="x",
                      machine=MACHINE)
    assert result["action"] == "refused"
    assert repo.patched == {}


@pytest.mark.req("REQ-BACKLOG-RESTRUCTURE-001")
def test_merging_with_no_reason_is_refused():
    repo = Repo(issues={1: "open", 2: "open"})
    result = rs.merge(client(repo), "o/r", keep=1, drop=2, reason="",
                      machine=MACHINE)
    assert result["action"] == "refused"
    assert repo.patched == {}


@pytest.mark.req("REQ-BACKLOG-RESTRUCTURE-001")
def test_merging_does_not_strand_the_dropped_items_children():
    repo = Repo(issues={1: "open", 2: "open", 3: "open"}, children={2: [3]})
    result = rs.merge(client(repo), "o/r", keep=1, drop=2, reason="same",
                      machine=MACHINE)
    assert result["action"] == "refused"
    assert "reparent them to #1" in result["problems"][0]
    assert repo.patched == {}


@pytest.mark.req("REQ-BACKLOG-RESTRUCTURE-001")
def test_split_and_merge_are_not_in_decompose():
    # decompose creates children under an Epic; these create siblings and end
    # the original. Two opposite models in one file is how the wrong one gets
    # called.
    source = (SCRIPTS / "decompose.py").read_text(encoding="utf-8")
    assert "def split(" not in source and "def merge(" not in source
