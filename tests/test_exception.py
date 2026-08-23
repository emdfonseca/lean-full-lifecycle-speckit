"""The exception policy, finally read by something.

`exception-policy.yml` has named ten required fields and four forbidden shapes
since 0.1.0 and no code has ever looked at it. An unenforced exception policy is
worse than none: it is a document teams cite while doing the opposite.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
spec = importlib.util.spec_from_file_location("exception", SCRIPTS / "exception.py")
ex = importlib.util.module_from_spec(spec)
sys.modules["exception"] = ex
spec.loader.exec_module(ex)

POLICY = ex.load_policy(ROOT)
TODAY = date(2026, 8, 23)
BROWNFIELD = load_yaml(
    ROOT / "bundle/components/workflows/lifecycle-brownfield-adoption/workflow.yml")


def record(**over):
    base = {
        "id": "EX-001",
        "scope": "src/legacy/parser/**",
        "policy_rule": "lint.no-bare-except",
        "reason": "The parser predates the rule; rewriting needs the grammar work.",
        "owner": "platform-team",
        "approver": "emdfonseca",
        "created_at": "2026-08-01",
        "review_or_expiry_at": "2026-12-01",
        "compensating_controls": ["characterization tests"],
        "disposition": "active",
        "baseline": "41 occurrences at commit b700f30",
    }
    base.update(over)
    return base


def check(rec, as_of=TODAY):
    return ex.validate(rec, POLICY, as_of)


def test_a_well_formed_exception_is_accepted():
    result = check(record())
    assert result.accepted, result.refusals
    assert result.suppresses_rule


# --- AC2: required fields -----------------------------------------------------

@pytest.mark.req("REQ-CORE-EXCEPTION-001")
@pytest.mark.parametrize("missing", ["owner", "approver", "review_or_expiry_at",
                                     "compensating_controls", "policy_rule"])
def test_a_missing_required_field_is_refused_by_name(missing):
    rec = {k: v for k, v in record().items() if k != missing}
    result = check(rec)
    assert not result.accepted
    assert any(missing in r for r in result.refusals), result.refusals


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
@pytest.mark.parametrize("placeholder", ["", "  ", "n/a", "TBD", "none", "team"])
def test_a_placeholder_owner_is_not_an_owner(placeholder):
    # Present but empty is absent. This is how an exception survives with
    # nobody to answer for it.
    result = check(record(owner=placeholder))
    assert not result.accepted
    assert any("owner" in r for r in result.refusals)


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_every_required_field_in_policy_is_checked():
    for name in POLICY["required"]:
        rec = {k: v for k, v in record().items() if k != name}
        assert not check(rec).accepted, f"{name} is required but unchecked"


# --- AC3: blanket, whatever its wording ---------------------------------------

@pytest.mark.req("REQ-CORE-EXCEPTION-001")
@pytest.mark.parametrize("scope", ["*", "**", ".", "all", "everything", "./**"])
def test_a_whole_repository_scope_is_refused(scope):
    result = check(record(scope=scope))
    assert not result.accepted
    assert any("no particular thing" in r for r in result.refusals)


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
@pytest.mark.parametrize("scope", ["legacy/**", "src/*", "app/**/*.py"])
def test_a_tree_too_near_the_root_is_refused(scope):
    assert not check(record(scope=scope)).accepted


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
@pytest.mark.parametrize("scope", ["src/legacy/parser/**", "app/billing/tax/*.py"])
def test_a_scope_that_names_a_place_is_accepted(scope):
    # The rule has to permit the case it exists to distinguish from, or it is
    # just a ban on globs.
    assert check(record(scope=scope)).accepted


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
@pytest.mark.parametrize("rule", ["*", "all", "any", "ALL"])
def test_an_exception_to_a_family_of_rules_is_refused(rule):
    result = check(record(policy_rule=rule))
    assert not result.accepted
    assert any("policy change" in r for r in result.refusals)


# --- AC4: expiry --------------------------------------------------------------

@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_an_exception_past_its_review_date_is_reported_expired():
    result = check(record(review_or_expiry_at="2026-01-01"))
    assert result.expired


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_an_expired_exception_stops_suppressing_its_rule():
    result = check(record(review_or_expiry_at="2026-01-01"))
    assert result.suppresses_rule is False


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_an_expired_exception_is_reported_not_deleted():
    # Deleting it loses what was accepted and by whom.
    result = check(record(review_or_expiry_at="2026-01-01"))
    assert result.accepted, "expiry is a status, not a malformed record"
    assert any("not deleted" in n for n in result.notes)


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_an_exception_reviewed_today_has_not_expired():
    assert check(record(review_or_expiry_at=TODAY.isoformat())).expired is False


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_a_non_date_review_field_is_refused_rather_than_ignored():
    result = check(record(review_or_expiry_at="when we get to it"))
    assert not result.accepted


# --- AC5: permanence ----------------------------------------------------------

@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_a_permanent_exception_without_an_approver_is_refused():
    result = check(record(disposition="accepted_permanently_by_authority",
                          approver=""))
    assert not result.accepted
    assert any("permanent exception must name" in r for r in result.refusals)


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_a_permanent_exception_with_an_approver_is_accepted():
    result = check(record(disposition="accepted_permanently_by_authority"))
    assert result.accepted, result.refusals


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_a_permanent_exception_does_not_suppress_by_virtue_of_permanence():
    # Only `active` suppresses. Permanence records a decision; it is not a
    # standing licence the gate reads.
    result = check(record(disposition="accepted_permanently_by_authority"))
    assert result.suppresses_rule is False


# --- hiding new violations ----------------------------------------------------

@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_a_glob_scope_without_a_baseline_is_refused():
    rec = {k: v for k, v in record().items() if k != "baseline"}
    result = check(rec)
    assert not result.accepted
    assert any("widens on every commit" in r for r in result.refusals)


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_an_exact_path_needs_no_baseline():
    rec = {k: v for k, v in record().items() if k != "baseline"}
    rec["scope"] = "src/legacy/parser/grammar.py"
    assert check(rec).accepted


# --- AC1: a scan reads --------------------------------------------------------

def scan_branch():
    step = [s for s in BROWNFIELD["steps"] if s["id"] == "scoped-discovery"][0]
    return step["cases"]["scan"]


@pytest.mark.req("REQ-CORE-BROWNFIELD-001")
def test_the_scan_mode_is_declared_rather_than_implied():
    # It used to be an empty `target`. An implied mode is how a scan quietly
    # becomes a modification.
    mode = BROWNFIELD["inputs"]["scope_mode"]
    assert mode["enum"] == ["scan", "targeted"]
    assert mode["default"] == "scan"


@pytest.mark.req("REQ-CORE-BROWNFIELD-001")
def test_the_scan_branch_writes_only_under_specify():
    import re

    written = []
    for step in scan_branch():
        written += re.findall(r"(?<![\w./])[\w./-]+\.md\b", step.get("prompt", ""))
    assert written
    for path in written:
        assert path.startswith(".specify/"), path


@pytest.mark.req("REQ-CORE-BROWNFIELD-001")
@pytest.mark.wording
def test_the_scan_branch_names_the_small_changes_that_are_still_changes():
    joined = " ".join(s.get("prompt", "") for s in scan_branch())
    for temptation in ("formatting", "lint fix", "dependency bump"):
        assert temptation in joined, temptation


@pytest.mark.req("REQ-CORE-BROWNFIELD-001")
@pytest.mark.wording
def test_the_scan_reports_what_it_wrote_and_stops_on_a_stray_file():
    joined = " ".join(s.get("prompt", "") for s in scan_branch())
    assert "read-only" in joined
    assert "say which and stop" in joined


@pytest.mark.req("REQ-CORE-BROWNFIELD-001")
@pytest.mark.wording
def test_the_scan_recommends_one_target_not_a_backlog():
    joined = " ".join(s.get("prompt", "") for s in scan_branch())
    assert "modernization backlog" in joined


@pytest.mark.req("REQ-CORE-BROWNFIELD-001")
def test_only_the_targeted_branch_validates_exceptions():
    step = [s for s in BROWNFIELD["steps"] if s["id"] == "scoped-discovery"][0]
    scan_cmds = [s.get("command") for s in step["cases"]["scan"]]
    targeted = [s.get("command") for s in step["cases"]["targeted"]]
    assert "speckit.github-lifecycle.exception" in targeted
    assert set(scan_cmds) == {None}, "a scan runs no command that could write"


# --- policy is the source -----------------------------------------------------

@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_the_forbidden_shapes_all_have_a_detector():
    for shape in POLICY["forbidden"]:
        assert shape in POLICY["detection"], (
            f"{shape} is forbidden by policy and nothing detects it")


@pytest.mark.req("REQ-CORE-EXCEPTION-001")
def test_the_placeholders_are_not_hardcoded_in_the_script():
    source = (SCRIPTS / "exception.py").read_text(encoding="utf-8")
    for value in ("tbd", "n/a"):
        assert f'"{value}"' not in source, f"{value} is hardcoded"
