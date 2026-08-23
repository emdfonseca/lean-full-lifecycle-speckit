"""Production data, and what ends up in the evidence we write down.

Coverage used to be scattered across four policy files with the only
implemented redaction covering the adapter's audit trail. Nothing covered the
records the workflows write, which is where production data lands during a
brownfield adoption.

The fake credentials below are shaped like the real thing and are not real.
"""
from __future__ import annotations

import importlib.util
import sys

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
spec = importlib.util.spec_from_file_location("sensitive", SCRIPTS / "sensitive.py")
sd = importlib.util.module_from_spec(spec)
sys.modules["sensitive"] = sd
spec.loader.exec_module(sd)

POLICY = sd.load_policy(ROOT)
PATTERNS = sd.compile_patterns(ROOT)
MARKER = POLICY["redaction"]["marker"]
BROWNFIELD = load_yaml(
    ROOT / "bundle/components/workflows/lifecycle-brownfield-adoption/workflow.yml")

FAKE = "ghp_0123456789abcdefghijABCDEFGHIJ0123"
AUTH = {"authorized_by": "data_owner", "source": "production_database",
        "scope": "one query, billing table", "expires_at": "2026-09-01"}


# --- AC1: production data is denied by default --------------------------------

@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
@pytest.mark.parametrize("source", POLICY["production_data"]["denied_sources"])
def test_every_denied_source_is_refused_without_authorization(source):
    problems = sd.authorization_problems(source, None, POLICY)
    assert problems


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_the_refusal_cites_the_rule_rather_than_denying_generically():
    problems = sd.authorization_problems("production_database", None, POLICY)
    assert POLICY["production_data"]["rule_id"] in problems[0]
    assert "denied to the agent unless" in problems[0]


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_a_source_that_is_not_production_is_not_refused():
    # The rule has to permit what it does not cover, or it is a ban on reading.
    assert sd.authorization_problems("staging_database", None, POLICY) == []


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_a_complete_authorization_by_an_authority_permits_the_read():
    assert sd.authorization_problems("production_database", AUTH, POLICY) == []


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
@pytest.mark.parametrize(
    "missing", POLICY["production_data"]["authorization"]["required_fields"])
def test_an_incomplete_authorization_does_not_permit_it(missing):
    auth = {k: v for k, v in AUTH.items() if k != missing}
    problems = sd.authorization_problems("production_database", auth, POLICY)
    assert problems
    assert missing in problems[0]


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_authorization_by_someone_who_is_not_an_authority_is_refused():
    auth = dict(AUTH, authorized_by="the agent")
    problems = sd.authorization_problems("production_database", auth, POLICY)
    assert problems
    assert "not one of" in problems[0]


# --- AC2: a finding names the record and the field, never the value ----------

@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_a_credential_in_a_record_is_found():
    result = sd.scan({"notes": f"the runner uses {FAKE}"}, "discovery.md",
                     PATTERNS)
    assert not result.clean
    assert result.findings[0].field == "notes"
    assert result.findings[0].record == "discovery.md"


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_the_finding_never_repeats_the_value():
    # A report that quotes the secret has copied it somewhere new.
    result = sd.scan({"notes": FAKE}, "discovery.md", PATTERNS)
    rendered = str(result.findings[0]) + repr(result.to_dict())
    assert FAKE not in rendered
    assert "not repeated here" in str(result.findings[0])


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_a_nested_field_is_named_by_its_path():
    record = {"observations": [{"detail": FAKE}]}
    result = sd.scan(record, "discovery.md", PATTERNS)
    assert result.findings[0].field == "observations[0].detail"


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
@pytest.mark.parametrize("shape", [s["id"] for s in POLICY["credential_shapes"]])
def test_every_declared_shape_is_compiled(shape):
    assert shape in [name for name, _ in PATTERNS.shapes]


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
@pytest.mark.parametrize("value", [
    "AKIAIOSFODNN7EXAMPLE",
    "-----BEGIN RSA PRIVATE KEY-----",
    "postgres://user:hunter2@db.internal:5432/app",
    "password = hunter2",
])
def test_credential_shapes_are_caught(value):
    assert not sd.scan({"f": value}, "r.md", PATTERNS).clean


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_ordinary_prose_is_not_a_finding():
    record = {"summary": "The billing module reads a token from the environment.",
              "owner": "platform-team"}
    assert sd.scan(record, "r.md", PATTERNS).clean


# --- AC3: redaction is visible ------------------------------------------------

@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_redaction_leaves_a_visible_marker():
    out = sd.redact(f"token used: {FAKE}", PATTERNS)
    assert FAKE not in out
    assert MARKER in out


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_redaction_is_not_silent_removal():
    # Evidence that was silently cleaned reads as complete and is not.
    assert POLICY["redaction"]["visible"] is True
    assert sd.redact(FAKE, PATTERNS) != ""


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_an_already_redacted_field_is_not_reported_again():
    # Flagging the marker would report the fix as the fault.
    assert sd.scan({"f": f"token: {MARKER}"}, "r.md", PATTERNS).clean


# --- AC4: redaction is not authorization --------------------------------------

@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_redacting_does_not_authorize_the_read():
    assert POLICY["redaction"]["is_not_authorization"] is True
    # The authorization decision does not consult redaction at all: the read
    # already happened by the time anything could be redacted.
    problems = sd.authorization_problems("production_logs", None, POLICY)
    assert problems


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_the_authorization_check_takes_no_redaction_argument():
    import inspect as _inspect

    params = _inspect.signature(sd.authorization_problems).parameters
    assert "redact" not in params and "redacted" not in params, (
        "if redaction could influence this decision it would eventually be "
        "used to")


# --- AC5: the policy is one file and the code reads it ------------------------

@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_the_adapter_uses_the_same_pattern_list():
    # Two lists of what a credential looks like drift, and the copy that
    # drifts is the one nobody is testing.
    source = (SCRIPTS / "github_api.py").read_text(encoding="utf-8")
    assert "_SECRET_PATTERNS" not in source
    assert "sensitive.redact" in source


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_adding_a_shape_to_policy_changes_behaviour_without_editing_code(
        tmp_path):
    policy = dict(POLICY)
    policy["credential_shapes"] = POLICY["credential_shapes"] + [
        {"id": "internal_ticket", "pattern": r"INT-[0-9]{6}"}]
    root = tmp_path
    (root / "policy").mkdir()
    (root / "policy" / "sensitive-data.yml").write_text(
        sd.yaml.safe_dump(policy), encoding="utf-8")
    patterns = sd.compile_patterns(root)
    assert not sd.scan({"f": "INT-123456"}, "r.md", patterns).clean
    assert sd.scan({"f": "INT-123456"}, "r.md", PATTERNS).clean


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_a_fallback_says_so_rather_than_pretending(tmp_path):
    # Silently falling back would be the same mistake as an unreadable
    # repository reading as empty.
    patterns = sd.compile_patterns(tmp_path)
    assert patterns.from_policy is False
    assert sd.scan({"f": "x"}, "r.md", patterns).patterns_from_policy is False


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_the_fallback_still_catches_the_common_shape(tmp_path):
    assert not sd.scan({"f": FAKE}, "r.md", sd.compile_patterns(tmp_path)).clean


# --- wiring -------------------------------------------------------------------

@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_the_discovery_record_is_scanned_before_it_is_reviewed():
    ids = [s["id"] for s in BROWNFIELD["steps"]]
    assert ids.index("scan-evidence-for-sensitive-data") < \
        ids.index("review-discovery")


@pytest.mark.req("REQ-SECURITY-SENSITIVE-001")
def test_the_scan_step_forbids_quoting_the_value():
    step = [s for s in BROWNFIELD["steps"]
            if s["id"] == "scan-evidence-for-sensitive-data"][0]
    args = step["input"]["args"]
    assert "never the value" in args
    assert "patterns_from_policy is false" in args
