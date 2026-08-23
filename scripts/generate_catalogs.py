#!/usr/bin/env python3
"""Generate the four component catalogs from the manifests on disk.

A bundle artifact is not a container: `specify bundle install` reads only the
manifest and resolves every component from a catalog (or from an asset shipped
inside Spec Kit itself). Catalogs are therefore the only install path, and they
must be generated rather than hand-maintained -- there are four of them, each
with one entry per component.

The catalog root is a parameter. Locally it is a `file://` URL over `dist/`,
which makes the whole install lifecycle testable with no hosting; at release it
is the published base URL. Nothing else differs between the two.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"

# Kept in sync with the published release-tag layout.
RELEASE_PATH = "releases/download/v{version}/{filename}"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _components() -> dict:
    """Read every component manifest. The manifests are the single source of truth."""
    preset_dir = BUNDLE / "components/presets/lean-full-lifecycle-governance"
    ext_dir = BUNDLE / "components/extensions/github-lifecycle"
    return {
        "bundle": _load(BUNDLE / "bundle.yml"),
        "preset": (preset_dir, _load(preset_dir / "preset.yml")),
        "extension": (ext_dir, _load(ext_dir / "extension.yml")),
        "workflows": [
            (d, _load(d / "workflow.yml"))
            for d in sorted((BUNDLE / "components/workflows").iterdir())
            if (d / "workflow.yml").exists()
        ],
    }


def default_layout(catalog_root: str | None) -> str:
    """Local roots serve archives flat out of dist/; published roots use release tags."""
    if catalog_root is None:
        return "flat"
    root = catalog_root.rstrip("/")
    local = root.startswith(("file://", "/")) or "//localhost" in root or "//127.0.0.1" in root
    return "flat" if local else "release"


def _download_url(
    catalog_root: str | None, version: str, filename: str, layout: str
) -> str:
    if catalog_root is None:
        return "UNSET"
    root = catalog_root.rstrip("/")
    if layout == "flat":
        return f"{root}/{filename}"
    return f"{root}/{RELEASE_PATH.format(version=version, filename=filename)}"


def _catalog_url(catalog_root: str | None, name: str) -> str:
    if catalog_root is None:
        return "UNSET"
    return f"{catalog_root.rstrip('/')}/catalogs/{name}.json"


def build_catalogs(
    catalog_root: str | None, updated_at: str, layout: str | None = None
) -> dict[str, dict]:
    layout = layout or default_layout(catalog_root)
    c = _components()
    bundle = c["bundle"]["bundle"]
    version = str(bundle["version"])

    def envelope(name: str, key: str, entries: dict) -> dict:
        return {
            "schema_version": "1.0",
            "updated_at": updated_at,
            "catalog_url": _catalog_url(catalog_root, name),
            key: entries,
        }

    preset_dir, preset = c["preset"]
    pmeta = preset["preset"]
    presets = {
        pmeta["id"]: {
            "name": pmeta["name"],
            "id": pmeta["id"],
            "version": str(pmeta["version"]),
            "description": pmeta["description"],
            "author": pmeta.get("author", ""),
            "license": pmeta.get("license", "MIT"),
            "download_url": _download_url(
                catalog_root, version, f"{pmeta['id']}-{pmeta['version']}.zip", layout
            ),
            "repository": pmeta.get("repository", "UNSET"),
            "requires": preset.get("requires", {}),
            "provides": {
                "templates": sum(
                    1 for t in preset.get("provides", {}).get("templates", [])
                    if t.get("type") == "template"
                ),
                "commands": sum(
                    1 for t in preset.get("provides", {}).get("templates", [])
                    if t.get("type") == "command"
                ),
            },
            "tags": preset.get("tags", []),
            "verified": False,
        }
    }

    ext_dir, extension = c["extension"]
    emeta = extension["extension"]
    extensions = {
        emeta["id"]: {
            "name": emeta["name"],
            "id": emeta["id"],
            "version": str(emeta["version"]),
            "description": emeta["description"],
            "author": emeta.get("author", ""),
            "license": emeta.get("license", "MIT"),
            "category": emeta.get("category", "integration"),
            "effect": emeta.get("effect", "read-write"),
            "download_url": _download_url(
                catalog_root, version, f"{emeta['id']}-{emeta['version']}.zip", layout
            ),
            "repository": emeta.get("repository", "UNSET"),
            "requires": extension.get("requires", {}),
            "provides": {
                "commands": len(extension.get("provides", {}).get("commands", [])),
                "hooks": len(extension.get("provides", {}).get("hooks", [])),
            },
            "tags": extension.get("tags", []),
            "verified": False,
        }
    }

    workflows = {}
    for wdir, wf in c["workflows"]:
        wmeta = wf["workflow"]
        workflows[wmeta["id"]] = {
            "name": wmeta["name"],
            "id": wmeta["id"],
            "version": str(wmeta["version"]),
            "description": wmeta["description"],
            "author": wmeta.get("author", ""),
            "license": wmeta.get("license", "MIT"),
            # Workflow entries key the archive as "url"; presets, extensions,
            # and bundles all use "download_url". Not interchangeable.
            "url": _download_url(
                catalog_root, version, f"{wmeta['id']}-{wmeta['version']}.zip", layout
            ),
            "repository": bundle.get("repository", "UNSET"),
            "requires": wf.get("requires", {}),
            "provides": {"steps": len(wf.get("steps", []))},
            "tags": wf.get("tags", []),
            "verified": False,
        }

    bundles = {
        bundle["id"]: {
            "name": bundle["name"],
            "id": bundle["id"],
            "version": version,
            "role": bundle.get("role", "developer"),
            "description": bundle["description"],
            "author": bundle.get("author", ""),
            "license": bundle.get("license", "MIT"),
            "download_url": _download_url(
                catalog_root, version, f"{bundle['id']}-{version}.zip", layout
            ),
            "repository": bundle.get("repository", "UNSET"),
            "requires": c["bundle"].get("requires", {}),
            "provides": {
                "extensions": len(c["bundle"]["provides"].get("extensions", [])),
                "presets": len(c["bundle"]["provides"].get("presets", [])),
                "steps": len(c["bundle"]["provides"].get("steps", [])),
                "workflows": len(c["bundle"]["provides"].get("workflows", [])),
            },
            "tags": c["bundle"].get("tags", []),
            "verified": False,
        }
    }

    return {
        "presets": envelope("presets", "presets", presets),
        "extensions": envelope("extensions", "extensions", extensions),
        "workflows": envelope("workflows", "workflows", workflows),
        "bundles": envelope("bundles", "bundles", bundles),
    }


def write_catalogs(
    out_dir: Path,
    catalog_root: str | None,
    updated_at: str = "2026-08-23T00:00:00Z",
    layout: str | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in build_catalogs(catalog_root, updated_at, layout).items():
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "catalogs")
    ap.add_argument(
        "--catalog-root",
        default=None,
        help="Base URL or file:// path the catalogs point at. Omit to emit UNSET.",
    )
    ap.add_argument("--updated-at", default="2026-08-23T00:00:00Z")
    ap.add_argument(
        "--layout",
        choices=["flat", "release"],
        default=None,
        help="Artifact layout under the root. Defaults to flat for local roots.",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Fail if the committed catalogs differ from freshly generated ones.",
    )
    args = ap.parse_args()

    if args.check:
        expected = build_catalogs(args.catalog_root, args.updated_at, args.layout)
        drift = []
        for name, data in expected.items():
            path = args.out / f"{name}.json"
            want = json.dumps(data, indent=2) + "\n"
            if not path.exists() or path.read_text(encoding="utf-8") != want:
                drift.append(str(path.relative_to(ROOT)))
        if drift:
            print("Catalogs are stale; run scripts/generate_catalogs.py:")
            for d in drift:
                print(f"  - {d}")
            return 1
        print("Catalogs match the manifests.")
        return 0

    written = write_catalogs(args.out, args.catalog_root, args.updated_at, args.layout)
    for path in written:
        print(f"wrote {path.relative_to(ROOT) if ROOT in path.parents else path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
