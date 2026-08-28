"""The router that decides the next lifecycle step, and what it will not decide.

Two properties matter here and they pull against each other.

The first is that the router *routes*: given a state, a type, blockers and
children, it names the right transition, the right workflow and the right step.

The second is that it holds no copy of the policy it routes by. That one cannot
be tested by asserting outputs -- a hardcoded table produces the same answers
until the policy moves. So several tests move the policy in a temp tree and
assert the answer moves with it, and one reads the source for state literals.
That second kind is the point of the module; #182 named a router that hardcodes
a state name as the failure to watch for.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys

import pytest
import yaml

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/work/scripts"
COMMANDS = ROOT / "bundle/components/extensions/work/commands"

spec = importlib.util.spec_from_file_location("work_router", SCRIPTS / "router.py")
router = importlib.util.module_from_spec(spec)
sys.modules["work_router"] = router
spec.loader.exec_module(router)

MACHINE = yaml.safe_load((ROOT / "policy/state-machine.yml").read_text(encoding="utf-8"))
ITEM_TYPES = yaml.safe_load((ROOT / "policy/item-types.yml").read_text(encoding="utf-8"))
STATES = MACHINE["delivery_status"]["values"]
ENTRY, REFINING, STARTABLE, DELIVERING = STATES[0], STATES[1], STATES[2], STATES[3]
TERMINAL = MACHINE["delivery_status"]["terminal_states"][0]


def project(tmp_path, machine=None, item_types=None):
    """A source-shaped tree, so the policy under test can be moved."""
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy/state-machine.yml").write_text(
        yaml.safe_dump(machine or MACHINE, sort_keys=False), encoding="utf-8")
    (tmp_path / "policy/item-types.yml").write_text(
        yaml.safe_dump(item_types or ITEM_TYPES, sort_keys=False), encoding="utf-8")
    return tmp_path


def workflow(tmp_path, workflow_id, steps):
    d = tmp_path / "bundle/components/workflows" / workflow_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "workflow.yml").write_text(
        yaml.safe_dump({"workflow": {"id": workflow_id}, "steps": steps},
                       sort_keys=False), encoding="utf-8")


# --- it routes ----------------------------------------------------------------

@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_the_forward_transition_carries_the_evidence_the_policy_declares(tmp_path):
    root = project(tmp_path)
    answer = router.route(root, REFINING, "story")
    edge = next(e for e in MACHINE["delivery_status"]["transitions"]
                if e["from"] == REFINING and e["to"] == STARTABLE)
    assert answer["transition"]["to"] == STARTABLE
    assert answer["transition"]["evidence"] == edge["evidence"]
    assert answer["transition"]["authority"] == edge["authority"]


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_retirement_is_never_the_forward_transition(tmp_path):
    # Every live state can reach it, which is exactly why it must not be
    # offered as "what happens next".
    root = project(tmp_path)
    retire = router.retirement_state(MACHINE)
    assert retire
    for state in STATES:
        answer = router.route(root, state, "story")
        assert (answer["transition"] or {}).get("to") != retire


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_each_type_routes_to_the_workflow_item_types_names(tmp_path):
    root = project(tmp_path)
    declared = ITEM_TYPES["state_workflows"][DELIVERING]
    for item_type, workflow_id in declared.items():
        assert router.route(root, DELIVERING, item_type)["workflow"] == workflow_id


# --- it refuses ---------------------------------------------------------------

@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_a_blocked_item_is_refused_the_transition_the_policy_refuses(tmp_path):
    root = project(tmp_path)
    refused = MACHINE["blocking"]["refuses_transition_to"]
    state = next(e["from"] for e in MACHINE["delivery_status"]["transitions"]
                 if e["to"] == refused)
    answer = router.route(root, state, "story", blocked_by=["acme/x#9"])
    assert answer["refusals"]
    assert "acme/x#9" in answer["refusals"][0]
    assert refused in answer["refusals"][0]


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_refine_ahead_refuses_only_the_step_that_produces_the_startable_state(tmp_path):
    root = project(tmp_path)
    # At Refining the refine-ahead rule is the one that applies...
    refining = router.route(root, REFINING, "story", blocked_by=["acme/x#9"])
    assert len(refining["refusals"]) == 1
    assert "refine_ahead_requires" in refining["refusals"][0]
    # ...and at the startable state it does not, because refuses_transition_to
    # covers that edge. Reporting both would say one thing twice.
    startable = router.route(root, STARTABLE, "story", blocked_by=["acme/x#9"])
    assert len(startable["refusals"]) == 1
    assert "refuses" in startable["refusals"][0]


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_the_entry_state_is_not_refused_for_a_blocker(tmp_path):
    # Triaging a blocked item is fine. The policy only refuses refining it to
    # the startable state.
    root = project(tmp_path)
    assert router.route(root, ENTRY, "story", blocked_by=["acme/x#9"])["refusals"] == []


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_a_decomposable_item_with_a_live_child_cannot_finish(tmp_path):
    root = project(tmp_path)
    decomposable = next(t for t, e in ITEM_TYPES["types"].items()
                        if e.get("decomposable"))
    answer = router.route(root, DELIVERING, decomposable,
                          child_states=[REFINING])
    assert answer["refusals"]
    assert TERMINAL in answer["refusals"][0]


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_a_decomposable_item_whose_children_are_all_terminal_is_not_refused(tmp_path):
    root = project(tmp_path)
    decomposable = next(t for t, e in ITEM_TYPES["types"].items()
                        if e.get("decomposable"))
    assert router.route(root, DELIVERING, decomposable,
                        child_states=[TERMINAL, TERMINAL])["refusals"] == []


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_an_unknown_state_or_type_is_refused_rather_than_routed(tmp_path):
    root = project(tmp_path)
    with pytest.raises(router.RouterError):
        router.route(root, "Marinating", "story")
    with pytest.raises(router.RouterError):
        router.route(root, REFINING, "saga")


# --- it holds no copy of the policy -------------------------------------------

@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_no_delivery_state_is_named_in_the_router_source():
    # The property the whole module exists for. A literal here is how two
    # surfaces over one policy become two policies.
    source = (SCRIPTS / "router.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    named = literals & set(STATES)
    assert not named, f"router.py names delivery states: {sorted(named)}"


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_renaming_a_state_in_the_policy_moves_the_answer(tmp_path):
    # A hardcoded table would keep answering the old name.
    machine = json.loads(json.dumps(MACHINE))
    values = machine["delivery_status"]["values"]
    values[values.index(REFINING)] = "Grooming"
    for edge in machine["delivery_status"]["transitions"]:
        if edge.get("from") == REFINING:
            edge["from"] = "Grooming"
        if edge.get("to") == REFINING:
            edge["to"] = "Grooming"
    item_types = json.loads(json.dumps(ITEM_TYPES))
    item_types["state_workflows"]["Grooming"] = item_types["state_workflows"].pop(REFINING)

    root = project(tmp_path, machine, item_types)
    assert router.route(root, "Grooming", "story")["transition"]["to"] == STARTABLE
    with pytest.raises(router.RouterError):
        router.route(root, REFINING, "story")


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_retyping_the_workflow_map_moves_the_workflow(tmp_path):
    item_types = json.loads(json.dumps(ITEM_TYPES))
    item_types["state_workflows"][DELIVERING]["story"] = "lifecycle-somewhere-else"
    root = project(tmp_path, item_types=item_types)
    assert router.route(root, DELIVERING, "story")["workflow"] == "lifecycle-somewhere-else"


# --- what it will not guess ---------------------------------------------------

@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_the_next_step_is_the_first_whose_artifact_is_absent(tmp_path):
    root = project(tmp_path)
    workflow(root, ITEM_TYPES["state_workflows"][DELIVERING]["story"], [
        {"id": "specify", "command": "speckit.specify", "produces": "spec.md"},
        {"id": "plan", "command": "speckit.plan", "produces": "plan.md"},
        {"id": "tasks", "command": "speckit.tasks", "produces": "tasks.md"},
    ])
    feature = root / "specs/001"
    feature.mkdir(parents=True)
    (feature / "spec.md").write_text("x", encoding="utf-8")

    answer = router.route(root, DELIVERING, "story", feature_dir=feature)
    assert answer["step"]["id"] == "plan"


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_an_empty_directory_artifact_does_not_count_as_produced(tmp_path):
    root = project(tmp_path)
    workflow(root, ITEM_TYPES["state_workflows"][DELIVERING]["story"], [
        {"id": "checklist", "command": "speckit.checklist", "produces": "checklists/"},
    ])
    feature = root / "specs/001"
    (feature / "checklists").mkdir(parents=True)
    assert router.route(root, DELIVERING, "story",
                        feature_dir=feature)["step"]["id"] == "checklist"


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_a_step_producing_nothing_nameable_is_reported_unverifiable(tmp_path):
    # Not "done" and not "next": the router says it could not tell, because a
    # second record of progress is what #182 rules out.
    root = project(tmp_path)
    workflow(root, ITEM_TYPES["state_workflows"][DELIVERING]["story"], [
        {"id": "verify", "type": "shell", "run": "devbox run verify"},
        {"id": "specify", "command": "speckit.specify", "produces": "spec.md"},
    ])
    feature = root / "specs/001"
    feature.mkdir(parents=True)
    answer = router.route(root, DELIVERING, "story", feature_dir=feature)
    assert "verify" in answer["unverifiable"]
    assert answer["step"]["id"] == "specify"


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_an_uninstalled_workflow_is_reported_not_invented(tmp_path):
    root = project(tmp_path)
    answer = router.route(root, DELIVERING, "story")
    assert answer["step"] is None
    assert any("not installed" in note for note in answer["notes"])


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_a_type_with_no_outcome_gets_no_outcome_axis(tmp_path):
    item_types = json.loads(json.dumps(ITEM_TYPES))
    item_types["types"]["story"]["carries_outcome"] = False
    root = project(tmp_path, item_types=item_types)
    answer = router.route(root, TERMINAL, "story")
    assert answer["workflow"] is None
    assert any("does not carry an outcome" in note for note in answer["notes"])


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_the_reopen_edge_is_left_to_a_person(tmp_path):
    root = project(tmp_path)
    answer = router.route(root, TERMINAL, "story")
    assert answer["transition"] is None
    assert any("reopen" in note for note in answer["notes"])


# --- the command line and the contract ----------------------------------------

@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_a_refusal_is_an_answer_not_a_failure(tmp_path):
    root = project(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "router.py"), "--root", str(root),
         "--state", STARTABLE, "--type", "story",
         "--blocked-by", "acme/x#9", "--format", "json"],
        capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["refusals"]


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_an_unroutable_item_exits_non_zero(tmp_path):
    root = project(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "router.py"), "--root", str(root),
         "--state", "Marinating", "--type", "story"],
        capture_output=True, text=True)
    assert result.returncode == 2
    assert "not a delivery state" in result.stderr


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_status_declares_that_it_writes_nothing():
    text = (COMMANDS / "status.md").read_text(encoding="utf-8")
    assert "Writes nothing" in text or "writes nothing" in text
    assert "Write anything" in text


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_every_command_refuses_the_git_branch_as_a_source():
    # The one resolution source Spec Kit does not use either.
    for name in ("status", "start", "continue"):
        text = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
        assert "git branch" in text


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_continue_performs_one_step_and_says_so():
    text = (COMMANDS / "continue.md").read_text(encoding="utf-8")
    assert "One step, not the rest of the item." in text
    assert "Perform two steps" in text


@pytest.mark.req("REQ-WORKFLOW-ROUTER-001")
def test_change_leaves_the_item_where_it_is():
    text = (COMMANDS / "change.md").read_text(encoding="utf-8")
    assert "does not move" in text
    assert "Retire is not finish" in text
