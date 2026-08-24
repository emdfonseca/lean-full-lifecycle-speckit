"""Documentation claims that a test can actually hold to.

Most documentation cannot be tested, and pretending otherwise produces
ceremony. What *is* testable is the shape of a status document: that it
distinguishes verified from unverified rather than implying everything works.
"""
from __future__ import annotations

import re

import json

import pytest

from lib.inventory import ROOT, load_yaml


@pytest.mark.req("REQ-DOCS-TRUTH-001")
def test_validation_states_unverified_areas():
    text = (ROOT / "VALIDATION.md").read_text(encoding="utf-8")
    assert "## Not verified" in text, "VALIDATION.md must say what has not been verified"
    section = text.split("## Not verified", 1)[1].split("##", 1)[0]
    assert len(section.strip()) > 100, "the unverified section is a stub"


def test_validation_names_the_platform_it_was_run_on():
    text = (ROOT / "VALIDATION.md").read_text(encoding="utf-8")
    assert re.search(r"Spec Kit `?\d+\.\d+\.\d+", text), "no Spec Kit version recorded"


@pytest.mark.parametrize("doc", ["README.md", "VALIDATION.md", "INSTALL-LOCAL.md",
                                 "docs/installation.md", "docs/publishing.md"])
def test_no_doc_recommends_the_unusable_validate_form(doc):
    # `bundle validate` resolves references against the project containing the
    # manifest, so the online form can never pass from a source checkout.
    text = (ROOT / doc).read_text(encoding="utf-8")
    for line in text.splitlines():
        if "bundle validate" in line and "--path" in line:
            assert "--offline" in line, f"{doc}: {line.strip()!r} cannot pass from a checkout"


@pytest.mark.parametrize("doc", ["README.md", "VALIDATION.md", "INSTALL-LOCAL.md",
                                 "docs/installation.md", "docs/publishing.md",
                                 "scripts/README.md"])
def test_no_doc_references_a_deleted_script(doc):
    text = (ROOT / doc).read_text(encoding="utf-8")
    assert "install_dev.py" not in text, f"{doc} references a script that no longer exists"


@pytest.mark.req("REQ-SECURITY-UNTRUSTED-001")
def test_no_workflow_interpolates_untrusted_content_into_a_command():
    # The enforceable half of "untrusted input never authorizes an action".
    # No Python check stops prompt injection reaching an agent's context, and
    # one claiming to would be worse than none.
    import subprocess
    import sys as _sys

    result = subprocess.run(
        [_sys.executable, str(ROOT / "scripts/validate_source.py"),
         "--only", "SEC-UNTRUSTED-NO-COMMAND-INTERPOLATION", "--format", "json"],
        capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload["errors"] == [], payload["errors"]


@pytest.mark.req("REQ-SECURITY-UNTRUSTED-001")
def test_the_issue_reference_is_still_usable():
    # A check that refused `inputs.issue_ref` would refuse nearly every step
    # in the bundle. What is untrusted is the content, not the address.
    delivery = load_yaml(
        ROOT / "bundle/components/workflows/lifecycle-story-delivery/workflow.yml")
    text = json.dumps(delivery)
    assert "inputs.issue_ref" in text
