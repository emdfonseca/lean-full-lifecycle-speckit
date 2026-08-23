#!/usr/bin/env python3
"""Generate the OpenCode configuration, and say what it cannot enforce.

`agent-policy.yml` states ten runtime rules. OpenCode expresses some directly
-- `permission.bash`, `permission.edit`, `permission.webfetch`,
`permission.external_directory`, each ask/allow/deny, plus `share` -- some only
as bash patterns, and two not at all: `plugin_default: deny` and
`mcp_default: deny` have no permission primitive, only allowlists.

A generator that emitted a config and reported success would be claiming
enforcement it does not have, and everyone downstream would believe the config
is stricter than it is. So the report is in two halves: what was configured, and
what could not be. The second half is the point.

Three judgements, all in `bootstrap-policy.yml`:

**A rule with no primitive is listed, not dropped.** Each names why OpenCode
cannot express it and what compensates. One of them -- cost and runtime
ceilings -- has no compensation and says so, because a made-up mitigation is
worse than an admitted gap.

**The bash default stays `ask` while the verification commands are allowed by
pattern.** Allowing the two commands the workflows run is not a reason to open
the shell.

**Nothing is written until a proposal has been approved.** Propose writes a
proposal; apply writes the config and refuses without one.
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


@dataclass
class Unenforceable:
    rule: str
    why: str
    compensated_by: str

    @property
    def uncompensated(self) -> bool:
        return "Nothing in the configuration" in self.compensated_by


@dataclass
class Proposal:
    config: dict = field(default_factory=dict)
    configured: dict[str, str] = field(default_factory=dict)
    by_pattern: dict[str, list[str]] = field(default_factory=dict)
    unenforceable: list[Unenforceable] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "config": self.config,
            "configured": self.configured,
            "by_pattern": self.by_pattern,
            "unenforceable": [
                {"rule": u.rule, "why": u.why.strip(),
                 "compensated_by": u.compensated_by.strip(),
                 "uncompensated": u.uncompensated}
                for u in self.unenforceable],
            # Stated, so a reader does not have to infer it from an empty
            # problems list: a generated config is not a fully enforced policy.
            "fully_enforced": not self.unenforceable,
        }


def _set(target: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def build(bootstrap: dict, agent: dict, routing: dict) -> Proposal:
    spec = bootstrap["integrations"]["opencode"]
    runtime = agent["runtime"]
    proposal = Proposal()

    for rule, key in spec["permission_mapping"].items():
        value = runtime.get(rule)
        if value is None:
            continue
        _set(proposal.config, key, value)
        proposal.configured[rule] = key

    # Allowing the two commands the workflows run is not a reason to open the
    # shell, so the default stays whatever the policy says and the allowances
    # are named individually.
    allowed = list(bootstrap["verification_commands"]["required"]) + \
        list(bootstrap["verification_commands"]["release"])
    # The same key the mapping already named for shell_default. Writing it
    # again here would mean a policy that moved the key sent the defaults to
    # the new place and the pattern map to the old one.
    bash_key = spec["permission_mapping"]["shell_default"]
    bash = {"*": runtime.get("shell_default", "ask")}
    for command in allowed:
        bash[command] = "allow"

    for rule, entry in (spec.get("bash_pattern_rules") or {}).items():
        decision = runtime.get(rule)
        if decision is None:
            continue
        for pattern in entry["patterns"]:
            bash[pattern] = decision
        proposal.by_pattern[rule] = list(entry["patterns"])
    _set(proposal.config, bash_key, bash)

    # Per-agent permissions. The reviewer's edit denial is a policy constraint,
    # not a preference, and it maps cleanly onto a per-agent permission object.
    agents: dict[str, dict] = {}
    for role, role_spec in (routing.get("roles") or {}).items():
        constraints = (role_spec or {}).get("constraints") or {}
        edit = constraints.get("edit_permission")
        if edit:
            agents[role] = {"permission": {"edit": edit}}
    if agents:
        proposal.config["agent"] = agents

    for rule, entry in (spec.get("unenforceable") or {}).items():
        proposal.unenforceable.append(
            Unenforceable(rule, entry["why"], entry["compensated_by"]))
    return proposal


PROPOSAL_MARKER = "opencode-config-proposal"


def write_proposal(path: Path, proposal: Proposal, root: Path) -> Path:
    target = project_root.ensure_within(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(proposal.to_dict(), kind=PROPOSAL_MARKER)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def load_proposal(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") != PROPOSAL_MARKER:
        raise ValueError(
            f"{path} is not an approved configuration proposal. Apply writes "
            f"the file that decides what an agent may do; it does not take a "
            f"config from anywhere else.")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, "
                         "then the nearest ancestor with a .specify/ directory.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_propose = sub.add_parser("propose", help="Build a proposal. Writes no config.")
    p_propose.add_argument("--out", type=Path, required=True)
    p_apply = sub.add_parser("apply", help="Write the config from an approved proposal.")
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
            proposal = build(bootstrap, agent, routing)
            target = write_proposal(args.out, proposal, args.policy_root)
            print(json.dumps(proposal.to_dict(), indent=2))
            print(f"\nProposal written to {target}. No configuration has "
                  f"changed.", file=sys.stderr)
            for item in proposal.unenforceable:
                mark = "UNCOMPENSATED" if item.uncompensated else "compensated"
                print(f"{mark} {item.rule}", file=sys.stderr)
            return 0

        data = load_proposal(args.proposal)
        target = project_root.ensure_within(args.policy_root, args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data["config"], indent=2), encoding="utf-8")
        print(f"Wrote {target} from {args.proposal}.")
        return 0
    except (OSError, ValueError, project_root.OutsideProjectError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
