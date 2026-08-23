"""Which feature is active.

In concurrent worktrees two features are checked out at once -- that is what
worktrees are for -- so an agent inferring the feature from the branch is
choosing between two right answers by accident.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pr = _load("project_root")
fc = _load("feature_context")


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".specify").mkdir()
    for name in ("specs/001-billing", "specs/002-invoicing"):
        (tmp_path / name).mkdir(parents=True)
    return tmp_path


def write_feature_json(project, value):
    (project / ".specify" / "feature.json").write_text(
        json.dumps({fc.FEATURE_KEY: value}), encoding="utf-8")


# --- AC1: the environment selects the feature ---------------------------------

@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_the_environment_variable_selects_the_feature(project):
    env = {fc.FEATURE_DIR: "specs/001-billing"}
    assert fc.resolve(project, env) == project / "specs/001-billing"


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_feature_json_is_not_consulted_when_the_variable_is_set(project):
    # Reading both would invite reconciling two answers. The environment is
    # what somebody set for this run.
    write_feature_json(project, "specs/002-invoicing")
    env = {fc.FEATURE_DIR: "specs/001-billing"}
    assert fc.resolve(project, env) == project / "specs/001-billing"
    assert fc.source(project, env) == fc.FEATURE_DIR


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_an_empty_variable_is_treated_as_unset(project):
    write_feature_json(project, "specs/002-invoicing")
    assert fc.resolve(project, {fc.FEATURE_DIR: "  "}) == \
        project / "specs/002-invoicing"


# --- AC2: feature.json when the variable is unset -----------------------------

@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_feature_json_selects_the_feature(project):
    write_feature_json(project, "specs/002-invoicing")
    assert fc.resolve(project, {}) == project / "specs/002-invoicing"


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_a_feature_json_with_no_declaration_is_an_error(project):
    # The file exists, so something meant to declare a feature and did not.
    write_feature_json(project, "")
    with pytest.raises(fc.FeatureContextError) as exc:
        fc.resolve(project, {})
    assert fc.FEATURE_KEY in str(exc.value)


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_an_unreadable_feature_json_is_not_an_absent_one(project):
    (project / ".specify" / "feature.json").write_text("{ not json",
                                                       encoding="utf-8")
    with pytest.raises(fc.FeatureContextError) as exc:
        fc.resolve(project, {})
    assert "not an absent one" in str(exc.value)


# --- AC3: the branch does not decide ------------------------------------------

@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_switching_branches_does_not_switch_the_feature(project):
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "002-invoicing"],
                   cwd=project, check=True)
    write_feature_json(project, "specs/001-billing")
    before = fc.resolve(project, {})

    subprocess.run(["git", "checkout", "-q", "-b", "003-something-else"],
                   cwd=project, check=True)
    assert fc.resolve(project, {}) == before


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_a_branch_matching_a_feature_name_still_does_not_select_it(project):
    # The tempting case: the branch happens to name a real feature directory.
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "001-billing"],
                   cwd=project, check=True)
    with pytest.raises(fc.FeatureContextError):
        fc.resolve(project, {})


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_the_resolver_never_shells_out_to_git():
    # Spec Kit does not read the branch either: its get_current_branch returns
    # os.environ.get("SPECIFY_FEATURE", ""). A resolver that ran `git` would be
    # diverging from the CLI, not hardening it.
    import ast

    # Scanned by parsing, not by substring: the module's own docstring explains
    # why it does not read git, and a substring check cannot tell a rule from
    # its explanation.
    tree = ast.parse((SCRIPTS / "feature_context.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "subprocess" not in imported
    assert "os" in imported, "it reads the environment and nothing else"


# --- AC4: refused, not guessed ------------------------------------------------

@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_an_undeclared_feature_is_refused(project):
    with pytest.raises(fc.FeatureContextError):
        fc.resolve(project, {})


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_the_refusal_names_both_declaring_sources(project):
    with pytest.raises(fc.FeatureContextError) as exc:
        fc.resolve(project, {})
    assert fc.FEATURE_DIR in str(exc.value)
    assert fc.FEATURE_JSON in str(exc.value)


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_an_undeclared_feature_returns_none_when_not_required(project):
    assert fc.resolve(project, {}, required=False) is None


# --- AC5: relative against the project root -----------------------------------

@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_a_relative_value_resolves_against_the_project_root(project, monkeypatch):
    # Spec Kit resolves it against its repo root, which its own get_repo_root
    # derives the same way project_root.resolve does. Resolving against cwd
    # would disagree with the CLI for the same value.
    elsewhere = project / "specs"
    monkeypatch.chdir(elsewhere)
    env = {fc.FEATURE_DIR: "specs/001-billing"}
    assert fc.resolve(project, env) == project / "specs/001-billing"


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_an_absolute_value_stands_alone(project, tmp_path):
    outside = tmp_path / "elsewhere" / "feature"
    outside.mkdir(parents=True)
    assert fc.resolve(project, {fc.FEATURE_DIR: str(outside)}) == outside


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_a_relative_feature_json_value_also_resolves_against_the_project(
        project, monkeypatch):
    write_feature_json(project, "specs/002-invoicing")
    monkeypatch.chdir(project / "specs")
    assert fc.resolve(project, {}) == project / "specs/002-invoicing"


# --- the two resolvers together -----------------------------------------------

@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_two_members_can_hold_two_active_features(tmp_path):
    for member, feature in (("member_a", "specs/001-billing"),
                            ("member_b", "specs/002-invoicing")):
        (tmp_path / member / ".specify").mkdir(parents=True)
        (tmp_path / member / feature).mkdir(parents=True)
        write_feature_json(tmp_path / member, feature)

    a_root = pr.resolve(cwd=tmp_path / "member_a", env={})
    b_root = pr.resolve(cwd=tmp_path / "member_b", env={})
    assert fc.resolve(a_root, {}) == tmp_path / "member_a" / "specs/001-billing"
    assert fc.resolve(b_root, {}) == tmp_path / "member_b" / "specs/002-invoicing"


@pytest.mark.req("REQ-TEAM-FEATURE-001")
def test_the_source_is_reported_rather_than_implied(project):
    assert fc.source(project, {}) == "none"
    write_feature_json(project, "specs/001-billing")
    assert fc.source(project, {}) == fc.FEATURE_JSON
