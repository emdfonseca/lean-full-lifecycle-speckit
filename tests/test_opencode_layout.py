"""Which OpenCode layout a project uses.

Spec Kit writes commands to `.opencode/commands` and reads `.opencode/command`
as legacy. A project initialized by an older CLI has the second, and writing
into the wrong one produces a project where the commands are present and the
agent cannot see them.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pr = _load("project_root")
ol = _load("opencode_layout")

POLICY = ol.load_policy(ROOT)
DIRS = POLICY["commands_dirs"]


def project(tmp_path, *generations, with_policy=False):
    (tmp_path / ".specify").mkdir(parents=True, exist_ok=True)
    for name in generations:
        (tmp_path / DIRS[name]).mkdir(parents=True)
    if with_policy:
        # A real project carries the governance preset. Without it the command
        # cannot load policy, which is a different failure from the one under
        # test.
        installed = tmp_path / ol.POLICY_CANDIDATES[0]
        installed.parent.mkdir(parents=True, exist_ok=True)
        installed.write_text(
            (ROOT / "policy/bootstrap-policy.yml").read_text(encoding="utf-8"),
            encoding="utf-8")
    return tmp_path


# --- AC1 / AC2: each generation is detected -----------------------------------

@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_the_current_generation_is_detected(tmp_path):
    layout = ol.detect(project(tmp_path, "current"), POLICY)
    assert layout.generation == ol.CURRENT
    assert layout.commands_dir == tmp_path / DIRS["current"]
    assert layout.usable


@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_the_legacy_generation_is_detected(tmp_path):
    layout = ol.detect(project(tmp_path, "legacy"), POLICY)
    assert layout.generation == ol.LEGACY
    assert layout.commands_dir == tmp_path / DIRS["legacy"]
    assert layout.usable


@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_the_reported_directory_is_the_one_that_exists(tmp_path):
    # The two names differ by one character. Reporting the wrong one is the
    # failure this exists to prevent, not a cosmetic slip.
    layout = ol.detect(project(tmp_path, "legacy"), POLICY)
    assert layout.commands_dir.is_dir()
    assert layout.commands_dir.name == "command"


# --- AC3: both present is reported, not resolved ------------------------------

@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_both_generations_present_is_reported_as_both(tmp_path):
    layout = ol.detect(project(tmp_path, "current", "legacy"), POLICY)
    assert layout.generation == ol.BOTH
    assert set(layout.present) == {"current", "legacy"}


@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_both_present_chooses_neither(tmp_path):
    layout = ol.detect(project(tmp_path, "current", "legacy"), POLICY)
    assert layout.commands_dir is None
    assert not layout.usable


@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_both_present_says_it_is_a_migration(tmp_path):
    # Choosing one on the project's behalf hides the migration from whoever
    # has to finish it.
    with pytest.raises(ol.LayoutError) as exc:
        ol.require(project(tmp_path, "current", "legacy"), POLICY)
    assert "part way through a migration" in str(exc.value)
    for rel in DIRS.values():
        assert rel in str(exc.value)


# --- AC4: neither present is refused, naming where it looked ------------------

@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_a_project_with_no_layout_is_refused(tmp_path):
    with pytest.raises(ol.LayoutError):
        ol.require(project(tmp_path), POLICY)


@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_the_refusal_names_every_directory_it_looked_for(tmp_path):
    root = project(tmp_path)
    with pytest.raises(ol.LayoutError) as exc:
        ol.require(root, POLICY)
    for rel in DIRS.values():
        assert str(root / rel) in str(exc.value)


@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_a_file_where_a_directory_belongs_is_not_a_layout(tmp_path):
    root = project(tmp_path)
    target = root / DIRS["current"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not a directory", encoding="utf-8")
    assert ol.detect(root, POLICY).generation == ol.NONE


# --- AC5: the project root, not the working directory -------------------------

@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_detection_runs_against_the_resolved_project_root(tmp_path):
    root = project(tmp_path, "current")
    deep = root / "src" / "billing"
    deep.mkdir(parents=True)
    resolved = pr.resolve(cwd=deep, env={})
    assert ol.detect(resolved, POLICY).generation == ol.CURRENT


@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_the_command_detects_from_a_subdirectory(tmp_path):
    root = project(tmp_path, "legacy", with_policy=True)
    deep = root / "src"
    deep.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "opencode_layout.py"),
         "--format", "json"],
        cwd=deep, capture_output=True, text=True,
        env={"PATH": subprocess.os.environ["PATH"]})
    assert '"generation": "legacy"' in result.stdout, result.stderr


@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_a_sibling_member_layout_is_not_this_members(tmp_path):
    # In a monorepo the same relative path is a different member's layout.
    (tmp_path / ".git").mkdir()
    a = project(tmp_path / "member_a", "current")
    b = project(tmp_path / "member_b")
    assert ol.detect(a, POLICY).usable
    assert not ol.detect(b, POLICY).usable


# --- the paths are declared, not written here ---------------------------------

@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_the_directories_come_from_policy():
    import ast

    # Parsed, not scanned: the module's docstring names both directories while
    # explaining why they are not written here, and a substring check cannot
    # tell a rule from its explanation.
    tree = ast.parse((SCRIPTS / "opencode_layout.py").read_text(encoding="utf-8"))
    docstrings = {id(ast.get_docstring(n, clean=False))
                  for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))}
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n.value) not in docstrings]
    for rel in DIRS.values():
        assert not [v for v in literals if rel in v], \
            f"{rel} is hardcoded; policy would not move it"


@pytest.mark.req("REQ-CORE-LAYOUT-001")
def test_an_undescribed_integration_is_refused(tmp_path):
    with pytest.raises(ol.LayoutError) as exc:
        ol.load_policy(ROOT, integration="some-other-agent")
    assert "not one to guess at" in str(exc.value)


def test_the_policy_names_both_generations():
    declared = load_yaml(ROOT / "policy/bootstrap-policy.yml")
    dirs = declared["integrations"]["opencode"]["commands_dirs"]
    assert set(dirs) == {"current", "legacy"}
