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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.inventory import ROOT, load_inventory  # noqa: E402

# Kept in sync with the published release-tag layout.
RELEASE_PATH = "releases/download/v{version}/{filename}"


def published_root(meta: dict) -> str | None:
    """The published catalog root, or None while the bundle is unpublished."""
    pub = meta.get("publishing", {}) or {}
    org = pub.get("org")
    if not org:
        return None
    return f"{pub['host'].rstrip('/')}/{org}/{pub['repo']}"


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
    inv = load_inventory()
    if catalog_root is None:
        catalog_root = published_root(inv.meta)
    layout = layout or default_layout(catalog_root)
    version = inv.version
    repo = published_root(inv.meta) or "UNSET"
    requires = dict(inv.meta["requires"])

    def envelope(name: str, key: str, entries: dict) -> dict:
        return {
            "schema_version": "1.0",
            "updated_at": updated_at,
            "catalog_url": _catalog_url(catalog_root, name),
            key: entries,
        }

    def archive(component_id: str, component_version: str) -> str:
        return _download_url(
            catalog_root, version, f"{component_id}-{component_version}.zip", layout
        )

    def common(comp) -> dict:
        meta = comp.meta
        return {
            "name": meta["name"],
            "id": comp.id,
            "version": comp.version,
            "description": meta["description"],
            "author": meta.get("author", ""),
            "license": meta.get("license", "MIT"),
            "repository": repo,
            "requires": comp.manifest.get("requires", requires),
            "tags": comp.manifest.get("tags", []),
            "verified": False,
        }

    preset = inv.preset
    templates = preset.manifest.get("provides", {}).get("templates", []) or []
    presets = {
        preset.id: {
            **common(preset),
            "download_url": archive(preset.id, preset.version),
            "provides": {
                "templates": sum(1 for t in templates if t.get("type") == "template"),
                "commands": sum(1 for t in templates if t.get("type") == "command"),
            },
        }
    }

    ext = inv.extension
    ext_provides = ext.manifest.get("provides", {}) or {}
    extensions = {
        ext.id: {
            **common(ext),
            "category": ext.meta.get("category", "integration"),
            "effect": ext.meta.get("effect", "read-write"),
            "download_url": archive(ext.id, ext.version),
            "provides": {
                "commands": len(ext_provides.get("commands", []) or []),
                "hooks": len(ext_provides.get("hooks", []) or []),
            },
        }
    }

    workflows = {}
    for comp in inv.by_kind("workflow"):
        workflows[comp.id] = {
            **common(comp),
            # Workflow entries key the archive as "url"; presets, extensions,
            # and bundles all use "download_url". Not interchangeable: a
            # workflow with download_url lists and searches fine and fails only
            # at install with "does not have an install URL in the catalog".
            "url": archive(comp.id, comp.version),
            "provides": {"steps": len(comp.manifest.get("steps", []) or [])},
        }

    bmeta = inv.meta["bundle"]
    bundles = {
        bmeta["id"]: {
            "name": bmeta["name"],
            "id": bmeta["id"],
            "version": version,
            "role": bmeta.get("role", "developer"),
            "description": bmeta["description"],
            "author": bmeta.get("author", ""),
            "license": bmeta.get("license", "MIT"),
            "download_url": archive(bmeta["id"], version),
            "repository": repo,
            "requires": requires,
            "provides": {
                "extensions": len(inv.by_kind("extension")),
                "presets": len(inv.by_kind("preset")) + len(inv.external_preset_refs()),
                "steps": 0,
                "workflows": len(inv.by_kind("workflow")),
            },
            "tags": list(inv.meta.get("tags", [])),
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
