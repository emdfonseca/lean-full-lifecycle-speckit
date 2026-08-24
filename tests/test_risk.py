"""Risk scoring from policy, offline.

`risk-policy.yml` scored twelve dimensions and named seven overrides, and no
code read it. These tests concentrate on the three things that make the
scoring worth trusting: it reads every number from the policy, an override
beats the arithmetic, and it never claims a control was satisfied.
"""
from __future__ import annotations

import importlib.util
import sys

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(SCRIPTS))
risk = _load("risk")
POLICY = risk.load_policy(ROOT)


def _code_literals(path):
    """Every string literal in the module except docstrings.

    Docstrings are excluded deliberately: naming a dimension while explaining
    the design is documentation, and a test that forbade it would push the
    reasoning out of the file to satisfy a check.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings}


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_no_dimension_or_override_is_named_in_the_code():
    # A number or a name this script invented would be an opinion wearing a
    # policy's clothes. Every weight, threshold, override and control set is
    # read from the installed file.
    declared = load_yaml(ROOT / "policy/risk-policy.yml")
    literals = _code_literals(SCRIPTS / "risk.py")
    for name in declared["dimensions"]:
        assert name not in literals, f"{name} is hardcoded in risk.py"
    for override in declared["overrides_to_high"]:
        assert override not in literals, f"{override} is hardcoded in risk.py"
    for band, controls in declared["controls"].items():
        assert band not in literals, f"band {band} is hardcoded in risk.py"
        for control in controls:
            assert control not in literals, f"{control} is hardcoded in risk.py"


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_a_low_item_scores_low_and_gets_the_low_controls():
    result = risk.score({k: 0 for k in POLICY["dimensions"]}, POLICY)
    assert result.level == "low"
    assert result.total == 0
    assert result.controls == POLICY["controls"]["low"]
    assert not result.unrated


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_the_maximum_is_every_dimension_at_its_ceiling():
    result = risk.score({k: 3 for k in POLICY["dimensions"]}, POLICY)
    assert result.level == "high"
    assert result.total == result.maximum


@pytest.mark.req("REQ-RISK-SCORING-001")
@pytest.mark.parametrize("override", load_yaml(
    ROOT / "policy/risk-policy.yml")["overrides_to_high"])
def test_every_declared_override_makes_an_otherwise_zero_item_high(override):
    # The dimensions describe degree; the overrides describe kind. A weighted
    # sum that could out-vote an auth-boundary change would be a scoring
    # system arguing with its own policy.
    result = risk.score({k: 0 for k in POLICY["dimensions"]}, POLICY, [override])
    assert result.total == 0
    assert result.level == "high"
    assert result.overridden
    assert result.controls == POLICY["controls"]["high"]


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_a_migration_carrying_the_override_is_high_and_carries_high_controls():
    # AC-BROWNFIELD-005: a data migration.
    result = risk.score(
        {"migration_complexity": 3, "blast_radius": 3, "reversibility": 3},
        POLICY, ["irreversible_high_blast_radius_migration"])
    assert result.level == "high"
    assert "rollout_and_rollback" in result.controls
    assert "observability_and_audit" in result.controls


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_an_auth_boundary_change_is_high_and_requires_security_review():
    # AC-BROWNFIELD-006: a security-sensitive change.
    result = risk.score({"authentication_authorization": 1}, POLICY,
                        ["authentication_or_authorization_boundary_change"])
    assert result.level == "high"
    assert "explicit_threat_analysis" in result.controls
    assert "authorized_security_review" in result.controls
    assert "security_tests" in result.controls


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_an_override_the_policy_does_not_declare_escalates_nothing():
    result = risk.score({k: 0 for k in POLICY["dimensions"]}, POLICY,
                        ["not_a_real_override"])
    assert result.level == "low"
    assert result.overrides == []
    assert result.unknown_overrides == ["not_a_real_override"]
    assert any("cannot escalate" in p for p in risk.problems(result))


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_an_invented_dimension_is_reported_rather_than_scored():
    result = risk.score({"vibes": 3}, POLICY)
    assert result.total == 0
    assert result.unknown_dimensions == ["vibes"]
    assert any("not dimensions" in p for p in risk.problems(result))


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_unrated_dimensions_are_reported_because_zero_understates():
    result = risk.score({"data_sensitivity": 3}, POLICY)
    assert result.unrated
    assert any("understates the risk" in p for p in risk.problems(result))


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_a_rating_outside_the_policy_range_is_refused():
    with pytest.raises(ValueError, match="outside 0..3"):
        risk.score({"data_sensitivity": 4}, POLICY)
    with pytest.raises(ValueError, match="outside 0..3"):
        risk.score({"data_sensitivity": -1}, POLICY)


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_the_controls_are_required_not_certified():
    # high requires an authorized_security_review and nothing here can decide
    # one happened. Claiming otherwise is the failure this exists to prevent.
    result = risk.score({k: 3 for k in POLICY["dimensions"]}, POLICY)
    assert result.to_dict()["controls_are_required_not_satisfied"] is True


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_the_band_boundaries_match_the_policy_exactly():
    thresholds = POLICY["score"]["thresholds"]
    assert risk.level_for(thresholds["low"]["maximum"], POLICY) == "low"
    assert risk.level_for(thresholds["medium"]["minimum"], POLICY) == "medium"
    assert risk.level_for(thresholds["medium"]["maximum"], POLICY) == "medium"
    assert risk.level_for(thresholds["high"]["minimum"], POLICY) == "high"


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_the_escalation_target_follows_a_renamed_policy():
    # Escalation goes to the band with the greatest minimum, not to the
    # literal string "high", so a renamed band does not silently escalate to
    # one that no longer exists.
    renamed = {
        "dimensions": {"a": 1},
        "score": {"per_dimension": {"minimum": 0, "maximum": 3},
                  "thresholds": {"calm": {"maximum": 2},
                                 "severe": {"minimum": 3}}},
        "overrides_to_high": ["boom"],
        "controls": {"calm": ["x"], "severe": ["y", "z"]},
    }
    assert risk.highest_band(renamed) == "severe"
    result = risk.score({"a": 0}, renamed, ["boom"])
    assert result.level == "severe"
    assert result.controls == ["y", "z"]


@pytest.mark.req("REQ-RISK-SCORING-001")
def test_a_total_no_band_covers_is_an_error_not_a_silent_low():
    gapped = {
        "dimensions": {"a": 1},
        "score": {"per_dimension": {"minimum": 0, "maximum": 3},
                  "thresholds": {"low": {"maximum": 0}, "high": {"minimum": 3}}},
        "controls": {"low": [], "high": []},
    }
    with pytest.raises(ValueError, match="falls in no band"):
        risk.score({"a": 1}, gapped)
