#!/usr/bin/env python3
"""Generate Claude Code's settings from policy, and say what does not map.

`#71` did this for OpenCode. Claude Code's model is a different *shape*, not a
subset: `.claude/settings.json` sorts rule strings into `allow`, `deny`, and
`ask` lists under a default mode, rather than carrying a key per capability.

Different shape means a different set of gaps, and asserting they are the same
set would be guessing. Two rules OpenCode could not express at all --
`plugin_default: deny` and `mcp_default: deny` -- map here:
`enableAllProjectMcpServers: false` and an `enabledPlugins` allowlist. Copying
the other integration's gap list across would understate what this agent
enforces, and a report that is wrong in the alarming direction wastes the
reader's attention on a gap that is not there.

Three rules genuinely do not map, and two of them do not need to: Claude Code
has no session sharing to disable and selects no provider to restrict. The
third, cost and runtime ceilings, is a real gap and says so.

A read-only role is an agent whose tool list omits the writing tools, which is
how `.claude/agents/*.md` frontmatter already works.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

BOOTSTRAP_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/bootstrap-policy.yml",
    "policy/bootstrap-policy.yml",
)
AGENT_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/agent-policy.yml",
    "policy/agent-policy.yml",
)
ROUTING_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/model-routing.yml",
    "policy/model-routing.yml",
)
PROPOSAL_MARKER = "claude-settings-proposal"

# agent-policy speaks of allowing, asking, and denying; the settings sort rules
# into lists with those names. The words line up, and the mapping is stated
# rather than assumed to be identity.
DECISION_TO_LIST = {"allow": "allow", "ask": "ask", "deny": "deny"}


def _load(root: Path, candidates) -> dict:
    for rel in candidates:
        path = root / rel
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"none of {list(candidates)} found; the governance preset must be "
        "installed")


def load_policies(root: Path | None = None) -> tuple[dict, dict, dict]:
    root = root or project_root.resolve(required=False) or Path.cwd()
    return (_load(root, BOOTSTRAP_CANDIDATES),
            _load(root, AGENT_CANDIDATES),
            _load(root, ROUTING_CANDIDATES))


def load_sensitive(root: Path | None = None) -> dict | None:
    """The sensitive-data policy, or None when the preset predates it.

    Loaded here rather than through `load_policies` so the three policies that
    function returns keep their arity -- the other generator reads them too.
    A project whose preset has no `denied_paths` gets no secret-path rules,
    which `--format json` reports as `rules_from_policy: false` rather than
    emitting a config that looks stricter than it is.
    """
    import sensitive
    try:
        return sensitive.load_policy(root)
    except (FileNotFoundError, KeyError):
        return None


@dataclass
class Unmappable:
    rule: str
    why: str
    compensated_by: str

    @property
    def uncompensated(self) -> bool:
        return "Nothing in the configuration" in self.compensated_by

    @property
    def not_applicable(self) -> bool:
        return "Nothing is needed" in self.compensated_by


@dataclass
class Proposal:
    settings: dict = field(default_factory=dict)
    agents: dict[str, dict] = field(default_factory=dict)
    by_rule: dict[str, list[str]] = field(default_factory=dict)
    by_setting: dict[str, str] = field(default_factory=dict)
    unmappable: list[Unmappable] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "settings": self.settings,
            "agents": self.agents,
            "by_rule": self.by_rule,
            "by_setting": self.by_setting,
            "unmappable": [
                {"rule": u.rule, "why": u.why.strip(),
                 "compensated_by": u.compensated_by.strip(),
                 "uncompensated": u.uncompensated,
                 "not_applicable": u.not_applicable}
                for u in self.unmappable],
            "fully_enforced": not [u for u in self.unmappable
                                   if not u.not_applicable],
        }


def _set(target: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def secret_path_rules(sensitive: dict | None) -> list[str]:
    """Deny rules for the file paths a secret lives in.

    `sensitive-data.yml` denies six production data *sources*, none of which
    is a file, so nothing generated here ever stopped a read of `.env`. These
    are the missing half: the deny is at the path, before the read, because a
    secret already read has entered a context redaction cannot reach.

    Emitted for both Read and the shell tools that would otherwise walk
    straight round a Read rule -- denying `Read(.env)` while allowing
    `Bash(cat .env)` is a rule that reads as protection and is not.
    """
    patterns = (sensitive or {}).get("denied_paths") or {}
    rules: list[str] = []
    for entry in patterns.get("patterns") or []:
        glob = entry["glob"]
        rules.append(f"Read({glob})")
        for command in ("cat", "less", "head", "tail"):
            rules.append(f"Bash({command} {glob})")
    return rules


def build(bootstrap: dict, agent: dict, routing: dict,
          sensitive: dict | None = None) -> Proposal:
    spec = bootstrap["integrations"]["claude"]
    runtime = agent["runtime"]
    proposal = Proposal()
    lists: dict[str, list[str]] = {"allow": [], "ask": [], "deny": []}

    for rule, entry in spec["permission_mapping"].items():
        decision = runtime.get(rule)
        target = DECISION_TO_LIST.get(decision)
        if target is None:
            continue
        lists[target].extend(entry["rules"])
        proposal.by_rule[rule] = list(entry["rules"])

    # The commands the workflows run are allowed by name. The default mode
    # still asks, so allowing two commands is not opening the shell.
    for command in (list(bootstrap["verification_commands"]["required"]) +
                    list(bootstrap["verification_commands"]["release"])):
        lists["allow"].append(f"Bash({command})")

    secret_rules = secret_path_rules(sensitive)
    if secret_rules:
        lists["deny"].extend(secret_rules)
        proposal.by_rule["secret_file_read"] = list(secret_rules)

    for name, values in lists.items():
        if values:
            _set(proposal.settings, f"permissions.{name}", values)

    for rule, entry in spec["settings_mapping"].items():
        decision = runtime.get(rule)
        key = f"value_when_{decision}"
        if decision is None or key not in entry:
            continue
        _set(proposal.settings, entry["key"], entry[key])
        proposal.by_setting[rule] = entry["key"]

    read_only = spec["agent_tools"]["read_only"]
    for role, role_spec in (routing.get("roles") or {}).items():
        constraints = (role_spec or {}).get("constraints") or {}
        if constraints.get("edit_permission") == "deny":
            proposal.agents[role] = {"tools": list(read_only)}

    for rule, entry in (spec.get("unmappable") or spec.get("unenforceable")
                        or {}).items():
        proposal.unmappable.append(
            Unmappable(rule, entry["why"], entry["compensated_by"]))
    return proposal


def write_proposal(path: Path, proposal: Proposal, root: Path) -> Path:
    target = project_root.ensure_within(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dict(proposal.to_dict(), kind=PROPOSAL_MARKER), indent=2),
        encoding="utf-8")
    return target


def load_proposal(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") != PROPOSAL_MARKER:
        raise ValueError(
            f"{path} is not an approved settings proposal. Apply writes the "
            f"file that decides what an agent may do; it does not take "
            f"settings from anywhere else.")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, "
                         "then the nearest ancestor with a .specify/ directory.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_propose = sub.add_parser("propose", help="Build a proposal. Writes no settings.")
    p_propose.add_argument("--out", type=Path, required=True)
    p_apply = sub.add_parser("apply", help="Write settings from an approved proposal.")
    p_apply.add_argument("--proposal", type=Path, required=True)
    p_apply.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    try:
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
        bootstrap, agent, routing = load_policies(args.policy_root)
    except (FileNotFoundError, KeyError, project_root.ProjectRootError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.cmd == "propose":
            proposal = build(bootstrap, agent, routing,
                             load_sensitive(args.policy_root))
            target = write_proposal(args.out, proposal, args.policy_root)
            print(json.dumps(proposal.to_dict(), indent=2))
            print(f"\nProposal written to {target}. No settings have changed.",
                  file=sys.stderr)
            for item in proposal.unmappable:
                mark = ("not applicable" if item.not_applicable else
                        "UNCOMPENSATED" if item.uncompensated else "compensated")
                print(f"{mark}: {item.rule}", file=sys.stderr)
            return 0

        data = load_proposal(args.proposal)
        target = project_root.ensure_within(args.policy_root, args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data["settings"], indent=2), encoding="utf-8")
        print(f"Wrote {target} from {args.proposal}.")
        return 0
    except (OSError, ValueError, project_root.OutsideProjectError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
