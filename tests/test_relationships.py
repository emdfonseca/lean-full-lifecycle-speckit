"""Hierarchy and dependencies, offline.

A structural write that reports success without taking effect is harder to
notice than a wrong field value: nothing looks wrong until a parent completes
over work that was never attached to it. So every link is read back, and the
tests concentrate on the writes that must not happen at all.
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
rel = _load("relationships")


class Repo:
    """Issues with containment and dependencies, remembering writes."""

    def __init__(self, parents=None, deps=None, missing=()):
        self.parents = dict(parents or {})       # child -> parent
        self.deps = {k: list(v) for k, v in (deps or {}).items()}
        self.missing = set(missing)
        self.calls: list[list[str]] = []
        self.write_fails = False

    def __call__(self, args, stdin):
        self.calls.append(list(args))
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        number = int(url.split("/issues/")[1].split("/")[0])

        if url.endswith("/sub_issues"):
            if method == "POST":
                if not self.write_fails:
                    child = json.loads(stdin)["sub_issue_id"] - 1000
                    self.parents[child] = number
                return self._ok({})
            kids = [c for c, p in self.parents.items() if p == number]
            return self._ok([{"number": c} for c in kids])

        if url.endswith("/blocked_by"):
            if method == "POST":
                if not self.write_fails:
                    blocker = json.loads(stdin)["issue_id"] - 1000
                    self.deps.setdefault(number, []).append(
                        {"number": blocker, "state": "open",
                         "repository": {"full_name": "other/repo"}})
                return self._ok({})
            return self._ok(self.deps.get(number, []))

        if number in self.missing:
            return subprocess.CompletedProcess([], 1, "", "gh: Not Found (HTTP 404)")
        # A plain issue read: id and parent url.
        parent = self.parents.get(number)
        payload = {"id": number + 1000}
        if parent is not None:
            payload["parent_issue_url"] = f"https://api.github.com/repos/o/r/issues/{parent}"
        if "--jq" in args and args[args.index("--jq") + 1] == ".id":
            return self._ok(number + 1000)
        return self._ok(payload)

    @staticmethod
    def _ok(payload):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")


def client(repo):
    return gh_api.GitHub(runner=repo, sleep=lambda _: None, max_attempts=1)


# --- linking ------------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-RELATIONSHIPS-001")
def test_a_child_is_linked_and_read_back():
    repo = Repo()
    link = rel.link_child(client(repo), "o/r", parent=1, child=2)
    assert not link.already_present
    assert rel.children(client(repo), "o/r", 1) == [2]


@pytest.mark.req("REQ-GITHUB-RELATIONSHIPS-001")
def test_a_link_that_does_not_take_is_a_conflict():
    # The write returning success is not evidence the link exists.
    repo = Repo()
    repo.write_fails = True
    with pytest.raises(gh_api.Conflict) as exc:
        rel.link_child(client(repo), "o/r", parent=1, child=2)
    assert "did not take" in str(exc.value)


@pytest.mark.req("REQ-GITHUB-RELATIONSHIPS-001")
def test_linking_twice_writes_once():
    repo = Repo(parents={2: 1})
    link = rel.link_child(client(repo), "o/r", parent=1, child=2)
    assert link.already_present
    assert not any("POST" in c for c in repo.calls)


def test_linking_a_missing_issue_is_reported():
    repo = Repo(missing={2})
    with pytest.raises(gh_api.NotFound):
        rel.link_child(client(repo), "o/r", parent=1, child=2)


# --- cycles -------------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-RELATIONSHIPS-001")
def test_an_item_cannot_parent_itself():
    repo = Repo()
    with pytest.raises(rel.CycleError):
        rel.link_child(client(repo), "o/r", parent=1, child=1)
    assert not repo.calls


@pytest.mark.req("REQ-GITHUB-RELATIONSHIPS-001")
def test_a_direct_cycle_is_refused_before_any_write():
    repo = Repo(parents={2: 1})          # 2 is under 1
    with pytest.raises(rel.CycleError) as exc:
        rel.link_child(client(repo), "o/r", parent=2, child=1)
    assert "cycle" in str(exc.value)
    assert not any("POST" in c for c in repo.calls)


@pytest.mark.req("REQ-GITHUB-RELATIONSHIPS-001")
def test_an_indirect_cycle_is_refused():
    repo = Repo(parents={2: 1, 3: 2})    # 1 -> 2 -> 3
    with pytest.raises(rel.CycleError) as exc:
        rel.link_child(client(repo), "o/r", parent=3, child=1)
    assert "#3" in str(exc.value) and "#1" in str(exc.value)


def test_ancestor_walking_terminates_on_a_pre_existing_cycle():
    # Data can already be wrong; discovering that must not hang.
    repo = Repo(parents={1: 2, 2: 1})
    chain = rel.ancestors(client(repo), "o/r", 1)
    assert len(chain) <= 32


# --- dependencies -------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-RELATIONSHIPS-001")
def test_a_dependency_may_cross_repositories():
    repo = Repo()
    assert rel.add_blocker(client(repo), "o/r", 1, "other/repo", 99) is True
    found = rel.blockers(client(repo), "o/r", 1)
    assert found[0]["repository"]["full_name"] == "other/repo"


def test_adding_the_same_dependency_twice_writes_once():
    repo = Repo(deps={1: [{"number": 99, "state": "open",
                           "repository": {"full_name": "other/repo"}}]})
    assert rel.add_blocker(client(repo), "o/r", 1, "other/repo", 99) is False
    assert not any("POST" in c for c in repo.calls)


def test_an_issue_cannot_block_itself():
    repo = Repo()
    with pytest.raises(rel.CycleError):
        rel.add_blocker(client(repo), "o/r", 1, "o/r", 1)


def test_closed_blockers_are_excluded_by_default():
    repo = Repo(deps={1: [
        {"number": 98, "state": "closed", "repository": {"full_name": "o/r"}},
        {"number": 99, "state": "open", "repository": {"full_name": "o/r"}}]})
    assert [b["number"] for b in rel.blockers(client(repo), "o/r", 1)] == [99]
    assert len(rel.blockers(client(repo), "o/r", 1, include_closed=True)) == 2


def test_a_dependency_that_does_not_take_is_a_conflict():
    repo = Repo()
    repo.write_fails = True
    with pytest.raises(gh_api.Conflict):
        rel.add_blocker(client(repo), "o/r", 1, "other/repo", 99)
