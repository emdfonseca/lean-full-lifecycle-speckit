#!/usr/bin/env python3
"""Run a clean local-install smoke test when the Spec Kit CLI is available."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--integration", default="opencode")
    args = parser.parse_args()

    if shutil.which("specify") is None:
        print("SKIP: `specify` is not installed.")
        return 2

    with tempfile.TemporaryDirectory(prefix="lean-full-lifecycle-") as tmp:
        target = Path(tmp)
        run([
            sys.executable,
            str(ROOT / "scripts/install_dev.py"),
            "--target", str(target),
            "--integration", args.integration,
        ], ROOT)
        run(["specify", "bundle", "list"], target)
        run(["specify", "preset", "resolve", "speckit.specify"], target)
        run(["specify", "workflow", "info", "lifecycle-story-delivery"], target)

        # Run the installer twice; the second pass must not fail.
        run([
            sys.executable,
            str(ROOT / "scripts/install_dev.py"),
            "--target", str(target),
            "--integration", args.integration,
        ], ROOT)

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
