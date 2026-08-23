"""Whether a repository already has a product in it.

Greenfield bootstrap writes on the assumption the repository is empty. These
tests hold the two judgements that make the check trustworthy: counts never
decide, and an unreadable repository is not an empty one.
"""
from __future__ import annotations

import importlib.util
import sys

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
spec = importlib.util.spec_from_file_location("mismatch", SCRIPTS / "mismatch.py")
mm = importlib.util.module_from_spec(spec)
sys.modules["mismatch"] = mm
spec.loader.exec_module(mm)

POLICY = mm.load_policy(ROOT)
WORKFLOW = load_yaml(
    ROOT / "bundle/components/workflows/lifecycle-greenfield-bootstrap/workflow.yml")


def repo(tmp_path, *paths):
    for rel in paths:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
    return tmp_path


# --- AC1: scaffolding alone does not stop the bootstrap -----------------------

@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_scaffolding_only_is_not_a_mismatch(tmp_path):
    root = repo(tmp_path, "README.md", "pyproject.toml", "Makefile",
                "devbox.json", ".github/workflows/ci.yml", ".gitignore")
    assert mm.assess(root, POLICY).verdict == mm.NO_MISMATCH


@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_an_empty_repository_is_not_a_mismatch(tmp_path):
    assert mm.assess(tmp_path, POLICY).verdict == mm.NO_MISMATCH


@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_configuration_written_in_a_language_is_still_configuration(tmp_path):
    # The suffix says code and the name says configuration; the name wins.
    root = repo(tmp_path, "vite.config.ts", "webpack.config.js",
                "eslint.config.mjs")
    assert mm.assess(root, POLICY).verdict == mm.NO_MISMATCH


# --- AC2: application code stops it, with named evidence ----------------------

@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_one_domain_module_is_a_mismatch(tmp_path):
    root = repo(tmp_path, "README.md", "src/billing.py")
    result = mm.assess(root, POLICY)
    assert result.verdict == mm.MISMATCH
    assert "src/billing.py" in result.stated_reason
    assert result.evidence == ["src/billing.py"]


@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_a_mismatch_recommends_brownfield_adoption(tmp_path):
    result = mm.assess(repo(tmp_path, "app/main.go"), POLICY)
    assert result.recommends == "lifecycle-brownfield-adoption"


@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_a_test_suite_is_evidence_of_a_product(tmp_path):
    # Treating tests as scaffolding is how a repository with a full suite and
    # one thin module reads as empty.
    result = mm.assess(repo(tmp_path, "tests/test_billing.py"), POLICY)
    assert result.verdict == mm.MISMATCH


# --- AC3: counts never decide -------------------------------------------------

@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_many_configuration_files_are_still_not_a_mismatch(tmp_path):
    root = repo(tmp_path, *[f"conf/{i}.yml" for i in range(80)], "package.json")
    assert mm.assess(root, POLICY).verdict == mm.NO_MISMATCH


@pytest.mark.req("REQ-CORE-GREENFIELD-001")
@pytest.mark.parametrize("paths", [
    ("src/a.py",),
    ("src/a.py", "src/b.py", "src/c.py", "src/d.py", "src/e.py"),
])
def test_no_verdict_states_a_count(tmp_path, paths):
    result = mm.assess(repo(tmp_path, *paths), POLICY)
    assert not mm.reason_states_a_count(result.stated_reason), \
        result.stated_reason


@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_the_count_detector_recognises_a_count_and_ignores_a_filename():
    # A regex that fires on any digit would flag `oauth2.py`, and one that fires
    # on none would miss the thing it exists to catch.
    assert mm.reason_states_a_count("found 12 files carrying logic")
    assert mm.reason_states_a_count("the total exceeds the threshold")
    assert not mm.reason_states_a_count("logic in src/oauth2.py and api/v3.py")


@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_a_long_evidence_list_is_summarised_without_counting(tmp_path):
    root = repo(tmp_path, *[f"src/m{i}.py" for i in range(20)])
    result = mm.assess(root, POLICY)
    assert len(result.evidence) == 20
    assert not mm.reason_states_a_count(result.stated_reason)
    assert "other files listed in the evidence" in result.stated_reason


# --- AC5: unreadable does not read as empty -----------------------------------

@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_an_unreadable_repository_blocks(tmp_path, monkeypatch):
    def refuse(_root):
        raise PermissionError("cannot enumerate")

    monkeypatch.setattr(mm, "enumerate_files", refuse)
    result = mm.assess(tmp_path, POLICY)
    assert result.verdict == mm.BLOCKED
    assert result.verdict != mm.NO_MISMATCH
    assert "not evidence of an empty repository" in result.stated_reason


@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_enumeration_raises_rather_than_returning_a_partial_list(tmp_path,
                                                                monkeypatch):
    # A half-read repository that happens to miss the one module present would
    # report no mismatch, which is the failure this exists to prevent.
    real = mm.enumerate_files
    assert real.__doc__ and "partial" in real.__doc__
    monkeypatch.setattr(mm.Path, "rglob",
                        lambda self, pat: (_ for _ in ()).throw(OSError("io")))
    assert mm.assess(tmp_path, POLICY).verdict == mm.BLOCKED


# --- AC4: a person decides, before anything is written ------------------------

@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_the_check_and_its_gate_precede_every_writing_step():
    ids = [s["id"] for s in WORKFLOW["steps"]]
    gate = ids.index("confirm-no-mismatch")
    assert ids.index("check-greenfield-mismatch") < gate
    for writer in ("establish-constitution", "apply-greenfield-bootstrap"):
        assert ids.index(writer) > gate, writer


@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_rejecting_the_gate_aborts_rather_than_continuing():
    gate = [s for s in WORKFLOW["steps"] if s["id"] == "confirm-no-mismatch"][0]
    assert gate["on_reject"] == "abort"
    assert gate["show_file"].endswith("greenfield-mismatch-{{ context.run_id }}.md")


@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_the_gate_says_what_each_choice_costs():
    gate = [s for s in WORKFLOW["steps"] if s["id"] == "confirm-no-mismatch"][0]
    assert "costs a rerun" in gate["message"]
    assert "lifecycle-brownfield-adoption" in gate["message"]


# --- policy is the source -----------------------------------------------------

@pytest.mark.req("REQ-CORE-GREENFIELD-001")
def test_the_classification_comes_from_policy_not_the_script():
    source = (SCRIPTS / "mismatch.py").read_text(encoding="utf-8")
    for suffix in (".py", ".go", ".rs"):
        assert f'"{suffix}"' not in source, (
            f"{suffix} is hardcoded; changing policy would not change behaviour")
    for name in ("pyproject.toml", "package.json"):
        assert name not in source, f"{name} is hardcoded"
