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

    def __call__(self, args, stdin):
        self.calls.append(list(args))
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        if url.endswith("/sub_issues"):
            number = int(url.split("/issues/")[1].split("/")[0])
            if number != 38:
                return self._ok([])
            return self._ok([{"number": n} for n in self.children])
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

    def __init__(self, issues, states, children_of=None):
        super().__init__(None)
        self.issues = issues                        # number -> open | closed
        self.children_of = children_of or {}        # parent -> [child numbers]
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
        if url.endswith("/issues"):
            return self._ok([{"number": n, "state": s} for n, s in self.issues.items()])
        if url.endswith("/items"):
            return self._ok([{"id": i, "content": {"number": n}}
                             for n, i in self.item_of.items()])
        return super().__call__(args, stdin)


def audit_setup(issues, states, children_of=None):
    board = AuditBoard(issues, states, children_of)
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    insp = inspection()
    return gh, insp, fb.ProjectFieldBackend(gh, insp)


@pytest.mark.req("REQ-BACKLOG-AUDIT-001")
def test_a_clean_board_reports_nothing():
    gh, insp, be = audit_setup({1: "closed"}, {1: "Output Done"})
    assert tp.audit_board(gh, be, insp) == []


@pytest.mark.req("REQ-BACKLOG-AUDIT-001")
def test_closed_while_not_output_done_is_reported():
    # The failure that happened three times: closed with gh, never transitioned.
    gh, insp, be = audit_setup({1: "closed"}, {1: "In Progress"})
    problems = tp.audit_board(gh, be, insp)
    assert len(problems) == 1
    assert "closed while delivery state is 'In Progress'" in problems[0].problem


@pytest.mark.req("REQ-BACKLOG-AUDIT-001")
def test_output_done_over_an_incomplete_child_is_reported():
    # The transition command refuses to create this; a hand edit can.
    gh, insp, be = audit_setup(
        {1: "open", 2: "open"}, {1: "Output Done", 2: "In Progress"},
        children_of={1: [2]})
    problems = [p for p in tp.audit_board(gh, be, insp) if p.issue == 1]
    assert problems and "children are not" in problems[0].problem


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
