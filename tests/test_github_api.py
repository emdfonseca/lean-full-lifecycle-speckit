"""The GitHub adapter, exercised entirely offline.

Every test injects a runner, so nothing here touches the network or needs
credentials. The properties under test are the ones `gh` has no opinion about:
which failures a caller can branch on, what is safe to retry, whether a
mutation can be applied twice, and whether a secret can reach the audit log.

The tests live here rather than inside the extension because the extension
directory is packaged verbatim into the published artifact.
"""
from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
import sys
import subprocess
from pathlib import Path

import pytest

from lib.inventory import ROOT

_MODULE = (ROOT / "bundle/components/extensions/github-lifecycle/scripts/github_api.py")
_spec = importlib.util.spec_from_file_location("github_api", _MODULE)
gh_api = importlib.util.module_from_spec(_spec)
# Register before executing: @dataclass resolves annotations through
# sys.modules[cls.__module__], which is absent for a module loaded by path.
sys.modules["github_api"] = gh_api
_spec.loader.exec_module(gh_api)


def fake(stdout: str = "", stderr: str = "", returncode: int = 0):
    """A runner that always answers the same way, recording what it was asked."""
    calls: list[list[str]] = []

    def runner(args, stdin):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def scripted(*responses):
    """A runner that answers differently on each successive call."""
    seq = list(responses)
    calls: list[list[str]] = []

    def runner(args, stdin):
        calls.append(list(args))
        rc, out, err = seq[min(len(calls) - 1, len(seq) - 1)]
        return subprocess.CompletedProcess(args, rc, out, err)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def client(runner, **kw):
    kw.setdefault("sleep", lambda _: None)
    return gh_api.GitHub(runner=runner, **kw)


# --- error classification -----------------------------------------------------

@pytest.mark.parametrize("stderr,expected", [
    ("gh: Not Found (HTTP 404)", gh_api.NotFound),
    ("HTTP 403: Resource not accessible", gh_api.Forbidden),
    ("Bad credentials", gh_api.Forbidden),
    ("You have exceeded a secondary rate limit", gh_api.RateLimited),
    ("API rate limit exceeded", gh_api.RateLimited),
    ("HTTP 409: already exists", gh_api.Conflict),
    ("HTTP 500: internal error", gh_api.TransportError),
])
@pytest.mark.req("REQ-GITHUB-ADAPTER-001")
def test_failures_are_classified_not_stringly_typed(stderr, expected):
    c = client(fake(stderr=stderr, returncode=1), max_attempts=1)
    with pytest.raises(expected):
        c.rest("GET", "repos/o/r/issues/1")


def test_rate_limit_carries_a_retry_delay():
    c = client(fake(stderr="secondary rate limit; retry after 30", returncode=1), max_attempts=1)
    with pytest.raises(gh_api.RateLimited) as exc:
        c.rest("GET", "x")
    assert exc.value.retry_after == 30.0


# --- retry policy -------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-ADAPTER-001")
def test_reads_retry_until_they_succeed():
    runner = scripted((1, "", "HTTP 500"), (1, "", "HTTP 500"), (0, '{"ok":true}', ""))
    assert client(runner).rest("GET", "x") == {"ok": True}
    assert len(runner.calls) == 3


@pytest.mark.req("REQ-GITHUB-ADAPTER-001")
def test_a_mutation_without_an_operation_id_is_never_retried():
    # A timeout that actually succeeded would otherwise be applied twice.
    runner = scripted((1, "", "HTTP 500"), (0, '{"ok":true}', ""))
    with pytest.raises(gh_api.TransportError):
        client(runner).rest("POST", "x", body={})
    assert len(runner.calls) == 1


@pytest.mark.req("REQ-GITHUB-ADAPTER-001")
def test_a_mutation_with_an_operation_id_may_retry():
    runner = scripted((1, "", "HTTP 500"), (0, '{"ok":true}', ""))
    assert client(runner).rest("POST", "x", body={}, operation_id="op-1") == {"ok": True}
    assert len(runner.calls) == 2


def test_not_found_is_not_retried():
    runner = scripted((1, "", "Not Found"))
    with pytest.raises(gh_api.NotFound):
        client(runner).rest("GET", "x")
    assert len(runner.calls) == 1


# --- idempotency --------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-ADAPTER-001")
def test_the_same_operation_id_is_not_applied_twice():
    runner = fake('{"ok":true}')
    c = client(runner)
    c.rest("POST", "x", body={}, operation_id="op-1")
    c.rest("POST", "x", body={}, operation_id="op-1")
    assert len(runner.calls) == 1
    assert c.audit[-1].outcome == "skipped-already-applied"


def test_a_failed_mutation_does_not_count_as_applied():
    runner = scripted((1, "", "Not Found"), (0, '{"ok":true}', ""))
    c = client(runner)
    with pytest.raises(gh_api.NotFound):
        c.rest("POST", "x", body={}, operation_id="op-1")
    c.rest("POST", "x", body={}, operation_id="op-1")
    assert len(runner.calls) == 2


# --- dry run ------------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-ADAPTER-001")
def test_dry_run_performs_no_mutation_but_reports_it():
    runner = fake('{"ok":true}')
    c = client(runner, dry_run=True)
    assert c.rest("POST", "x", body={"a": 1}) is None
    assert runner.calls == []
    assert c.audit[-1].outcome == "dry-run"
    assert "gh api" in c.audit[-1].detail


def test_dry_run_still_permits_reads():
    runner = fake('{"ok":true}')
    assert client(runner, dry_run=True).rest("GET", "x") == {"ok": True}
    assert len(runner.calls) == 1


# --- graphql ------------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-ADAPTER-001")
def test_graphql_errors_in_a_200_body_are_raised():
    # gh exits 0 for these; treating them as success is the trap.
    body = json.dumps({"data": None, "errors": [{"message": "Could not resolve to a node"}]})
    with pytest.raises(gh_api.GitHubError):
        client(fake(body), max_attempts=1).graphql("query Q { viewer { login } }")


def test_graphql_success_returns_the_payload():
    body = json.dumps({"data": {"viewer": {"login": "octocat"}}})
    assert client(fake(body)).graphql("query Q { viewer { login } }")["data"]["viewer"]["login"] == "octocat"


def test_graphql_operation_name_is_audited():
    c = client(fake('{"data":{}}'))
    c.graphql("mutation AddSubIssue($p:ID!){ addSubIssue(input:{}) { issue { number } } }")
    assert c.audit[-1].target == "AddSubIssue"


# --- audit and redaction ------------------------------------------------------

@pytest.mark.req("REQ-SECURITY-AUDIT-001")
@pytest.mark.parametrize("secret", [
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "github_pat_11ABCDEFG0123456789_abcdefghij",
    "Authorization: Bearer sk-live-abcdef",
])
@pytest.mark.parametrize("route", ["stderr", "path"])
def test_secrets_never_reach_the_audit_log(secret, route, tmp_path):
    # Parametrised over the route as well as the shape. Testing only stderr let
    # `operation` ship unredacted while `target`, built from the same path
    # string, was masked beside it.
    path = tmp_path / "audit.jsonl"
    stderr = f"failed: {secret}" if route == "stderr" else "failed"
    endpoint = "x" if route == "stderr" else f"x?token={secret}"
    c = client(fake(stderr=stderr, returncode=1), max_attempts=1, audit_path=path)
    with pytest.raises(gh_api.GitHubError):
        c.rest("GET", endpoint)
    written = path.read_text(encoding="utf-8")
    assert secret not in written
    assert "[redacted]" in written


@pytest.mark.req("REQ-SECURITY-AUDIT-001")
@pytest.mark.parametrize("field", ["operation", "target", "detail"])
def test_every_free_text_audit_field_is_redacted(field):
    # One case per field that carries caller-supplied text, so removing any
    # single redact() call fails a test rather than none.
    secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    record = gh_api.AuditRecord(
        operation="GET x", target="x", outcome="failed", attempts=1,
        dry_run=False, operation_id="op-1", detail="")
    written = json.loads(replace(record, **{field: f"carrying {secret}"}).to_json())
    assert secret not in json.dumps(written)
    assert "[redacted]" in written[field]


@pytest.mark.req("REQ-SECURITY-AUDIT-001")
def test_the_exception_message_is_redacted_too():
    secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    c = client(fake(stderr=f"boom {secret}", returncode=1), max_attempts=1)
    with pytest.raises(gh_api.GitHubError) as exc:
        c.rest("GET", "x")
    assert secret not in str(exc.value)


@pytest.mark.req("REQ-SECURITY-AUDIT-001")
def test_every_call_is_audited(tmp_path):
    path = tmp_path / "audit.jsonl"
    c = client(fake('{"ok":true}'), audit_path=path)
    c.rest("GET", "a")
    c.rest("POST", "b", body={}, operation_id="op")
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [x["outcome"] for x in lines] == ["ok", "ok"]
    assert lines[1]["operation_id"] == "op"


# --- shape --------------------------------------------------------------------

@pytest.mark.parametrize("stdout,expected", [
    ('{"a":1}', {"a": 1}),
    ("User", "User"),                      # --jq can emit a bare scalar
    ("42", 42),
    ('{"a":1}\n{"b":2}', [{"a": 1}, {"b": 2}]),   # --paginate: one doc per page
    ("", None),
    # --jq can emit multi-line text, such as an issue body. Splitting it into
    # lines turned a string into a list and corrupted every consumer of it.
    ("## Acceptance\n\nGiven a thing\nWhen acted on\nThen observed",
     "## Acceptance\n\nGiven a thing\nWhen acted on\nThen observed"),
    ("line one\nline two", "line one\nline two"),
])
def test_output_parsing_survives_what_gh_actually_emits(stdout, expected):
    assert client(fake(stdout)).rest("GET", "x") == expected


def test_pagination_is_delegated_to_gh():
    runner = fake("[]")
    client(runner).rest("GET", "repos/o/r/issues", paginate=True)
    assert "--paginate" in runner.calls[0]


def test_the_adapter_owns_no_http_client():
    # The drift test from #34: if this grows a client or its own auth, it has
    # stopped being an adapter.
    source = _MODULE.read_text(encoding="utf-8")
    for forbidden in ("import requests", "import httpx", "urllib.request",
                      "http.client", "Authorization:"):
        assert forbidden not in source, f"adapter should not contain {forbidden!r}"
