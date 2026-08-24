"""The acceptance registry is executable evidence, not a coverage claim."""
from __future__ import annotations

import copy

import pytest
import yaml

import validate_acceptance as acceptance


@pytest.fixture(scope="session")
def pytest_evidence():
    return acceptance.collect_pytest_evidence()


def changed_registry(tmp_path, change):
    data = copy.deepcopy(acceptance.load_yaml(acceptance.REGISTRY))
    change(data["scenarios"])
    path = tmp_path / "acceptance-scenarios.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def scenario(rows, name):
    return next(row for row in rows if row["name"] == name)


@pytest.mark.req("REQ-TOOLING-ACCEPTANCE-001")
def test_registry_is_consistent(pytest_evidence):
    result, data = acceptance.validate_registry(collected=pytest_evidence)
    assert result.errors == []
    assert len(data["scenarios"]) == 50


@pytest.mark.req("REQ-TOOLING-ACCEPTANCE-001")
def test_unknown_test_evidence_is_rejected(tmp_path, pytest_evidence):
    def change(rows):
        scenario(rows, "Official validation")["verified_by"][0] = \
            "tests/missing.py::test_not_collected"

    result, _ = acceptance.validate_registry(
        changed_registry(tmp_path, change), collected=pytest_evidence)
    assert any("is not a collected test" in error for error in result.errors)


@pytest.mark.req("REQ-TOOLING-ACCEPTANCE-001")
def test_missing_test_evidence_is_rejected(tmp_path, pytest_evidence):
    def change(rows):
        scenario(rows, "Official validation").pop("verified_by")

    result, _ = acceptance.validate_registry(
        changed_registry(tmp_path, change), collected=pytest_evidence)
    assert any("verified_by" in error and "required" in error for error in result.errors)


@pytest.mark.req("REQ-TOOLING-ACCEPTANCE-001")
def test_wording_evidence_is_rejected(tmp_path, pytest_evidence):
    def change(rows):
        scenario(rows, "Scoped exception expiry/ownership")["verified_by"] = [
            "tests/test_exception.py::test_the_scan_recommends_one_target_not_a_backlog"]

    result, _ = acceptance.validate_registry(
        changed_registry(tmp_path, change), collected=pytest_evidence)
    assert any("wording-marked" in error for error in result.errors)


@pytest.mark.req("REQ-TOOLING-ACCEPTANCE-001")
def test_blocked_metadata_is_required(tmp_path, pytest_evidence):
    def change(rows):
        # Any scenario still phase: blocked. Named rather than found by
        # scanning so the test says which case it is exercising; if this one
        # is ever delivered, point it at another blocked scenario.
        blocked = scenario(rows, "Split/merge/retire Story")
        blocked.pop("missing")
        blocked["tracked_by"] = 0

    result, _ = acceptance.validate_registry(
        changed_registry(tmp_path, change), collected=pytest_evidence)
    joined = "\n".join(result.errors)
    assert "missing" in joined
    assert "tracked_by" in joined


@pytest.mark.req("REQ-TOOLING-ACCEPTANCE-001")
def test_p12_gate_rejects_partial_and_absent_but_ignores_other_phases(
        pytest_evidence):
    result, _ = acceptance.validate_registry(phase="p12", collected=pytest_evidence)
    joined = "\n".join(result.errors)
    assert "Failed-outcome capture" in joined
    assert "Unapproved protected push" in joined
    assert "Unapproved MCP/plugin/skill" in joined
    assert "GitHub rate-limit handling" in joined
    assert "Invalid data source" in joined
    assert "Framework-only empty repo" not in joined
    assert "Data migration" not in joined
