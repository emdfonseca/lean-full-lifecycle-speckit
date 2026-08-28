"""Shared fixtures.

`scripts/` is on the path via pyproject's `pythonpath`, so tests import the
inventory and generators directly instead of shelling out to them.
"""
from __future__ import annotations

import os
import shutil

import pytest

from lib import checks as _checks  # noqa: F401  (registers the checks)
from lib.inventory import ROOT, load_inventory, load_yaml


@pytest.fixture(scope="session")
def inv():
    return load_inventory()


@pytest.fixture(scope="session")
def invariants():
    return load_yaml(ROOT / "tooling" / "invariants.yml")


@pytest.fixture(scope="session")
def root():
    return ROOT


def pytest_runtest_setup(item):
    if item.get_closest_marker("requires_opencode") and not shutil.which("opencode"):
        pytest.skip("opencode CLI not on PATH")
    if item.get_closest_marker("requires_specify") and not shutil.which("specify"):
        pytest.skip("specify CLI not on PATH")


def pytest_runtest_protocol(item, nextitem):
    """Name the current test where a spawned process can read it.

    Many tests here drive a script through `subprocess.run` because the refusal
    text is what a reader sees. Coverage's `dynamic_context` needs a pytest
    frame, which a spawned process does not have, so its lines land against no
    context at all. `tooling/coverage-subprocess/.coveragerc` reads this
    variable as a static context, which is what lets a `check:` component be
    attributed to the test that exercised it.

    Unset outside a measurement run, where it costs one env write per test.
    """
    os.environ["COVERAGE_CONTEXT"] = item.name.split("[", 1)[0]
    return None
