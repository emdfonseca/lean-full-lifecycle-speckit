"""Reading and writing field values, offline.

The fake is stateful: a PATCH changes what a subsequent GET returns. A
stateless mock would let read-after-write pass without the write having
happened, which is the failure read-back exists to catch.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(SCRIPTS))
gh_api = _load("github_api")
it = _load("inspect_target")
fb = _load("field_backend")

STATES = list(it.DELIVERY_STATES)
# Opaque, as GitHub's really are: "2fde52c1", not "opt_In Progress".
OPT = {s: f"{i + 1:08x}" for i, s in enumerate(STATES)}


class FakeBoard:
    """A project board that remembers writes."""

    def __init__(self, items=None, fields=None):
        # issue number -> item id
        self.items = items if items is not None else {36: 900, 37: 901}
        self.fields = fields or {
            "403": {"name": "Status", "options": dict(OPT)},
            "404": {"name": "Capability", "options": {}},
        }
        # item id -> {field id -> stored value}
        self.values: dict[int, dict[str, object]] = {i: {} for i in self.items.values()}
        # The real POST takes the issue's id, not its number. A fake keyed on
        # number would let a caller pass the wrong one and still pass here.
        self.issue_ids = {36: 3600, 37: 3700, 42: 4200}
        self.next_item = 950
        self.calls: list[list[str]] = []

    def __call__(self, args, stdin):
        self.calls.append(list(args))
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        url = args[args.index("--method") + 2] if "--method" in args else args[args.index("api") + 1]
        url, _, query = url.partition("?")
        requested = None
        if query.startswith("fields="):
            requested = {q for q in query[len("fields="):].split(",") if q}

        if url.endswith("/items") and method == "POST":
            body = json.loads(stdin or "{}")
            if body.get("type") != "Issue" or "id" not in body:
                return self._err("gh: Validation Failed (HTTP 422)")
            number = next((n for n, i in self.issue_ids.items()
                           if i == int(body["id"])), None)
            if number is None:
                return self._err("gh: Not Found (HTTP 404)")
            item = self.next_item
            self.next_item += 1
            self.items[number] = item
            self.values[item] = {}
            return self._ok({"id": item, "content": {"number": number}})

        if url.endswith("/items"):
            rows = [{"id": iid, "content": {"number": num}}
                    for num, iid in self.items.items()]
            return self._ok(rows)

        if "/items/" in url:
            item = int(url.rsplit("/", 1)[-1])
            if item not in self.values:
                return self._err("gh: Not Found (HTTP 404)")
            if method == "GET" and requested is None:
                # A bare GET carries the content. This is what a placement
                # reads back, and the listing lags behind a fresh POST.
                number = next((n for n, i in self.items.items() if i == item),
                              None)
                return self._ok({"id": item, "content": {"number": number},
                                 "content_type": "Issue"})
            if method == "PATCH":
                body = json.loads(stdin or "{}")
                for entry in body.get("fields", []):
                    self.values[item][str(entry["id"])] = entry["value"]
                return self._ok({"id": item, "fields": self._render(item)})
            # A GET returns only the fields asked for. The real API returns
            # Title alone when none are named; a fake that returned everything
            # let read-after-write pass here and fail against GitHub.
            return self._ok({"id": item, "fields": self._render(item, requested)})

        return self._err("gh: Not Found (HTTP 404)")

    def _render(self, item, requested=None):
        out = []
        for fid, stored in self.values[item].items():
            if requested is not None and fid not in requested:
                continue
            spec = self.fields.get(fid, {})
            if stored is None:
                out.append({"id": int(fid), "name": spec.get("name"), "value": None})
            elif spec.get("options"):
                name = next((n for n, o in spec["options"].items() if o == stored), None)
                out.append({"id": int(fid), "name": spec.get("name"),
                            "value": {"id": stored, "name": {"raw": name}}})
            else:
                out.append({"id": int(fid), "name": spec.get("name"),
                            "value": {"raw": stored}})
        return out

    @staticmethod
    def _ok(payload):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    @staticmethod
    def _err(stderr):
        return subprocess.CompletedProcess([], 1, "", stderr)


def inspection(**over):
    base = dict(
        owner="acme", repo="widgets", owner_type="User",
        backend=it.BACKEND_PROJECT, issue_fields_available=False,
        issue_types_available=False, sub_issues_available=True,
        dependencies_available=True, project_number=3,
        fields={
            "Status": it.FieldRef("Status", "403", "single_select",
                                  options=dict(OPT)),
            "Capability": it.FieldRef("Capability", "404", "text"),
        },
        roles={"delivery_state": "Status", "capability": "Capability"},
    )
    base.update(over)
    return it.Inspection(**base)


def backend(board=None, insp=None):
    board = board or FakeBoard()
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    return fb.ProjectFieldBackend(gh, insp or inspection()), board


# --- reading ------------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-FIELDS-001")
def test_an_unset_field_reads_as_none():
    be, _ = backend()
    assert be.read(36, "delivery_state").value is None


@pytest.mark.req("REQ-GITHUB-FIELDS-001")
def test_a_written_value_reads_back_by_name():
    be, _ = backend()
    be.write(36, "delivery_state", "Ready")
    got = be.read(36, "delivery_state")
    assert got.value == "Ready"
    assert got.field_name == "Status"


def test_a_text_field_round_trips():
    be, _ = backend()
    assert be.write(36, "capability", "billing").value == "billing"


def test_an_issue_not_on_the_board_is_reported():
    be, _ = backend()
    with pytest.raises(gh_api.NotFound) as exc:
        be.read(99, "delivery_state")
    assert "#99" in str(exc.value)


def test_an_unknown_role_is_reported():
    be, _ = backend()
    with pytest.raises(gh_api.NotFound):
        be.read(36, "severity")


# --- writing by id, not name --------------------------------------------------

@pytest.mark.req("REQ-GITHUB-FIELDS-001")
def test_writes_send_an_option_id_not_a_display_name():
    be, board = backend()
    be.write(36, "delivery_state", "In Progress")
    # gh receives the body on stdin, so the assertion is on what the board
    # stored: an option id, never the display name.
    assert board.values[900]["403"] == OPT["In Progress"]
    assert "In Progress" not in str(list(board.values[900].values()))


def test_an_unknown_option_is_refused_before_any_write():
    be, board = backend()
    with pytest.raises(gh_api.NotFound):
        be.write(36, "delivery_state", "Shipped")
    assert not any("PATCH" in c for c in board.calls)


# --- read-back ----------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-READBACK-001")
def test_a_write_that_does_not_stick_raises_conflict():
    board = FakeBoard()
    original = board.__call__

    def sabotage(args, stdin):
        result = original(args, stdin)
        if "--method" in args and args[args.index("--method") + 1] == "PATCH":
            board.values[900].clear()      # accepted, then silently discarded
        return result

    be, _ = backend(board=type("B", (), {"__call__": staticmethod(sabotage),
                                         "calls": board.calls})())
    with pytest.raises(gh_api.Conflict) as exc:
        be.write(36, "delivery_state", "Ready")
    assert "read-back mismatch" in str(exc.value)


@pytest.mark.req("REQ-GITHUB-READBACK-001")
def test_write_returns_the_value_it_verified():
    be, _ = backend()
    assert be.write(36, "delivery_state", "Output Done").value == "Output Done"


# --- never labels -------------------------------------------------------------

@pytest.mark.req("REQ-GITHUB-FIELDS-001")
def test_no_operation_ever_touches_labels():
    # allow_status_labels is false; a label is not an auditable field value.
    be, board = backend()
    be.write(36, "delivery_state", "Ready")
    be.read(36, "delivery_state")
    assert not any("label" in " ".join(c).lower() for c in board.calls)


# --- selection ----------------------------------------------------------------

def test_an_unusable_inspection_is_refused():
    bad = inspection(roles={}, missing_roles=["delivery_state"])
    with pytest.raises(ValueError):
        fb.for_inspection(gh_api.GitHub(runner=FakeBoard()), bad)


def test_a_project_backend_requires_a_selected_project():
    with pytest.raises(ValueError):
        fb.ProjectFieldBackend(gh_api.GitHub(runner=FakeBoard()),
                               inspection(project_number=None))


def test_org_owner_uses_the_orgs_route():
    be, board = backend(insp=inspection(owner_type="Organization"))
    be.read(36, "delivery_state")
    assert any("orgs/acme/projectsV2/3" in " ".join(c) for c in board.calls)


# --- idempotency semantics ----------------------------------------------------

@pytest.mark.req("REQ-GITHUB-FIELDS-001")
def test_replaying_an_operation_id_does_not_write_again():
    be, board = backend()
    be.write(36, "delivery_state", "Ready", operation_id="op-1")
    patches = sum(1 for c in board.calls if "PATCH" in c)
    be.write(36, "delivery_state", "Ready", operation_id="op-1")
    assert sum(1 for c in board.calls if "PATCH" in c) == patches


@pytest.mark.req("REQ-GITHUB-READBACK-001")
def test_replaying_an_id_after_the_value_moved_on_is_a_conflict():
    """Not silent success: the caller is asserting an effect that no longer holds."""
    be, _ = backend()
    be.write(36, "delivery_state", "Ready", operation_id="op-1")
    be.write(36, "delivery_state", "In Progress", operation_id="op-2")
    with pytest.raises(gh_api.Conflict) as exc:
        be.write(36, "delivery_state", "Ready", operation_id="op-1")
    assert "already applied" in str(exc.value)
    assert "new operation id" in str(exc.value)


@pytest.mark.req("REQ-GITHUB-FIELDS-001")
def test_dry_run_reports_the_intent_and_writes_nothing():
    board = FakeBoard()
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, dry_run=True)
    be = fb.ProjectFieldBackend(gh, inspection())
    assert be.write(36, "delivery_state", "Ready").value == "Ready"
    assert not any("PATCH" in c for c in board.calls)
    assert board.values[900] == {}


# --- organization Issue Fields backend ----------------------------------------

class FakeOrgIssues:
    """Issues carrying `issue_field_values`, in the shape the real API sends.

    Captured from `plaincodelab` during #37 and recorded in
    docs/evidence/orgfields-round-trip.md. The previous version of this fake
    rendered `field_id` and a plain `value`, which is a reasonable guess and
    is not what GitHub returns -- so the backend passed every test here and
    read `None` from every real issue.

    The asymmetry is real and deliberate, not a simplification: a write sends
    `field_id` and the option *name*, and a read returns `issue_field_id` and
    the option *id*, with the name under `single_select_option`.
    """

    def __init__(self, fields=None):
        self.fields = fields or {"501": {"name": "Delivery Status"}}
        self.values: dict[int, dict[str, str | None]] = {19: {}, 20: {}}
        self.calls: list[list[str]] = []

    def _option_id(self, name):
        return f"o{STATES.index(name)}" if name in STATES else None

    def __call__(self, args, stdin):
        self.calls.append(list(args))
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).split("?")[0]
        number = int(url.rsplit("/", 1)[-1])
        if number not in self.values:
            return subprocess.CompletedProcess([], 1, "", "gh: Not Found (HTTP 404)")
        if method == "PATCH":
            for entry in json.loads(stdin or "{}").get("issue_field_values", []):
                self.values[number][str(entry["field_id"])] = entry["value"]
        rendered = []
        for field_id, name in self.values[number].items():
            option_id = self._option_id(name)
            rendered.append({
                "data_type": "single_select",
                "issue_field_id": int(field_id),
                "issue_field_name": self.fields.get(field_id, {}).get("name"),
                "single_select_option": (
                    {"id": option_id, "name": name} if option_id else None),
                "value": option_id,
            })
        return subprocess.CompletedProcess(
            [], 0, json.dumps({"number": number, "issue_field_values": rendered}), "")


def org_inspection(**over):
    base = dict(
        owner="acme", repo="widgets", owner_type="Organization",
        backend=it.BACKEND_ISSUE_FIELDS, issue_fields_available=True,
        issue_types_available=True, sub_issues_available=True,
        dependencies_available=True,
        fields={"Delivery Status": it.FieldRef(
            "Delivery Status", "501", "single_select",
            options={s: f"o{i}" for i, s in enumerate(STATES)})},
        roles={"delivery_state": "Delivery Status"},
    )
    base.update(over)
    return it.Inspection(**base)


def org_backend(board=None):
    board = board or FakeOrgIssues()
    gh = gh_api.GitHub(runner=board, sleep=lambda _: None, max_attempts=1)
    return fb.IssueFieldBackend(gh, org_inspection()), board


@pytest.mark.req("REQ-GITHUB-ORGFIELDS-001")
def test_org_backend_round_trips_a_value():
    be, _ = org_backend()
    assert be.read(19, "delivery_state").value is None
    assert be.write(19, "delivery_state", "Ready").value == "Ready"
    assert be.read(19, "delivery_state").value == "Ready"


@pytest.mark.req("REQ-GITHUB-ORGFIELDS-001")
def test_org_backend_sends_the_option_name_not_its_id():
    # GitHub rejects an option id here outright: "must be a string option name".
    # This is the opposite of Projects v2 and is the asymmetry worth pinning.
    be, board = org_backend()
    be.write(19, "delivery_state", "In Progress")
    assert board.values[19]["501"] == "In Progress"


@pytest.mark.req("REQ-GITHUB-ORGFIELDS-001")
def test_org_backend_uses_field_id_not_id_in_the_payload():
    be, board = org_backend()
    be.write(19, "delivery_state", "Ready")
    patch = next(c for c in board.calls if "PATCH" in c)
    assert "/issues/19" in " ".join(patch)
    # The board only stores what it parsed from `field_id`; an `id` key would
    # have raised a KeyError above.
    assert board.values[19] == {"501": "Ready"}


def test_org_backend_refuses_an_unknown_option_before_writing():
    be, board = org_backend()
    with pytest.raises(gh_api.NotFound):
        be.write(19, "delivery_state", "Shipped")
    assert not any("PATCH" in c for c in board.calls)


def test_org_backend_reads_back_and_conflicts_on_mismatch():
    board = FakeOrgIssues()
    original = board.__call__

    def sabotage(args, stdin):
        result = original(args, stdin)
        if "--method" in args and args[args.index("--method") + 1] == "PATCH":
            board.values[19].clear()
        return result

    gh = gh_api.GitHub(runner=sabotage, sleep=lambda _: None, max_attempts=1)
    be = fb.IssueFieldBackend(gh, org_inspection())
    with pytest.raises(gh_api.Conflict):
        be.write(19, "delivery_state", "Ready")


@pytest.mark.req("REQ-GITHUB-ORGFIELDS-001")
def test_org_backend_never_touches_a_project():
    be, board = org_backend()
    be.write(19, "delivery_state", "Ready")
    assert not any("projectsV2" in " ".join(c) for c in board.calls)


@pytest.mark.req("REQ-GITHUB-FIELDS-001")
def test_selection_returns_the_backend_the_inspection_chose():
    gh = gh_api.GitHub(runner=FakeOrgIssues())
    assert isinstance(fb.for_inspection(gh, org_inspection()), fb.IssueFieldBackend)
    assert isinstance(fb.for_inspection(gh_api.GitHub(runner=FakeBoard()), inspection()),
                      fb.ProjectFieldBackend)


def test_both_backends_expose_the_same_interface():
    # Callers ask for a role; they must never need to know which answered.
    for cls in (fb.ProjectFieldBackend, fb.IssueFieldBackend):
        assert issubclass(cls, fb.FieldBackend)
        for method in ("read", "write"):
            assert callable(getattr(cls, method))


# --- placing an issue on the board --------------------------------------------

@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_an_issue_can_be_placed_on_the_board():
    be, board = backend()
    item = be.place(42, board.issue_ids[42])
    assert item == 950
    assert be.read(42, "delivery_state").value is None


@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_placing_an_issue_already_present_is_idempotent():
    be, board = backend()
    first = be.place(36, board.issue_ids[36])
    second = be.place(36, board.issue_ids[36])
    assert first == second == 900
    assert not [c for c in board.calls if "POST" in c], \
        "a second placement would create a duplicate row"


@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_placing_takes_the_issue_id_not_its_number():
    # The real API takes the id. Passing a number would create nothing, and
    # the caller would never learn.
    be, _ = backend()
    with pytest.raises(gh_api.NotFound):
        be.place(42, 42)


@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_a_placed_issue_is_readable_and_writable():
    be, board = backend()
    be.place(42, board.issue_ids[42])
    be.write(42, "delivery_state", STATES[0])
    assert be.read(42, "delivery_state").value == STATES[0]


class LaggingBoard(FakeBoard):
    """A board whose item listing trails a fresh POST.

    Not hypothetical: a live run created an item and failed to find it in the
    very next request. A read-back that can report a successful write as a
    failure is worse than none.
    """

    def __call__(self, args, stdin):
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).partition("?")[0]
        if url.endswith("/items") and method == "GET":
            rows = [{"id": iid, "content": {"number": num}}
                    for num, iid in self.items.items() if iid < self.next_item]
            self.calls.append(list(args))
            return self._ok([r for r in rows if r["id"] < 950])
        return super().__call__(args, stdin)


@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_placement_survives_a_listing_that_lags_behind_the_write():
    be, board = backend(LaggingBoard())
    item = be.place(42, board.issue_ids[42])
    assert item == 950


class MisreportingBoard(FakeBoard):
    """A board whose fresh item reads back as a different issue.

    Trusting the POST response alone would record a placement that put some
    other issue on the board, and nothing downstream would notice.
    """

    def __call__(self, args, stdin):
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        url = (args[args.index("--method") + 2] if "--method" in args
               else args[args.index("api") + 1]).partition("?")[0]
        if "/items/" in url and method == "GET":
            self.calls.append(list(args))
            return self._ok({"id": int(url.rsplit("/", 1)[-1]),
                             "content": {"number": 999}})
        return super().__call__(args, stdin)


@pytest.mark.req("REQ-GITHUB-BOARD-001")
def test_placement_refuses_when_the_item_reads_back_as_another_issue():
    be, board = backend(MisreportingBoard())
    with pytest.raises(gh_api.GitHubError):
        be.place(42, board.issue_ids[42])


# --- the shape the real API actually sends ------------------------------------
#
# Captured from plaincodelab during #37. These are unit tests over the readers
# rather than the backend, so a future change to the payload shape fails on the
# line that reads it instead of three layers up.

@pytest.mark.req("REQ-GITHUB-ORGFIELDS-001")
def test_the_field_id_key_is_issue_field_id():
    # `field_id` and `id` are reasonable guesses and neither is what GitHub
    # sends. Matching on them meant every read returned None.
    entry = {"issue_field_id": 46024252, "issue_field_name": "Delivery Status"}
    assert fb._entry_field_id(entry) == "46024252"


@pytest.mark.req("REQ-GITHUB-ORGFIELDS-001")
def test_the_earlier_key_guesses_still_resolve():
    # Kept as fallbacks: `id` is plausible for a related endpoint, and
    # dropping it would trade one silent mismatch for another.
    assert fb._entry_field_id({"field_id": 7}) == "7"
    assert fb._entry_field_id({"id": 7}) == "7"
    assert fb._entry_field_id({}) is None


@pytest.mark.req("REQ-GITHUB-ORGFIELDS-001")
def test_a_single_select_reads_its_name_not_its_option_id():
    # `value` is the option id. Returning it gives '80557703' where the
    # caller expects 'Inbox'.
    entry = {
        "data_type": "single_select",
        "issue_field_id": 46024252,
        "issue_field_name": "Delivery Status",
        "single_select_option": {"color": "gray", "id": 80557703, "name": "Inbox"},
        "value": 80557703,
    }
    assert fb._issue_field_value(entry) == "Inbox"
    assert fb._issue_field_value(entry) != str(entry["value"])


@pytest.mark.req("REQ-GITHUB-ORGFIELDS-001")
def test_a_field_with_no_option_falls_back_to_the_plain_value():
    # Text and number fields carry no single_select_option.
    assert fb._issue_field_value({"value": "some text"}) == "some text"
    assert fb._issue_field_value({"value": None}) is None


@pytest.mark.req("REQ-GITHUB-ORGFIELDS-001")
def test_the_projects_reader_is_not_used_for_issue_fields():
    # The two APIs differ: Projects sends the option inline under `value`,
    # Issue Fields sends the option id there. One shared reader served both
    # and served one of them wrongly.
    entry = {"single_select_option": {"name": "Inbox"}, "value": 80557703}
    assert fb._read_value(entry) == "80557703"
    assert fb._issue_field_value(entry) == "Inbox"
