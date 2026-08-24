"""Mapping the policy onto Claude Code, which is shaped differently.

`#71` mapped the same policy onto OpenCode and found two rules with no
primitive at all. Claude Code sorts rule strings into allow/deny/ask lists under
a default mode rather than carrying a key per capability, so the set of gaps is
different — and asserting it is the same set would be guessing.
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
cc = _load("claude_config")
oc = _load("opencode_config")

BOOTSTRAP, AGENT, ROUTING = cc.load_policies(ROOT)
SPEC = BOOTSTRAP["integrations"]["claude"]
RUNTIME = AGENT["runtime"]


@pytest.fixture
def proposal():
    return cc.build(BOOTSTRAP, AGENT, ROUTING)


# --- AC1: every rule maps or is named -----------------------------------------

@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_no_runtime_rule_is_silently_absent(proposal):
    accounted = (set(proposal.by_rule) | set(proposal.by_setting)
                 | {u.rule for u in proposal.unmappable})
    assert set(RUNTIME) <= accounted, set(RUNTIME) - accounted


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
@pytest.mark.parametrize("rule", sorted(SPEC["permission_mapping"]))
def test_each_permission_rule_lands_in_some_list(proposal, rule):
    permissions = proposal.settings["permissions"]
    listed = [rule for bucket in ("allow", "ask", "deny")
              if isinstance(permissions.get(bucket), list)
              for rule in permissions[bucket]]
    for entry in SPEC["permission_mapping"][rule]["rules"]:
        assert entry in listed


# Written out rather than read from the policy the generator also reads.
PINNED = {
    "deny": ["Bash(git push:*)", "Bash(rm -rf:*)"],
    "ask": ["WebFetch", "Bash(kubectl apply:*)"],
    "allow": ["Bash(devbox run verify)"],
}


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
@pytest.mark.parametrize("bucket", sorted(PINNED))
def test_the_generated_rules_are_the_ones_we_meant(proposal, bucket):
    listed = proposal.settings["permissions"][bucket]
    for rule in PINNED[bucket]:
        assert rule in listed, f"{rule} missing from {bucket}"


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_a_denial_flipped_in_policy_changes_the_output():
    relaxed = copy.deepcopy(AGENT)
    relaxed["runtime"]["protected_push"] = "allow"
    built = cc.build(BOOTSTRAP, relaxed, ROUTING)
    assert "Bash(git push:*)" in built.settings["permissions"]["allow"]
    assert "Bash(git push:*)" not in built.settings["permissions"].get("deny", [])


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_mcp_stays_off_unless_policy_says_otherwise():
    relaxed = copy.deepcopy(AGENT)
    relaxed["runtime"]["mcp_default"] = "allow"
    built = cc.build(BOOTSTRAP, relaxed, ROUTING)
    # No `value_when_allow` is declared, so nothing is emitted rather than a
    # permissive default being invented.
    assert "enableAllProjectMcpServers" not in built.settings


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_a_denied_rule_is_not_also_allowed(proposal):
    permissions = proposal.settings["permissions"]
    assert not set(permissions.get("deny", [])) & set(permissions.get("allow", []))


# --- AC2: the reviewer cannot edit --------------------------------------------

@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_the_reviewer_agent_has_no_writing_tools(proposal):
    tools = proposal.agents["reviewer"]["tools"]
    assert tools == SPEC["agent_tools"]["read_only"]
    for writer in ("Edit", "Write", "NotebookEdit"):
        assert writer not in tools


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_the_tool_list_comes_from_the_role_constraint():
    routing = copy.deepcopy(ROUTING)
    routing["roles"]["reviewer"]["constraints"].pop("edit_permission")
    assert "reviewer" not in cc.build(BOOTSTRAP, AGENT, routing).agents


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_a_role_without_the_constraint_gets_no_agent(proposal):
    assert "builder" not in proposal.agents


# --- AC3: the commands are allowed, the shell is not --------------------------

@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_the_verification_commands_are_allowed_by_name(proposal):
    allowed = proposal.settings["permissions"]["allow"]
    for command in (BOOTSTRAP["verification_commands"]["required"] +
                    BOOTSTRAP["verification_commands"]["release"]):
        assert f"Bash({command})" in allowed


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_the_default_mode_does_not_permit_arbitrary_commands(proposal):
    # Allowing two commands is not opening the shell. `bypassPermissions` and
    # `acceptEdits` would both do that.
    mode = proposal.settings["permissions"]["defaultMode"]
    assert mode == SPEC["settings_mapping"]["shell_default"]["value_when_ask"]
    assert mode not in {"bypassPermissions", "acceptEdits"}


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_an_unlisted_command_is_not_allowed(proposal):
    allowed = proposal.settings["permissions"]["allow"]
    assert "Bash(curl:*)" not in allowed


# --- AC4: what this agent enforces better is not reported as a gap ------------

@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
@pytest.mark.parametrize("rule", ["plugin_default", "mcp_default"])
def test_a_rule_opencode_could_not_express_is_generated_here(rule):
    # The point of the story. Copying the other integration's gap list would
    # understate what this one enforces.
    opencode_gaps = {u.rule for u in
                     oc.build(BOOTSTRAP, AGENT, ROUTING).unenforceable}
    assert rule in opencode_gaps

    built = cc.build(BOOTSTRAP, AGENT, ROUTING)
    assert rule not in {u.rule for u in built.unmappable}
    assert rule in built.by_setting


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_mcp_servers_are_not_enabled_wholesale(proposal):
    assert proposal.settings["enableAllProjectMcpServers"] is False


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_external_directories_are_declared_empty(proposal):
    # Claude Code confines itself to the project unless told otherwise, so
    # declaring none is the denial.
    assert proposal.settings["additionalDirectories"] == []


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_the_gap_lists_of_the_two_integrations_differ():
    claude = {u.rule for u in cc.build(BOOTSTRAP, AGENT, ROUTING).unmappable}
    opencode = {u.rule for u in
                oc.build(BOOTSTRAP, AGENT, ROUTING).unenforceable}
    assert claude != opencode


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_a_rule_this_agent_cannot_have_is_marked_not_applicable(proposal):
    # Session sharing and provider selection are capabilities Claude Code does
    # not have. Reporting them as gaps would spend the reader's attention on
    # something that is not there.
    not_applicable = {u.rule for u in proposal.unmappable if u.not_applicable}
    assert not_applicable == {"sharing", "provider_allowlist_required"}


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_the_one_genuine_gap_is_marked_uncompensated(proposal):
    uncompensated = [u.rule for u in proposal.unmappable if u.uncompensated]
    assert uncompensated == ["cost_and_runtime_limits"]


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_a_not_applicable_rule_does_not_make_the_report_unenforced(proposal):
    payload = proposal.to_dict()
    assert payload["fully_enforced"] is False  # the real gap still counts
    assert len([u for u in proposal.unmappable if u.not_applicable]) == 2


# --- AC5: nothing written before approval -------------------------------------

@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_apply_refuses_a_document_that_is_not_a_proposal(tmp_path):
    stray = tmp_path / "settings.json"
    stray.write_text(json.dumps({"permissions": {"allow": ["Bash"]}}),
                     encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        cc.load_proposal(stray)
    assert "not an approved settings proposal" in str(exc.value)


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_an_opencode_proposal_is_not_a_claude_proposal(tmp_path, proposal):
    # Both write a JSON proposal. Applying one to the other would write a
    # config in the wrong schema into the wrong agent's file.
    (tmp_path / ".specify").mkdir()
    other = oc.write_proposal(tmp_path / ".specify" / "o.json",
                              oc.build(BOOTSTRAP, AGENT, ROUTING), tmp_path)
    with pytest.raises(ValueError):
        cc.load_proposal(other)


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_proposing_writes_no_settings_file(tmp_path, proposal):
    (tmp_path / ".specify").mkdir()
    cc.write_proposal(tmp_path / ".specify" / "p.json", proposal, tmp_path)
    assert not (tmp_path / ".claude" / "settings.json").exists()


@pytest.mark.req("REQ-SECURITY-CLAUDE-001")
def test_a_proposal_cannot_be_written_outside_the_project(tmp_path, proposal):
    (tmp_path / ".specify").mkdir()
    with pytest.raises(pr.OutsideProjectError):
        cc.write_proposal(tmp_path.parent / "elsewhere.json", proposal, tmp_path)


# --- secret file paths --------------------------------------------------------

SENSITIVE = cc.load_sensitive(ROOT)


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_secret_paths_reach_the_generated_deny_list():
    # AC-SECURITY-004 asserts the generated permissions deny secret files.
    # Before this, no generated rule mentioned a path at all.
    deny = cc.build(BOOTSTRAP, AGENT, ROUTING, SENSITIVE) \
             .settings["permissions"]["deny"]
    assert "Read(**/.env)" in deny
    assert "Read(**/*.pem)" in deny
    assert "Read(**/.ssh/**)" in deny


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_the_shell_route_round_a_read_rule_is_denied_too():
    # Denying Read(.env) while allowing Bash(cat .env) is a rule that reads
    # as protection and is not.
    deny = cc.build(BOOTSTRAP, AGENT, ROUTING, SENSITIVE) \
             .settings["permissions"]["deny"]
    for command in ("cat", "less", "head", "tail"):
        assert f"Bash({command} **/.env)" in deny


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_every_policy_pattern_becomes_a_rule():
    import sensitive as sd
    rules = cc.secret_path_rules(SENSITIVE)
    for entry in sd.denied_path_patterns(SENSITIVE):
        assert f"Read({entry['glob']})" in rules, (
            f"{entry['id']} is in the policy and not in the generated config")


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_a_preset_without_the_policy_emits_no_secret_rules():
    # No rules rather than an exception, and no config that looks stricter
    # than it is.
    assert cc.secret_path_rules(None) == []
    assert cc.secret_path_rules({}) == []
    built = cc.build(BOOTSTRAP, AGENT, ROUTING, None)
    assert not [r for r in built.settings["permissions"].get("deny", [])
                if r.startswith("Read(")]


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_the_secret_rules_are_attributed_to_a_rule_name():
    # by_rule is what the report shows a reviewer; rules that appear from
    # nowhere cannot be argued with.
    built = cc.build(BOOTSTRAP, AGENT, ROUTING, SENSITIVE)
    assert "secret_file_read" in built.by_rule
    assert "Read(**/.env)" in built.by_rule["secret_file_read"]


# --- what untrusted input may never authorize ---------------------------------

@pytest.mark.req("REQ-SECURITY-UNTRUSTED-001")
def test_the_never_authorize_list_reaches_the_deny_rules():
    # agent-policy.yml listed eight forbidden authorizations and nothing read
    # the list.
    built = cc.build(BOOTSTRAP, AGENT, ROUTING, SENSITIVE)
    deny = built.settings["permissions"]["deny"]
    assert "Bash(claude mcp add:*)" in deny
    assert "Bash(claude plugin install:*)" in deny
    assert "untrusted_inputs_never_authorize" in built.by_rule


@pytest.mark.req("REQ-SECURITY-UNTRUSTED-001")
def test_what_cannot_be_expressed_is_reported_not_approximated():
    # A rule half-covering production_access would make the config look
    # stricter than it is, which is the failure this issue is about.
    _, unenforced = cc.never_authorize_rules(AGENT)
    assert set(unenforced) == {"shell_execution", "production_access",
                               "policy_change"}
    built = cc.build(BOOTSTRAP, AGENT, ROUTING, SENSITIVE)
    reported = {u.rule.split(":", 1)[1] for u in built.unmappable
                if u.rule.startswith("untrusted_inputs_never_authorize:")}
    assert reported == set(unenforced)


@pytest.mark.req("REQ-SECURITY-UNTRUSTED-001")
def test_every_listed_action_is_either_a_rule_or_reported():
    # The whole list is accounted for. An action silently dropped would be a
    # policy line nobody reads, again.
    listed = set(AGENT["untrusted_inputs_never_authorize"])
    mapped = {a for a in listed if cc.NEVER_AUTHORIZE_RULES.get(a) is not None}
    _, unenforced = cc.never_authorize_rules(AGENT)
    assert mapped | set(unenforced) == listed


@pytest.mark.req("REQ-SECURITY-UNTRUSTED-001")
def test_the_shell_is_not_denied_outright():
    # shell_default is `ask`. Denying Bash entirely would stop the workflows
    # this bundle ships, so the protection there is the prompt, not a rule.
    deny = cc.build(BOOTSTRAP, AGENT, ROUTING, SENSITIVE) \
             .settings["permissions"]["deny"]
    assert "Bash" not in deny
    assert "Bash(*)" not in deny
