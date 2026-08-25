"""Production data, and what ends up in the evidence we write down.

Coverage used to be scattered across four policy files with the only
implemented redaction covering the adapter's audit trail. Nothing covered the
records the workflows write, which is where production data lands during a
brownfield adoption.

The fake credentials below are shaped like the real thing and are not real.
"""
from __future__ import annotations

import importlib.util
import json
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


# --- secret file paths --------------------------------------------------------
#
# `denied_sources` names six places production data lives and none of them is
# a file, so nothing here stopped a read of `.env`. These cover the half that
# was missing: the refusal at the path, before the read.

@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
@pytest.mark.parametrize("path", [
    ".env", "src/.env", "/a/b/.env.local", "config/secrets.pem",
    ".ssh/id_rsa", "/home/me/.ssh/anything/at/all", ".netrc",
    ".aws/credentials", "deep/.kube/config", "vault.kdbx",
])
def test_a_secret_path_is_refused(path):
    refusals = sd.path_problems(path, POLICY)
    assert refusals, f"{path} was not refused"
    assert "SENSITIVE-PATH-001" in refusals[0]


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
@pytest.mark.parametrize("path", [
    "src/app.py", "README.md", "notes/id_generator.py",
    "environments.md", "docs/env.md", "tests/test_env.py",
])
def test_an_ordinary_path_is_not_refused(path):
    # A deny rule wide enough to catch working files gets switched off, and
    # then it protects nothing at all.
    assert sd.path_problems(path, POLICY) == []


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_the_refusal_names_the_pattern_that_matched():
    # "Denied" without a reason is a refusal an author disables.
    refusal = sd.path_problems(".env", POLICY)[0]
    assert "'dotenv'" in refusal
    assert "**/.env" in refusal


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_every_denied_path_glob_is_expressible():
    # The guard that matters. `**/id_{rsa,ed25519}` is a glob pathlib does not
    # expand, so it would sit in the policy matching nothing while reporting
    # itself as present -- the exact defect this requirement is about.
    for entry in sd.denied_path_patterns(POLICY):
        glob = entry["glob"]
        assert "{" not in glob and "[" not in glob, (
            f"{entry['id']}: brace or class alternation is not translated; "
            f"split it into separate patterns")
        sample = glob.replace("**/", "x/").replace("*", "y")
        assert sd.glob_to_regex(glob).match(sample), (
            f"{entry['id']}: {glob} matches nothing, not even {sample}")


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_a_star_does_not_cross_a_directory_separator():
    # fnmatch's `*` would, which makes a rule broader than it reads.
    assert sd.glob_to_regex("**/*.pem").match("a/b/key.pem")
    assert not sd.glob_to_regex("secrets/*.pem").match("secrets/nested/key.pem")


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_a_policy_without_denied_paths_refuses_nothing_and_says_so():
    # An older preset gets no rules rather than an exception. It also gets no
    # protection, which the report states rather than hiding.
    assert sd.path_problems(".env", {"production_data": {}}) == []
    assert sd.denied_path_patterns({}) == []


# --- redaction as a reachable command -----------------------------------------

@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_redacting_a_record_clears_its_findings(tmp_path):
    record = tmp_path / "evidence.yml"
    record.write_text(
        "note: adoption evidence\n"
        f"token: {FAKE}\n"
        "connection: \"postgres://svc:pw@db.internal:5432/app\"\n",
        encoding="utf-8")
    before = sd.scan(load_yaml(record), record.name)
    assert not before.clean

    cleaned = sd.redact(record.read_text(encoding="utf-8"))
    after = sd.scan(sd.yaml.safe_load(cleaned), record.name)
    assert after.clean
    assert sd.compile_patterns().marker in cleaned


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_redaction_leaves_a_visible_marker(tmp_path):
    # A silent redaction leaves evidence that reads as complete and is not.
    cleaned = sd.redact(f"token: {FAKE}\n")
    assert "[redacted]" in cleaned
    assert FAKE not in cleaned


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_the_workflow_redacts_after_scanning_and_before_review():
    ids = [s["id"] for s in BROWNFIELD["steps"]]
    assert ids.index("scan-evidence-for-sensitive-data") < \
        ids.index("redact-evidence-before-review") < \
        ids.index("review-discovery")


@pytest.mark.req("REQ-SECURITY-SENSITIVE-002")
def test_the_redact_step_does_not_treat_redaction_as_authorization():
    step = [s for s in BROWNFIELD["steps"]
            if s["id"] == "redact-evidence-before-review"][0]
    args = step["input"]["args"]
    assert "not authorization" in args
    assert "findings_after" in args


# --- a record is scanned as what it is ----------------------------------------

MD_RECORD = (
    "# Discovery\n"
    "\n"
    "Scan run: `scan` mode, read-only.\n"
    "\n"
    f"Token found: {FAKE}\n"
)


@pytest.mark.req("REQ-SECURITY-SENSITIVE-003")
def test_a_markdown_record_is_scanned_rather_than_parsed_as_yaml():
    result = sd.scan_record(MD_RECORD, "discovery.md", PATTERNS)
    assert not result.clean
    assert [f.field for f in result.findings] == ["line 5"]


@pytest.mark.req("REQ-SECURITY-SENSITIVE-003")
def test_a_secret_in_a_markdown_heading_is_not_reported_clean():
    # YAML reads `#` as a comment, so parsing this record discarded the line
    # holding the token and certified it clean.
    record = f"# Token found: {FAKE}\n\nEverything else is fine.\n"
    result = sd.scan_record(record, "discovery.md", PATTERNS)
    assert not result.clean
    assert [f.field for f in result.findings] == ["line 1"]


@pytest.mark.req("REQ-SECURITY-SENSITIVE-003")
def test_a_finding_in_a_markdown_record_still_never_names_the_value():
    result = sd.scan_record(MD_RECORD, "discovery.md", PATTERNS)
    assert FAKE not in str(result.findings[0])
    assert FAKE not in json.dumps(result.to_dict())


@pytest.mark.req("REQ-SECURITY-SENSITIVE-003")
def test_a_yaml_record_still_reports_the_field_path():
    result = sd.scan_record(f"discovery:\n  token: {FAKE}\n", "d.yml", PATTERNS)
    assert [f.field for f in result.findings] == ["discovery.token"]


@pytest.mark.req("REQ-SECURITY-SENSITIVE-003")
def test_a_yaml_record_that_does_not_parse_is_scanned_as_text_not_skipped():
    # Refusing to scan is safer than certifying an unscanned record clean.
    result = sd.scan_record(f"key: [unclosed\ntoken: {FAKE}\n", "d.yml", PATTERNS)
    assert not result.clean


@pytest.mark.req("REQ-SECURITY-SENSITIVE-003")
def test_redaction_clears_a_markdown_finding_on_the_rescan():
    cleaned = sd.redact(MD_RECORD, PATTERNS)
    assert sd.scan_record(cleaned, "discovery.md", PATTERNS).clean


@pytest.mark.req("REQ-SECURITY-SENSITIVE-003")
def test_an_already_redacted_markdown_line_is_not_reported_again():
    record = f"Token found: {MARKER}\n"
    assert sd.scan_record(record, "discovery.md", PATTERNS).clean
