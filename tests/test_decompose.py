"""Rolling-wave decomposition, offline.

The horizon is a target count of **Ready** children. That distinction is the
whole design: creating children does not make work startable, so an Epic short
of its target whose children are all unrefined needs refinement rather than
more decomposition. Most of these tests exist to hold that line.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from lib.inventory import ROOT, load_inventory, load_yaml

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
fb = _load("field_backend")
_load("relationships")
_load("capture")
dec = _load("decompose")

OPT = {s: f"{i + 1:08x}" for i, s in enumerate(it.DELIVERY_STATES)}


def horizon(target, children):
    h = dec.Horizon(epic=1, target=target)
    h.children = dict(children)
    return h


# --- the horizon --------------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-DECOMPOSE-001")
def test_only_ready_children_count_toward_the_horizon():
    # Creating children does not fill the queue; refining them does.
    h = horizon(3, {10: "Inbox", 11: "Refining", 12: "In Progress"})
    assert h.ready == []
    assert h.shortfall == 3
    assert not h.met


@pytest.mark.req("REQ-BACKLOG-DECOMPOSE-001")
def test_a_met_horizon_asks_for_nothing_more():
    h = horizon(2, {10: "Ready", 11: "Ready", 12: "Inbox"})
    assert h.met and h.shortfall == 0
    assert "Decompose no further" in h._advice()


@pytest.mark.req("REQ-BACKLOG-DECOMPOSE-001")
def test_unrefined_children_are_recommended_before_new_ones():
    # The case that keeps decomposition and refinement cooperating.
    h = horizon(3, {10: "Inbox", 11: "Inbox", 12: "Refining"})
    advice = h._advice()
    assert "Refine those before creating more" in advice


def test_a_shortfall_larger_than_the_unrefined_pool_invites_proposals():
    h = horizon(3, {10: "Inbox"})
    assert "Propose up to 2 more" in h._advice()


def test_completed_children_do_not_count_as_ready():
    # Done work is not startable work.
    h = horizon(2, {10: "Output Done", 11: "Output Done"})
    assert h.ready == [] and h.done == [10, 11]
    assert h.shortfall == 2


def test_a_child_with_no_delivery_state_counts_as_neither():
    h = horizon(1, {10: None})
    assert h.ready == [] and h.in_flight == []


# --- applying proposals -------------------------------------------------------

class Board:
    def __init__(self, children=None, states=None, existing_titles=()):
        self.children = list(children or [])
        self.states = dict(states or {})
        self.titles = list(existing_titles)
        self.created: list[str] = []
        self.next_number = 200
        self.calls: list[list[str]] = []

    def __call__(self, args, stdin):
        self.calls.append(list(args))
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        raw = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1])
        url, _, _q = raw.partition("?")

        if url.endswith("/sub_issues"):
            if method == "POST":
                self.children.append(json.loads(stdin)["sub_issue_id"] - 1000)
                return self._ok({})
            return self._ok([{"number": n} for n in self.children])
        if url.endswith("/issues") and method == "POST":
            body = json.loads(stdin)
            number = self.next_number
            self.next_number += 1
            self.created.append(body["title"])
            self.states[number] = "Inbox"
            return self._ok({"number": number})
        if url.endswith("/issues"):
            return self._ok([{"number": i, "title": t, "state": "open", "labels": []}
                             for i, t in enumerate(self.titles, start=1)])
        if url.endswith("/fields"):
            return self._ok([{"id": 403, "name": "Status", "data_type": "single_select",
                              "options": [{"id": o, "name": {"raw": n}}
                                          for n, o in OPT.items()]}])
        if url.endswith("/items"):
            return self._ok([{"id": 900 + n, "content": {"number": n}}
                             for n in self.states])
        if "/items/" in url:
            item = int(url.rsplit("/", 1)[-1])
            n = item - 900
            state = self.states.get(n)
            fields = ([{"id": 403, "name": "Status",
                        "value": {"id": OPT[state], "name": {"raw": state}}}]
                      if state else [])
            return self._ok({"id": item, "fields": fields})
        if "/issues/" in url:
            number = int(url.rsplit("/", 1)[-1])
            if "--jq" in args and args[args.index("--jq") + 1] == ".id":
                return self._ok(number + 1000)
            return self._ok({"number": number, "id": number + 1000,
                             "labels": [{"name": "story"}]})
        return self._ok({})

    @staticmethod
    def _ok(payload):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")


def inspection():
    return it.Inspection(
        owner="o", repo="r", owner_type="User", backend=it.BACKEND_PROJECT,
        issue_fields_available=False, issue_types_available=False,
        sub_issues_available=True, dependencies_available=True, project_number=3,
        fields={"Status": it.FieldRef("Status", "403", "single_select", options=dict(OPT))},
        roles={"delivery_state": "Status"})


def setup(board):
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    insp = inspection()
    return gh, insp, fb.ProjectFieldBackend(gh, insp)


def proposal(title):
    return dec.Proposal(title=title,
                        body="Acceptance criteria: given a when b then c",
                        type="story")


@pytest.mark.req("REQ-BACKLOG-DECOMPOSE-001")
def test_a_rerun_against_a_met_horizon_creates_nothing():
    board = Board(children=[10, 11], states={10: "Ready", 11: "Ready"})
    gh, insp, be = setup(board)
    result = dec.apply_proposals(gh, be, insp, epic=1, target=2,
                                 proposals=[proposal("Something new")])
    assert result["action"] == "none"
    assert board.created == []


@pytest.mark.req("REQ-BACKLOG-DECOMPOSE-001")
def test_nothing_beyond_the_horizon_is_created():
    board = Board(children=[], states={})
    gh, insp, be = setup(board)
    result = dec.apply_proposals(
        gh, be, insp, epic=1, target=1,
        proposals=[proposal("Alpha"), proposal("Beta"), proposal("Gamma")])
    assert len(result["created"]) == 1
    assert result["undecomposed"] == ["Beta", "Gamma"]


@pytest.mark.req("REQ-BACKLOG-DECOMPOSE-001")
def test_created_children_begin_inbox():
    # Ready is earned through a readiness verdict, by a different authority.
    board = Board(children=[], states={})
    gh, insp, be = setup(board)
    result = dec.apply_proposals(gh, be, insp, epic=1, target=1,
                                 proposals=[proposal("Alpha")])
    number = result["created"][0]["number"]
    assert board.states[number] == "Inbox"


@pytest.mark.req("REQ-BACKLOG-DECOMPOSE-001")
def test_a_duplicate_proposal_is_skipped_not_created():
    board = Board(children=[], states={}, existing_titles=["Alpha the thing"])
    gh, insp, be = setup(board)
    result = dec.apply_proposals(gh, be, insp, epic=1, target=2,
                                 proposals=[proposal("Alpha the thing")])
    assert result["created"] == []
    assert "duplicate" in result["skipped"][0]["reason"]


def test_a_proposal_failing_its_content_contract_is_skipped():
    board = Board(children=[], states={})
    gh, insp, be = setup(board)
    weak = dec.Proposal(title="Vague idea", body="It would be nice.", type="story")
    result = dec.apply_proposals(gh, be, insp, epic=1, target=2, proposals=[weak])
    assert result["created"] == []
    assert "needs" in result["skipped"][0]["reason"]


@pytest.mark.req("REQ-BACKLOG-DECOMPOSE-001")
def test_created_children_are_linked_to_the_epic():
    board = Board(children=[], states={})
    gh, insp, be = setup(board)
    result = dec.apply_proposals(gh, be, insp, epic=1, target=1,
                                 proposals=[proposal("Alpha")])
    assert result["created"][0]["number"] in board.children


def test_proposals_must_be_a_list(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"proposals": "nope"}', encoding="utf-8")
    with pytest.raises(ValueError):
        dec.load_proposals(path)


# --- the workflow -------------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-DECOMPOSE-001")
def test_the_workflow_gates_before_creating():
    wf = load_inventory().by_id("workflow", "lifecycle-decompose")
    steps = wf.manifest["steps"]
    ids = [s["id"] for s in steps]
    creating = ids.index("create-children")
    assert any(s.get("type") == "gate" for s in steps[:creating])
    gate = next(s for s in steps if s.get("type") == "gate")
    assert gate["on_reject"] == "abort"
    assert gate["show_file"].endswith(".json")


def test_the_workflow_reads_the_horizon_before_proposing():
    wf = load_inventory().by_id("workflow", "lifecycle-decompose")
    ids = [s["id"] for s in wf.manifest["steps"]]
    assert ids.index("read-horizon") < ids.index("propose-children")
    assert ids.index("decide-whether-to-decompose") < ids.index("propose-children")


# --- the second wave, which nothing exercised --------------------------------

@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_a_second_wave_creates_only_what_the_horizon_still_needs():
    # Every existing case decomposed once. The roadmap asks for first *and*
    # second waves, and the horizon is only interesting on the second: the
    # first wave's children are what it now has to count.
    board = Board(children=[], states={})
    gh, insp, be = setup(board)

    first = dec.apply_proposals(gh, be, insp, epic=1, target=2,
                                proposals=[proposal("Alpha"), proposal("Beta")])
    assert len(first["created"]) == 2

    # Those two are Inbox, not Ready, so the horizon is still unmet.
    gh, insp, be = setup(board)
    second = dec.apply_proposals(gh, be, insp, epic=1, target=2,
                                 proposals=[proposal("Gamma")])
    assert second["action"] != "none"


@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_a_second_wave_stops_once_the_horizon_is_met():
    board = Board(children=[10], states={10: "Ready"})
    gh, insp, be = setup(board)

    first = dec.apply_proposals(gh, be, insp, epic=1, target=2,
                                proposals=[proposal("Alpha")])
    assert len(first["created"]) == 1

    # Mark every child the epic now has as Ready, however the fake numbered
    # them, so the horizon is genuinely met rather than met by assumption.
    for number in board.children:
        board.states[number] = "Ready"

    # A second wave is a second run. The backend caches its item map, so
    # reusing the first run's would hide the children the first wave created --
    # which is what a fresh process would never do.
    gh, insp, be = setup(board)
    second = dec.apply_proposals(gh, be, insp, epic=1, target=2,
                                 proposals=[proposal("Beta")])
    assert second["action"] == "none"
    assert "Beta" not in [c.get("title") for c in second.get("created", [])]
