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


# --- AC2: the reviewer's edit denial is reported, not approximated ------------

@pytest.mark.req("REQ-SECURITY-CLAUDE-002")
def test_edit_permission_is_reported_as_unmappable(proposal):
    assert "edit_permission" in {u.rule for u in proposal.unmappable}


@pytest.mark.req("REQ-SECURITY-CLAUDE-002")
def test_the_edit_denial_is_not_claimed_as_compensated_by_the_config(proposal):
    # Claude Code has no per-agent edit permission. Reporting it as compensated
    # would say the generated settings hold a denial they do not hold.
    entry = [u for u in proposal.unmappable if u.rule == "edit_permission"][0]
    assert entry.uncompensated
    assert not entry.not_applicable


@pytest.mark.req("REQ-SECURITY-CLAUDE-002")
def test_the_proposal_carries_no_per_agent_tool_list(proposal):
    # A curated tool list decides what an agent is offered, not what it is
    # refused, and Bash alone writes anything the shell reaches. Emitting one
    # made the config read as stricter than it is.
    assert "agents" not in proposal.to_dict()
    assert not hasattr(proposal, "agents")


@pytest.mark.req("REQ-SECURITY-CLAUDE-002")
def test_no_policy_key_feeds_a_per_agent_tool_list():
    assert "agent_tools" not in SPEC


@pytest.mark.req("REQ-SECURITY-CLAUDE-002")
def test_a_role_constraint_the_settings_cannot_express_leaves_them_unchanged():
    routing = copy.deepcopy(ROUTING)
    routing["roles"]["reviewer"]["constraints"].pop("edit_permission")
    assert (cc.build(BOOTSTRAP, AGENT, routing).settings
            == cc.build(BOOTSTRAP, AGENT, ROUTING).settings)


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
def test_the_genuine_gaps_are_marked_uncompensated(proposal):
    # Two, since edit_permission stopped being approximated by a tool list and
    # started being reported as the gap it always was.
    uncompensated = {u.rule for u in proposal.unmappable if u.uncompensated}
    assert uncompensated == {"cost_and_runtime_limits", "edit_permission",
                             "secret_file_read_via_subprocess"}


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
def test_no_generated_rule_names_a_reader():
    """The control is the path, not a list of commands that read it.

    This asserted `Bash(cat **/.env)` and three more like it. Enumerating
    readers denies four spellings of an operation the shell offers a dozen ways,
    and the next reader not on the list still passes -- the rule the docstring
    itself calls "protection that is not" (#135).

    Those rules were inert besides: a Bash rule matches the whole command text
    with `*` standing for any text, so `Bash(cat **/.env)` requires a literal
    `/` before `.env` and never matched `cat .env`.
    """
    deny = cc.build(BOOTSTRAP, AGENT, ROUTING, SENSITIVE) \
             .settings["permissions"]["deny"]
    named = [r for r in deny if r.startswith("Bash(")
             and any(f"({reader} " in r
                     for reader in ("cat", "less", "head", "tail", "sed",
                                    "awk", "xxd", "base64", "strings"))]
    assert not named, f"rules naming a reader rather than a path: {named}"


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_each_denied_path_gets_exactly_one_rule():
    # One path, one rule. Four extra per path was the enumeration this removed.
    import sensitive as sd
    rules = cc.secret_path_rules(SENSITIVE)
    assert len(rules) == len(sd.denied_path_patterns(SENSITIVE))
    assert all(r.startswith("Read(") for r in rules)


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_what_no_permission_list_covers_is_reported_not_approximated():
    # A subprocess opening the file itself reads a denied path through an
    # interpreter no list enumerates. Reported as a gap rather than answered
    # with more command names.
    built = cc.build(BOOTSTRAP, AGENT, ROUTING, SENSITIVE)
    gap = [u for u in built.unmappable
           if u.rule == "secret_file_read_via_subprocess"]
    assert gap, "the residue is not recorded"
    assert gap[0].uncompensated, "an open gap must not read as compensated"


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
