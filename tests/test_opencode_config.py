"""Generating the file that decides what an agent may do.

`agent-policy.yml` states ten runtime rules. OpenCode expresses some directly,
some only as bash patterns, and two not at all. A generator that emitted a
config and reported success would be claiming enforcement it does not have.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys

import pytest

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pr = _load("project_root")
oc = _load("opencode_config")

BOOTSTRAP, AGENT, ROUTING = oc.load_policies(ROOT)
SPEC = BOOTSTRAP["integrations"]["opencode"]
RUNTIME = AGENT["runtime"]


@pytest.fixture
def proposal():
    return oc.build(BOOTSTRAP, AGENT, ROUTING)


# --- AC1: directly expressible rules become permission keys -------------------

@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
@pytest.mark.parametrize("rule,key", sorted(SPEC["permission_mapping"].items()))
def test_each_mapped_rule_reaches_its_config_key(proposal, rule, key):
    node = proposal.config
    for part in key.split("."):
        assert part in node, f"{rule} did not reach {key}"
        node = node[part]
    # That the rule reached its key is the claim here. Whether the value is
    # the one we meant is pinned in PINNED below, so a relaxed policy cannot
    # satisfy both.
    assert node is not None


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_session_sharing_is_disabled(proposal):
    assert proposal.config["share"] == "disabled"


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_external_directory_access_is_denied(proposal):
    assert proposal.config["permission"]["external_directory"] == "deny"


# --- AC2: the reviewer cannot edit --------------------------------------------

@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_the_reviewer_agent_is_denied_edit(proposal):
    assert proposal.config["agent"]["reviewer"]["permission"]["edit"] == "deny"


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_the_edit_denial_comes_from_the_role_constraint():
    # It is a policy constraint, not a preference. Removing it from the policy
    # must remove it from the config.
    routing = copy.deepcopy(ROUTING)
    routing["roles"]["reviewer"]["constraints"].pop("edit_permission")
    built = oc.build(BOOTSTRAP, AGENT, routing)
    assert "reviewer" not in built.config.get("agent", {})


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_a_role_without_an_edit_constraint_gets_no_agent_entry(proposal):
    assert "builder" not in proposal.config.get("agent", {})


# --- AC3: the fixed commands are allowed, the shell is not --------------------

@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_the_verification_commands_are_allowed_by_pattern(proposal):
    bash = proposal.config["permission"]["bash"]
    for command in (BOOTSTRAP["verification_commands"]["required"] +
                    BOOTSTRAP["verification_commands"]["release"]):
        assert bash[command] == "allow"


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_the_bash_default_is_still_ask(proposal):
    # Allowing the two commands the workflows run is not a reason to open the
    # shell.
    assert proposal.config["permission"]["bash"]["*"] == "ask"


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
@pytest.mark.parametrize("rule", sorted(SPEC["bash_pattern_rules"]))
def test_each_pattern_rule_reaches_the_bash_map(proposal, rule):
    bash = proposal.config["permission"]["bash"]
    for pattern in SPEC["bash_pattern_rules"][rule]["patterns"]:
        assert pattern in bash


# The decisions, written out. Reading them from the policy the generator also
# reads makes the assertion agree with itself: flip `protected_push` to
# `allow` and a self-referential test still passes.
PINNED = {
    "*": "ask",
    ".specify/lifecycle/verify": "allow",
    ".specify/lifecycle/release-verify": "allow",
    "git push --force*": "deny",
    "kubectl apply*": "ask",
    "rm -rf*": "deny",
}


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
@pytest.mark.parametrize("pattern,decision", sorted(PINNED.items()))
def test_the_generated_decision_is_the_one_we_meant(proposal, pattern, decision):
    assert proposal.config["permission"]["bash"][pattern] == decision


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_a_denial_flipped_in_policy_changes_the_output():
    # The property the pinned values exist to give us: if somebody relaxes the
    # policy, the suite notices.
    relaxed = copy.deepcopy(AGENT)
    relaxed["runtime"]["protected_push"] = "allow"
    built = oc.build(BOOTSTRAP, relaxed, ROUTING)
    assert built.config["permission"]["bash"]["git push --force*"] == "allow"
    assert built.config["permission"]["bash"]["git push --force*"] != \
        PINNED["git push --force*"]


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_a_protected_push_is_denied_and_a_deploy_asks(proposal):
    bash = proposal.config["permission"]["bash"]
    assert bash["git push --force*"] == "deny"
    assert bash["kubectl apply*"] == "ask"


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_the_patterns_that_were_used_are_reported(proposal):
    # A bash pattern matches commands, not intents. Saying which patterns stood
    # in for a rule is what lets somebody judge whether they are enough.
    assert set(proposal.by_pattern) == set(SPEC["bash_pattern_rules"])


# --- AC4: what cannot be enforced is listed -----------------------------------

@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_every_unenforceable_rule_is_reported(proposal):
    reported = {u.rule for u in proposal.unenforceable}
    assert reported == set(SPEC["unenforceable"])


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
@pytest.mark.parametrize("rule", ["plugin_default", "mcp_default"])
def test_the_two_rules_with_no_primitive_are_named(proposal, rule):
    # These are the ones a reader would otherwise assume were enforced: the
    # policy says deny, and the config has no way to say it.
    assert rule in {u.rule for u in proposal.unenforceable}
    assert rule in RUNTIME
    assert RUNTIME[rule] == "deny"


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_each_unenforceable_rule_says_why_and_what_compensates(proposal):
    for item in proposal.unenforceable:
        assert item.why.strip()
        assert item.compensated_by.strip()


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_an_uncompensated_gap_is_marked_as_one(proposal):
    # A made-up mitigation is worse than an admitted gap.
    uncompensated = [u.rule for u in proposal.unenforceable if u.uncompensated]
    assert uncompensated == ["cost_and_runtime_limits"]


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_the_report_does_not_read_as_fully_enforced(proposal):
    assert proposal.to_dict()["fully_enforced"] is False


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_no_runtime_rule_is_silently_absent(proposal):
    # Every rule the policy states is either configured, carried by a pattern,
    # or named unenforceable. Nothing falls off the list.
    accounted = (set(proposal.configured) | set(proposal.by_pattern)
                 | {u.rule for u in proposal.unenforceable})
    assert set(RUNTIME) <= accounted, set(RUNTIME) - accounted


# --- AC5: nothing is written before approval ----------------------------------

@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_apply_refuses_a_document_that_is_not_a_proposal(tmp_path):
    stray = tmp_path / "config.json"
    stray.write_text(json.dumps({"permission": {"bash": "allow"}}),
                     encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        oc.load_proposal(stray)
    assert "not an approved configuration proposal" in str(exc.value)


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_a_written_proposal_is_recognised(tmp_path, proposal):
    (tmp_path / ".specify").mkdir()
    written = oc.write_proposal(tmp_path / ".specify" / "p.json", proposal,
                                tmp_path)
    assert oc.load_proposal(written)["config"] == proposal.config


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_a_proposal_cannot_be_written_outside_the_project(tmp_path, proposal):
    (tmp_path / ".specify").mkdir()
    outside = tmp_path.parent / "elsewhere.json"
    with pytest.raises(pr.OutsideProjectError):
        oc.write_proposal(outside, proposal, tmp_path)


@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_proposing_writes_no_config_file(tmp_path, proposal):
    (tmp_path / ".specify").mkdir()
    oc.write_proposal(tmp_path / ".specify" / "p.json", proposal, tmp_path)
    for name in SPEC["config_files"]:
        assert not (tmp_path / name).exists()


# --- policy is the source -----------------------------------------------------

@pytest.mark.req("REQ-SECURITY-OPENCODE-001")
def test_the_mapping_is_not_hardcoded_in_the_script():
    import ast

    tree = ast.parse((SCRIPTS / "opencode_config.py").read_text(encoding="utf-8"))
    docstrings = {id(ast.get_docstring(n, clean=False)) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))}
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n.value) not in docstrings]
    for key in SPEC["permission_mapping"].values():
        assert key not in literals, f"{key} is hardcoded"
