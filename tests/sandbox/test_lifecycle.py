"""The install lifecycle, over a real catalog.

`scripts/smoke_test.py` runs the same sequence as a standalone gate. This is the
pytest face of it, so requirements can cite specific node ids in `verified_by`
rather than pointing at a script the traceability validator cannot resolve.

Marked `sandbox` and `requires_specify`: it builds archives, serves them, and
installs into a scratch project, so it is skipped by default in unit runs.
"""
from __future__ import annotations

import json
import re
import subprocess

import pytest

pytestmark = [pytest.mark.sandbox, pytest.mark.requires_specify]


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True)


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """A scratch project with the bundle installed from a local catalog."""
    import local_catalog

    project = tmp_path_factory.mktemp("project")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    r = run(["specify", "init", "--here", "--force", "--non-interactive",
             "--integration", "opencode", "--script", "py"], project)
    assert r.returncode == 0, r.stderr

    with local_catalog.serve() as base:
        local_catalog.register(project, base)
        local_catalog.install_workflows(project)
        r = run(["specify", "bundle", "install", "lean-full-lifecycle"], project)
        assert r.returncode == 0, r.stderr
        yield project, base


@pytest.mark.req("REQ-PACKAGE-CATALOG-001")
def test_bundle_installs_from_catalog(installed):
    project, _ = installed
    out = run(["specify", "bundle", "list"], project).stdout
    assert "lean-full-lifecycle" in out


def test_both_presets_installed_at_declared_priorities(installed):
    project, _ = installed
    out = run(["specify", "preset", "list"], project).stdout
    assert len(re.findall(r"priority \d+", out)) == 2
    assert "priority 10" in out and "priority 20" in out


@pytest.mark.req("REQ-PACKAGE-CATALOG-001")
def test_all_workflows_installed(installed, inv):
    project, _ = installed
    out = run(["specify", "workflow", "list"], project).stdout
    for comp in inv.by_kind("workflow"):
        assert comp.id in out


@pytest.mark.req("REQ-CORE-COMPOSE-001")
def test_preset_composition_layers_over_lean(installed):
    project, _ = installed
    out = run(["specify", "preset", "resolve", "speckit.specify"], project).stdout
    # Governance must append onto Lean, not replace it.
    assert "[base] lean" in out
    assert "[append] lean-full-lifecycle-governance" in out


@pytest.mark.req("REQ-PACKAGE-LIFECYCLE-001")
def test_second_install_is_idempotent(installed):
    project, _ = installed
    r = run(["specify", "bundle", "install", "lean-full-lifecycle"], project)
    assert r.returncode == 0
    assert "0 added" in r.stdout


@pytest.mark.req("REQ-PACKAGE-LIFECYCLE-001")
def test_bundle_update_succeeds(installed):
    project, _ = installed
    assert run(["specify", "bundle", "update", "lean-full-lifecycle"], project).returncode == 0


@pytest.mark.req("REQ-PACKAGE-LIFECYCLE-001")
def test_remove_then_reinstall(installed):
    project, _ = installed
    assert run(["specify", "bundle", "remove", "lean-full-lifecycle"], project).returncode == 0
    out = run(["specify", "preset", "list"], project).stdout
    assert "lean-full-lifecycle-governance" not in out
    assert run(["specify", "bundle", "install", "lean-full-lifecycle"], project).returncode == 0


def test_extension_config_target_is_scaffoldable(installed):
    """D9: bundle install does not scaffold config, so only the template lands.

    Asserted rather than skipped: if upstream starts scaffolding on the bundler
    path, this fails and tells us the workaround can be removed.
    """
    project, _ = installed
    home = project / ".specify/extensions/github-lifecycle"
    assert (home / "config-template.yml").exists()
    scaffolded = home / "github-lifecycle-config.yml"
    if scaffolded.exists():
        pytest.fail("upstream now scaffolds config on the bundler path; "
                    "remove the D9 workaround in doctor.py and this branch")
