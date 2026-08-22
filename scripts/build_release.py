#!/usr/bin/env python3
"""Build local component archives and checksums.

The official `specify bundle build` command remains authoritative for the
published bundle artifact.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION = "0.1.0"


def zip_dir(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_source.py")],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        return result.returncode

    DIST.mkdir(exist_ok=True)
    for path in DIST.iterdir():
        if path.name != ".gitkeep":
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    artifacts: list[Path] = []

    preset = ROOT / "components/presets/lean-full-lifecycle-governance"
    preset_zip = DIST / f"lean-full-lifecycle-governance-{VERSION}.zip"
    zip_dir(preset, preset_zip)
    artifacts.append(preset_zip)

    extension = ROOT / "components/extensions/github-lifecycle"
    extension_zip = DIST / f"github-lifecycle-{VERSION}.zip"
    zip_dir(extension, extension_zip)
    artifacts.append(extension_zip)

    for workflow in sorted((ROOT / "components/workflows").iterdir()):
        if not (workflow / "workflow.yml").exists():
            continue
        destination = DIST / f"{workflow.name}-{VERSION}.zip"
        zip_dir(workflow, destination)
        artifacts.append(destination)

    # Local source artifact for inspection only. Use `specify bundle build`
    # to create the canonical published bundle artifact.
    bundle_local = DIST / f"lean-full-lifecycle-local-source-{VERSION}.zip"
    with zipfile.ZipFile(bundle_local, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT / "bundle.yml", "bundle.yml")
        archive.write(ROOT / "README.md", "README.md")
    artifacts.append(bundle_local)

    catalogs = DIST / "catalogs"
    catalogs.mkdir()
    for path in (ROOT / "catalogs").glob("*.json"):
        shutil.copy2(path, catalogs / path.name)

    checksum_lines = [f"{sha256(path)}  {path.name}" for path in artifacts]
    (DIST / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    print(f"Built {len(artifacts)} local artifacts in {DIST}")
    print("Run `specify bundle build --path . --output dist/` for the canonical bundle ZIP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
