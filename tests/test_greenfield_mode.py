"""What a greenfield bootstrap run can be asked for.

The workflow declared two modes and shipped a contract for one. Nothing in
`product_documents.required` was conditional, so a `framework-only` run was
asked for seven documents, forbidden two of them by its own apply step, and
told not to proceed while the check reported a problem. The mode was removed
rather than given a document set: what it produced -- a constitution, a
mismatch record, an inspection and an agent-settings proposal -- is what five
commands of this extension already produce on their own, and none of them
needs a mode (#133).

The tests here pin the deletion in both halves. The mode is gone from the
declaration, and it is gone from the prose: an enum value removed while the
step that branched on it still says "for framework-only mode" leaves the run
being told to do something no input can ask for.
"""
from __future__ import annotations

import pytest
import yaml

from lib.inventory import BUNDLE, ROOT

WORKFLOW = yaml.safe_load(
    (ROOT / "bundle/components/workflows/lifecycle-greenfield-bootstrap"
            "/workflow.yml").read_text(encoding="utf-8"))
CONTRACT = yaml.safe_load(
    (ROOT / "policy/bootstrap-policy.yml").read_text(
        encoding="utf-8"))["product_documents"]

STEPS = {step["id"]: step for step in WORKFLOW["steps"]}


@pytest.mark.req("REQ-CORE-GREENFIELD-002")
def test_the_bootstrap_declares_no_mode():
    # A one-value enum is the same defect wearing a smaller hat: it offers a
    # choice the workflow does not have.
    assert "mode" not in WORKFLOW["inputs"]


@pytest.mark.req("REQ-CORE-GREENFIELD-002")
def test_no_step_branches_on_a_mode():
    for step in WORKFLOW["steps"]:
        text = yaml.safe_dump(step)
        assert "inputs.mode" not in text, f"{step['id']} still renders a mode"
        assert "framework-only" not in text, f"{step['id']} still branches"


@pytest.mark.req("REQ-CORE-GREENFIELD-002")
def test_the_apply_step_asks_for_the_product_artifacts_unconditionally():
    # The half of the branch that survives has to survive as an instruction,
    # not as the second arm of a conditional whose first arm was deleted.
    prompt = STEPS["apply-greenfield-bootstrap"]["prompt"]
    assert "PRODUCT.md" in prompt
    assert "Epic" in prompt
    assert "For product mode" not in prompt


@pytest.mark.req("REQ-CORE-GREENFIELD-002")
def test_no_shipped_surface_offers_a_framework_only_bootstrap():
    # The bundle is what a target project installs. A mode named in a README
    # there is a promise, whatever the workflow declares.
    offenders = [p.relative_to(ROOT) for p in BUNDLE.rglob("*")
                 if p.is_file() and p.suffix in (".yml", ".yaml", ".md")
                 and "framework-only" in p.read_text(encoding="utf-8")]
    assert offenders == []


@pytest.mark.req("REQ-CORE-GREENFIELD-002")
def test_every_declared_document_is_required_of_every_run():
    # One contract, both routes. A per-entry condition here is how the set
    # starts differing by mode again, which is what had no contract.
    for spec in CONTRACT["required"]:
        assert "condition" not in spec, spec["path"]
        assert "mode" not in spec, spec["path"]
    assert len(CONTRACT["required"]) == 7
