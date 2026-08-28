#!/usr/bin/env python3
"""Read-only diagnostics for the GitHub Lifecycle extension."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402


def run(command: list[str], timeout: int = 20) -> dict[str, Any]:
    if shutil.which(command[0]) is None:
        return {"status": "missing", "command": command}
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "command": command}
    return {
        "status": "ok" if result.returncode == 0 else "error",
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout.strip()[:4000],
        "stderr": result.stderr.strip()[:4000],
    }


POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/bootstrap-policy.yml",
    "policy/bootstrap-policy.yml",
)

MODEL_ROUTING_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/model-routing.yml",
    "policy/model-routing.yml",
)

# The binaries a shipped script executes without a condition attached, and what
# their absence costs. A flat pass/fail list would be wrong: `gh` and `git` do
# not fail alike, and stating only that one is missing says nothing about which
# workflow stops.
FIXED_BINARIES = (
    {
        "binary": "gh",
        "condition": "unconditional",
        "on_absence": "every board command fails; the extension reaches "
                      "GitHub no other way",
    },
    {
        "binary": "git",
        "condition": "optional",
        "on_absence": "transition_plan.modified_tracked_files returns None and "
                      "the audit runs without its working_tree_disagreement "
                      "rule, reporting nothing rather than failing",
    },
)


def _load_yaml(path: Path):
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


INTEGRATION_JSON = ".specify/integration.json"


def resolve_integration(project: Path, override: str | None = None) -> dict:
    """Which integration this project uses, and where that was read.

    The bundle is agent-neutral, so no agent is named as a default here. Spec
    Kit records the project's answer in `.specify/integration.json` --
    `default_integration`, or `integration` in the older shape -- and that is
    the only place it exists, because `framework.yml` says `integration: auto`
    and leaves resolution to run time.

    Unresolved is a real answer and is reported as one. Assuming an agent is
    how a project gets told to install a binary nothing here will run.
    """
    if override:
        return {"integration": override, "source": "--integration"}
    path = project / INTEGRATION_JSON
    if not path.is_file():
        return {"integration": None, "source": None,
                "detail": f"{INTEGRATION_JSON} is absent, so this project "
                          f"declares no integration and none is assumed"}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"integration": None, "source": None,
                "detail": f"{INTEGRATION_JSON} could not be read "
                          f"({exc.__class__.__name__})"}
    key = state.get("default_integration") or state.get("integration")
    key = str(key).strip().lower() if isinstance(key, str) and key.strip() else None
    if key is None:
        return {"integration": None, "source": None,
                "detail": f"{INTEGRATION_JSON} names no default integration"}
    return {"integration": key, "source": INTEGRATION_JSON}


def binary_dependencies(project: Path, integration: str | None = None,
                        which=shutil.which) -> list[dict]:
    """Every binary this project will execute, with the condition attached.

    `gh` and `git` are executed by every project. The model-inventory binary is
    not: `model-routing.yml` keys `inventory_command` by integration, and an
    integration declaring null cannot be asked at all. Naming that binary to a
    project that never runs it would be a false prerequisite, which is the same
    defect as not naming it to a project that does.
    """
    reports = [
        {**entry,
         "status": "ok" if which(entry["binary"]) else "missing"}
        for entry in FIXED_BINARIES
    ]

    if not integration:
        # Not "no binary needed": we do not know which one, and saying so is
        # different from having looked.
        reports.append({
            "integration": None,
            "status": "unknown",
            "detail": "this project declares no integration, so which "
                      "model-inventory binary it executes is unknown",
        })
        return reports

    declared = None
    for rel in MODEL_ROUTING_CANDIDATES:
        candidate = project / rel
        if candidate.is_file():
            try:
                declared = _load_yaml(candidate)["resolution"]["inventory_command"]
            except Exception:  # noqa: BLE001
                declared = None
            break
    if declared is None:
        reports.append({
            "integration": integration,
            "status": "unknown",
            "detail": "the governance preset is not installed, so no inventory "
                      "command is declared for this integration",
        })
        return reports

    if isinstance(declared, list):
        # A policy predating the per-integration form, honoured the way
        # opencode_models.inventory_command honours it.
        command = list(declared)
    elif integration not in declared:
        reports.append({
            "integration": integration,
            "status": "unknown",
            "detail": f"model-routing.yml declares no inventory command for "
                      f"{integration!r}; it has {sorted(declared)}",
        })
        return reports
    else:
        command = declared[integration]

    if not command:
        # Stated, not omitted: this project has no model-inventory binary, and
        # saying so is different from having failed to look.
        reports.append({
            "integration": integration,
            "status": "not_applicable",
            "detail": f"{integration!r} declares no inventory command in "
                      f"model-routing.yml, so this project executes no binary "
                      f"to read a model inventory",
        })
        return reports

    reports.append({
        "binary": command[0],
        "condition": f"required by integration {integration!r}, whose "
                     f"inventory command is {' '.join(command)!r}",
        "on_absence": "opencode_models.read_inventory raises InventoryError, "
                      "so no model id can be verified and model routing "
                      "refuses",
        "status": "ok" if which(command[0]) else "missing",
    })
    return reports


def script_flavour(project: Path) -> dict:
    """Whether this project asked for a script flavour we provide.

    `specify init --script py|sh` records the choice, and Spec Kit installs
    both flavours of its own scripts either way. This extension provides one.
    A mismatch is not a broken install -- the scripts are there and run
    wherever python3 is -- it means the project asked for shell and nothing
    here honours that. Better learned now than during a command.
    """
    policy = None
    for rel in POLICY_CANDIDATES:
        candidate = project / rel
        if candidate.is_file():
            try:
                import yaml

                policy = yaml.safe_load(
                    candidate.read_text(encoding="utf-8")).get("script_flavours")
            except Exception:  # noqa: BLE001
                policy = None
            break
    if not policy:
        return {"status": "unknown",
                "detail": "the governance preset is not installed, so the "
                          "provided flavour is not declared"}

    options = project / policy["project_choice_file"]
    if not options.is_file():
        return {"status": "unknown", "provided": policy["provided"],
                "detail": f"{policy['project_choice_file']} is absent; this "
                          f"may not be a project `specify init` created"}
    try:
        chosen = json.loads(options.read_text(encoding="utf-8")).get(
            policy["project_choice_key"])
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "unknown", "provided": policy["provided"],
                "detail": f"{policy['project_choice_file']} could not be read "
                          f"({exc.__class__.__name__})"}

    if chosen in policy["provided"]:
        return {"status": "ok", "chosen": chosen, "provided": policy["provided"]}
    return {"status": "mismatch", "chosen": chosen,
            "provided": policy["provided"],
            "detail": " ".join(policy["on_mismatch"].split())}


def report(project: Path, integration: str | None = None) -> dict:
    """Everything this doctor knows about one project.

    Separated from `main` so `status.py` can compose the same answer instead of
    shelling out to this command and parsing it back, or -- worse -- carrying a
    second copy of the wiring checks that would drift from these.
    """
    # Spec Kit scaffolds extension config as <id>-config.yml and reads the
    # .local.yml sibling first; anything else is not preserved across an update.
    #
    # The template is a deliberate last resort: `specify bundle install` does
    # not scaffold extension config (only `specify extension add` does), so a
    # bundle-installed project legitimately has no scaffolded file yet.
    flavour = script_flavour(project)
    resolved_integration = resolve_integration(project, integration)

    ext_home = project / ".specify/extensions/github-lifecycle"
    config_candidates = [
        ext_home / "github-lifecycle-config.local.yml",
        ext_home / "github-lifecycle-config.yml",
    ]
    template = ext_home / "config-template.yml"
    resolved = next((p for p in config_candidates if p.exists()), None)
    return {
        "gh_auth": run(["gh", "auth", "status"]),
        "repository": run(["gh", "repo", "view", "--json", "nameWithOwner,url"]),
        "config": str(resolved) if resolved else None,
        "config_source": (
            "scaffolded" if resolved
            else "template-only" if template.exists()
            else "missing"
        ),
        "specify_project": (project / ".specify").exists(),
        "script_flavour": flavour,
        "integration": resolved_integration,
        "binaries": binary_dependencies(
            project, resolved_integration["integration"]),
        "notes": [
            "This doctor is read-only.",
            "binaries lists what this project will execute, with the condition "
            "attached. A binary another integration needs is not reported to a "
            "project that never runs it.",
            "Use the inspect command for agent-assisted schema inspection.",
            "config_source=template-only means the extension was installed via "
            "`specify bundle install`, which does not scaffold config. Run "
            "`specify extension add github-lifecycle` or copy config-template.yml "
            "to github-lifecycle-config.yml.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # An override, not a default. framework.yml says `integration: auto`, and
    # the project's own integration.json is where Spec Kit records what that
    # resolved to.
    ap.add_argument("--integration", default=None,
                    help="Override the integration. Without it the project's "
                         "own .specify/integration.json decides, and an "
                         "absent one is reported rather than guessed.")
    args = ap.parse_args()
    # The command whose job is saying where you are had the worst version of
    # the bug: run it one directory below a project and it reported
    # `specify_project: false` about a project that was right there.
    try:
        project = project_root.resolve(required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, indent=2))
        return 2
    print(json.dumps(report(project, args.integration), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
