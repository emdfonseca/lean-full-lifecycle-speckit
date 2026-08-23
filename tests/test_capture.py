"""Duplicate search and guarded creation, offline.

Capture's value is in what it refuses. A backlog that accepts everything is a
backlog nobody reads, so the tests concentrate on the two refusals: an item
that already exists, and an observation being filed as work.
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
cap = _load("capture")

EXISTING = [
    {"number": 40, "title": "Define backlog item types and their content contract",
     "state": "closed", "labels": []},
    {"number": 12, "title": "Author the lifecycle-triage workflow",
     "state": "open", "labels": []},
]


class Repo:
    def __init__(self, issues=None, drop_label=False):
        self.issues = list(issues if issues is not None else EXISTING)
        self.drop_label = drop_label
        self.calls: list[list[str]] = []
        self.next_number = 100

    def __call__(self, args, stdin):
        self.calls.append(list(args))
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        raw = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1])
        url, _, query = raw.partition("?")
        # The real API filters by ?state=; a fake that ignores it would test
        # the fake rather than the delegation.
        wanted_state = "all"
        for part in query.split("&"):
            if part.startswith("state="):
                wanted_state = part[len("state="):]
        if url.endswith("/issues") and method == "POST":
            body = json.loads(stdin or "{}")
            number = self.next_number
            self.next_number += 1
            labels = [] if self.drop_label else [{"name": l} for l in body.get("labels", [])]
            self.issues.append({"number": number, "id": 10000 + number,
                                "title": body["title"],
                                "state": "open", "labels": labels})
            return self._ok({"number": number})
        if url.endswith("/issues"):
            if wanted_state == "all":
                return self._ok(self.issues)
            return self._ok([i for i in self.issues if i["state"] == wanted_state])
        if "/issues/" in url:
            number = int(url.rsplit("/", 1)[-1])
            found = next((i for i in self.issues if i["number"] == number), None)
            return self._ok(found) if found else self._ok({})
        return self._ok({})

    @staticmethod
    def _ok(payload):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")


def client(repo):
    return gh_api.GitHub(runner=repo, sleep=lambda _: None, max_attempts=1)


# --- similarity ---------------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-CAPTURE-001")
def test_an_exact_title_matches():
    assert cap.similarity("Author the triage workflow",
                          "Author the triage workflow") == 1.0


@pytest.mark.req("REQ-BACKLOG-CAPTURE-001")
def test_a_reworded_title_still_matches():
    # The commonest duplicate is somebody's rewording, not a copy.
    score = cap.similarity(
        "Backlog item type definitions and content contracts",
        "Define backlog item types and their content contract")
    assert score >= cap.DEFAULT_THRESHOLD


def test_unrelated_titles_do_not_match():
    assert cap.similarity("Rotate the release signing key",
                          "Author the triage workflow") < cap.DEFAULT_THRESHOLD


@pytest.mark.parametrize("plural,singular", [
    ("types", "type"), ("contracts", "contract"), ("definitions", "definition"),
    ("boxes", "box"), ("classes", "class"),
])
def test_stemming_pairs_plural_with_singular(plural, singular):
    assert cap.stem(plural) == cap.stem(singular)


def test_stemming_leaves_a_word_that_merely_ends_in_s():
    # "process" is not a plural. Over-stripping is how "types" became "typ".
    assert cap.stem("process") == "process"


# --- searching ----------------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-CAPTURE-001")
def test_a_duplicate_is_surfaced_before_creation():
    repo = Repo()
    found = cap.search_duplicates(client(repo), "o/r",
                                  "Define backlog item types and their content contract")
    assert [c.number for c in found] == [40]


@pytest.mark.req("REQ-BACKLOG-CAPTURE-001")
def test_closed_issues_are_searched_too():
    # Something already fixed or rejected is exactly what a duplicate report
    # needs to surface.
    repo = Repo()
    found = cap.search_duplicates(client(repo), "o/r",
                                  "Define backlog item types and their content contract")
    assert found and found[0].state == "closed"
    assert not cap.search_duplicates(
        client(repo), "o/r", "Define backlog item types and their content contract",
        include_closed=False)


# --- refusing -----------------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-CAPTURE-001")
@pytest.mark.parametrize("item_type,body,missing", [
    ("bug", "It seems slow.", "reproduction"),
    ("story", "We should do the thing.", "acceptance"),
    ("spike", "Look into it.", "question"),
])
def test_an_observation_is_not_filed_as_work(item_type, body, missing):
    assert missing in cap.has_evidence(body, item_type)


def test_a_body_meeting_the_contract_is_accepted():
    body = "Reproduction: run x. Expected: y. Actual: z."
    assert cap.has_evidence(body, "bug") == []


# --- creating -----------------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-CAPTURE-001")
def test_creation_reads_back_the_type_label():
    repo = Repo()
    result = cap.create_item(client(repo), "o/r", "A new finding", "body", "story")
    assert result["number"] == 100


@pytest.mark.req("REQ-BACKLOG-CAPTURE-001")
def test_an_item_created_without_its_type_is_a_failure():
    # An untyped item has no content contract, so nothing can refine it.
    repo = Repo(drop_label=True)
    with pytest.raises(gh_api.GitHubError) as exc:
        cap.create_item(client(repo), "o/r", "A new finding", "body", "story")
    assert "type label" in str(exc.value)


# --- placement on the board ---------------------------------------------------

class StubBackend:
    """A backend that records placements, standing in for a real board."""

    def __init__(self, fail=None):
        self.placed: list[tuple[int, int]] = []
        self.fail = fail

    def place(self, number, issue_id, operation_id=None):
        if self.fail:
            raise self.fail
        self.placed.append((number, issue_id))
        return 900 + number


class NoBoardBackend:
    """The organization Issue Fields backend, which has no board at all."""


def _wire(monkeypatch, backend):
    import field_backend
    import inspect_target

    stub_inspection = type("I", (), {"backend": "organization issue fields"})()
    monkeypatch.setattr(inspect_target, "inspect",
                        lambda gh, o, n, p=None: stub_inspection)
    monkeypatch.setattr(field_backend, "for_inspection",
                        lambda gh, insp: backend)


@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_a_captured_item_is_placed_on_the_board(monkeypatch):
    # Every transition, the audit, and the refinement queue read delivery state
    # from the project. An item created off the board cannot be moved.
    stub = StubBackend()
    _wire(monkeypatch, stub)
    repo = Repo()
    result = cap.create_item(client(repo), "acme/widgets", "A new finding",
                             "**Reproduction**\nx\n**Expected**\ny\n"
                             "**Actual**\nz\n**Regression test**\nt",
                             "bug", project=3)
    assert result["on_board"] is True
    assert stub.placed and stub.placed[0][0] == result["number"]


@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_placement_uses_the_issue_id_from_the_read_back(monkeypatch):
    stub = StubBackend()
    _wire(monkeypatch, stub)
    repo = Repo()
    result = cap.create_item(client(repo), "acme/widgets", "A new finding",
                             "**Reproduction**\nx\n**Expected**\ny\n"
                             "**Actual**\nz\n**Regression test**\nt",
                             "bug", project=3)
    number = result["number"]
    issue = next(i for i in repo.issues if i["number"] == number)
    assert stub.placed[0][1] == issue["id"]


@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_a_capture_that_cannot_place_says_so(monkeypatch):
    # Returning a clean creation would hand back an item nobody can transition
    # and let the caller believe otherwise.
    _wire(monkeypatch, StubBackend(fail=RuntimeError("no project selected")))
    result = cap.create_item(client(Repo()), "acme/widgets", "A new finding",
                             "**Reproduction**\nx\n**Expected**\ny\n"
                             "**Actual**\nz\n**Regression test**\nt",
                             "bug", project=None)
    assert result["on_board"] is False
    assert "no transition can be planned" in result["board_note"]
    assert result["number"] is not None, "the issue was still created"


@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_a_backend_without_a_board_is_not_reported_as_a_failure(monkeypatch):
    # Organization Issue Fields carry state on the issue itself. There is no
    # board to be off.
    _wire(monkeypatch, NoBoardBackend())
    result = cap.create_item(client(Repo()), "acme/widgets", "A new finding",
                             "**Reproduction**\nx\n**Expected**\ny\n"
                             "**Actual**\nz\n**Regression test**\nt", "bug")
    assert result["on_board"] is False
    assert "no board" in result["board_note"]
    assert "could not place" not in result["board_note"]


@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_a_dry_run_places_nothing(monkeypatch):
    stub = StubBackend()
    _wire(monkeypatch, stub)
    gh = gh_api.GitHub(runner=Repo(), sleep=lambda _: None, max_attempts=1,
                       dry_run=True)
    result = cap.create_item(gh, "acme/widgets", "A new finding",
                             "**Reproduction**\nx\n**Expected**\ny\n"
                             "**Actual**\nz\n**Regression test**\nt", "bug")
    assert result.get("dry_run") is True
    assert stub.placed == []
