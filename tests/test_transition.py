"""Planning and applying a transition, offline.

This is the only component that changes someone else's system, so the tests
concentrate on refusal: an illegal edge, a stale plan, missing evidence, a plan
for another repository, and any path from issue state to a delivery state.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

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
it = _load("inspect_target")
fb = _load("field_backend")
tp = _load("transition_plan")

MACHINE = load_yaml(ROOT / "policy/state-machine.yml")
STATES = list(it.DELIVERY_STATES)
OPT = {s: f"{i + 1:08x}" for i, s in enumerate(STATES)}


class Board:
    """Remembers writes, so a plan applied twice is observable."""

    def __init__(self, initial=None):
        self.values = {900: {"403": OPT[initial]} if initial else {}}
        self.calls: list[list[str]] = []

    def __call__(self, args, stdin):
        self.calls.append(list(args))
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        if url.endswith("/items"):
            return self._ok([{"id": 900, "content": {"number": 38}}])
        if "/items/" in url:
            item = int(url.rsplit("/", 1)[-1])
            if method == "PATCH":
                for e in json.loads(stdin or "{}").get("fields", []):
                    self.values[item][str(e["id"])] = e["value"]
            rendered = []
            for fid, stored in self.values[item].items():
                name = next((n for n, o in OPT.items() if o == stored), None)
                rendered.append({"id": int(fid), "name": "Status",
                                 "value": {"id": stored, "name": {"raw": name}}})
            return self._ok({"id": item, "fields": rendered})
        return self._ok("User")

    @staticmethod
    def _ok(payload):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")


def inspection():
    return it.Inspection(
        owner="acme", repo="widgets", owner_type="User",
        backend=it.BACKEND_PROJECT, issue_fields_available=False,
        issue_types_available=False, sub_issues_available=True,
        dependencies_available=True, project_number=3,
        fields={"Status": it.FieldRef("Status", "403", "single_select", options=dict(OPT))},
        roles={"delivery_state": "Status"},
    )


def setup(initial="Ready"):
    board = Board(initial)
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    insp = inspection()
    return gh, insp, fb.ProjectFieldBackend(gh, insp), board


def plan_for(target, initial="Ready"):
    gh, insp, be, board = setup(initial)
    return tp.build_plan(be, insp, MACHINE, 38, target), be, insp, board


# --- legality -----------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_a_legal_transition_plans():
    plan, *_ = plan_for("In Progress", initial="Ready")
    assert plan.observed == "Ready" and plan.target == "In Progress"
    assert plan.authority == "assigned_engineering_owner"
    assert set(plan.evidence_required) == {"owner_assigned", "work_started"}


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_an_illegal_edge_is_refused_with_the_legal_ones_named():
    # Refining -> In Progress skips the readiness gate. It is not an edge.
    with pytest.raises(tp.PlanError) as exc:
        plan_for("In Progress", initial="Refining")
    assert "not a legal transition" in str(exc.value)
    assert "Ready" in str(exc.value)


def test_an_unknown_target_state_is_refused():
    with pytest.raises(tp.PlanError) as exc:
        plan_for("Shipped", initial="Ready")
    assert "not a delivery status" in str(exc.value)


def test_planning_writes_nothing():
    plan, be, insp, board = plan_for("In Progress")
    assert not any("PATCH" in c for c in board.calls)


# --- the plan artifact --------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_a_plan_round_trips_through_markdown():
    plan, *_ = plan_for("In Progress")
    parsed = tp.TransitionPlan.from_markdown(plan.to_markdown())
    assert parsed == plan


def test_a_plan_names_exactly_one_field_and_one_value():
    plan, *_ = plan_for("In Progress")
    text = plan.to_markdown()
    assert text.count("Writes exactly one value") == 1
    assert plan.field_name == "Status"


def test_a_plan_without_its_yaml_block_is_refused():
    with pytest.raises(tp.PlanError):
        tp.TransitionPlan.from_markdown("# Approved, honest\n")


def test_a_truncated_plan_is_refused():
    plan, *_ = plan_for("In Progress")
    partial = plan.to_markdown().replace("operation_id:", "unrelated:")
    with pytest.raises(tp.PlanError) as exc:
        tp.TransitionPlan.from_markdown(partial)
    assert "missing" in str(exc.value)


# --- applying -----------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_applying_moves_the_value_and_reads_it_back():
    plan, be, insp, _ = plan_for("In Progress")
    result = tp.apply_plan(be, insp, plan,
                           {"owner_assigned": "me", "work_started": "yes"},
                           machine=MACHINE)
    assert result.value == "In Progress"
    assert be.read(38, "delivery_state").value == "In Progress"


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_missing_evidence_refuses_the_write():
    plan, be, insp, board = plan_for("In Progress")
    with pytest.raises(gh_api.Forbidden) as exc:
        tp.apply_plan(be, insp, plan, {"owner_assigned": "me"}, machine=MACHINE)
    assert "work_started" in str(exc.value)
    assert not any("PATCH" in c for c in board.calls)


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_a_stale_plan_will_not_overwrite_someone_elses_change():
    plan, be, insp, _ = plan_for("In Progress", initial="Ready")
    # Someone else moves it while the plan awaits approval.
    be.write(38, "delivery_state", "Output Done")
    with pytest.raises(gh_api.Conflict) as exc:
        tp.apply_plan(be, insp, plan,
                      {"owner_assigned": "m", "work_started": "y"}, machine=MACHINE)
    assert "stale" in str(exc.value)
    assert be.read(38, "delivery_state").value == "Output Done"


def test_a_plan_for_another_repository_is_refused():
    plan, be, insp, _ = plan_for("In Progress")
    foreign = tp.TransitionPlan(**{**plan.__dict__, "issue": "other/repo#38"})
    with pytest.raises(tp.PlanError) as exc:
        tp.apply_plan(be, insp, foreign,
                      {"owner_assigned": "m", "work_started": "y"}, machine=MACHINE)
    assert "other/repo" in str(exc.value)


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_reapplying_the_same_plan_is_idempotent():
    plan, be, insp, board = plan_for("In Progress")
    ev = {"owner_assigned": "m", "work_started": "y"}
    tp.apply_plan(be, insp, plan, ev, machine=MACHINE)
    patches = sum(1 for c in board.calls if "PATCH" in c)
    again = tp.apply_plan(be, insp, plan, ev, machine=MACHINE)
    assert sum(1 for c in board.calls if "PATCH" in c) == patches
    assert again.value == "In Progress"


def test_already_applied_is_distinguished_from_stale():
    """Reaching the target is success; reaching something else is not."""
    plan, be, insp, _ = plan_for("In Progress", initial="Ready")
    be.write(38, "delivery_state", "In Progress")      # someone did it first
    ev = {"owner_assigned": "m", "work_started": "y"}
    assert tp.apply_plan(be, insp, plan, ev, machine=MACHINE).value == "In Progress"

    other, be2, insp2, _ = plan_for("In Progress", initial="Ready")
    be2.write(38, "delivery_state", "Output Done")     # somewhere else entirely
    with pytest.raises(gh_api.Conflict):
        tp.apply_plan(be2, insp2, other, ev, machine=MACHINE)


def test_the_operation_id_is_stable_for_one_intent():
    a, *_ = plan_for("In Progress")
    b, *_ = plan_for("In Progress")
    assert a.operation_id == b.operation_id
    c, *_ = plan_for("Output Done", initial="In Progress")
    assert c.operation_id != a.operation_id


# --- never infer completion ---------------------------------------------------

@pytest.mark.req("REQ-STATE-OUTPUT-001")
def test_no_code_path_leads_from_issue_state_to_a_delivery_state():
    # infer_output_done_from_closed_issue is false. A check that warned would
    # still be a path; there must be none.
    import ast

    tree = ast.parse((SCRIPTS / "transition_plan.py").read_text(encoding="utf-8"))
    ISSUE_STATE = {"state", "state_reason", "closed_at", "closed", "is_closed"}

    # Reading issue state to *report* on it is legitimate; the audit does that.
    # What must not exist is a function that reads it and also writes a
    # delivery state, which is what inferring completion would look like.
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        body = ast.dump(node)
        writes = ".write" in body or "backend.write" in body
        if not writes:
            continue
        literals = {n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        overlap = literals & ISSUE_STATE
        assert not overlap, (
            f"{node.name} both writes a delivery state and reads issue state "
            f"via {sorted(overlap)}")


@pytest.mark.req("REQ-STATE-OUTPUT-001")
def test_no_code_path_leads_from_an_outcome_to_a_delivery_state():
    # The other direction, and the half the requirement was left `implemented`
    # for. The first test covers issue state; this covers outcome status, which
    # is what "an unvalidated outcome never reopens completed work" forbids.
    import ast

    tree = ast.parse((SCRIPTS / "transition_plan.py").read_text(encoding="utf-8"))
    OUTCOME = {"Outcome Status", "outcome_status", "Outcome Validated",
               "Outcome Missed / Inconclusive", "Measuring",
               "Not Yet Measurable"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        body = ast.dump(node)
        if not (".write" in body or "backend.write" in body):
            continue
        literals = {n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        overlap = literals & OUTCOME
        assert not overlap, (
            f"{node.name} both writes a delivery state and reads outcome "
            f"status via {sorted(overlap)}")


@pytest.mark.req("REQ-STATE-OUTPUT-001")
def test_output_done_still_requires_a_legal_edge_and_evidence():
    plan, be, insp, board = plan_for("Output Done", initial="In Progress")
    assert "acceptance_criteria_satisfied" in plan.evidence_required
    with pytest.raises(gh_api.Forbidden):
        tp.apply_plan(be, insp, plan, {}, machine=MACHINE)
    assert not any("PATCH" in c for c in board.calls)


# --- policy is read, not compiled in ------------------------------------------

def test_the_state_machine_comes_from_installed_policy():
    machine = tp.load_state_machine(ROOT)
    assert machine["delivery_status"]["values"] == list(it.DELIVERY_STATES)


def test_a_missing_policy_is_an_error_not_a_default(tmp_path):
    with pytest.raises(tp.PlanError) as exc:
        tp.load_state_machine(tmp_path)
    assert "governance preset" in str(exc.value)


# --- derived completion -------------------------------------------------------

class BoardWithChildren(Board):
    """A board where issues have sub-issues and their own delivery states."""

    def __init__(self, parent_state="In Progress", children=None):
        super().__init__(parent_state)
        # issue number -> (item id, delivery state)
        self.children = children if children is not None else {}
        self.item_of = {38: 900}
        next_item = 901
        for number in self.children:
            self.item_of[number] = next_item
            self.values[next_item] = {"403": OPT[self.children[number]]} \
                if self.children[number] else {}
            next_item += 1

    blocked_by: list = []

    def __call__(self, args, stdin):
        self.calls.append(list(args))
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        if url.endswith("/sub_issues"):
            number = int(url.split("/issues/")[1].split("/")[0])
            if number != 38:
                return self._ok([])
            return self._ok([{"number": n} for n in self.children])
        if url.endswith("/blocked_by"):
            # The real endpoint returns a list. The fake used to fall through
            # to a bare "User" string, which is not a shape the caller could
            # ever see from GitHub.
            return self._ok(list(self.blocked_by))
        if url.endswith("/items"):
            return self._ok([{"id": i, "content": {"number": n}}
                             for n, i in self.item_of.items()])
        return super().__call__(args, stdin)


def parent_setup(children):
    board = BoardWithChildren(children=children)
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    insp = inspection()
    return gh, insp, fb.ProjectFieldBackend(gh, insp), board


@pytest.mark.req("REQ-BACKLOG-DERIVED-001")
def test_a_parent_cannot_complete_while_a_child_is_open():
    gh, insp, be, _ = parent_setup({101: "Output Done", 102: "In Progress"})
    with pytest.raises(tp.PlanError) as exc:
        tp.build_plan(be, insp, MACHINE, 38, "Output Done", gh=gh)
    assert "#102" in str(exc.value)
    assert "#101" not in str(exc.value)      # names only what blocks


@pytest.mark.req("REQ-BACKLOG-DERIVED-001")
def test_a_parent_completes_once_every_child_is_done():
    gh, insp, be, _ = parent_setup({101: "Output Done", 102: "Output Done"})
    plan = tp.build_plan(be, insp, MACHINE, 38, "Output Done", gh=gh)
    assert plan.target == "Output Done"


@pytest.mark.req("REQ-BACKLOG-DERIVED-001")
def test_a_child_absent_from_the_board_blocks_completion():
    # No delivery state means it cannot be shown delivered.
    gh, insp, be, _ = parent_setup({101: None})
    with pytest.raises(tp.PlanError) as exc:
        tp.build_plan(be, insp, MACHINE, 38, "Output Done", gh=gh)
    assert "not on the board" in str(exc.value)


def test_a_childless_item_is_unaffected():
    gh, insp, be, _ = parent_setup({})
    assert tp.build_plan(be, insp, MACHINE, 38, "Output Done", gh=gh).target == "Output Done"


@pytest.mark.req("REQ-BACKLOG-DERIVED-001")
def test_completion_is_judged_by_delivery_state_not_closure():
    # A child closed as a duplicate has not been delivered. The check must not
    # consult sub_issues_summary, which counts closures.
    source = (SCRIPTS / "transition_plan.py").read_text(encoding="utf-8")
    # Mentioned in a comment explaining why it is not used; what must not
    # appear is an actual read of it.
    for access in ('["sub_issues_summary"]', '.get("sub_issues_summary"',
                   '["percent_completed"]', '.get("percent_completed"'):
        assert access not in source, f"completion judged via {access}"


def test_non_terminal_transitions_do_not_inspect_children():
    gh, insp, be, board = parent_setup({101: "In Progress"})
    be.write(38, "delivery_state", "Ready")
    tp.build_plan(be, insp, MACHINE, 38, "In Progress", gh=gh)
    assert not any("sub_issues" in " ".join(c) for c in board.calls)


# --- board audit --------------------------------------------------------------

class AuditBoard(Board):
    """A board plus an issue list, so closure and delivery state can disagree."""

    def __init__(self, issues, states, children_of=None, labels=None,
                 blocked=None, reasons=None):
        super().__init__(None)
        self.issues = issues                        # number -> open | closed
        self.reasons = reasons or {}                # number -> state_reason
        self.children_of = children_of or {}        # parent -> [child numbers]
        self.labels = labels or {}                  # number -> [label]
        self.blocked = blocked or {}                # number -> [(repo, number, state)]
        self.item_of, self.values = {}, {}
        item = 900
        for number, st in states.items():
            self.item_of[number] = item
            self.values[item] = {"403": OPT[st]} if st else {}
            item += 1

    def __call__(self, args, stdin):
        self.calls.append(list(args))
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        if url.endswith("/sub_issues"):
            parent = int(url.split("/issues/")[1].split("/")[0])
            return self._ok([{"number": n} for n in self.children_of.get(parent, [])])
        if url.endswith("/blocked_by"):
            n = int(url.split("/issues/")[1].split("/")[0])
            return self._ok([
                {"number": num, "state": st, "repository": {"full_name": repo}}
                for repo, num, st in self.blocked.get(n, [])])
        if url.endswith("/issues"):
            return self._ok([
                {"number": n, "state": s,
                 # The real API sends this on every closed issue; a fake that
                 # omitted it would test a payload GitHub does not send.
                 "state_reason": self.reasons.get(n,
                                                  "completed" if s == "closed" else None),
                 "labels": [{"name": lbl} for lbl in self.labels.get(n, [])]}
                for n, s in self.issues.items()])
        if url.endswith("/items"):
            return self._ok([{"id": i, "content": {"number": n}}
                             for n, i in self.item_of.items()])
        return super().__call__(args, stdin)


def audit_setup(issues, states, children_of=None, labels=None, blocked=None,
                reasons=None):
    board = AuditBoard(issues, states, children_of, labels, blocked, reasons)
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    insp = inspection()
    return gh, insp, fb.ProjectFieldBackend(gh, insp)


@pytest.mark.req("REQ-BACKLOG-AUDIT-001")
def test_a_clean_board_reports_nothing():
    gh, insp, be = audit_setup({1: "closed"}, {1: "Output Done"})
    assert tp.audit_board(gh, be, insp) == []


@pytest.mark.req("REQ-BACKLOG-AUDIT-001")
@pytest.mark.req("REQ-BACKLOG-CLOSURE-001")
def test_closed_while_not_output_done_is_reported():
    # The failure that happened three times: closed with gh, never transitioned.
    gh, insp, be = audit_setup({1: "closed"}, {1: "In Progress"})
    problems = tp.audit_board(gh, be, insp)
    assert len(problems) == 1
    assert "closed as 'completed' while delivery state is 'In Progress'" \
        in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-AUDIT-001")
@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_output_done_over_an_incomplete_child_is_reported():
    # The transition command refuses to create this; a hand edit can.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open"}, {1: "Output Done", 2: "In Progress"},
        children_of={1: [2]})
    problems = [p for p in tp.audit_board(gh, be, insp) if p.issue == 1]
    assert problems and "children are not" in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_an_epic_in_progress_whose_every_child_is_blocked_is_reported():
    # The shape #16 and #61 were both in: they read as active work, and no
    # child of either could be started by anyone.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open"}, {1: "In Progress", 2: "Refining"},
        children_of={1: [2]}, labels={1: ["epic"], 2: ["story"]},
        blocked={2: [("acme/widgets", 3, "open")]})
    problems = [p for p in tp.audit_board(gh, be, insp) if p.issue == 1]
    assert problems, "a stalled epic was not reported"
    assert "no child can move" in problems[0].problem
    assert "#2" in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_an_epic_with_one_movable_child_is_not_reported():
    # One unblocked child is enough. In Progress is then a claim the board
    # supports, and reporting it would train a reader to ignore the audit.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open", 3: "open"},
        {1: "In Progress", 2: "Refining", 3: "Ready"},
        children_of={1: [2, 3]}, labels={1: ["epic"]},
        blocked={2: [("emdfonseca/lean-full-lifecycle-speckit", 9, "open")]})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue == 1] == []


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_an_epic_whose_children_are_all_delivered_is_reported():
    # Every child at Output Done and the epic still In Progress: nothing is
    # left to do, so the epic is waiting on a transition nobody made. The
    # message must say that, not "no child can move" -- both are true and
    # only one tells the reader what to do next.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open"}, {1: "In Progress", 2: "Output Done"},
        children_of={1: [2]}, labels={1: ["epic"]})
    problems = [p for p in tp.audit_board(gh, be, insp) if p.issue == 1]
    assert problems
    assert "every child is delivered" in problems[0].problem
    assert "no child can move" not in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_a_blocker_at_output_done_no_longer_stalls_its_parent():
    # Judged by delivery state, not closure -- the same rule the terminal
    # check uses. A blocker delivered but not yet closed blocks nothing.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open", 3: "open"},
        {1: "In Progress", 2: "Refining", 3: "Output Done"},
        children_of={1: [2]}, labels={1: ["epic"]},
        blocked={2: [("acme/widgets", 3, "open")]})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue == 1] == []


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_a_story_in_progress_with_blocked_children_is_not_reported():
    # The rule is about epics, whose progress derives from children.
    # A story owns its own progress and may have children regardless.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open"}, {1: "In Progress", 2: "Refining"},
        children_of={1: [2]}, labels={1: ["story"]},
        blocked={2: [("emdfonseca/lean-full-lifecycle-speckit", 9, "open")]})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue == 1] == []


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_an_epic_with_no_children_is_not_reported_by_this_rule():
    # An undecomposed epic is a decomposition gap, not a stall, and this
    # rule must not become the place that reports it.
    gh, insp, be = audit_setup(
        {1: "open"}, {1: "In Progress"}, labels={1: ["epic"]})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue == 1] == []


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_an_epic_in_refining_with_a_delivered_child_is_reported():
    # The shape #17 was in: four children at Output Done while the epic
    # claimed nothing had been built. The rule for #87 never looked at it,
    # because it examined only epics already In Progress.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open", 3: "open"},
        {1: "Refining", 2: "Output Done", 3: "Inbox"},
        children_of={1: [2, 3]}, labels={1: ["epic"]})
    problems = [p for p in tp.audit_board(gh, be, insp) if p.issue == 1]
    assert problems, "an understated epic was not reported"
    assert "already started or finished" in problems[0].problem
    assert "#2" in problems[0].problem
    assert "nothing has been built yet" in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_an_epic_in_inbox_with_a_child_in_progress_is_reported():
    # Understating is not only about delivered children. Work has started.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open"}, {1: "Inbox", 2: "In Progress"},
        children_of={1: [2]}, labels={1: ["epic"]})
    problems = [p for p in tp.audit_board(gh, be, insp) if p.issue == 1]
    assert problems and "already started or finished" in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_an_epic_in_refining_whose_children_are_all_pre_delivery_is_not_reported():
    # Refinement of an epic and its children at once is ordinary work.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open", 3: "open"},
        {1: "Refining", 2: "Refining", 3: "Ready"},
        children_of={1: [2, 3]}, labels={1: ["epic"]})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue == 1] == []


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_a_story_in_refining_with_a_delivered_child_is_not_reported():
    # A story owns its own progress. Only an epic derives progress from its
    # children, so only an epic can understate it.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open"}, {1: "Refining", 2: "Output Done"},
        children_of={1: [2]}, labels={1: ["story"]})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue == 1] == []


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_a_non_epic_parent_at_output_done_over_an_undelivered_child_is_still_reported():
    # The one angle that is NOT epic-only. Folding this into an epic-only
    # rule would have dropped coverage for every other parent type, which is
    # the regression this test exists to prevent.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open"}, {1: "Output Done", 2: "In Progress"},
        children_of={1: [2]}, labels={1: ["story"]})
    problems = [p for p in tp.audit_board(gh, be, insp) if p.issue == 1]
    assert problems and "children are not" in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_the_state_order_comes_from_the_state_machine_not_from_constants():
    # "Further along than" is a fact about the policy. A second copy of the
    # order living in this script is the copy that drifts.
    values = tp.load_state_machine(ROOT)["delivery_status"]["values"]
    kids = [tp.ChildState(2, "Output Done", None), tp.ChildState(3, "Inbox", None)]
    # Under the real order, Refining sits below In Progress, so a delivered
    # child means the epic understates itself.
    assert tp.parent_disagreement(values, "Refining", kids, True)
    # Reverse the policy order and Refining no longer sits below In Progress.
    # Same inputs, opposite verdict: the order is read, not assumed.
    assert tp.parent_disagreement(list(reversed(values)), "Refining", kids, True) is None


@pytest.mark.req("REQ-BACKLOG-AUDIT-002")
def test_one_rule_decides_every_parent_child_disagreement():
    # The point of #96: three rules examining one relationship drifted apart.
    # audit_board must reach parent_disagreement once and nowhere else.
    source = (SCRIPTS / "transition_plan.py").read_text()
    body = source.split("def audit_board(")[1].split("\ndef ")[0]
    assert body.count("parent_disagreement(") == 1
    assert "child_mobility" not in source, "the superseded helper survived"
    assert "incomplete_children(" not in body, "a second child rule is still in the audit"


def test_a_delivered_child_is_not_asked_about_blockers():
    # A finished child cannot be blocked. Asking spends one request per child
    # to learn nothing.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open"}, {1: "In Progress", 2: "Output Done"},
        children_of={1: [2]}, labels={1: ["epic"]})
    tp.audit_board(gh, be, insp)
    assert not any("/issues/2/dependencies" in " ".join(c) for c in gh.audit and [] or [])


# --- the board against the working tree -------------------------------------
#
# Every other rule compares the board to the policy. This one compares it to
# what was actually built, which is the comparison #93 found missing.

@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_the_audit_reports_the_tree_when_nothing_is_in_progress(monkeypatch, tmp_path):
    # End to end through audit_board: the board says Refining, the tree says
    # two files changed, and the audit is what reconciles them.
    monkeypatch.setattr(tp, "working_trees", lambda root: [tmp_path])
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: ["a.py", "b.py"])
    gh, insp, be = audit_setup({1: "open"}, {1: "Refining"})
    problems = [p for p in tp.audit_board(gh, be, insp, root=tmp_path)
                if p.issue is None]
    assert len(problems) == 1
    assert "no item is In Progress" in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_the_audit_stays_silent_when_an_item_is_in_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: ["a.py"])
    gh, insp, be = audit_setup({1: "open"}, {1: "In Progress"})
    assert [p for p in tp.audit_board(gh, be, insp, root=tmp_path)
            if p.issue is None] == []


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_a_closed_item_in_progress_does_not_silence_it(monkeypatch, tmp_path):
    # A closed issue is not somebody working. Counting it would let a stale
    # board silence the rule permanently.
    monkeypatch.setattr(tp, "working_trees", lambda root: [tmp_path])
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: ["a.py"])
    gh, insp, be = audit_setup({1: "closed"}, {1: "In Progress"})
    assert [p for p in tp.audit_board(gh, be, insp, root=tmp_path)
            if p.issue is None] != []


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_without_a_root_the_tree_is_not_consulted():
    # Every other caller of audit_board passes no root and must be unaffected.
    gh, insp, be = audit_setup({1: "open"}, {1: "Refining"})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue is None] == []


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_an_item_in_progress_silences_it(monkeypatch, tmp_path):
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: ["a.py"])
    assert tp.working_tree_disagreement(tmp_path, [42]) is None


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_nothing_in_progress_with_a_modified_tree_reports(monkeypatch, tmp_path):
    monkeypatch.setattr(tp, "working_trees", lambda root: [tmp_path])
    monkeypatch.setattr(tp, "modified_tracked_files",
                        lambda root: ["a.py", "b.py"])
    drift = tp.working_tree_disagreement(tmp_path, [])
    assert drift and tmp_path.name in drift
    assert "work_started" in drift, "the refusal does not say why it matters"


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_a_clean_tree_reports_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: [])
    assert tp.working_tree_disagreement(tmp_path, []) is None


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_git_being_unable_to_answer_is_not_reported_as_clean(monkeypatch, tmp_path):
    # "nothing changed" and "we could not look" are different answers, and
    # reporting the second as the first is how a check quietly stops working.
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: None)
    assert tp.working_tree_disagreement(tmp_path, []) is None
    assert tp.modified_tracked_files(tmp_path) is None, \
        "a non-repository should answer None, not []"


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_untracked_files_do_not_trigger_it(tmp_path):
    # A scratch file is not evidence that delivery began. Counting it would
    # make the rule fire constantly and then be ignored.
    import subprocess as sp
    sp.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("one\n")
    sp.run(["git", "add", "."], cwd=tmp_path, check=True)
    sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "scratch.tmp").write_text("noise\n")
    assert tp.modified_tracked_files(tmp_path) == []
    (tmp_path / "tracked.txt").write_text("two\n")
    assert tp.modified_tracked_files(tmp_path) == ["tracked.txt"]


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_the_finding_is_attributed_to_the_tree_not_to_an_issue():
    assert str(tp.Inconsistency(None, "x")) == "working tree: x"
    assert str(tp.Inconsistency(7, "x")) == "#7: x"


@pytest.mark.req("REQ-BACKLOG-CLOSURE-001")
def test_a_not_planned_closure_is_not_reported():
    # state-machine.yml declares set_output_done: false for this route.
    # Reporting it would report the policy's own sanctioned route as a
    # contradiction of the policy.
    #
    # At Inbox, which claims nothing. The exemption is from reaching Output
    # Done, not from leaving a column that says work is under way (#139).
    gh, insp, be = audit_setup({1: "closed"}, {1: "Inbox"},
                               reasons={1: "not_planned"})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue == 1] == []


@pytest.mark.req("REQ-BACKLOG-CLOSURE-001")
def test_a_duplicate_closure_is_not_reported():
    # Superseded work is carried by the item that supersedes it. GitHub
    # records `duplicate` natively, verified against the live API.
    gh, insp, be = audit_setup({1: "closed"}, {1: "Inbox"},
                               reasons={1: "duplicate"})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue == 1] == []


@pytest.mark.req("REQ-BACKLOG-CLOSURE-001")
def test_a_completed_closure_short_of_output_done_is_still_reported():
    # The rule that mattered must survive the exemption.
    gh, insp, be = audit_setup({1: "closed"}, {1: "In Progress"},
                               reasons={1: "completed"})
    problems = [p for p in tp.audit_board(gh, be, insp) if p.issue == 1]
    assert problems and "closed as 'completed'" in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-CLOSURE-001")
def test_an_unknown_close_reason_is_reported_rather_than_exempted():
    # The conservative direction: a reason the policy has not considered gets
    # looked at, rather than silently exempted because nobody wrote it down.
    gh, insp, be = audit_setup({1: "closed"}, {1: "Refining"},
                               reasons={1: "invented_by_someone"})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue == 1] != []


@pytest.mark.req("REQ-BACKLOG-CLOSURE-001")
def test_the_exempt_reasons_come_from_policy_not_from_the_audit():
    machine = tp.load_state_machine(ROOT)
    assert tp.closure_exempt_reasons(machine) == {"not_planned", "duplicate"}
    # A route the policy adds must not need the audit edited to match.
    extended = {"closure": dict(machine["closure"],
                                archived={"set_output_done": False,
                                          "close_reason": "archived"})}
    assert tp.closure_exempt_reasons(extended) == {
        "not_planned", "duplicate", "archived"}
    source = (SCRIPTS / "transition_plan.py").read_text()
    body = source.split("def closure_exempt_reasons(")[1].split("\ndef ")[0]
    assert '"not_planned"' not in body and '"duplicate"' not in body, \
        "close reasons are hardcoded in the audit"


@pytest.mark.req("REQ-BACKLOG-CLOSURE-001")
def test_the_policy_declares_the_route_supersession_will_use():
    machine = tp.load_state_machine(ROOT)
    routes = {r.get("close_reason") for r in machine["closure"].values()}
    assert {"completed", "not_planned", "duplicate"} <= routes


def test_an_item_with_no_delivery_state_is_reported():
    gh, insp, be = audit_setup({1: "open"}, {1: None})
    problems = tp.audit_board(gh, be, insp)
    assert len(problems) == 1
    assert "no delivery state" in problems[0].problem


def test_an_open_item_mid_flight_is_not_reported():
    gh, insp, be = audit_setup({1: "open"}, {1: "Refining"})
    assert tp.audit_board(gh, be, insp) == []


def test_the_audit_writes_nothing():
    gh, insp, be = audit_setup({1: "closed"}, {1: "In Progress"})
    tp.audit_board(gh, be, insp)
    assert not any("PATCH" in " ".join(c) for c in gh.audit and [] or [])
    assert all(a.outcome in ("ok", "error") for a in gh.audit)


# --- blocking and the ready queue ---------------------------------------------

class QueueBoard(AuditBoard):
    """Issues with labels and dependencies."""

    def __init__(self, issues, states, blocked=None, labels=None):
        super().__init__(issues, states)
        self.blocked = blocked or {}          # number -> [(repo, number, state)]
        self.labels = labels or {}            # number -> [label]

    def __call__(self, args, stdin):
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        if url.endswith("/blocked_by"):
            self.calls.append(list(args))
            n = int(url.split("/issues/")[1].split("/")[0])
            return self._ok([
                {"number": num, "state": st, "repository": {"full_name": repo}}
                for repo, num, st in self.blocked.get(n, [])])
        if url.endswith("/issues"):
            self.calls.append(list(args))
            return self._ok([
                {"number": n, "state": s,
                 "labels": [{"name": lbl} for lbl in self.labels.get(n, [])]}
                for n, s in self.issues.items()])
        return super().__call__(args, stdin)


def queue_setup(issues, states, blocked=None, labels=None):
    board = QueueBoard(issues, states, blocked, labels)
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    insp = inspection()
    return gh, insp, fb.ProjectFieldBackend(gh, insp)


@pytest.mark.req("REQ-BACKLOG-BLOCKED-001")
def test_blocking_does_not_change_the_delivery_state():
    gh, insp, be = queue_setup(
        {1: "open"}, {1: "Ready"},
        blocked={1: [("github/spec-kit", 4282, "open")]})
    assert be.read(1, "delivery_state").value == "Ready"
    entry = tp.ready_queue(gh, be, insp)[0]
    assert entry.state == "Ready"


@pytest.mark.req("REQ-BACKLOG-BLOCKED-001")
def test_a_ready_but_blocked_item_is_reported():
    gh, insp, be = queue_setup(
        {1: "open"}, {1: "Ready"},
        blocked={1: [("github/spec-kit", 4282, "open")]})
    problems = tp.audit_board(gh, be, insp)
    assert problems and "Ready but blocked" in problems[0].problem
    assert "github/spec-kit#4282" in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-BLOCKED-001")
def test_a_blocked_item_elsewhere_in_the_flow_is_not_reported():
    # Nothing claimed it was startable, so nothing is misleading.
    gh, insp, be = queue_setup(
        {1: "open"}, {1: "Refining"},
        blocked={1: [("github/spec-kit", 4282, "open")]})
    assert tp.audit_board(gh, be, insp) == []


def test_a_closed_blocker_no_longer_blocks():
    gh, insp, be = queue_setup(
        {1: "open"}, {1: "Ready"},
        blocked={1: [("github/spec-kit", 4282, "closed")]})
    assert tp.audit_board(gh, be, insp) == []
    assert tp.ready_queue(gh, be, insp)[0].startable


@pytest.mark.req("REQ-BACKLOG-BLOCKED-001")
def test_the_state_machine_gains_no_state():
    # A guard against casual growth, not against growth. `Retired` was added
    # deliberately in #160: a retirement left an item at Refining or In
    # Progress, the audit correctly reported that it claimed work under way,
    # and no forward transition could fix it. Blocking is still not a state --
    # that is the property this test exists for (ADR 0004).
    machine = tp.load_state_machine(ROOT)
    assert machine["delivery_status"]["values"] == [
        "Inbox", "Refining", "Ready", "In Progress", "Output Done", "Retired"]
    assert machine["blocking"]["changes_delivery_status"] is False


# --- refining ahead -----------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-QUEUE-001")
def test_only_unblocked_ready_items_count_as_startable():
    gh, insp, be = queue_setup(
        {1: "open", 2: "open"}, {1: "Ready", 2: "Ready"},
        blocked={2: [("other/repo", 9, "open")]})
    startable = [e for e in tp.ready_queue(gh, be, insp) if e.startable]
    assert [e.issue for e in startable] == [1]


@pytest.mark.req("REQ-BACKLOG-QUEUE-001")
def test_an_item_with_an_open_blocker_is_not_safe_to_refine_ahead():
    # Its blocker may change what it means, so refining it now wastes the work.
    gh, insp, be = queue_setup(
        {1: "open"}, {1: "Inbox"},
        blocked={1: [("other/repo", 9, "open")]},
        labels={1: ["story"]})
    entry = tp.ready_queue(gh, be, insp)[0]
    assert entry.blocked_by and not entry.startable


@pytest.mark.req("REQ-BACKLOG-QUEUE-001")
def test_epics_are_separated_from_refinable_items():
    # An Epic is decomposed, not refined to Ready. Listing them together tells
    # a refiner to do the wrong thing.
    gh, insp, be = queue_setup(
        {1: "open", 2: "open"}, {1: "Inbox", 2: "Inbox"},
        labels={1: ["epic"], 2: ["story"]})
    entries = {e.issue: e for e in tp.ready_queue(gh, be, insp)}
    assert entries[1].decomposable
    assert not entries[2].decomposable


# --- starting work that waits on something else -------------------------------

class BlockedBoard(BoardWithChildren):
    """A board plus a dependency list, so blockers can be given per issue."""

    def __init__(self, blockers, states=None):
        super().__init__(children=states or {})
        self._blockers = blockers

    def __call__(self, args, stdin):
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        if url.endswith("/blocked_by"):
            self.calls.append(list(args))
            number = int(url.split("/issues/")[1].split("/")[0])
            return self._ok(list(self._blockers.get(number, [])))
        return super().__call__(args, stdin)


class UnreadableDependencies(BoardWithChildren):
    """A board whose dependency list cannot be read."""

    def __call__(self, args, stdin):
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        if url.endswith("/blocked_by"):
            self.calls.append(list(args))
            return self._ok(None)
        return super().__call__(args, stdin)


HERE = "acme/widgets"


def blocker(number, state="open", repo=HERE):
    return {"number": number, "state": state,
            "repository": {"full_name": repo}}


def blocked_setup(blockers, states):
    board = BlockedBoard(blockers, states)
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    insp = inspection()
    return gh, insp, fb.ProjectFieldBackend(gh, insp), board


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_a_blocked_item_cannot_start():
    gh, insp, be, _ = blocked_setup({38: [blocker(101)]},
                                    {101: "In Progress"})
    be.write(38, "delivery_state", "Ready")
    with pytest.raises(tp.PlanError) as exc:
        tp.build_plan(be, insp, MACHINE, 38, "In Progress", gh=gh)
    assert "blocked by" in str(exc.value)


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_the_refusal_names_each_blocker_and_its_state():
    gh, insp, be, _ = blocked_setup({38: [blocker(101), blocker(102)]},
                                    {101: "In Progress", 102: "Ready"})
    be.write(38, "delivery_state", "Ready")
    with pytest.raises(tp.PlanError) as exc:
        tp.build_plan(be, insp, MACHINE, 38, "In Progress", gh=gh)
    message = str(exc.value)
    assert "#101 (In Progress)" in message
    assert "#102 (Ready)" in message


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_a_delivered_blocker_does_not_block():
    gh, insp, be, _ = blocked_setup({38: [blocker(101)]},
                                    {101: "Output Done"})
    be.write(38, "delivery_state", "Ready")
    plan = tp.build_plan(be, insp, MACHINE, 38, "In Progress", gh=gh)
    assert plan.target == "In Progress"


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_an_item_with_no_blockers_starts():
    gh, insp, be, _ = blocked_setup({}, {})
    be.write(38, "delivery_state", "Ready")
    assert tp.build_plan(be, insp, MACHINE, 38, "In Progress", gh=gh)


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_a_blocker_closed_as_a_duplicate_has_not_been_delivered():
    # Judged by delivery state, not by closure: the same rule the parent check
    # uses, for the same reason. A blocker still returned by the endpoint while
    # short of Output Done has not landed.
    gh, insp, be, _ = blocked_setup({38: [blocker(101)]}, {101: "Refining"})
    be.write(38, "delivery_state", "Ready")
    with pytest.raises(tp.PlanError) as exc:
        tp.build_plan(be, insp, MACHINE, 38, "In Progress", gh=gh)
    assert "#101 (Refining)" in str(exc.value)


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_a_blocker_in_another_repository_still_blocks():
    gh, insp, be, _ = blocked_setup(
        {38: [blocker(4282, repo="github/spec-kit")]}, {})
    be.write(38, "delivery_state", "Ready")
    with pytest.raises(tp.PlanError) as exc:
        tp.build_plan(be, insp, MACHINE, 38, "In Progress", gh=gh)
    message = str(exc.value)
    assert "github/spec-kit#4282" in message
    # A reader who does not know which signal answered cannot tell what would
    # clear it.
    assert "not ours to read" in message


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_a_blocker_not_on_the_board_blocks():
    gh, insp, be, _ = blocked_setup({38: [blocker(999)]}, {})
    be.write(38, "delivery_state", "Ready")
    with pytest.raises(tp.PlanError) as exc:
        tp.build_plan(be, insp, MACHINE, 38, "In Progress", gh=gh)
    assert "not on the board" in str(exc.value)


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_an_unreadable_dependency_list_refuses_rather_than_permits():
    board = UnreadableDependencies(children={})
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    insp = inspection()
    be = fb.ProjectFieldBackend(gh, insp)
    be.write(38, "delivery_state", "Ready")
    with pytest.raises(tp.PlanError) as exc:
        tp.build_plan(be, insp, MACHINE, 38, "In Progress", gh=gh)
    assert "could not be determined" in str(exc.value)


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_blocking_does_not_change_delivery_status():
    # ADR 0004: blocking is a dependency, never a state. This adds a refusal,
    # not a sixth delivery status.
    gh, insp, be, _ = blocked_setup({38: [blocker(101)]}, {101: "Ready"})
    be.write(38, "delivery_state", "Ready")
    with pytest.raises(tp.PlanError):
        tp.build_plan(be, insp, MACHINE, 38, "In Progress", gh=gh)
    assert be.read(38, "delivery_state").value == "Ready"


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_a_blocked_item_may_still_be_refined():
    # Only starting is refused. An item can be corrected while it waits.
    gh, insp, be, _ = blocked_setup({38: [blocker(101)]}, {101: "Ready"})
    be.write(38, "delivery_state", "Inbox")
    assert tp.build_plan(be, insp, MACHINE, 38, "Refining", gh=gh)


@pytest.mark.req("REQ-TEAM-BLOCKED-001")
def test_the_blocker_check_does_not_run_for_other_targets():
    board = UnreadableDependencies(children={})
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    insp = inspection()
    be = fb.ProjectFieldBackend(gh, insp)
    be.write(38, "delivery_state", "Inbox")
    # An unreadable dependency list would refuse if it were consulted.
    assert tp.build_plan(be, insp, MACHINE, 38, "Refining", gh=gh)


# --- the edge every existing case skipped over -------------------------------

@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_refining_to_ready_requires_the_readiness_evidence():
    # Every transition test targeted In Progress or Output Done, so the one
    # edge a readiness verdict guards was never exercised.
    gh, insp, be, _ = blocked_setup({}, {})
    be.write(38, "delivery_state", "Refining")
    plan = tp.build_plan(be, insp, MACHINE, 38, "Ready", gh=gh)
    assert plan.target == "Ready"
    assert "readiness_verdict_ready" in plan.evidence_required


@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_ready_is_refused_without_that_evidence():
    gh, insp, be, _ = blocked_setup({}, {})
    be.write(38, "delivery_state", "Refining")
    plan = tp.build_plan(be, insp, MACHINE, 38, "Ready", gh=gh)
    with pytest.raises(tp.Forbidden):
        tp.apply_plan(be, insp, plan, {}, machine=MACHINE)


@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_ready_is_applied_once_the_evidence_is_asserted():
    gh, insp, be, _ = blocked_setup({}, {})
    be.write(38, "delivery_state", "Refining")
    plan = tp.build_plan(be, insp, MACHINE, 38, "Ready", gh=gh)
    tp.apply_plan(be, insp, plan, {"readiness_verdict_ready": "true"},
                  machine=MACHINE)
    assert be.read(38, "delivery_state").value == "Ready"


# --- exempt from the terminal state, not from claiming work -------------------
#
# The exemption was one thing and is two claims. A duplicate or not_planned
# closure is rightly excused from reaching Output Done, which is the policy's
# own route. It was also excused from leaving In Progress, so #100 sat in that
# column claiming work was under way on something closed weeks earlier.

@pytest.mark.req("REQ-BACKLOG-CLOSURE-002")
@pytest.mark.parametrize("state", ["Refining", "Ready", "In Progress"])
@pytest.mark.parametrize("reason", ["duplicate", "not_planned"])
def test_an_exempt_closure_left_where_work_is_claimed_is_reported(state, reason):
    gh, insp, be = audit_setup({1: "closed"}, {1: state}, reasons={1: reason})
    problems = [p for p in tp.audit_board(gh, be, insp) if p.issue == 1]
    assert problems, f"{reason} at {state} claims work and was not reported"
    assert "claims work is under way" in problems[0].problem
    assert state in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-CLOSURE-002")
@pytest.mark.parametrize("reason", ["duplicate", "not_planned"])
def test_an_exempt_closure_at_inbox_is_not_reported(reason):
    # Inbox asserts nothing beyond existence, so a closed item resting there
    # says nothing false. This is the half of the exemption that was right.
    gh, insp, be = audit_setup({1: "closed"}, {1: "Inbox"}, reasons={1: reason})
    assert [p for p in tp.audit_board(gh, be, insp) if p.issue == 1] == []


@pytest.mark.req("REQ-BACKLOG-CLOSURE-002")
def test_a_completed_closure_is_reported_once_not_twice():
    # Two findings for one fact teaches a reader to skim.
    gh, insp, be = audit_setup({1: "closed"}, {1: "In Progress"},
                               reasons={1: "completed"})
    problems = [p for p in tp.audit_board(gh, be, insp) if p.issue == 1]
    assert len(problems) == 1, problems


@pytest.mark.req("REQ-BACKLOG-CLOSURE-002")
def test_the_states_that_claim_work_come_from_the_machine():
    # Not a list here: the ends are Inbox and Output Done, and everything
    # between them claims something actionable.
    machine = tp.load_state_machine(ROOT)
    assert tp.states_asserting_work(machine) == ["Refining", "Ready", "In Progress"]
    values = machine["delivery_status"]["values"]
    assert values[0] not in tp.states_asserting_work(machine)
    assert values[-1] not in tp.states_asserting_work(machine)


# --- retirement has a terminal state to reach --------------------------------

@pytest.mark.req("REQ-STATE-RETIRED-001")
def test_retired_is_a_declared_terminal_state():
    ds = MACHINE["delivery_status"]
    assert "Retired" in ds["values"]
    assert "Retired" in ds["terminal_states"]


@pytest.mark.req("REQ-STATE-RETIRED-001")
@pytest.mark.parametrize("state", ["Inbox", "Refining", "Ready", "In Progress"])
def test_every_live_state_can_reach_retired(state):
    # Work is abandoned wherever it happened to be. A route from only some
    # states would leave the rest stuck, which is the defect (#160).
    edges = {(t["from"], t["to"]) for t in MACHINE["delivery_status"]["transitions"]}
    assert (state, "Retired") in edges


@pytest.mark.req("REQ-STATE-RETIRED-001")
def test_nothing_follows_retired():
    # Terminal means terminal. Output Done has a reopen edge deliberately;
    # abandonment has no equivalent -- reviving abandoned work is a new item.
    outgoing = [t["to"] for t in MACHINE["delivery_status"]["transitions"]
                if t["from"] == "Retired"]
    assert outgoing == []


@pytest.mark.req("REQ-STATE-RETIRED-001")
def test_a_terminal_state_does_not_assert_work():
    # The regression this guards: states_asserting_work read `values[1:-1]`,
    # which encoded "one terminal, and it is last". Adding Retired made Output
    # Done assert work, which would have flagged every completed item.
    asserting = tp.states_asserting_work(MACHINE)
    assert "Output Done" not in asserting
    assert "Retired" not in asserting
    assert "Inbox" not in asserting
    assert asserting == ["Refining", "Ready", "In Progress"]


@pytest.mark.req("REQ-STATE-RETIRED-001")
def test_asserting_work_is_read_from_the_machine_not_counted_from_the_end():
    # Same machine with a further terminal appended: the answer must not change.
    import copy
    extended = copy.deepcopy(MACHINE)
    extended["delivery_status"]["values"].append("Archived")
    extended["delivery_status"]["terminal_states"].append("Archived")
    assert tp.states_asserting_work(extended) == tp.states_asserting_work(MACHINE)


# --- evidence that denies itself is not evidence ------------------------------
#
# Presence was the whole check, so `--evidence work_started=false` passed
# exactly as `=true` did.

@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_evidence_asserted_as_false_is_refused():
    plan, be, insp, board = plan_for("In Progress")
    with pytest.raises(gh_api.Forbidden) as exc:
        tp.apply_plan(be, insp, plan,
                      {"owner_assigned": "me", "work_started": "false"},
                      machine=MACHINE)
    assert "asserted as false" in str(exc.value)
    assert "work_started" in str(exc.value)
    assert not any("PATCH" in c for c in board.calls), (
        "a denial that still wrote would be the defect wearing a refusal")


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_an_empty_evidence_value_is_refused():
    # `--evidence work_started=` is the same denial with fewer characters.
    plan, be, insp, _ = plan_for("In Progress")
    with pytest.raises(gh_api.Forbidden):
        tp.apply_plan(be, insp, plan,
                      {"owner_assigned": "me", "work_started": ""},
                      machine=MACHINE)


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_output_done_asks_for_one_thing_nobody_can_derive():
    # The other four restated step ordering or were defined nowhere. What is
    # left is the judgement: did the acceptance criteria hold.
    edge = [t for t in MACHINE["delivery_status"]["transitions"]
            if t["from"] == "In Progress" and t["to"] == "Output Done"][0]
    assert edge["evidence"] == ["acceptance_criteria_satisfied"]


# --- --expect is the compare-and-swap the plan file used to carry -------------

@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_a_transition_refuses_when_the_board_moved_since_approval():
    # The plan file recorded an observed value so applying could refuse when
    # the board had moved. That refusal is the only thing the plan bought, and
    # losing it in a simplification would trade ceremony for a real bug: two
    # runs in parallel, and the second overwrites a change it never saw.
    plan, be, insp, board = plan_for("In Progress", initial="Ready")
    # Somebody else moves it while this run is at its gate.
    board.values[900]["403"] = OPT["Refining"]
    with pytest.raises(gh_api.Conflict) as exc:
        tp.apply_plan(be, insp, plan,
                      {"owner_assigned": "me", "work_started": "yes"},
                      machine=MACHINE)
    assert "Ready" in str(exc.value) and "Refining" in str(exc.value)
    assert not any("PATCH" in " ".join(c) for c in board.calls)


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_reapplying_a_finished_transition_changes_nothing():
    # A retry after a timeout must not report drift against a value it wrote.
    plan, be, insp, _ = plan_for("In Progress", initial="Ready")
    tp.apply_plan(be, insp, plan,
                  {"owner_assigned": "me", "work_started": "yes"},
                  machine=MACHINE)
    again = tp.apply_plan(be, insp, plan,
                          {"owner_assigned": "me", "work_started": "yes"},
                          machine=MACHINE)
    assert again.value == "In Progress"


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_no_workflow_writes_or_reads_a_transition_plan_file():
    # 335 accumulated under a gitignored path, each read once by the apply that
    # ran seconds after writing it.
    import pathlib as _p
    for f in sorted(_p.Path(ROOT / "bundle/components/workflows").glob("*/workflow.yml")):
        text = f.read_text(encoding="utf-8")
        assert "github-lifecycle/plans/" not in text, f.parent.name
        assert "speckit.github-lifecycle.plan\n" not in text, f.parent.name


# --- the guard against shipping prototype code missed its own main case -------

@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_a_prototype_run_needs_a_disposal_record_whatever_the_item_is_labelled(tmp_path):
    # Detection read the item's labels only. A story labelled `story` and run
    # with uncertainty_mode: prototype builds a prototype and never triggered
    # this -- which is the item most likely to ship prototype code, because the
    # label describes what the item is and not what the run did.
    assert tp.disposal_required(None, 38, _insp(), None, root=tmp_path,
                                uncertainty_mode="prototype")
    assert tp.disposal_required(None, 38, _insp(), None, root=tmp_path,
                                uncertainty_mode="spike")


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_a_recorded_disposal_satisfies_the_prototype_guard(tmp_path):
    d = tmp_path / tp.DISPOSAL_DIR
    d.mkdir(parents=True)
    (d / "38-run.md").write_text("disposed", encoding="utf-8")
    assert not tp.disposal_required(None, 38, _insp(), None, root=tmp_path,
                                    uncertainty_mode="prototype")


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_a_run_declaring_no_uncertainty_still_falls_back_to_the_labels(tmp_path):
    # The mode is one source, not a replacement: a later run that declares no
    # mode must not become a way past the guard.
    assert not tp.disposal_required(None, 38, _insp(), None, root=tmp_path,
                                    uncertainty_mode="none")


def _insp():
    return inspection()


# --- the one transition out of the null state --------------------------------
#
# state-machine.yml declares the edge from no state to Inbox, and it was
# unreachable from the CLI: --expect is a string and argparse can never make
# one equal None, so an item placed on the board without a state could not be
# repaired by the tool that owns transitions. Repair meant `gh project
# item-edit` with a raw field id and option id, outside the extension.

@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
@pytest.mark.parametrize("raw", ["", "   ", None])
def test_an_empty_expect_means_no_delivery_state(raw):
    assert tp.expected_state(raw) is None


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_a_named_state_is_carried_through_unchanged():
    # The empty case must not swallow a real one: "None" is a state name a
    # board could legitimately carry, and it is not the absence of a state.
    assert tp.expected_state("In Progress") == "In Progress"
    assert tp.expected_state("None") == "None"


@pytest.mark.req("REQ-GITHUB-TRANSITION-002")
def test_the_state_machine_declares_the_edge_out_of_no_state():
    edges = [e for e in MACHINE["delivery_status"]["transitions"]
             if e["from"] is None]
    assert edges, "nothing declares how an item with no state gets one"
    assert [e["to"] for e in edges] == [START := "Inbox"]



# --- work in flight, counted rather than attributed ---------------------------

def trees(monkeypatch, tmp_path, dirty, clean=0):
    """`dirty` trees carrying changes and `clean` carrying none."""
    made = []
    for i in range(dirty + clean):
        d = tmp_path / f"tree-{i}"
        d.mkdir()
        made.append(d)
    monkeypatch.setattr(tp, "working_trees", lambda root: list(made))
    monkeypatch.setattr(
        tp, "modified_tracked_files",
        lambda root: ["a.py"] if made.index(Path(root)) < dirty else [])
    return made


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_more_trees_than_started_items_is_reported(monkeypatch, tmp_path):
    """The case the old rule stayed silent through.

    Four trees were carrying work while one item said `In Progress` and three
    others said `Ready`. A rule that fired only when *nothing* was started saw
    the one and said nothing about the three.
    """
    trees(monkeypatch, tmp_path, dirty=4)
    drift = tp.working_tree_disagreement(tmp_path, [155])
    assert drift
    assert "4 working tree(s)" in drift
    assert "1 item(s) are In Progress" in drift and "#155" in drift


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_as_many_started_items_as_dirty_trees_is_silent(monkeypatch, tmp_path):
    trees(monkeypatch, tmp_path, dirty=2)
    assert tp.working_tree_disagreement(tmp_path, [1, 2]) is None


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_more_started_items_than_trees_is_silent(monkeypatch, tmp_path):
    # Work committed but the item not yet moved on is ordinary, not a defect.
    trees(monkeypatch, tmp_path, dirty=1)
    assert tp.working_tree_disagreement(tmp_path, [1, 2, 3]) is None


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_a_clean_tree_does_not_count_towards_work_in_flight(monkeypatch, tmp_path):
    trees(monkeypatch, tmp_path, dirty=1, clean=3)
    assert tp.working_tree_disagreement(tmp_path, [1]) is None


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_nothing_is_attributed_to_an_item(monkeypatch, tmp_path):
    """It counts and never guesses which item a change belongs to.

    Attribution is a question a second person makes interesting, and where it
    is interesting the board already answers it: an issue has an assignee.
    Inventing a branch convention or a claim file here would be a third source
    of truth for something the board already holds.
    """
    trees(monkeypatch, tmp_path, dirty=3)
    drift = tp.working_tree_disagreement(tmp_path, [])
    assert "a.py" not in drift            # no file is named against an item
    assert "belongs" not in drift.lower()


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_a_tree_git_cannot_read_is_not_counted_as_clean(monkeypatch, tmp_path):
    # "we could not look" and "nothing changed" are different answers.
    monkeypatch.setattr(tp, "working_trees", lambda root: [tmp_path])
    monkeypatch.setattr(tp, "modified_tracked_files", lambda root: None)
    assert tp.trees_with_changes(tmp_path) is None
    assert tp.working_tree_disagreement(tmp_path, []) is None


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_no_worktree_list_means_no_verdict(monkeypatch, tmp_path):
    monkeypatch.setattr(tp, "working_trees", lambda root: None)
    assert tp.working_tree_disagreement(tmp_path, []) is None


@pytest.mark.req("REQ-BACKLOG-BUILDORDER-001")
def test_every_worktree_is_enumerated_not_just_the_current_one(tmp_path):
    # Work here happens in several trees at once, which is the whole reason
    # worktrees exist; looking at one would be blind to the situation this is
    # for. Run against the real repository, whose list git alone can answer.
    found = tp.working_trees(ROOT)
    assert found and ROOT in [p.resolve() for p in found]
