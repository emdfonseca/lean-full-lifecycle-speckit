"""Which agent a workflow dispatches to.

All fifteen workflows shipped with `integration` defaulting to `opencode`, so a
project initialized with any other agent still shelled out to that one. Spec
Kit's engine already carries the mechanism: `auto` is a runtime sentinel it
exempts from enum validation specifically, resolved to the project's configured
integration at execution time.
"""
from __future__ import annotations

import pytest

from lib.inventory import ROOT, load_yaml

SENTINEL = "auto"
DOCS = ["README.md", "docs/installation.md", "INSTALL-LOCAL.md",
        "bundle/README.md"]


# --- AC1: no workflow names an agent ------------------------------------------

@pytest.mark.req("REQ-CORE-INTEGRATION-001")
def test_every_workflow_defaults_to_the_runtime_sentinel(inv):
    named = {c.id: (c.manifest["inputs"]["integration"]["default"])
             for c in inv.by_kind("workflow")
             if "default" in (c.manifest.get("inputs") or {}).get("integration", {})}
    assert named
    assert set(named.values()) == {SENTINEL}, named


@pytest.mark.req("REQ-CORE-INTEGRATION-001")
def test_the_input_is_still_a_string_with_no_enum(inv):
    # The sentinel is exempted from enum membership, not from type checking.
    # An enum here would reject `auto` at install time.
    for comp in inv.by_kind("workflow"):
        spec = (comp.manifest.get("inputs") or {}).get("integration") or {}
        if not spec:
            continue
        assert spec.get("type") == "string", comp.id
        assert "enum" not in spec, comp.id


@pytest.mark.req("REQ-CORE-INTEGRATION-001")
def test_the_framework_policy_follows_the_project(root):
    framework = load_yaml(root / "policy/framework.yml")["spec_kit"]
    assert framework["integration"] == SENTINEL
    # Under test is not the same as required, and a reader has to be able to
    # tell them apart.
    assert framework["reference_integration"] == "opencode"


# --- AC5: the fix cannot be undone by copying a neighbour ---------------------

@pytest.mark.req("REQ-CORE-INTEGRATION-001")
def test_the_invariant_declares_the_expected_default(invariants):
    assert invariants["integration_default"] == SENTINEL


@pytest.mark.req("REQ-CORE-INTEGRATION-001")
def test_a_registered_check_enforces_it():
    from lib import checks  # noqa: F401  (registers them)
    from lib import registry

    assert "INV-INTEGRATION-DEFAULT" in registry.REGISTRY


# --- AC4: the docs say which agent the bundle assumes -------------------------

@pytest.mark.req("REQ-CORE-INTEGRATION-001")
@pytest.mark.parametrize("doc", DOCS)
def test_no_document_tells_a_user_to_pass_a_specific_integration(root, doc):
    # `--integration opencode` on a `specify` command reads as a requirement.
    # The smoke test legitimately names one: a harness has to pick something to
    # exercise, and it says so on the line.
    for line in (root / doc).read_text(encoding="utf-8").splitlines():
        if "smoke_test" in line:
            continue
        assert "--integration opencode" not in line, (doc, line)
        assert "integration=opencode" not in line, (doc, line)


@pytest.mark.req("REQ-CORE-INTEGRATION-001")
def test_the_bundle_readme_says_the_workflows_follow_the_project(root):
    text = (root / "bundle/README.md").read_text(encoding="utf-8")
    assert "do not name an agent" in text
    assert "not the one required" in text
