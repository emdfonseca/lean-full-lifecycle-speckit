#!/usr/bin/env python3
"""Read-only diagnostics for the GitHub Lifecycle extension."""

from __future__ import annotations

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


def main() -> int:
    # The command whose job is saying where you are had the worst version of
    # the bug: run it one directory below a project and it reported
    # `specify_project: false` about a project that was right there.
    try:
        project = project_root.resolve(required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, indent=2))
        return 2
    # Spec Kit scaffolds extension config as <id>-config.yml and reads the
    # .local.yml sibling first; anything else is not preserved across an update.
    #
    # The template is a deliberate last resort: `specify bundle install` does
    # not scaffold extension config (only `specify extension add` does), so a
    # bundle-installed project legitimately has no scaffolded file yet.
    flavour = script_flavour(project)

    ext_home = project / ".specify/extensions/github-lifecycle"
    config_candidates = [
        ext_home / "github-lifecycle-config.local.yml",
        ext_home / "github-lifecycle-config.yml",
    ]
    template = ext_home / "config-template.yml"
    resolved = next((p for p in config_candidates if p.exists()), None)
    report = {
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
        "notes": [
            "This doctor is read-only.",
            "Use the inspect command for agent-assisted schema inspection.",
            "config_source=template-only means the extension was installed via "
            "`specify bundle install`, which does not scaffold config. Run "
            "`specify extension add github-lifecycle` or copy config-template.yml "
            "to github-lifecycle-config.yml.",
        ],
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
