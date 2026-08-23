"""The traceability validator holds, and can be shown to fail.

Same principle as the source checks: proving the catalogue is currently
consistent says nothing about whether the validator would notice if it were
not. Each case below breaks one direction of the reciprocity in a copy and
asserts the error surfaces.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from lib.inventory import ROOT


def run(cwd=ROOT, *args):
    return subprocess.run(
        [sys.executable, "scripts/validate_requirements.py", *args],
        cwd=cwd, text=True, capture_output=True,
    )


def test_catalogue_is_consistent():
    r = run()
    assert r.returncode == 0, r.stdout


def test_report_renders():
    r = run(ROOT, "--report", "md")
    assert r.returncode == 0
    assert "Requirement coverage" in r.stdout


@pytest.fixture
def tree(tmp_path):
    dest = tmp_path / "src"
    dest.mkdir()
    for item in ("bundle", "policy", "tooling", "scripts", "tests", "pyproject.toml",
                 "VALIDATION.md", "README.md", "INSTALL-LOCAL.md", "docs", "catalogs"):
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(src, dest / item, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dest / item)
    return dest


def _sub(path, old, new):
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_detects_a_test_that_stopped_claiming(tree):
    _sub(tree / "tests/test_docs.py", '@pytest.mark.req("REQ-DOCS-TRUTH-001")\n', "")
    r = run(tree)
    assert r.returncode == 1
    assert "does not claim it" in r.stdout


def test_detects_a_claim_the_catalogue_does_not_list(tree):
    _sub(tree / "tests/test_docs.py",
         "def test_validation_names_the_platform_it_was_run_on(",
         '@pytest.mark.req("REQ-DOCS-TRUTH-001")\n'
         "def test_validation_names_the_platform_it_was_run_on(")
    r = run(tree)
    assert r.returncode == 1
    assert "appears in no verified_by entry" in r.stdout


def test_detects_a_renamed_test(tree):
    _sub(tree / "tooling/requirements/requirements.yml",
         "test_validation_states_unverified_areas", "test_gone_away")
    r = run(tree)
    assert r.returncode == 1
    assert "is not a collected test" in r.stdout


def test_detects_an_unresolvable_component(tree):
    _sub(tree / "tooling/requirements/requirements.yml",
         "check:INV-POLICY-MIRROR", "check:INV-DOES-NOT-EXIST")
    r = run(tree)
    assert r.returncode == 1
    assert "unknown check id" in r.stdout


def test_detects_a_claimed_requirement_that_does_not_exist(tree):
    _sub(tree / "tests/test_docs.py",
         '@pytest.mark.req("REQ-DOCS-TRUTH-001")',
         '@pytest.mark.req("REQ-DOCS-TRUTH-999")')
    r = run(tree)
    assert r.returncode == 1
    assert "unknown requirement" in r.stdout
