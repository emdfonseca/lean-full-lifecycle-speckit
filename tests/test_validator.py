"""The validator runs clean, and every registered check actually executes.

Deliberately absent: re-implementations of individual checks. The previous
suite reimplemented five of them, and one of those copies was weaker than the
validator's own version -- it omitted the plan-path comparison, so it passed on
a bundle the validator rejected. Two implementations of one rule is the bug this
repository exists to prevent.

Checks are proven to *fail* in test_check_negatives.py, which is the property
this file cannot establish.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from lib.inventory import ROOT
from lib.registry import REGISTRY


def run_validator(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/validate_source.py", *args],
        cwd=ROOT, text=True, capture_output=True,
    )


def test_source_is_valid():
    r = run_validator("--format", "json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["errors"] == []


@pytest.mark.req("REQ-TOOLING-CHECKS-001")
def test_every_registered_check_executes():
    # A check that silently stopped being reached would otherwise look healthy.
    executed = set(json.loads(run_validator("--format", "json").stdout)["executed"])
    assert executed == set(REGISTRY), f"not executed: {set(REGISTRY) - executed}"


def test_list_checks_is_machine_readable():
    # P1 requirements cite check ids; this is the contract that makes them resolvable.
    r = run_validator("--list-checks", "--format", "json")
    assert r.returncode == 0
    rows = json.loads(r.stdout)
    assert {row["id"] for row in rows} == set(REGISTRY)
    for row in rows:
        assert row["scope"] and row["title"]


def test_unknown_check_id_is_rejected():
    assert run_validator("--only", "NOPE-000").returncode == 2


@pytest.mark.parametrize("scope", sorted({c.scope for c in REGISTRY.values()}))
def test_each_scope_runs(scope):
    r = run_validator("--scope", scope, "--format", "json")
    assert r.returncode == 0
    assert json.loads(r.stdout)["executed"]
