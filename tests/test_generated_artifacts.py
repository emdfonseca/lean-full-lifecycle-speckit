"""Generated files match the manifests they derive from.

bundle.yml and the four catalogs are outputs. A hand-edit to any of them is
drift, and this is what turns that into a test failure rather than a surprise
at publish time.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from lib.inventory import ROOT


@pytest.mark.parametrize("script", ["generate_manifests.py", "generate_catalogs.py"])
@pytest.mark.req("REQ-TOOLING-SOT-001")
def test_generated_output_is_current(script):
    r = subprocess.run(
        [sys.executable, f"scripts/{script}", "--check"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_yaml_dump_emits_no_anchors():
    # PyYAML emits &id001/*id001 for any repeated node. The workflow manifests
    # already carry them from an earlier round-trip, and in a byte-compared
    # artifact one inserted input renumbers every anchor.
    from lib.yamlfmt import dump

    shared = {"enum": ["", "approve", "reject"]}
    text = dump({"a": shared, "b": shared})
    assert "&id" not in text and "*id" not in text
