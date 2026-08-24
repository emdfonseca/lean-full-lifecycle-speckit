"""The bundle-mechanics gaps the coverage map found.

Four of these scenarios had no test at all, and two passed on a no-op: every
`bundle update` test asserted only that the command exited 0, so an update that
refreshed nothing was indistinguishable from one that worked — and overlay
preservation, the bundle's headline guarantee, rests on exactly that.

This group's "covered" ratings survived the adversarial pass, which is why its
gaps are worth trusting too.
"""
from __future__ import annotations

import subprocess

import pytest

from lib.inventory import ROOT

pytestmark = [pytest.mark.sandbox, pytest.mark.requires_specify]

BUNDLE = "lean-full-lifecycle"
PRESET = ".specify/presets/lean-full-lifecycle-governance"
EXTENSION = ".specify/extensions/github-lifecycle"


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True)


def fresh(tmp_path, base):
    """A scratch project with the bundle installed from the served catalog."""
    import local_catalog

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    r = run(["specify", "init", "--here", "--force", "--non-interactive",
             "--integration", "opencode", "--script", "py"], tmp_path)
    assert r.returncode == 0, r.stderr
    local_catalog.register(tmp_path, base)
    local_catalog.install_workflows(tmp_path)
    r = run(["specify", "bundle", "install", BUNDLE], tmp_path)
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    return tmp_path


@pytest.fixture(scope="module")
def served():
    import local_catalog

    with local_catalog.serve() as base:
        yield base


# --- AC1: the official validator runs in the suite ---------------------------

@pytest.mark.req("REQ-PACKAGE-MECHANICS-001")
def test_the_official_validator_runs_and_passes():
    # It is the gate CI enforces and the suite had never executed it, so
    # scripts/validate_source.py was silently standing in for a validator that
    # checks different things.
    result = run(["specify", "bundle", "validate", "--path", "bundle/",
                  "--offline"], ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "well-formed and valid" in result.stdout


@pytest.mark.req("REQ-PACKAGE-MECHANICS-001")
def test_the_official_validator_rejects_a_broken_manifest(tmp_path):
    # Without this the test above could pass because the validator never fails.
    import shutil

    copy = tmp_path / "bundle"
    shutil.copytree(ROOT / "bundle", copy)
    manifest = copy / "bundle.yml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("schema_version", "nope"),
        encoding="utf-8")
    result = run(["specify", "bundle", "validate", "--path", str(copy),
                  "--offline"], tmp_path)
    assert result.returncode != 0


# --- AC2: local source installation materializes every component -------------

@pytest.mark.req("REQ-PACKAGE-MECHANICS-001")
def test_dev_install_loads_every_source_component(tmp_path, inv):
    import local_catalog

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    initialized = run(["specify", "init", "--here", "--force",
                       "--non-interactive", "--integration", "opencode",
                       "--script", "py"], tmp_path)
    assert initialized.returncode == 0, initialized.stderr

    assert local_catalog.dev_install(tmp_path) == 0
    assert (tmp_path / PRESET).is_dir()
    assert (tmp_path / EXTENSION / "scripts" / "doctor.py").is_file()

    workflows = run(["specify", "workflow", "list"], tmp_path).stdout
    for component in inv.by_kind("workflow"):
        assert component.id in workflows

    # Source installs deliberately install components without bundle ownership.
    assert BUNDLE not in run(["specify", "bundle", "list"], tmp_path).stdout


# --- AC3: an update that refreshes nothing fails ------------------------------

@pytest.mark.req("REQ-PACKAGE-MECHANICS-001")
def test_update_restores_a_component_that_was_changed(tmp_path_factory, served):
    project = fresh(tmp_path_factory.mktemp("update"), served)
    target = project / EXTENSION / "scripts" / "doctor.py"
    original = target.read_text(encoding="utf-8")

    target.write_text("# local edit that update must undo\n", encoding="utf-8")
    assert target.read_text(encoding="utf-8") != original

    result = run(["specify", "bundle", "update", BUNDLE], project)
    assert result.returncode == 0, f"{result.stdout}{result.stderr}"
    assert target.read_text(encoding="utf-8") == original, (
        "update exited 0 without refreshing the component; every existing "
        "update test would pass against this")


@pytest.mark.req("REQ-PACKAGE-MECHANICS-001")
def test_update_restores_a_deleted_component_file(tmp_path_factory, served):
    project = fresh(tmp_path_factory.mktemp("update-del"), served)
    target = project / EXTENSION / "scripts" / "doctor.py"
    target.unlink()

    assert run(["specify", "bundle", "update", BUNDLE], project).returncode == 0
    assert target.is_file(), "update did not restore a deleted file"


# --- AC4: a reinstall is asserted to have restored what removal took ---------

@pytest.mark.req("REQ-PACKAGE-MECHANICS-001")
def test_reinstall_restores_presets_commands_and_components(tmp_path_factory,
                                                            served):
    import re

    def components(project):
        listed = run(["specify", "bundle", "list"], project).stdout
        m = re.search(r"(\d+) components", listed)
        return int(m.group(1)) if m else None

    project = fresh(tmp_path_factory.mktemp("reinstall"), served)
    before = components(project)
    assert before

    assert run(["specify", "bundle", "remove", BUNDLE], project).returncode == 0
    assert "lean-full-lifecycle-governance" not in \
        run(["specify", "preset", "list"], project).stdout
    assert not (project / EXTENSION).is_dir()

    assert run(["specify", "bundle", "install", BUNDLE], project).returncode == 0

    # The half the existing test never checked: that anything came back.
    assert "lean-full-lifecycle-governance" in \
        run(["specify", "preset", "list"], project).stdout
    assert (project / EXTENSION / "scripts" / "doctor.py").is_file()
    # The listing carries an install timestamp, so compare what it installed
    # rather than the line it printed.
    assert components(project) == before


# --- AC5: installing from a built archive ------------------------------------

@pytest.mark.req("REQ-PACKAGE-MECHANICS-001")
def test_installing_from_a_built_archive_is_recorded(tmp_path_factory, served):
    """A bundle archive is a manifest of references, not a container.

    Recorded rather than asserted green: `specify bundle install <zip>` reads
    the manifest and resolves each component outward, so an archive alone
    cannot install. This test pins the observed behaviour so a future CLI that
    changes it is noticed.
    """
    project = tmp_path_factory.mktemp("from-zip")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    assert run(["specify", "init", "--here", "--force", "--non-interactive",
                "--integration", "opencode", "--script", "py"],
               project).returncode == 0

    built = run(["specify", "bundle", "build", "--path", str(ROOT / "bundle"),
                 "--output", str(project / "dist")], ROOT)
    assert built.returncode == 0, built.stderr
    archives = list((project / "dist").glob("*.zip"))
    assert archives, "bundle build produced no archive"

    result = run(["specify", "bundle", "install", str(archives[0])], project)
    # No catalog is registered, so the components cannot be resolved.
    assert result.returncode != 0, (
        "installing from an archive now succeeds; docs/evidence and the "
        "install_source axis both say it cannot, and one of them is stale")
    assert not (project / EXTENSION).is_dir()


# --- AC6: a failed install leaves the project clean --------------------------

@pytest.mark.req("REQ-PACKAGE-MECHANICS-001")
def test_a_failed_install_leaves_no_partial_component(tmp_path_factory):
    project = tmp_path_factory.mktemp("failed-install")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    assert run(["specify", "init", "--here", "--force", "--non-interactive",
                "--integration", "opencode", "--script", "py"],
               project).returncode == 0

    # No catalog is registered, so nothing can resolve. `catalog add` refuses
    # an unreachable URL at add time, which is itself the CLI declining to
    # record a source it cannot use.
    dead = run(["specify", "bundle", "catalog", "add",
                "http://127.0.0.1:9/bundles.json", "--name", "dead"], project)
    assert dead.returncode != 0, "an unreachable catalog was accepted"

    result = run(["specify", "bundle", "install", BUNDLE], project)

    assert result.returncode != 0
    assert not (project / EXTENSION).is_dir(), "a component survived a failed install"
    assert not (project / PRESET).is_dir()
    listed = run(["specify", "bundle", "list"], project).stdout
    assert BUNDLE not in listed, "a failed install was recorded as installed"
