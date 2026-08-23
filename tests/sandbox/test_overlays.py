"""Project workflow overlays survive bundle operations.

Overlays are the documented way a product repository customizes a workflow --
most commonly to replace the verification step when it does not use the
`devbox run verify` entry point the bundle assumes. If an update silently
discarded them, every such project would lose its customization on upgrade and
only discover it when a workflow ran the wrong command.

The roadmap's Phase 1 exit gate has required "project overlays survive update"
since the beginning. It had never been tested.

Overlay priority and preset priority are unrelated despite sharing a default of
10; see docs/workflows.md.
"""
from __future__ import annotations

import re
import subprocess

import pytest

pytestmark = [pytest.mark.sandbox, pytest.mark.requires_specify]

TARGET_WORKFLOW = "lifecycle-story-delivery"
OVERLAY_ID = "project-verification"

OVERLAY = """\
id: "project-verification"
extends: "lifecycle-story-delivery"
priority: 10
enabled: true
edits:
  - replace: verify
    step:
      id: verify
      type: shell
      run: "devbox run ci"
"""


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True)


# Lines look like "  \u2022 verify: project:project-verification": a bullet, the
# step id, then the layer that supplied it.
_STEP_LINE = re.compile(r"^\W*verify:\s*(?P<source>.+?)\s*$")


def verify_step_source(project) -> str:
    """Which layer supplies the `verify` step, per the CLI's own attribution."""
    out = run(["specify", "workflow", "resolve", TARGET_WORKFLOW], project).stdout
    for line in out.splitlines():
        m = _STEP_LINE.match(line)
        if m:
            return m.group("source")
    return ""


def overlay_present(project) -> bool:
    out = run(["specify", "workflow", "overlay", "list", TARGET_WORKFLOW], project).stdout
    return OVERLAY_ID in out


@pytest.fixture(scope="module")
def project_with_overlay(tmp_path_factory):
    """A project with the bundle installed and a project overlay applied.

    The catalog server stays up for the whole module: `bundle update` re-resolves
    from the catalog, and against a dead server it fails without touching the
    overlay, which would look like a pass.
    """
    import local_catalog

    project = tmp_path_factory.mktemp("overlay-project")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    r = run(["specify", "init", "--here", "--force", "--non-interactive",
             "--integration", "opencode", "--script", "py"], project)
    assert r.returncode == 0, r.stderr

    with local_catalog.serve() as base:
        local_catalog.register(project, base)
        local_catalog.install_workflows(project)
        assert run(["specify", "bundle", "install", "lean-full-lifecycle"],
                   project).returncode == 0

        overlay_file = project / "project-overlay.yml"
        overlay_file.write_text(OVERLAY, encoding="utf-8")
        r = run(["specify", "workflow", "overlay", "add", str(overlay_file),
                 "--priority", "10"], project)
        assert r.returncode == 0, r.stderr
        yield project, base


@pytest.mark.req("REQ-PACKAGE-OVERLAY-001")
def test_overlay_applies_before_any_update(project_with_overlay):
    project, _ = project_with_overlay
    assert overlay_present(project)
    assert verify_step_source(project) == f"project:{OVERLAY_ID}"


@pytest.mark.req("REQ-PACKAGE-OVERLAY-001")
def test_overlay_survives_bundle_update(project_with_overlay):
    project, _ = project_with_overlay
    r = run(["specify", "bundle", "update", "lean-full-lifecycle"], project)
    # A failed update leaves the overlay untouched, which would pass the
    # assertions below for the wrong reason.
    assert r.returncode == 0, f"update did not run: {r.stdout}{r.stderr}"
    assert overlay_present(project), "bundle update discarded the overlay"
    assert verify_step_source(project) == f"project:{OVERLAY_ID}", \
        "overlay survived but no longer applies"


@pytest.mark.req("REQ-PACKAGE-OVERLAY-001")
def test_overlay_survives_workflow_update(project_with_overlay):
    project, _ = project_with_overlay
    r = run(["specify", "workflow", "update", TARGET_WORKFLOW], project)
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    assert overlay_present(project), "workflow update discarded the overlay"
    assert verify_step_source(project) == f"project:{OVERLAY_ID}"


@pytest.mark.req("REQ-PACKAGE-OVERLAY-001")
def test_overlay_survives_second_bundle_install(project_with_overlay):
    project, _ = project_with_overlay
    assert run(["specify", "bundle", "install", "lean-full-lifecycle"],
               project).returncode == 0
    assert overlay_present(project)
    assert verify_step_source(project) == f"project:{OVERLAY_ID}"


def test_overlay_outlives_bundle_removal(project_with_overlay):
    """Removal takes the bundle's components, not the project's customization.

    Asserted rather than assumed: an overlay is project-local, so removing a
    bundle should not reach it. Whatever this does is the documented behaviour.
    """
    project, _ = project_with_overlay
    assert run(["specify", "bundle", "remove", "lean-full-lifecycle"],
               project).returncode == 0
    assert overlay_present(project), \
        "bundle remove deleted a project-local overlay it did not create"
