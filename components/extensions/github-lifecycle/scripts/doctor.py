#!/usr/bin/env python3
"""Read-only diagnostics for the GitHub Lifecycle extension."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


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


def main() -> int:
    project = Path.cwd()
    config_candidates = [
        project / ".specify/extensions/github-lifecycle/config.yml",
        project / ".specify/extensions/github-lifecycle/config-template.yml",
    ]
    report = {
        "gh_auth": run(["gh", "auth", "status"]),
        "repository": run(["gh", "repo", "view", "--json", "nameWithOwner,url"]),
        "config": next((str(p) for p in config_candidates if p.exists()), None),
        "specify_project": (project / ".specify").exists(),
        "notes": [
            "This doctor is read-only.",
            "Use the inspect command for agent-assisted schema inspection.",
        ],
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
