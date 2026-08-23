"""What the bundle claims works under which agent.

Four documents and a policy field all named `opencode`, and a reader could not
tell whether that was a requirement, a default, or the only thing anybody had
tried. The matrix answers that from named tests rather than from intent.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from lib.inventory import ROOT, load_yaml

COMPAT = load_yaml(ROOT / "tooling/compatibility.yml")
DECLARED = list(load_yaml(ROOT / "policy/bootstrap-policy.yml")["integrations"])
DOC = ROOT / "docs/compatibility.md"


# --- AC1 / AC3: every integration appears, tested or not ----------------------

@pytest.mark.req("REQ-DOCS-COMPAT-001")
@pytest.mark.parametrize("integration", DECLARED)
def test_every_declared_integration_appears_in_the_matrix(integration):
    assert integration in DOC.read_text(encoding="utf-8")


@pytest.mark.req("REQ-DOCS-COMPAT-001")
def test_an_untested_capability_is_marked_not_tested(): 
    # Omitting it would let "nobody has tried" read as "fine".
    text = DOC.read_text(encoding="utf-8")
    assert "not tested" in text
    # claude has no overlay coverage today; that must be visible.
    assert not (COMPAT["integrations"]["claude"].get("overlays"))


@pytest.mark.req("REQ-DOCS-COMPAT-001")
def test_what_nobody_claims_is_stated(): 
    # Running a workflow end to end is claimed by no integration, and the
    # matrix says so rather than letting installation coverage imply it.
    assert "workflow_execution" in COMPAT["not_claimed_by_anyone"]
    assert "workflow execution" in DOC.read_text(encoding="utf-8")


# --- AC2: each entry says what was exercised ----------------------------------

@pytest.mark.req("REQ-DOCS-COMPAT-001")
def test_every_claim_names_at_least_one_test():
    for integration, entries in COMPAT["integrations"].items():
        for capability, tests in entries.items():
            assert tests, f"{integration}.{capability} claims coverage with no test"


@pytest.mark.req("REQ-DOCS-COMPAT-001")
def test_every_capability_used_is_declared():
    declared = set(COMPAT["capabilities"])
    for integration, entries in COMPAT["integrations"].items():
        assert set(entries) <= declared, integration


# --- AC4: derived, not maintained ---------------------------------------------

@pytest.mark.req("REQ-DOCS-COMPAT-001")
def test_the_document_is_current():
    result = subprocess.run(
        [sys.executable, "scripts/generate_compat_matrix.py", "--check"],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.req("REQ-DOCS-COMPAT-001")
def test_the_document_says_it_is_generated():
    assert "Do not edit" in DOC.read_text(encoding="utf-8")


# --- AC5: an unbacked claim fails validation ----------------------------------

@pytest.mark.req("REQ-DOCS-COMPAT-001")
def test_a_registered_check_verifies_the_claims():
    from lib import checks  # noqa: F401  (registers them)
    from lib import registry

    assert "PUB-COMPAT-CLAIM" in registry.REGISTRY


@pytest.mark.req("REQ-DOCS-COMPAT-001")
def test_every_claimed_node_id_is_collected():
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True)
    known = {line.strip() for line in collected.stdout.splitlines()
             if "::" in line}
    assert known, "collection produced nothing; this test would pass vacuously"
    for integration, entries in COMPAT["integrations"].items():
        for capability, tests in entries.items():
            for node in tests:
                assert node in known, f"{integration}.{capability}: {node}"
