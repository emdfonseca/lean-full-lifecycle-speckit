"""Triage decides what an item is, not when it will be done.

The tests are mostly about the boundary. A triage step that could reach Ready,
file an observation as work, or commit a priority would collapse three
decisions into one, and each collapse is a way a backlog stops meaning
anything.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from lib.inventory import ROOT, load_inventory

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(SCRIPTS))
gh_api = _load("github_api")
_load("capture")
tri = _load("triage")


class Repo:
    def __init__(self, issue, others=()):
        self.issue = issue
        self.others = list(others)

    def __call__(self, args, stdin):
        raw = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1])
        url, _, _q = raw.partition("?")
        if url.endswith("/issues"):
            return self._ok([self.issue, *self.others])
        if "/issues/" in url:
            number = int(url.rsplit("/", 1)[-1])
            found = self.issue if self.issue["number"] == number else None
            return self._ok(found or {})
        return self._ok({})

    @staticmethod
    def _ok(payload):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")


def issue(number=1, title="A thing", body="", labels=("story",)):
    return {"number": number, "title": title, "body": body, "state": "open",
            "labels": [{"name": l} for l in labels]}


def client(repo):
    return gh_api.GitHub(runner=repo, sleep=lambda _: None, max_attempts=1)


# --- the boundary -------------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-TRIAGE-001")
@pytest.mark.parametrize("target", ["Ready", "In Progress", "Output Done"])
def test_triage_cannot_target_anything_past_refining(target):
    with pytest.raises(gh_api.GitHubError) as exc:
        tri.check_target(target)
    assert "different authority" in str(exc.value)


@pytest.mark.req("REQ-BACKLOG-TRIAGE-001")
def test_refining_is_the_only_permitted_target():
    tri.check_target("Refining")          # does not raise
    with pytest.raises(gh_api.GitHubError):
        tri.check_target("Inbox")


@pytest.mark.req("REQ-BACKLOG-TRIAGE-001")
def test_the_proposed_transition_is_never_past_refining():
    repo = Repo(issue(body="Acceptance criteria: given a when b then c"))
    assessment = tri.assess(client(repo), "o/r", 1)
    assert assessment.proposed_transition == "Refining"


# --- observations -------------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-TRIAGE-001")
def test_an_observation_is_not_proposed_as_work():
    repo = Repo(issue(body="It feels slow sometimes.", labels=("bug",)))
    assessment = tri.assess(client(repo), "o/r", 1)
    assert assessment.is_observation
    assert assessment.proposed_transition is None
    assert "reproduction" in assessment.evidence_missing


@pytest.mark.req("REQ-BACKLOG-TRIAGE-001")
def test_an_untyped_item_cannot_be_assessed_against_a_contract():
    repo = Repo(issue(labels=()))
    assessment = tri.assess(client(repo), "o/r", 1)
    assert assessment.proposed_type is None
    assert assessment.evidence_missing == ["type"]
    assert assessment.proposed_transition is None


# --- duplicates ---------------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-TRIAGE-001")
def test_a_duplicate_stops_the_proposal():
    repo = Repo(issue(title="Author the triage workflow",
                      body="Acceptance criteria: given a when b then c"),
                others=[issue(2, "Author the triage workflow")])
    assessment = tri.assess(client(repo), "o/r", 1)
    assert [d["number"] for d in assessment.duplicates] == [2]
    assert assessment.proposed_transition is None


def test_an_item_is_not_its_own_duplicate():
    repo = Repo(issue(title="A distinctive title about provenance signing",
                      body="Acceptance criteria: given a when b then c"))
    assessment = tri.assess(client(repo), "o/r", 1)
    assert assessment.duplicates == []


def test_a_missing_issue_is_reported():
    repo = Repo(issue(number=99))
    with pytest.raises(gh_api.GitHubError):
        tri.assess(client(repo), "o/r", 1)


# --- what the record must say -------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-TRIAGE-001")
def test_the_record_states_that_priority_is_only_a_recommendation():
    # Stated rather than implied: a reader must not need to know the rules to
    # know no commitment was made.
    repo = Repo(issue(body="Acceptance criteria: given a when b then c"))
    record = tri.assess(client(repo), "o/r", 1).to_dict()
    assert record["priority_is_recommendation_only"] is True
    assert record["ready_not_reachable_by_triage"] is True


def test_the_record_serializes():
    repo = Repo(issue(body="Acceptance criteria: given a when b then c"))
    record = json.loads(json.dumps(tri.assess(client(repo), "o/r", 1).to_dict()))
    assert record["issue"] == 1


# --- the workflow -------------------------------------------------------------

@pytest.mark.req("REQ-BACKLOG-TRIAGE-001")
def test_the_workflow_only_ever_transitions_to_refining():
    wf = load_inventory().by_id("workflow", "lifecycle-triage")
    args = " ".join(str((s.get("input") or {}).get("args", ""))
                    for s in wf.manifest["steps"])
    assert "Refining" in args
    for forbidden in ("→ Ready", "→ In Progress", "→ Output Done"):
        assert forbidden not in args


def test_the_workflow_gates_before_any_write():
    wf = load_inventory().by_id("workflow", "lifecycle-triage")
    steps = wf.manifest["steps"]
    ids = [s["id"] for s in steps]
    writing = ids.index("transition-refining")
    assert any(s.get("type") == "gate" for s in steps[:writing])


# --- security findings --------------------------------------------------------
#
# #90 said a security finding is "a bug with no distinguishing field". A
# Severity field exists (github-schema.yml:47, applies_to: Bug). What was
# missing is the routing, not the field.

BUG_BODY = """**Reproduction**
x
**Expected**
y
**Actual**
z
**Regression test**
t"""


@pytest.mark.req("REQ-BACKLOG-SECURITY-001")
def test_a_security_bug_is_recognised_and_routed():
    repo = Repo(issue(labels=("bug", "security"), body=BUG_BODY))
    a = tri.assess(client(repo), "o/r", 1, policy_root=ROOT)
    assert a.is_security
    assert a.routing, "a security finding got no routing"
    assert {r["id"] for r in a.routing} >= {
        "severity_before_refining", "security_review_required",
        "no_public_reproduction"}


@pytest.mark.req("REQ-BACKLOG-SECURITY-001")
def test_an_ordinary_bug_gets_no_security_routing():
    repo = Repo(issue(labels=("bug",), body=BUG_BODY))
    a = tri.assess(client(repo), "o/r", 1, policy_root=ROOT)
    assert not a.is_security
    assert a.routing == []
    assert a.recommended_severity is None


@pytest.mark.req("REQ-BACKLOG-SECURITY-001")
def test_an_unclassified_security_finding_cannot_leave_triage():
    # Unclassified it is indistinguishable from an ordinary bug in every queue
    # that reads the board, which is the whole reason the routing exists.
    repo = Repo(issue(labels=("bug", "security"), body=BUG_BODY))
    a = tri.assess(client(repo), "o/r", 1, policy_root=ROOT)
    assert a.severity_missing
    assert a.proposed_transition is None


@pytest.mark.req("REQ-BACKLOG-SECURITY-001")
def test_a_classified_security_finding_may_be_proposed_for_refining():
    repo = Repo(issue(labels=("bug", "security"), body=BUG_BODY))
    a = tri.assess(client(repo), "o/r", 1, severity="High", policy_root=ROOT)
    assert not a.severity_missing
    assert a.proposed_transition == "Refining"


@pytest.mark.req("REQ-BACKLOG-SECURITY-001")
@pytest.mark.parametrize("wording,expected", [
    ("Remote code execution in the parser", "Critical"),
    ("Authentication bypass on the admin route", "Critical"),
    ("SQL injection in search", "High"),
    ("Stored XSS in comments", "High"),
    ("Open redirect on login", "Medium"),
])
def test_severity_is_recommended_from_the_wording(wording, expected):
    repo = Repo(issue(title=wording, labels=("bug", "security"), body=BUG_BODY))
    a = tri.assess(client(repo), "o/r", 1, policy_root=ROOT)
    assert a.recommended_severity == expected
    assert a.severity_reasoning


@pytest.mark.req("REQ-BACKLOG-SECURITY-001")
def test_nothing_recognisable_recommends_no_severity():
    # A default of "Medium" would be a number invented by a keyword scanner
    # and then read by a person as an assessment.
    repo = Repo(issue(title="Something is odd", labels=("bug", "security"),
                      body=BUG_BODY))
    a = tri.assess(client(repo), "o/r", 1, policy_root=ROOT)
    assert a.recommended_severity is None
    assert "security owner classifies it" in a.severity_reasoning


@pytest.mark.req("REQ-BACKLOG-SECURITY-001")
def test_the_recommendation_never_becomes_the_value():
    # Triage decides what an item is, never how bad it is. Same split it
    # already keeps for Priority.
    repo = Repo(issue(title="SQL injection in search",
                      labels=("bug", "security"), body=BUG_BODY))
    a = tri.assess(client(repo), "o/r", 1, policy_root=ROOT)
    assert a.recommended_severity == "High"
    assert a.severity is None, "triage set a severity it was only to recommend"
    assert a.to_dict()["severity_is_recommendation_only"] is True
    assert a.severity_missing, "a recommendation satisfied a required value"


@pytest.mark.req("REQ-BACKLOG-SECURITY-001")
def test_the_marker_comes_from_policy_not_from_this_script():
    import yaml
    policy = yaml.safe_load((ROOT / "policy/item-types.yml").read_text())
    rules = policy["security_findings"]
    assert rules["label"] == "security"
    assert rules["severity_required"] is True
    source = (SCRIPTS / "triage.py").read_text()
    assert 'get("label", "security")' in source, \
        "the label is read from policy with a fallback, not hardcoded"
