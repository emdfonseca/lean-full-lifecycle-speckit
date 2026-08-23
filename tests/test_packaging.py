"""What reaches a user, and what must not.

`specify bundle build` packages the entire bundle directory and honours no
ignore file: its exclusion list is `.git`, `__pycache__`, and `.DS_Store`.
Building from the repository root once produced a 123-file artifact containing
`dist/` with every prior release archive nested inside it, plus `scripts/`,
`tests/`, and `.github/`.

The protection is structural -- development tooling lives outside `bundle/` --
so this is the regression test on that boundary.
"""
from __future__ import annotations

import subprocess
import zipfile

import pytest

from lib.inventory import ROOT, load_inventory

pytestmark = pytest.mark.requires_specify

EXCLUDED_TOP_LEVEL = ("dist/", "tests/", "scripts/", "tooling/", ".github/",
                      ".claude/", ".specify/", "catalogs/", "docs/", ".venv/")


@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    out = tmp_path_factory.mktemp("artifact")
    r = subprocess.run(
        ["specify", "bundle", "build", "--path", str(ROOT / "bundle"), "--output", str(out)],
        text=True, capture_output=True,
    )
    assert r.returncode == 0, r.stderr
    built = list(out.glob("*.zip"))
    assert len(built) == 1, built
    with zipfile.ZipFile(built[0]) as z:
        return built[0], z.namelist()


@pytest.mark.req("REQ-PACKAGE-ARTIFACT-001")
def test_artifact_contains_no_development_files(artifact):
    _, names = artifact
    leaked = [n for n in names if n.startswith(EXCLUDED_TOP_LEVEL)]
    assert not leaked, f"development files in the published artifact: {leaked}"


def test_artifact_carries_the_manifest_and_readme(artifact):
    _, names = artifact
    assert "bundle.yml" in names
    assert "README.md" in names


def test_artifact_carries_every_component(artifact, inv):
    _, names = artifact
    joined = "\n".join(names)
    for comp in inv.components:
        assert f"components/" in joined and comp.path.name in joined, comp.ref


def test_artifact_embeds_no_prior_archive(artifact):
    _, names = artifact
    nested = [n for n in names if n.endswith(".zip")]
    assert not nested, f"artifact contains nested archives: {nested}"


# --- component archives -------------------------------------------------------

@pytest.fixture(scope="module")
def component_archives(tmp_path_factory):
    """The archives a catalog serves. `specify bundle build` does not make these."""
    import build_release

    out = tmp_path_factory.mktemp("components")
    original = build_release.DIST
    build_release.DIST = out
    try:
        build_release.main()
    finally:
        build_release.DIST = original
    return sorted(out.glob("*.zip"))


@pytest.mark.req("REQ-PACKAGE-ARTIFACT-001")
def test_no_component_archive_ships_build_residue(component_archives):
    # These are what `specify bundle install` downloads, so this is what users
    # get. The bundle artifact was already clean because Spec Kit's packager
    # excludes __pycache__; ours excluded nothing.
    assert component_archives, "no component archives were built"
    for archive in component_archives:
        with zipfile.ZipFile(archive) as z:
            bad = [n for n in z.namelist()
                   if "__pycache__" in n or n.endswith((".pyc", ".pyo", ".DS_Store"))]
        assert not bad, f"{archive.name} ships {bad}"


def test_component_archives_still_carry_their_manifest(component_archives):
    # Exclusion must not remove what the archive is for.
    for archive in component_archives:
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
        assert any(n.endswith((".yml", ".yaml")) for n in names), archive.name
