#!/usr/bin/env python3
"""Install local bundle source components into a target Spec Kit project.

This is a development installer. It does not publish catalogs or mutate GitHub.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
WORKFLOWS = [
    "lifecycle-greenfield-bootstrap",
    "lifecycle-brownfield-adoption",
    "lifecycle-story-delivery",
    "lifecycle-bugfix",
    "lifecycle-release-outcome",
    "lifecycle-incident-hotfix",
    "lifecycle-retirement",
]


def run(command: list[str], cwd: Path, dry_run: bool, capture: bool = False) -> str:
    print("+", " ".join(str(x) for x in command))
    if dry_run:
        return ""
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=capture,
        check=False,
    )
    if result.returncode != 0:
        if capture:
            if result.stdout:
                print(result.stdout, file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
        raise SystemExit(
            f"Command failed ({result.returncode}): {' '.join(command)}"
        )
    return result.stdout if capture else ""


def component_present(target: Path, kind: str, component_id: str) -> bool:
    plural = {
        "preset": "presets",
        "extension": "extensions",
        "workflow": "workflows",
    }[kind]
    return (target / ".specify" / plural / component_id).exists()


def require_clean_or_explicit(target: Path, dry_run: bool, allow_dirty: bool) -> None:
    if dry_run or allow_dirty or not (target / ".git").exists():
        return
    if shutil.which("git") is None:
        raise SystemExit(
            "Git repository detected but `git` is unavailable. "
            "Use --allow-dirty only after creating an external backup."
        )
    output = run(["git", "status", "--porcelain"], target, False, capture=True)
    if output.strip():
        raise SystemExit(
            "Target Git working tree is not clean. Commit/stash changes or "
            "rerun with --allow-dirty after explicitly accepting the risk."
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--integration", default="opencode")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--skip-bundle-record", action="store_true")
    args = parser.parse_args()

    target = args.target.expanduser().resolve()
    if not target.exists() or not target.is_dir():
        raise SystemExit(f"Target directory does not exist: {target}")

    if shutil.which("specify") is None and not args.dry_run:
        raise SystemExit("`specify` is not installed or not on PATH.")

    run(
        [sys.executable, str(ROOT / "scripts/validate_source.py")],
        ROOT,
        args.dry_run,
    )
    require_clean_or_explicit(target, args.dry_run, args.allow_dirty)

    if not (target / ".specify").exists():
        run(
            [
                "specify",
                "init",
                "--here",
                "--integration",
                args.integration,
                "--script",
                "py",
                "--non-interactive",
            ],
            target,
            args.dry_run,
        )

    if not component_present(target, "preset", "lean"):
        run(
            ["specify", "preset", "add", "lean", "--priority", "20"],
            target,
            args.dry_run,
        )

    if not component_present(
        target, "preset", "lean-full-lifecycle-governance"
    ):
        run(
            [
                "specify",
                "preset",
                "add",
                "--dev",
                str(
                    ROOT
                    / "bundle/components/presets/lean-full-lifecycle-governance"
                ),
                "--priority",
                "10",
            ],
            target,
            args.dry_run,
        )

    if not component_present(target, "extension", "github-lifecycle"):
        run(
            [
                "specify",
                "extension",
                "add",
                "--dev",
                str(BUNDLE / "components/extensions/github-lifecycle"),
            ],
            target,
            args.dry_run,
        )

    for workflow_id in WORKFLOWS:
        if component_present(target, "workflow", workflow_id):
            continue
        run(
            [
                "specify",
                "workflow",
                "add",
                str(BUNDLE / "components/workflows" / workflow_id),
            ],
            target,
            args.dry_run,
        )

    run(
        ["specify", "bundle", "validate", "--path", str(BUNDLE), "--offline"],
        target,
        args.dry_run,
    )

    if not args.skip_bundle_record:
        run(
            ["specify", "bundle", "install", str(BUNDLE)],
            target,
            args.dry_run,
        )

    run(
        ["specify", "preset", "resolve", "speckit.specify"],
        target,
        args.dry_run,
    )
    run(
        ["specify", "preset", "resolve", "speckit.plan"],
        target,
        args.dry_run,
    )
    run(
        ["specify", "workflow", "info", "lifecycle-story-delivery"],
        target,
        args.dry_run,
    )
    run(
        ["specify", "integration", "status", "--json"],
        target,
        args.dry_run,
    )

    print("Local development installation completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
