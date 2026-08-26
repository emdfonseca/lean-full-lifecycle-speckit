"""git, the one binary `transition_plan.py` runs and nothing declared.

`transition_plan.py` shells out to `git diff --name-only HEAD` so the audit can
compare the board against the working tree. `requires.tools` named `gh` and
`python3` and not `git`, so `specify check` could not report it and a machine
without git got a silently weaker audit instead of a named missing
prerequisite.

Scope is exactly that binary. These tests assert nothing about binaries in
general: the bundle also executes `opencode`, read from `model-routing.yml`
rather than written in a script, and that is undeclared today (#159). A test
worded as a universal here would be green while it was false, which is the
defect #143, #134 and #150 were all about.
"""
from __future__ import annotations

import ast

import pytest

from lib.inventory import ROOT, load_yaml

EXT_MANIFEST = ROOT / "bundle/components/extensions/github-lifecycle/extension.yml"
TRANSITION_PLAN = (ROOT / "bundle/components/extensions/github-lifecycle/scripts"
                   / "transition_plan.py")


def _literal_argv_first_words(path) -> set[str]:
    """First words of every literal argument list handed to subprocess here.

    Positional and `args=` keyword forms both count. Anything non-literal is
    invisible to this, which is why the tests below speak only about the call
    this file is named for.
    """
    words: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in {"run", "Popen", "call", "check_call", "check_output"}:
            continue
        argv = node.args[0] if node.args else next(
            (kw.value for kw in node.keywords if kw.arg == "args"), None)
        if not isinstance(argv, (ast.List, ast.Tuple)) or not argv.elts:
            continue
        first = argv.elts[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            words.add(first.value)
    return words


def _declared_tools() -> dict[str, dict]:
    requires = load_yaml(EXT_MANIFEST)["requires"]
    return {t["name"]: t for t in (requires.get("tools") or [])}


@pytest.mark.req("REQ-PACKAGE-GIT-001")
def test_transition_plan_executes_git():
    # The premise the declaration rests on. If the audit stops shelling out to
    # git, this fails and the declaration below should be revisited rather than
    # left standing for a dependency that is gone.
    assert "git" in _literal_argv_first_words(TRANSITION_PLAN), (
        "transition_plan.py no longer runs git in a literal argument list")


@pytest.mark.req("REQ-PACKAGE-GIT-001")
def test_git_is_declared_in_requires_tools():
    assert "git" in _declared_tools(), (
        "transition_plan.py runs git and extension.yml does not declare it; "
        "specify check cannot report a prerequisite nothing names")


@pytest.mark.req("REQ-PACKAGE-GIT-001")
def test_git_is_declared_optional_and_says_what_its_absence_costs():
    # Required would be wrong: transition_plan.py catches OSError and
    # SubprocessError and returns None, so a machine without git loses one
    # audit rule and keeps the rest. Declaring it required would fail installs
    # that work.
    entry = _declared_tools()["git"]
    assert entry.get("required") is False, "git is optional; its absence is caught"
    why = str(entry.get("why") or "")
    assert "without it" in why.lower(), (
        "an optional tool must say what its absence costs")
