"""Which Spec Kit project a command acts on.

Every script anchored on `Path.cwd()`: relative policy candidates, a
`--policy-root` defaulting to the working directory, and no upward search. Run
one a directory below a project and it found no policy; run one in a monorepo
and it acted on whichever member you were standing in.

This mirrors Spec Kit's own resolver rather than inventing a second contract.
Where it differs, the difference is deliberate and tested.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
spec = importlib.util.spec_from_file_location("project_root",
                                              SCRIPTS / "project_root.py")
pr = importlib.util.module_from_spec(spec)
sys.modules["project_root"] = pr
spec.loader.exec_module(pr)


@pytest.fixture
def monorepo(tmp_path):
    """One git root, two member projects, one member with a nested directory."""
    (tmp_path / ".git").mkdir()
    for member in ("member_a", "member_b"):
        (tmp_path / member / ".specify").mkdir(parents=True)
    (tmp_path / "member_a" / "src" / "billing").mkdir(parents=True)
    return tmp_path


# --- AC1: found from a subdirectory -------------------------------------------

@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_the_project_root_is_found_from_a_subdirectory(monorepo):
    deep = monorepo / "member_a" / "src" / "billing"
    assert pr.resolve(cwd=deep, env={}) == monorepo / "member_a"


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_a_project_root_resolves_to_itself(monorepo):
    root = monorepo / "member_b"
    assert pr.resolve(cwd=root, env={}) == root


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_the_nearest_ancestor_wins_over_an_outer_one(tmp_path):
    # A project inside a project resolves to the inner one: the member closest
    # to where the command runs is the one it was meant to act on.
    (tmp_path / ".specify").mkdir()
    inner = tmp_path / "packages" / "inner"
    (inner / ".specify").mkdir(parents=True)
    assert pr.resolve(cwd=inner, env={}) == inner


# --- AC2 / AC3: the environment override --------------------------------------

@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_the_environment_selects_the_project(monorepo):
    env = {pr.INIT_DIR: str(monorepo / "member_b")}
    deep = monorepo / "member_a" / "src"
    # Standing inside member_a, but member_b was named.
    assert pr.resolve(cwd=deep, env=env) == monorepo / "member_b"


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_a_relative_environment_value_resolves_against_the_working_directory(
        monorepo):
    env = {pr.INIT_DIR: "member_b"}
    assert pr.resolve(cwd=monorepo, env=env) == monorepo / "member_b"


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_a_nonexistent_environment_value_fails(monorepo):
    with pytest.raises(pr.ProjectRootError) as exc:
        pr.resolve(cwd=monorepo, env={pr.INIT_DIR: "member_c"})
    assert "existing directory" in str(exc.value)
    assert "member_c" in str(exc.value)


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_a_directory_without_the_marker_fails(monorepo):
    (monorepo / "not_a_project").mkdir()
    with pytest.raises(pr.ProjectRootError) as exc:
        pr.resolve(cwd=monorepo, env={pr.INIT_DIR: "not_a_project"})
    assert "not a Spec Kit project" in str(exc.value)


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_an_invalid_environment_value_never_falls_back_to_the_search(monorepo):
    # The whole point of the strictness. Spec Kit's own resolver refuses for
    # the stated reason that falling back would silently operate on the wrong
    # project's files, and a value naming member_c must not quietly become
    # member_a because that is where you were standing.
    deep = monorepo / "member_a" / "src"
    with pytest.raises(pr.ProjectRootError):
        pr.resolve(cwd=deep, env={pr.INIT_DIR: "member_c"})


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_an_empty_environment_value_is_treated_as_unset(monorepo):
    deep = monorepo / "member_a" / "src"
    assert pr.resolve(cwd=deep, env={pr.INIT_DIR: "  "}) == monorepo / "member_a"


# --- AC4: the git root is not the project root --------------------------------

@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_the_git_root_is_not_the_project_root(monorepo):
    resolved = pr.resolve(cwd=monorepo / "member_a" / "src", env={})
    assert resolved != monorepo
    assert resolved == monorepo / "member_a"


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_two_members_resolve_to_two_roots(monorepo):
    a = pr.resolve(cwd=monorepo / "member_a" / "src" / "billing", env={})
    b = pr.resolve(cwd=monorepo / "member_b", env={})
    assert a != b


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_the_search_does_not_stop_at_a_git_directory(tmp_path):
    # Stopping at `.git` would resolve every member of a monorepo to the git
    # root, which is one project the framework has never been installed into.
    (tmp_path / ".specify").mkdir()
    nested = tmp_path / "sub"
    (nested / ".git").mkdir(parents=True)
    assert pr.resolve(cwd=nested, env={}) == tmp_path


# --- precedence and absence ---------------------------------------------------

@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_an_explicit_root_wins_over_the_environment(monorepo):
    env = {pr.INIT_DIR: str(monorepo / "member_b")}
    resolved = pr.resolve(monorepo / "member_a", cwd=monorepo, env=env)
    assert resolved == monorepo / "member_a"


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_no_project_anywhere_is_an_error_when_required(tmp_path):
    with pytest.raises(pr.ProjectRootError) as exc:
        pr.resolve(cwd=tmp_path, env={})
    assert pr.INIT_DIR in str(exc.value)


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_no_project_returns_none_when_not_required(tmp_path):
    # The source checkout has no `.specify/`, and the second policy candidate
    # exists for exactly that case. Callers fall back deliberately, not by
    # accident.
    assert pr.resolve(cwd=tmp_path, env={}, required=False) is None


# --- AC5: one resolved root per run -------------------------------------------

@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_no_script_defaults_its_policy_root_to_the_working_directory():
    offenders = [p.name for p in sorted(SCRIPTS.glob("*.py"))
                 if '"--policy-root", type=Path, default=Path.cwd()'
                 in p.read_text(encoding="utf-8")]
    assert offenders == [], offenders


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_only_the_greenfield_check_still_defaults_a_path_to_the_cwd():
    # `mismatch --path` names the repository being assessed for greenfield,
    # which by definition may have no `.specify/` yet, so it cannot resolve to
    # a project root. Every other path-taking script follows the project.
    offenders = [p.name for p in sorted(SCRIPTS.glob("*.py"))
                 if '"--path", type=Path, default=Path.cwd()'
                 in p.read_text(encoding="utf-8")]
    assert offenders == ["mismatch.py"], offenders


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_the_ratchet_reads_exception_policy_from_the_root_it_was_given():
    # It called `exception.load_policy(Path.cwd())` while using --policy-root
    # everywhere else in the same file, so in a monorepo member it read quality
    # gates from the member and exception policy from wherever you started.
    source = (SCRIPTS / "ratchet.py").read_text(encoding="utf-8")
    assert "load_policy(Path.cwd())" not in source
    assert "load_policy(root or Path.cwd())" in source


@pytest.mark.req("REQ-TEAM-PROJECT-001")
def test_doctor_reports_a_project_it_is_standing_below(monorepo):
    # The command whose job is saying where you are had the worst version of
    # this: it reported `specify_project: false` about a project right there.
    deep = monorepo / "member_a" / "src" / "billing"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "doctor.py")],
        cwd=deep, capture_output=True, text=True)
    assert '"specify_project": true' in result.stdout


# --- refusing a write outside the resolved project ----------------------------

@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_a_path_inside_the_project_is_returned_resolved(monorepo):
    target = monorepo / "member_a" / ".specify" / "plans" / "p.md"
    assert pr.ensure_within(monorepo / "member_a", target) == target.resolve()


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_a_path_in_a_sibling_member_is_refused(monorepo):
    with pytest.raises(pr.OutsideProjectError):
        pr.ensure_within(monorepo / "member_a",
                         monorepo / "member_b" / "plan.md")


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_the_refusal_names_the_project_and_the_attempted_path(monorepo):
    # "Outside the project" without saying which project is a message you
    # cannot act on.
    target = monorepo / "member_b" / "plan.md"
    with pytest.raises(pr.OutsideProjectError) as exc:
        pr.ensure_within(monorepo / "member_a", target)
    assert str((monorepo / "member_a").resolve()) in str(exc.value)
    assert str(target.resolve()) in str(exc.value)


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
def test_the_git_root_is_outside_a_member(monorepo):
    # The same relative path means a different file in every member, so the
    # enclosing repository is not a safe place to write either.
    with pytest.raises(pr.OutsideProjectError):
        pr.ensure_within(monorepo / "member_a", monorepo / "shared.md")


@pytest.mark.req("REQ-TEAM-MONOREPO-001")
@pytest.mark.parametrize("script", ["transition_plan.py", "ratchet.py"])
def test_every_file_writing_script_passes_through_the_guard(script):
    # Testing the helper proves the helper. This proves the wiring: a writer
    # that skipped it would pass every test above.
    import ast

    tree = ast.parse((SCRIPTS / script).read_text(encoding="utf-8"))
    writes = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr == "write_text"]
    assert writes, f"{script} writes nothing; this test is stale"
    guarded = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute)
               and n.func.attr == "ensure_within"]
    assert guarded, f"{script} writes a file without ensure_within"
