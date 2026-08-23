"""What the suite's assertions can and cannot catch.

The P12 coverage map found two shapes that look like coverage and are not: an
assertion that reads its expected value out of the policy it is checking, and
one that greps a workflow's prose. The second is worth keeping — it catches an
accidental deletion — but it must not be counted as behavioural coverage.

This file makes that distinction checkable rather than remembered.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from lib.inventory import ROOT

PROSE_MARKER = "wording"


def collected(*args):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header",
         "-p", "no:cacheprovider", *args],
        cwd=ROOT, capture_output=True, text=True).stdout


@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_the_wording_marker_is_declared():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'"{PROSE_MARKER}:' in text
    assert "not its behaviour" in text


@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_the_prose_assertions_are_marked():
    marked = {line.strip() for line in collected("-m", PROSE_MARKER).splitlines()
              if "::" in line}
    assert marked, "no test claims to check wording; the marker is unused"
    # The brownfield scan tests are the ones the map named.
    assert any("test_exception.py" in node for node in marked), sorted(marked)


@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_a_marked_test_is_excluded_from_behavioural_selection():
    # `-m "not wording"` is what a reader runs to see only assertions that
    # would fail on a regression.
    everything = {line.strip() for line in collected().splitlines()
                  if "::" in line}
    behavioural = {line.strip() for line in
                   collected("-m", f"not {PROSE_MARKER}").splitlines()
                   if "::" in line}
    assert behavioural < everything
    assert everything - behavioural


@pytest.mark.req("REQ-TOOLING-ASSERT-001")
def test_no_permission_test_reads_its_expectation_from_the_policy():
    # The self-referential shape: `assert generated[x] == policy[rule]` agrees
    # with itself however the policy changes.
    for name in ("tests/test_opencode_config.py", "tests/test_claude_config.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "== RUNTIME[rule]" not in text, name
        assert "PINNED" in text, f"{name} pins no literal values"
