"""Fixtures shared by the sandbox suite.

These tests install the bundle through the real `specify` CLI, which is slow
enough that every module holds one catalog server open for its whole run. That
makes them the only tests in the suite that can contend with each other.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def dist_dir(tmp_path_factory):
    """A private build output for this module's catalog server.

    Building empties the directory before refilling it, so two servers sharing
    one delete each other's archives and bake conflicting ports into a single
    `catalogs/` (#191). Serially that never happened, because each module's
    server closed before the next opened; under `pytest -n` six of them are
    open at once.

    Module-scoped to match the servers: one build per module, not one per test.
    """
    return tmp_path_factory.mktemp("dist")
