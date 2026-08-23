"""One monorepo, two members, two worktrees, and no leakage between them.

The roadmap's Phase 8 scenario -- one monorepo, two member Spec Kit projects,
concurrent worktrees, distinct active features, no artifact cross-contamination
-- had no coverage, and until #65 and #66 the code it would exercise had no
implementation.

This is the file that makes those two provable. A resolver that returns the
right root in a unit test and the wrong one under a real `specify init` has not
been tested, and every earlier sandbox fixture creates exactly one project.

Contamination is the failure worth the setup cost. It is silent, and it is
discovered by somebody reading a record describing work they never did.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from lib.inventory import ROOT

pytestmark = [pytest.mark.sandbox, pytest.mark.requires_specify]

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
MEMBERS = ("member_a", "member_b")
FEATURES = {"member_a": "specs/001-billing", "member_b": "specs/002-invoicing"}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pr = _load("project_root")
fc = _load("feature_context")


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True)


@pytest.fixture(scope="module")
def monorepo(tmp_path_factory):
    """One git root, two initialized members, one worktree each.

    The catalog server stays up for the whole module so a later `bundle remove`
    in one member is a real operation rather than a failure that happens to
    leave the other alone.
    """
    import local_catalog

    from sandbox.monorepo import build

    root = tmp_path_factory.mktemp("monorepo")
    with local_catalog.serve() as base:
        yield build(root, base, FEATURES), base


# --- AC1: two members, two project roots --------------------------------------

@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_each_member_resolves_to_its_own_root(monorepo):
    root, _ = monorepo
    resolved = {m: pr.resolve(cwd=root / m, env={}) for m in MEMBERS}
    assert resolved["member_a"] != resolved["member_b"]
    for member in MEMBERS:
        assert resolved[member] == root / member


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_a_nested_directory_resolves_to_its_member(monorepo):
    root, _ = monorepo
    deep = root / "member_a" / FEATURES["member_a"]
    assert pr.resolve(cwd=deep, env={}) == root / "member_a"


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_neither_member_resolves_to_the_git_root(monorepo):
    root, _ = monorepo
    for member in MEMBERS:
        assert pr.resolve(cwd=root / member, env={}) != root


# --- AC2: concurrent worktrees, distinct features -----------------------------

@pytest.fixture(scope="module")
def worktrees(monorepo, tmp_path_factory):
    """A real `git worktree` per member, each declaring a different feature."""
    root, _ = monorepo
    out = {}
    for i, member in enumerate(MEMBERS):
        tree = tmp_path_factory.mktemp(f"wt-{member}")
        r = run(["git", "worktree", "add", "-q", "--detach", str(tree)], root)
        assert r.returncode == 0, r.stderr
        # A worktree is a checkout of the whole monorepo, so the member lives
        # at the same relative path inside it.
        member_dir = tree / member
        (member_dir / ".specify").mkdir(parents=True, exist_ok=True)
        feature = f"specs/00{i + 3}-worktree-feature"
        (member_dir / feature).mkdir(parents=True, exist_ok=True)
        (member_dir / ".specify" / "feature.json").write_text(
            json.dumps({"feature_directory": feature}), encoding="utf-8")
        out[member] = (member_dir, feature)
    return out


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_concurrent_worktrees_hold_distinct_features(worktrees):
    resolved = {m: fc.resolve(pr.resolve(cwd=d, env={}), {})
                for m, (d, _) in worktrees.items()}
    assert resolved["member_a"] != resolved["member_b"]


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_a_worktree_feature_differs_from_the_main_checkout(monorepo, worktrees):
    root, _ = monorepo
    main = fc.resolve(pr.resolve(cwd=root / "member_a", env={}), {})
    tree_dir, _ = worktrees["member_a"]
    in_tree = fc.resolve(pr.resolve(cwd=tree_dir, env={}), {})
    # Same member, two checkouts, two active features. This is the case a
    # branch-derived answer gets wrong.
    assert main != in_tree


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_each_worktree_resolves_to_its_own_project_root(worktrees):
    roots = {m: pr.resolve(cwd=d, env={}) for m, (d, _) in worktrees.items()}
    assert roots["member_a"] != roots["member_b"]


# --- AC3: no cross-contamination ----------------------------------------------

@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_a_record_written_in_one_context_is_absent_from_the_other(monorepo):
    root, _ = monorepo
    a_root = pr.resolve(cwd=root / "member_a", env={})
    feature = fc.resolve(a_root, {})
    record = feature / "discovery.md"
    record.write_text("member_a discovery", encoding="utf-8")

    b_root = pr.resolve(cwd=root / "member_b", env={})
    b_feature = fc.resolve(b_root, {})
    assert not (b_feature / "discovery.md").exists()
    assert not list(b_root.rglob("discovery.md"))


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_a_worktree_record_does_not_appear_in_the_main_checkout(monorepo,
                                                               worktrees):
    root, _ = monorepo
    tree_dir, _ = worktrees["member_a"]
    feature = fc.resolve(pr.resolve(cwd=tree_dir, env={}), {})
    (feature / "worktree-only.md").write_text("x", encoding="utf-8")
    assert not list((root / "member_a").rglob("worktree-only.md"))


# --- AC4: a write outside the resolved project is refused ---------------------

@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_a_plan_written_into_another_member_is_refused(monorepo):
    root, _ = monorepo
    a_root = root / "member_a"
    escape = root / "member_b" / ".specify" / "plan.md"
    with pytest.raises(pr.OutsideProjectError) as exc:
        pr.ensure_within(a_root, escape)
    assert str(a_root) in str(exc.value)
    assert str(escape) in str(exc.value)


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_a_traversal_out_of_the_member_is_refused(monorepo):
    root, _ = monorepo
    with pytest.raises(pr.OutsideProjectError):
        pr.ensure_within(root / "member_a",
                         root / "member_a" / ".." / "member_b" / "plan.md")


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_a_write_inside_the_member_is_permitted(monorepo):
    root, _ = monorepo
    target = root / "member_a" / ".specify" / "plans" / "p.md"
    assert pr.ensure_within(root / "member_a", target) == target.resolve()


# --- AC5: removing from one member leaves the other ---------------------------

@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_removing_the_bundle_from_one_member_leaves_the_other(monorepo):
    root, _ = monorepo
    r = run(["specify", "bundle", "remove", "lean-full-lifecycle"],
            root / "member_a")
    # A failed removal would leave member_b installed for the wrong reason.
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"

    listed = run(["specify", "bundle", "list"], root / "member_b").stdout
    assert "lean-full-lifecycle" in listed
    assert (root / "member_b" / ".specify" / "extensions"
            / "github-lifecycle").is_dir()
