"""The component inventory, read from the manifests on disk.

Before this existed, "what components are in this bundle" was written down in
five places -- bundle.yml, install_dev.py, validate_source.py, the tests, and
four catalog files -- and nothing checked that they agreed. Adding a workflow
meant editing all five by hand.

Here the manifests *are* the inventory. Everything else derives from it, so
adding a component means creating one directory.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "bundle"
TOOLING = ROOT / "tooling"

# Directory name -> (manifest filename, top-level manifest key, singular kind).
KINDS = {
    "presets": ("preset.yml", "preset", "preset"),
    "extensions": ("extension.yml", "extension", "extension"),
    "workflows": ("workflow.yml", "workflow", "workflow"),
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@dataclass(frozen=True)
class Component:
    kind: str          # preset | extension | workflow
    id: str
    version: str
    path: Path         # the component directory
    manifest: dict     # parsed manifest, whole document
    commands: tuple[str, ...] = ()   # command names this component contributes

    @property
    def ref(self) -> str:
        """Stable identifier used by requirements traceability: 'workflow:lifecycle-bugfix'."""
        return f"{self.kind}:{self.id}"

    @property
    def meta(self) -> dict:
        """The manifest's own metadata block."""
        return self.manifest.get(KINDS[self.kind + "s"][1], {})


@dataclass(frozen=True)
class Inventory:
    meta: dict                       # tooling/bundle-meta.yml
    components: tuple[Component, ...]
    policies: tuple[Path, ...] = field(default=())

    @property
    def version(self) -> str:
        return str(self.meta["bundle"]["version"])

    @property
    def speckit_version(self) -> str:
        return str(self.meta["requires"]["speckit_version"])

    def by_kind(self, kind: str) -> tuple[Component, ...]:
        return tuple(c for c in self.components if c.kind == kind)

    def by_ref(self, ref: str) -> Component | None:
        return next((c for c in self.components if c.ref == ref), None)

    def by_id(self, kind: str, id_: str) -> Component | None:
        return next((c for c in self.components if c.kind == kind and c.id == id_), None)

    @property
    def preset(self) -> Component:
        """The single preset this bundle ships."""
        presets = self.by_kind("preset")
        if len(presets) != 1:
            raise ValueError(f"expected exactly one owned preset, found {len(presets)}")
        return presets[0]

    @property
    def extensions(self) -> list[Component]:
        """Every extension this bundle ships, in manifest order.

        There was a singular `extension` property that raised on anything but
        one, and three checks read it. That was true of the bundle and not of
        the checks: each of them is about a property of *an* extension --
        how its commands invoke scripts, what its scripts may write, what its
        config is named -- and none of them wanted the bundle to have exactly
        one. Adding the `work` extension made the difference visible.
        """
        return self.by_kind("extension")

    def preset_commands(self) -> frozenset[str]:
        """Core command names the governance preset contributes to."""
        return frozenset(
            c for comp in self.by_kind("preset") for c in comp.commands
        )

    def extension_commands(self) -> frozenset[str]:
        return frozenset(
            c for comp in self.by_kind("extension") for c in comp.commands
        )

    def provided_commands(self) -> frozenset[str]:
        """Every command a workflow step may legally reference.

        Preset contributions are core Spec Kit commands the preset layers onto,
        so they are referenceable; extension commands are provided outright.
        """
        return self.preset_commands() | self.extension_commands()

    def external_preset_refs(self) -> list[dict]:
        return list(self.meta.get("external_presets", []))


def _commands_for(kind: str, manifest: dict) -> tuple[str, ...]:
    provides = manifest.get("provides", {}) or {}
    if kind == "extension":
        return tuple(c["name"] for c in provides.get("commands", []) or [])
    if kind == "preset":
        return tuple(
            t["name"]
            for t in provides.get("templates", []) or []
            if t.get("type") == "command"
        )
    return ()


def load_inventory(root: Path | None = None) -> Inventory:
    base = Path(root) if root else ROOT
    bundle = base / "bundle"
    meta = load_yaml(base / "tooling" / "bundle-meta.yml")

    components: list[Component] = []
    for dirname, (manifest_name, _key, kind) in KINDS.items():
        parent = bundle / "components" / dirname
        if not parent.is_dir():
            continue
        for comp_dir in sorted(parent.iterdir()):
            manifest_path = comp_dir / manifest_name
            if not manifest_path.is_file():
                continue
            manifest = load_yaml(manifest_path)
            block = manifest.get(_key, {}) or {}
            components.append(
                Component(
                    kind=kind,
                    id=str(block.get("id", comp_dir.name)),
                    version=str(block.get("version", "")),
                    path=comp_dir,
                    manifest=manifest,
                    commands=_commands_for(kind, manifest),
                )
            )

    policy_dir = base / "policy"
    policies = tuple(sorted(policy_dir.glob("*.yml"))) if policy_dir.is_dir() else ()
    return Inventory(meta=meta, components=tuple(components), policies=policies)


@functools.lru_cache(maxsize=1)
def inventory() -> Inventory:
    """Cached inventory for the default root."""
    return load_inventory()
