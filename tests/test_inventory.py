"""The inventory is the single source of truth; these are its guarantees.

Everything downstream -- bundle.yml, the catalogs, the validator, the installer
-- derives from load_inventory(). If it silently returned a partial inventory,
generated files would quietly shed components.
"""
from __future__ import annotations

import pytest


@pytest.mark.req("REQ-TOOLING-SOT-001")
def test_finds_every_component_directory(inv, root):
    on_disk = {
        d.name
        for kind in ("presets", "extensions", "workflows")
        for d in (root / "bundle" / "components" / kind).iterdir()
        if d.is_dir() and any(d.glob("*.yml"))
    }
    assert {c.id for c in inv.components} == on_disk


def test_refs_are_unique_and_resolvable(inv):
    refs = [c.ref for c in inv.components]
    assert len(refs) == len(set(refs))
    for ref in refs:
        assert inv.by_ref(ref) is not None


def test_ref_shape_is_stable(inv):
    # P1 requirements cite these strings; changing the shape breaks traceability.
    for c in inv.components:
        assert c.ref == f"{c.kind}:{c.id}"
        assert c.kind in {"preset", "extension", "workflow"}


def test_exactly_one_owned_preset_and_every_extension_is_named(inv):
    assert inv.preset.id
    # The bundle ships more than one extension. What must hold is that each is
    # identified, not that there is exactly one -- the singular accessor that
    # asserted the second was the assumption, not the requirement.
    assert inv.extensions
    assert all(ext.id for ext in inv.extensions)
    assert len({ext.id for ext in inv.extensions}) == len(inv.extensions)


@pytest.mark.req("REQ-CORE-COMMANDS-001")
def test_provided_commands_covers_every_workflow_step(inv):
    referenced = {
        step["command"]
        for c in inv.by_kind("workflow")
        for step in (c.manifest.get("steps") or [])
        if step.get("command")
    }
    assert referenced <= inv.provided_commands()


@pytest.mark.parametrize("kind", ["preset", "extension", "workflow"])
def test_versions_are_populated(inv, kind):
    for c in inv.by_kind(kind):
        assert c.version, f"{c.ref} has no version"
