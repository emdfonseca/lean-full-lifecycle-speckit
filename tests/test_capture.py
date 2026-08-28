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
import yaml

from lib.inventory import ROOT, load_yaml

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
        # number -> [body]. Recorded because a comment on an issue other than
        # the one being created is the one write no other capture path makes.
        self.comments: dict[int, list[str]] = {}

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
                                # Stored because the real API stores it: a
                                # fake that drops the body cannot show whether
                                # provenance reached the issue.
                                "body": body.get("body", ""),
                                "state": "open", "labels": labels})
            return self._ok({"number": number})
        if url.endswith("/comments") and method == "POST":
            number = int(url.split("/issues/")[1].split("/")[0])
            self.comments.setdefault(number, []).append(
                json.loads(stdin or "{}").get("body", ""))
            return self._ok({"id": 1})
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


GOOD_BODY = ("**Reproduction**\nx\n**Expected**\ny\n"
             "**Actual**\nz\n**Regression test**\nt")


def _run(monkeypatch, repo, argv):
    """Drive main() the way a person does, with the API faked underneath.

    Exercised through the CLI rather than the functions because the refusal
    text is what a person reads, and it is the refusal text this change is
    about.
    """
    monkeypatch.setattr(cap, "GitHub", lambda **kw: gh_api.GitHub(
        runner=repo, sleep=lambda _: None, max_attempts=1,
        dry_run=kw.get("dry_run", False)))
    monkeypatch.setattr(sys, "argv", ["capture.py"] + list(argv))
    return cap.main()


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

    def __init__(self, fail=None, fail_write=None):
        self.placed: list[tuple[int, int]] = []
        self.written: list[tuple[int, str, str]] = []
        self.fail = fail
        self.fail_write = fail_write

    def place(self, number, issue_id, operation_id=None):
        if self.fail:
            raise self.fail
        self.placed.append((number, issue_id))
        return 900 + number

    def write(self, number, role, value, *, operation_id=None):
        if self.fail_write:
            raise self.fail_write
        self.written.append((number, role, value))
        return value


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


@pytest.mark.req("REQ-GITHUB-BOARD-002")
def test_a_captured_item_gets_the_entry_delivery_state(monkeypatch):
    # Placing the row is half the job. A row with no delivery state is
    # reported by the audit and skipped by the refinement queue.
    stub = StubBackend()
    _wire(monkeypatch, stub)
    result = cap.create_item(client(Repo()), "acme/widgets", "A new finding",
                             "**Reproduction**\nx\n**Expected**\ny\n"
                             "**Actual**\nz\n**Regression test**\nt",
                             "bug", project=3, policy_root=ROOT)
    assert result["delivery_state"] == "Inbox"
    assert stub.written == [(result["number"], "delivery_state", "Inbox")]


@pytest.mark.req("REQ-GITHUB-BOARD-002")
def test_the_entry_state_comes_from_the_state_machine_not_this_script():
    # A second copy of the entry state living in capture.py is the copy that
    # drifts when the policy changes.
    machine = yaml.safe_load((ROOT / "policy/state-machine.yml").read_text())
    entries = [e["to"] for e in machine["delivery_status"]["transitions"]
               if e.get("from") is None]
    assert cap.initial_delivery_state(ROOT) == entries[0]
    source = (SCRIPTS / "capture.py").read_text()
    assert '"Inbox"' not in source, "the entry state is hardcoded in capture.py"


@pytest.mark.req("REQ-GITHUB-BOARD-002")
def test_a_capture_that_places_but_cannot_set_the_state_says_so(monkeypatch):
    # Half-placed is its own outcome and must not read as a clean creation.
    stub = StubBackend(fail_write=RuntimeError("field not found"))
    _wire(monkeypatch, stub)
    result = cap.create_item(client(Repo()), "acme/widgets", "A new finding",
                             "**Reproduction**\nx\n**Expected**\ny\n"
                             "**Actual**\nz\n**Regression test**\nt",
                             "bug", project=3, policy_root=ROOT)
    assert result["on_board"] is True
    assert result["delivery_state"] is None
    assert "could not set its delivery state" in result["board_note"]
    assert "the audit will report it" in result["board_note"].lower()


@pytest.mark.req("REQ-GITHUB-BOARD-002")
def test_a_backend_without_a_board_is_not_asked_for_a_state(monkeypatch):
    # Organization Issue Fields carry state on the issue itself. There is no
    # board row to write, and pretending otherwise would invent a failure.
    _wire(monkeypatch, NoBoardBackend())
    result = cap.create_item(client(Repo()), "acme/widgets", "A new finding",
                             "**Reproduction**\nx\n**Expected**\ny\n"
                             "**Actual**\nz\n**Regression test**\nt", "bug",
                             policy_root=ROOT)
    assert "delivery_state" not in result


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


# --- recording a duplicate decision -------------------------------------------
#
# The refusal used to name --threshold as the way through, which capture.md
# forbids. That left the only sanctioned route being the one the documentation
# said never to take, and nothing recorded what a person had decided.

@pytest.mark.req("REQ-BACKLOG-DUPLICATE-001")
def test_every_candidate_must_be_named_not_merely_one():
    # A flag that cleared the whole report once one item was named would let
    # the second duplicate through unseen.
    cands = [cap.Candidate(7, "a", "open", 0.9), cap.Candidate(8, "b", "closed", 0.6)]
    assert cap.unconsidered(cands, [7]) == [8]
    assert cap.unconsidered(cands, [7, 8]) == []
    assert cap.unconsidered(cands, []) == [7, 8]


@pytest.mark.req("REQ-BACKLOG-DUPLICATE-001")
def test_a_number_the_search_never_raised_is_refused():
    # A decision recorded against an item the search did not surface is a
    # typo or a claim about something else. Both need correcting.
    cands = [cap.Candidate(7, "a", "open", 0.9)]
    assert cap.phantom_considerations(cands, [7]) == []
    assert cap.phantom_considerations(cands, [7, 41]) == [41]


@pytest.mark.req("REQ-BACKLOG-DUPLICATE-001")
def test_the_refusal_names_the_flag_and_not_the_threshold(monkeypatch, capsys):
    repo = Repo()
    repo.issues.append({"number": 7, "id": 7007, "state": "open",
                        "title": "A new finding", "labels": []})
    _run(monkeypatch, repo, ["--repo", "acme/widgets", "--title", "A new finding",
                             "--type", "bug", "--body", GOOD_BODY, "--create"])
    report = json.loads(capsys.readouterr().out)
    assert report["action"] == "refused"
    reason = report["reason"]
    assert "--considered 7" in reason, "the refusal does not say what to run"
    assert "raise the threshold" not in reason.lower()


@pytest.mark.req("REQ-BACKLOG-DUPLICATE-001")
def test_naming_every_candidate_lets_the_creation_proceed(monkeypatch, capsys):
    _wire(monkeypatch, StubBackend())
    repo = Repo()
    repo.issues.append({"number": 7, "id": 7007, "state": "open",
                        "title": "A new finding", "labels": []})
    _run(monkeypatch, repo, ["--repo", "acme/widgets", "--title", "A new finding",
                             "--type", "bug", "--body", GOOD_BODY,
                             "--considered", "7", "--create"])
    report = json.loads(capsys.readouterr().out)
    assert report["action"] == "created"
    assert report["considered"] == [7]


@pytest.mark.req("REQ-BACKLOG-DUPLICATE-001")
def test_the_decision_is_readable_back_off_the_result(monkeypatch):
    # Without this the decision is a flag someone passed and nothing anyone
    # can read afterwards.
    stub = StubBackend()
    _wire(monkeypatch, stub)
    result = cap.create_item(client(Repo()), "acme/widgets", "A new finding",
                             GOOD_BODY, "bug", project=3, policy_root=ROOT,
                             considered=[63, 94])
    assert result["considered"] == [63, 94]


@pytest.mark.req("REQ-BACKLOG-DUPLICATE-001")
def test_threshold_remains_available_and_is_no_longer_the_only_route():
    # The decision was to keep --threshold. What made it a problem was being
    # the sole lever, which capture.md forbids using.
    source = (SCRIPTS / "capture.py").read_text()
    assert "--threshold" in source
    assert "--considered" in source
    doc = (ROOT / "bundle/components/extensions/github-lifecycle/commands/capture.md").read_text()
    assert "--considered" in doc, "the command doc does not mention the flag"


@pytest.mark.req("REQ-BACKLOG-DUPLICATE-001")
def test_the_documentation_and_the_refusal_agree():
    # They contradicted each other: the Never bullet forbade --threshold and
    # the refusal named it as the remedy.
    doc = (ROOT / "bundle/components/extensions/github-lifecycle/commands/capture.md").read_text()
    never = doc.split("## Never", 1)[1]
    assert "--threshold" in never, "the prohibition was dropped rather than resolved"
    source = (SCRIPTS / "capture.py").read_text()
    refusal = source.split("not yet decided", 1)[1].split(")", 1)[0]
    assert "--considered" in refusal


# --- provenance ---------------------------------------------------------------
#
# A finding from delivery that does not say where it came from is a finding
# nobody can put back in context.

@pytest.mark.req("REQ-BACKLOG-CAPTURE-002")
def test_a_finding_records_where_it_was_found(monkeypatch):
    _wire(monkeypatch, StubBackend())
    repo = Repo()
    result = cap.create_item(client(repo), "acme/widgets", "A new finding",
                             GOOD_BODY, "bug", project=3, policy_root=ROOT,
                             found_in=42)
    assert result["found_in"] == 42
    created = next(i for i in repo.issues if i["number"] == result["number"])
    assert "Found during #42." in created["body"], \
        "the provenance is not in the body, so nobody reading the issue sees it"


@pytest.mark.req("REQ-BACKLOG-CAPTURE-002")
def test_the_provenance_is_a_cross_reference_not_a_private_field():
    # GitHub renders #42 as a link from both ends, so the source issue shows
    # the finding without this command writing to it.
    body = cap.with_provenance("Body text.", 42)
    assert body.rstrip().endswith("Found during #42.")


@pytest.mark.req("REQ-BACKLOG-CAPTURE-002")
def test_provenance_is_not_added_twice():
    once = cap.with_provenance("Body text.", 42)
    assert cap.with_provenance(once, 42) == once


@pytest.mark.req("REQ-BACKLOG-CAPTURE-002")
def test_no_source_leaves_the_body_alone():
    assert cap.with_provenance("Body text.", None) == "Body text."


@pytest.mark.req("REQ-BACKLOG-CAPTURE-002")
def test_delivery_can_capture_a_finding_without_leaving_the_run():
    # Before this, capture was reachable from exactly one route: the
    # missed-outcome branch of outcome-review.
    delivery = load_yaml(
        ROOT / "bundle/components/workflows/lifecycle-story-delivery/workflow.yml")
    switch = next(s for s in delivery["steps"]
                  if s["id"] == "capture-a-technical-finding")
    ids = [step["id"] for step in switch["cases"]["capture"]]
    assert ids == ["search-for-a-technical-finding",
                   "approve-the-technical-finding",
                   "capture-the-technical-finding"]


@pytest.mark.req("REQ-BACKLOG-CAPTURE-002")
def test_the_delivery_capture_searches_before_it_creates_and_links_its_source():
    delivery = load_yaml(
        ROOT / "bundle/components/workflows/lifecycle-story-delivery/workflow.yml")
    switch = next(s for s in delivery["steps"]
                  if s["id"] == "capture-a-technical-finding")
    steps = {step["id"]: step for step in switch["cases"]["capture"]}
    search = steps["search-for-a-technical-finding"]["input"]["args"].lower()
    assert any(p in search for p in ("read-only", "read only", "writes nothing",
                                     "write nothing")), \
        "the read-only exemption is honoured only while the step declares it"
    assert "--create" not in search, "a searching step that creates is not a search"
    create = steps["capture-the-technical-finding"]["input"]["args"]
    assert "--found-in" in create
    assert "--considered" in create, \
        "the delivery route bypasses the duplicate decision #98 added"




# --- marking what a finding invalidates ----------------------------------------

def _posts(repo):
    """(index, url) for every POST the fake saw, in order.

    The url is the argument after `--method POST`, not the last one: `gh api`
    takes fields after the url, and reading argv[-1] made an ordering assertion
    match nothing and pass vacuously.
    """
    out = []
    for i, call in enumerate(repo.calls):
        if "--method" in call and call[call.index("--method") + 1] == "POST":
            out.append((i, call[call.index("--method") + 2].split("?")[0]))
    return out


def invalidation_repo():
    """An open item and a closed one, to invalidate or fail to."""
    return Repo(issues=[
        {"number": 42, "id": 10042, "title": "An epic this breaks",
         "state": "open", "labels": [{"name": "epic"}]},
        {"number": 43, "id": 10043, "title": "Already decided",
         "state": "closed", "labels": [{"name": "story"}]},
    ])


@pytest.mark.req("REQ-BACKLOG-INVALIDATE-001")
def test_an_invalidated_item_is_commented_on_with_the_new_issue_and_reason():
    repo = invalidation_repo()
    result = cap.create_item(
        client(repo), "o/r", "A finding", "body", "story",
        invalidates=[42], invalidation_reason="its exit condition cannot hold")

    assert result["invalidates"] == [42]
    body = repo.comments[42][0]
    assert f"#{result['number']}" in body
    assert "its exit condition cannot hold" in body


@pytest.mark.req("REQ-BACKLOG-INVALIDATE-001")
def test_a_closed_item_cannot_be_invalidated_and_the_refusal_names_it():
    repo = invalidation_repo()
    with pytest.raises(gh_api.Forbidden) as exc:
        cap.create_item(client(repo), "o/r", "A finding", "body", "story",
                        invalidates=[43], invalidation_reason="why")
    assert "#43" in str(exc.value)
    assert "closed" in str(exc.value)


@pytest.mark.req("REQ-BACKLOG-INVALIDATE-001")
def test_a_refused_invalidation_creates_nothing():
    # The whole shape of the feature. Discovering the target was closed after
    # creating the issue would leave a created item beside a refusal, and the
    # refusal would be the only part anyone could act on.
    repo = invalidation_repo()
    with pytest.raises(gh_api.Forbidden):
        cap.create_item(client(repo), "o/r", "A finding", "body", "story",
                        invalidates=[43], invalidation_reason="why")
    assert not [url for _, url in _posts(repo) if url.endswith("/issues")]
    assert [i["number"] for i in repo.issues] == [42, 43]


@pytest.mark.req("REQ-BACKLOG-INVALIDATE-001")
def test_the_comment_follows_creation_and_never_precedes_it():
    repo = invalidation_repo()
    cap.create_item(client(repo), "o/r", "A finding", "body", "story",
                    invalidates=[42], invalidation_reason="why")
    posts = _posts(repo)
    created_at = next(i for i, url in posts if url.endswith("/issues"))
    commented_at = next(i for i, url in posts if url.endswith("/comments"))
    assert created_at < commented_at


@pytest.mark.req("REQ-BACKLOG-INVALIDATE-001")
def test_several_items_are_each_marked():
    repo = Repo(issues=[
        {"number": 42, "id": 10042, "title": "One", "state": "open", "labels": []},
        {"number": 44, "id": 10044, "title": "Two", "state": "open", "labels": []},
    ])
    result = cap.create_item(client(repo), "o/r", "A finding", "body", "story",
                             invalidates=[42, 44], invalidation_reason="why")
    assert result["invalidates"] == [42, 44]
    assert set(repo.comments) == {42, 44}


@pytest.mark.req("REQ-BACKLOG-INVALIDATE-001")
def test_an_unreadable_item_is_not_treated_as_open():
    repo = invalidation_repo()
    with pytest.raises(gh_api.NotFound):
        cap.create_item(client(repo), "o/r", "A finding", "body", "story",
                        invalidates=[999], invalidation_reason="why")


@pytest.mark.req("REQ-BACKLOG-INVALIDATE-001")
def test_the_comment_does_not_decide_what_happens_next():
    # Retiring or respecifying the item is a person's judgement, and the
    # comment saying so is what keeps this from looking like a proposal.
    repo = invalidation_repo()
    cap.create_item(client(repo), "o/r", "A finding", "body", "story",
                    invalidates=[42], invalidation_reason="why")
    body = repo.comments[42][0]
    assert "not decided here" in body
    for word in ("retire", "respecify", "close"):
        assert word not in body.lower()


@pytest.mark.req("REQ-BACKLOG-INVALIDATE-001")
def test_searching_without_create_writes_to_no_issue(monkeypatch, capsys):
    repo = invalidation_repo()
    assert _run(monkeypatch, repo, [
        "--repo", "o/r", "--title", "A finding",
        "--invalidates", "42", "--invalidation-reason", "why"]) == 0
    assert repo.comments == {}
    assert json.loads(capsys.readouterr().out)["action"] == "searched only"


@pytest.mark.req("REQ-BACKLOG-INVALIDATE-001")
def test_invalidating_without_a_reason_is_refused(monkeypatch, capsys):
    repo = invalidation_repo()
    code = _run(monkeypatch, repo, [
        "--repo", "o/r", "--title", "A finding", "--create", "--type", "bug",
        "--body", GOOD_BODY, "--invalidates", "42"])
    assert code == 2
    assert repo.comments == {}


@pytest.mark.req("REQ-BACKLOG-INVALIDATE-001")
def test_the_command_documents_that_it_marks_and_stops():
    text = (ROOT / "bundle/components/extensions/github-lifecycle/commands"
            / "capture.md").read_text(encoding="utf-8")
    assert "Decide what happens to an invalidated item" in text
    assert "before creation and the comments after it" in text
