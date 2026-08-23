#!/usr/bin/env python3
"""End-to-end lifecycle smoke test over a local catalog.

This is the P0c gate. It exercises the only path a real user has: components
resolved from a catalog, not `--dev` directory installs. Every step here either
errored or silently no-opped before the catalog harness existed.

Exit codes: 0 pass, 1 fail, 2 skipped (no `specify` on PATH).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]

FAILED: list[str] = []
PASSED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
    return ok


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True)


def counts(project: Path) -> dict[str, int]:
    def n(args: list[str], pattern: str) -> int:
        out = run(args, project).stdout
        return len(re.findall(pattern, out))

    return {
        # "priority \\d+" and not "priority ": the listing footer explains
        # "Lower priority number = higher precedence" and would be counted.
        "presets": n(["specify", "preset", "list"], r"priority \d+"),
        "extensions": n(["specify", "extension", "list"], r"github-lifecycle"),
        "workflows": n(["specify", "workflow", "list"], r"lifecycle-[a-z-]+"),
    }


def bundle_components(project: Path) -> int:
    out = run(["specify", "bundle", "list"], project).stdout
    for line in out.splitlines():
        if "lean-full-lifecycle" in line and "component" in line:
            for token in line.replace("(", " ").split():
                if token.isdigit():
                    return int(token)
    return -1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--integration", default="opencode")
    ap.add_argument("--keep", action="store_true", help="Keep the scratch project.")
    args = ap.parse_args()

    if not shutil.which("specify"):
        print("SKIP: specify not on PATH")
        return 2

    import local_catalog

    tmp = Path(tempfile.mkdtemp(prefix="speckit-smoke-"))
    project = tmp / "project"
    project.mkdir()
    try:
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        r = run([
            "specify", "init", "--here", "--force", "--non-interactive",
            "--integration", args.integration, "--script", "py",
        ], project)
        if not check("specify init", r.returncode == 0, r.stderr.strip()[:120]):
            return 1

        with local_catalog.serve() as base:
            print(f"\nlocal catalog: {base}\n")
            local_catalog.register(project, base)
            check("catalog registration", True)

            # Workflows first: see local_catalog.install_workflows for why.
            local_catalog.install_workflows(project)

            r = run(["specify", "bundle", "install", "lean-full-lifecycle"], project)
            check("bundle install", r.returncode == 0, r.stderr.strip()[:120])

            c = counts(project)
            check("2 presets installed", c["presets"] == 2, str(c["presets"]))
            check("1 extension installed", c["extensions"] >= 1, str(c["extensions"]))
            check("7 workflows installed", c["workflows"] == 7, str(c["workflows"]))

            n = bundle_components(project)
            # 3 rather than 10: the upstream workflow_add defect forces
            # workflows to be installed ahead of the bundle, so they are
            # recorded as "already present" and never attributed to it.
            check("bundle records its components", n == 3, f"{n} attributed")

            r = run(["specify", "bundle", "info", "lean-full-lifecycle"], project)
            check("bundle info", r.returncode == 0, r.stderr.strip()[:120])

            r = run(["specify", "preset", "resolve", "speckit.specify"], project)
            layered = "[base]" in r.stdout and "[append]" in r.stdout
            check("preset composition layers", layered)

            r = run(["specify", "bundle", "install", "lean-full-lifecycle"], project)
            check("second install idempotent",
                  r.returncode == 0 and "0 added" in r.stdout,
                  r.stdout.strip().splitlines()[-1][:80] if r.stdout else "")

            r = run(["specify", "bundle", "update", "lean-full-lifecycle"], project)
            check("bundle update", r.returncode == 0, r.stderr.strip()[:120])

            r = run(["specify", "bundle", "remove", "lean-full-lifecycle"], project)
            check("bundle remove", r.returncode == 0, r.stderr.strip()[:120])
            after = counts(project)
            check("remove uninstalls attributed components",
                  after["presets"] == 0 and after["extensions"] == 0,
                  json.dumps(after))

            r = run(["specify", "bundle", "install", "lean-full-lifecycle"], project)
            check("reinstall after remove", r.returncode == 0, r.stderr.strip()[:120])

        print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
        if FAILED:
            for name in FAILED:
                print(f"  failed: {name}")
            return 1
        return 0
    finally:
        if args.keep:
            print(f"kept: {project}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
