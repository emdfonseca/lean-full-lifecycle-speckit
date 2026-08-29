"""Two members, two overlays of one workflow, and no bleed between them.

`test_overlays.py` covers the single-project case: an overlay survives
`bundle update`, `workflow update`, a second install, and outlives
`bundle remove`. All of it in one project, one worktree.

A monorepo is where this gets hard. Two members hold two overlays of the same
workflow under one git root, and every `specify` invocation has to pick one. An
overlay that leaked between members would replace a team's verification command
with another team's, and the first sign would be a workflow running something
nobody there configured.
"""
from __future__ import annotations

import re
import subprocess

import pytest

pytestmark = [pytest.mark.sandbox, pytest.mark.requires_specify]

TARGET_WORKFLOW = "lifecycle-story-delivery"
MEMBERS = ("member_a", "member_b")
FEATURES = {"member_a": "specs/001-billing", "member_b": "specs/002-invoicing"}

# Each member replaces the same step with a different command, so a leak is
# visible as the wrong command rather than as a missing overlay.
OVERLAYS = {
    "member_a": ("member-a-verification", "devbox run ci"),
    "member_b": ("member-b-verification", "devbox run check"),
}

OVERLAY_TEMPLATE = """\
id: "{id}"
extends: "lifecycle-story-delivery"
priority: 10
enabled: true
edits:
  - replace: verify
    step:
      id: verify
      type: shell
      run: "{command}"
"""

_STEP_LINE = re.compile(r"^\W*verify:\s*(?P<source>.+?)\s*$")


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True)


def verify_step_source(project) -> str:
    out = run(["specify", "workflow", "resolve", TARGET_WORKFLOW], project).stdout
    for line in out.splitlines():
        m = _STEP_LINE.match(line)
        if m:
            return m.group("source")
    return ""


def overlay_ids(project) -> str:
    return run(["specify", "workflow", "overlay", "list", TARGET_WORKFLOW],
               project).stdout


@pytest.fixture(scope="module")
def members(tmp_path_factory, dist_dir):
    """A fresh monorepo with a different overlay in each member.

    Its own instance, not the contamination suite's: that one ends by removing
    the bundle from a member, and asserting overlay behaviour against a project
    somebody already dismantled would prove nothing.
    """
    import local_catalog

    from sandbox.monorepo import build

    root = tmp_path_factory.mktemp("overlay-monorepo")
    with local_catalog.serve(dist=dist_dir) as base:
        build(root, base, FEATURES)
        for member in MEMBERS:
            overlay_id, command = OVERLAYS[member]
            path = root / member / "project-overlay.yml"
            path.write_text(
                OVERLAY_TEMPLATE.format(id=overlay_id, command=command),
                encoding="utf-8")
            r = run(["specify", "workflow", "overlay", "add", str(path),
                     "--priority", "10"], root / member)
            assert r.returncode == 0, r.stderr
        yield root, base


# --- AC1: each member's overlay applies to that member ------------------------

@pytest.mark.req("REQ-PACKAGE-OVERLAY-002")
@pytest.mark.parametrize("member", MEMBERS)
def test_each_member_resolves_its_own_overlay(members, member):
    root, _ = members
    overlay_id, _ = OVERLAYS[member]
    assert verify_step_source(root / member) == f"project:{overlay_id}"


@pytest.mark.req("REQ-PACKAGE-OVERLAY-002")
def test_no_member_sees_the_other_members_overlay(members):
    root, _ = members
    for member in MEMBERS:
        other_id, _ = OVERLAYS["member_b" if member == "member_a" else "member_a"]
        assert other_id not in overlay_ids(root / member), \
            f"{member} can see {other_id}"


@pytest.mark.req("REQ-PACKAGE-OVERLAY-002")
def test_the_two_members_resolve_to_two_different_overlays(members):
    root, _ = members
    sources = {m: verify_step_source(root / m) for m in MEMBERS}
    assert sources["member_a"] != sources["member_b"]


# --- AC2 / AC3: an update in one member ---------------------------------------

@pytest.mark.req("REQ-PACKAGE-OVERLAY-002")
def test_an_overlay_survives_an_update_in_its_member(members):
    root, _ = members
    r = run(["specify", "bundle", "update", "lean-full-lifecycle"],
            root / "member_a")
    # A failed update leaves everything untouched, which would pass the
    # assertions below for the wrong reason.
    assert r.returncode == 0, f"update did not run: {r.stdout}{r.stderr}"
    overlay_id, _ = OVERLAYS["member_a"]
    assert overlay_id in overlay_ids(root / "member_a")
    assert verify_step_source(root / "member_a") == f"project:{overlay_id}"


@pytest.mark.req("REQ-PACKAGE-OVERLAY-002")
def test_updating_one_member_does_not_disturb_the_other(members):
    root, _ = members
    assert run(["specify", "bundle", "update", "lean-full-lifecycle"],
               root / "member_a").returncode == 0
    overlay_id, _ = OVERLAYS["member_b"]
    assert overlay_id in overlay_ids(root / "member_b")
    assert verify_step_source(root / "member_b") == f"project:{overlay_id}"


# --- AC4: removing the bundle leaves the overlay ------------------------------

@pytest.mark.req("REQ-PACKAGE-OVERLAY-002")
def test_removing_the_bundle_from_a_member_leaves_both_overlays(members):
    """One removal, both assertions.

    Removal is not idempotent -- a second `bundle remove` reports the bundle is
    not installed -- so splitting this in two would make the second test depend
    on the first not having run, which is a passing test for the wrong reason.
    """
    root, _ = members
    r = run(["specify", "bundle", "remove", "lean-full-lifecycle"],
            root / "member_a")
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"

    # `bundle remove` must not delete a project-local overlay it did not create.
    a_id, _ = OVERLAYS["member_a"]
    assert a_id in overlay_ids(root / "member_a")

    # And the other member is untouched: still installed, still resolving its
    # own overlay.
    b_id, _ = OVERLAYS["member_b"]
    assert verify_step_source(root / "member_b") == f"project:{b_id}"
