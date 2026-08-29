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


sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
DIST = ROOT / "dist"


def bundle_version() -> str:
    """Read the version from the manifest so artifact names can never desync."""
    import yaml

    data = yaml.safe_load((BUNDLE / "bundle.yml").read_text(encoding="utf-8"))
    return str(data["bundle"]["version"])


# Never published. Mirrors packager.EXCLUDE_NAMES in Spec Kit, which is why
# `specify bundle build` was clean while these archives were not.
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
EXCLUDE_NAMES = {".DS_Store"}


def _publishable(path: Path, source: Path) -> bool:
    rel = path.relative_to(source)
    if EXCLUDE_DIRS.intersection(rel.parts):
        return False
    return path.suffix not in EXCLUDE_SUFFIXES and path.name not in EXCLUDE_NAMES


def zip_dir(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file() and _publishable(path, source):
                archive.write(path, path.relative_to(source))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(dist: Path | None = None) -> int:
    """Build every artifact into `dist`, which defaults to the published one.

    The parameter exists because this function empties its output directory
    before refilling it, and one shared directory is fine for a build and wrong
    for concurrent callers. Six test fixtures hold a catalog server open over
    this output at once under `pytest -n`, and each rebuild deleted archives the
    others were still serving (#191).
    """
    dist = dist or DIST
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_source.py")],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        return result.returncode

    dist.mkdir(parents=True, exist_ok=True)
    for path in dist.iterdir():
        if path.name != ".gitkeep":
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    artifacts: list[Path] = []
    VERSION = bundle_version()

    preset = BUNDLE / "components/presets/lean-full-lifecycle-governance"
    preset_zip = dist / f"lean-full-lifecycle-governance-{VERSION}.zip"
    zip_dir(preset, preset_zip)
    artifacts.append(preset_zip)

    # Every extension, discovered the way the workflows below are. Naming one
    # meant the second shipped in the catalog and not in dist/, so every
    # sandbox install 404'd on an archive the catalog promised.
    for extension in sorted((BUNDLE / "components/extensions").iterdir()):
        if not (extension / "extension.yml").exists():
            continue
        destination = dist / f"{extension.name}-{VERSION}.zip"
        zip_dir(extension, destination)
        artifacts.append(destination)

    for workflow in sorted((BUNDLE / "components/workflows").iterdir()):
        if not (workflow / "workflow.yml").exists():
            continue
        destination = dist / f"{workflow.name}-{VERSION}.zip"
        zip_dir(workflow, destination)
        artifacts.append(destination)

    from generate_catalogs import write_catalogs

    write_catalogs(dist / "catalogs", catalog_root=None)

    checksum_lines = [f"{sha256(path)}  {path.name}" for path in artifacts]
    (dist / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    print(f"Built {len(artifacts)} local artifacts in {dist}")
    print("Run `specify bundle build --path bundle/ --output dist/` for the canonical bundle ZIP.")
    print("Component archives above are what a catalog serves; the bundle ZIP is not installable on its own.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
