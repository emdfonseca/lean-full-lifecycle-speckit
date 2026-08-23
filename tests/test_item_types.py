"""The backlog item contract.

Nothing defined what an item of each type must contain, so issues were written
to a structure that existed only in one author's habit. These tests hold the
policy to being a contract rather than a description.
"""
from __future__ import annotations

import json
import subprocess
import sys

import jsonschema
import pytest

from lib.inventory import ROOT, load_yaml

POLICY = load_yaml(ROOT / "policy" / "item-types.yml")
SCHEMA = json.loads((ROOT / "tooling/schemas/readiness-verdict.schema.json")
                    .read_text(encoding="utf-8"))

VALID_VERDICT = {
    "readiness": "ready",
    "blocking_questions": [],
    "risk": "medium",
    "spec_impact": "create",
    "material_uncertainty": "none",
    "next_engineering_action": "Define the policy and generate the templates.",
}


@pytest.mark.req("REQ-BACKLOG-ITEMS-001")
def test_every_type_requires_something():
    # A type whose sections are all optional imposes no contract.
    for type_id, spec in POLICY["types"].items():
        assert any(s.get("required") for s in spec["sections"]), type_id


@pytest.mark.req("REQ-BACKLOG-ITEMS-001")
@pytest.mark.parametrize("type_id", sorted(POLICY["types"]))
def test_every_type_has_a_generated_template(type_id):
    path = ROOT / ".github/ISSUE_TEMPLATE" / f"{type_id}.yml"
    assert path.is_file(), f"no template for {type_id}"
    template = load_yaml(path)
    ids = {b.get("id") for b in template["body"] if b.get("id")}
    required = {s["id"] for s in POLICY["types"][type_id]["sections"]}
    common = {s["id"] for s in POLICY.get("common_sections") or []}
    assert required | common <= ids


@pytest.mark.req("REQ-BACKLOG-ITEMS-001")
def test_templates_are_regenerated_from_the_policy():
    r = subprocess.run([sys.executable, "scripts/generate_item_templates.py", "--check"],
                       cwd=ROOT, text=True, capture_output=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_blank_issues_are_disabled():
    # A blank issue has no contract and cannot be refined against one.
    cfg = load_yaml(ROOT / ".github/ISSUE_TEMPLATE/config.yml")
    assert cfg["blank_issues_enabled"] is False


# --- the readiness verdict ----------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-READINESS-001")
def test_a_well_formed_verdict_validates():
    jsonschema.validate(VALID_VERDICT, SCHEMA)


@pytest.mark.req("REQ-BACKLOG-READINESS-001")
@pytest.mark.parametrize("field", sorted(VALID_VERDICT))
def test_every_field_is_required(field):
    bad = {k: v for k, v in VALID_VERDICT.items() if k != field}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)


@pytest.mark.req("REQ-BACKLOG-READINESS-001")
@pytest.mark.parametrize("field,value", [
    ("readiness", "maybe"),
    ("risk", "catastrophic"),
    ("spec_impact", "rewrite"),
    ("material_uncertainty", "vibes"),
])
def test_an_out_of_vocabulary_value_is_rejected(field, value):
    jsonschema.validate(VALID_VERDICT, SCHEMA)   # control
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**VALID_VERDICT, field: value}, SCHEMA)


def test_an_unknown_field_is_rejected():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**VALID_VERDICT, "vibe": "good"}, SCHEMA)


def test_the_schema_matches_the_policy_vocabulary():
    for name, spec in POLICY["readiness_verdict"]["fields"].items():
        if spec["type"] == "enum":
            assert SCHEMA["properties"][name]["enum"] == list(spec["values"])


# --- agreement with the rest of the policy ------------------------------------

@pytest.mark.req("REQ-BACKLOG-ITEMS-001")
def test_severity_scope_agrees_with_github_schema():
    schema = load_yaml(ROOT / "policy/github-schema.yml")
    applies = {s.lower() for s in schema["issue_fields"]["Severity"]["applies_to"]}
    carries = {t for t, spec in POLICY["types"].items() if spec.get("carries_severity")}
    assert applies == carries


def test_only_epics_decompose():
    # A Story that needs splitting is two Stories, not a parent.
    decomposable = {t for t, s in POLICY["types"].items() if s.get("decomposable")}
    assert decomposable == {"epic"}


def test_the_verdict_applies_to_the_types_that_are_started():
    # Epics are not started directly; their children are.
    applies = set(POLICY["readiness_verdict"]["applies_to"])
    assert "epic" not in applies
    assert {"story", "bug", "spike"} <= applies


def test_the_policy_is_mirrored_into_the_preset():
    mirrored = (ROOT / "bundle/components/presets/lean-full-lifecycle-governance"
                / "policy/item-types.yml")
    assert mirrored.read_bytes() == (ROOT / "policy/item-types.yml").read_bytes()
