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
            self.issues.append({"number": number, "title": body["title"],
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
