#!/usr/bin/env python3
"""Reading and writing lifecycle field values.

Two backends exist because the target decides which is available: organization
Issue Fields where they carry the delivery state, and the project board
otherwise. `inspect_target` picks one; callers ask for a *role* and never
branch on which was chosen.

Every write is read back. A write that reports success and a read that returns
something else is a conflict, not a success -- `github-schema.yml` requires
read-after-write, and silently trusting the response is how a transition
appears to have happened without having happened.

Labels are never written. `allow_status_labels: false` is not a default to be
overridden; a label is not an auditable field value.
"""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_api import Conflict, GitHub, GitHubError, NotFound  # noqa: E402
from inspect_target import BACKEND_ISSUE_FIELDS, BACKEND_PROJECT, Inspection  # noqa: E402


@dataclass(frozen=True)
class FieldValue:
    role: str
    field_name: str
    value: str | None

    def __str__(self) -> str:
        return f"{self.field_name}={self.value!r}"


class FieldBackend(ABC):
    """What every command uses. Neither the role names nor this interface
    change with the backend underneath."""

    def __init__(self, gh: GitHub, inspection: Inspection) -> None:
        self.gh = gh
        self.inspection = inspection

    @abstractmethod
    def read(self, issue_number: int, role: str) -> FieldValue:
        """Current value of a role for one issue."""

    @abstractmethod
    def write(self, issue_number: int, role: str, value: str, *,
              operation_id: str | None = None) -> FieldValue:
        """Set exactly one value, then read it back. Raises Conflict on mismatch."""

    def _field(self, role: str):
        return self.inspection.field_for(role)

    def _verify(self, issue_number: int, role: str, intended: str,
                skipped: bool = False) -> FieldValue:
        observed = self.read(issue_number, role)
        if observed.value == intended:
            return observed
        if skipped:
            # The operation id says this already applied, and it did -- but the
            # value has since moved on. Surfacing that is the point: a caller
            # replaying an id is asserting an effect that no longer holds.
            raise Conflict(
                f"operation already applied to issue #{issue_number} {role}, "
                f"but the value has since changed: expected {intended!r}, "
                f"found {observed.value!r}. Use a new operation id to set it again."
            )
        raise Conflict(
            f"read-back mismatch on issue #{issue_number} {role}: "
            f"wrote {intended!r}, read {observed.value!r}"
        )


class ProjectFieldBackend(FieldBackend):
    """Projects v2 board, the `when_issue_fields_unavailable` fallback.

    Values live on the project *item*, not the issue, so every operation first
    resolves the issue number to an item id on the one authoritative board.
    """

    def __init__(self, gh: GitHub, inspection: Inspection) -> None:
        super().__init__(gh, inspection)
        if inspection.backend != BACKEND_PROJECT:
            raise ValueError(f"inspection selected {inspection.backend!r}")
        if inspection.project_number is None:
            raise ValueError("no project selected; inspection was ambiguous")
        root = "orgs" if inspection.owner_type == "Organization" else "users"
        self._base = f"{root}/{inspection.owner}/projectsV2/{inspection.project_number}"
        self._items: dict[int, int] | None = None

    def item_id(self, issue_number: int, refresh: bool = False) -> int:
        if self._items is None or refresh:
            rows = self.gh.rest("GET", f"{self._base}/items", paginate=True) or []
            if isinstance(rows, dict):
                rows = [rows]
            self._items = {}
            for row in rows:
                content = row.get("content") or {}
                number = content.get("number")
                if number is not None:
                    self._items[int(number)] = int(row["id"])
        try:
            return self._items[issue_number]
        except KeyError:
            raise NotFound(
                f"issue #{issue_number} is not on project "
                f"#{self.inspection.project_number}"
            ) from None

    def place(self, issue_number: int, issue_id: int, *,
              operation_id: str | None = None) -> int:
        """Put an issue on the board, and return its item id.

        Idempotent, and it has to be idempotent against a race rather than
        only against a repeat. The lookup below is not enough on a project
        with an auto-add workflow: that workflow can add the issue between the
        lookup and the POST, and the POST then returns "Content already exists"
        (HTTP 422). Treating that as a failure left the item on the board with
        no delivery state and took the field write down with it -- the caller
        reported `on_board: false` about an item that was on the board.

        An add that fails because the row is already there has its
        postcondition satisfied. Re-resolve and carry on.
        """
        try:
            return self.item_id(issue_number)
        except NotFound:
            pass
        try:
            created = self.gh.rest(
                "POST", f"{self._base}/items",
                body={"type": "Issue", "id": int(issue_id)},
                operation_id=operation_id,
            )
        except Conflict:
            self._items = None      # the cached listing predates the race
            return self.item_id(issue_number)
        if self.gh.last_outcome == "dry-run":
            return -1
        if not created or created.get("id") is None:
            raise GitHubError(
                f"placing #{issue_number} returned no item id")
        item = int(created["id"])

        # Read the item back directly rather than re-listing. The listing lags
        # a moment behind a fresh POST -- a live run created the item and then
        # failed to find it in the very next request -- and a read-back that
        # can report a successful write as a failure is worse than none.
        row = self.gh.rest("GET", f"{self._base}/items/{item}") or {}
        number = (row.get("content") or {}).get("number")
        if number is None or int(number) != issue_number:
            raise GitHubError(
                f"placed #{issue_number} but item {item} reads back as "
                f"{number!r}")
        if self._items is not None:
            self._items[issue_number] = item
        return item

    def read(self, issue_number: int, role: str) -> FieldValue:
        ref = self._field(role)
        item = self.item_id(issue_number)
        # A bare item GET returns Title alone; values must be asked for by id.
        payload = self.gh.rest(
            "GET", f"{self._base}/items/{item}?fields={ref.id}"
        ) or {}
        for entry in payload.get("fields") or []:
            if str(entry.get("id")) == ref.id:
                return FieldValue(role, ref.name, _read_value(entry))
        return FieldValue(role, ref.name, None)

    def write(self, issue_number: int, role: str, value: str, *,
              operation_id: str | None = None) -> FieldValue:
        ref = self._field(role)
        item = self.item_id(issue_number)
        # Resolve to an option id: names are renameable, ids are not.
        payload_value = ref.option_id(value) if ref.options else value
        self.gh.rest(
            "PATCH", f"{self._base}/items/{item}",
            body={"fields": [{"id": int(ref.id), "value": payload_value}]},
            operation_id=operation_id,
        )
        outcome = self.gh.last_outcome
        if outcome == "dry-run":
            # Nothing was written, so there is nothing to read back. Verifying
            # here would report a mismatch for a mutation deliberately not made.
            return FieldValue(role, ref.name, value)
        return self._verify(issue_number, role, value,
                            skipped=outcome == "skipped-already-applied")


def _entry_field_id(entry: dict) -> str | None:
    """The field this value belongs to.

    The organization Issue Fields API names it `issue_field_id`. The earlier
    guesses -- `field_id`, `id` -- are kept as fallbacks rather than removed,
    because `id` is a plausible shape for a related endpoint and dropping it
    would trade one silent mismatch for another. `issue_field_id` is first
    because it is the one the real API sends.
    """
    for key in ("issue_field_id", "field_id", "id"):
        if entry.get(key) is not None:
            return str(entry[key])
    return None


def _issue_field_value(entry: dict) -> str | None:
    """The readable value of one organization Issue Field entry.

    Distinct from `_read_value`, which reads the Projects v2 shape. The two
    APIs genuinely differ: a Projects single-select sends the option inline
    under `value`, while an Issue Field sends the option *id* as `value` and
    the option itself under `single_select_option`. Reading the id and
    returning it as the value is how this backend reported `'80557703'` where
    a caller expected `'Inbox'`.
    """
    option = entry.get("single_select_option")
    if isinstance(option, dict) and option.get("name") is not None:
        return str(option["name"])
    return _read_value(entry)


def _read_value(entry: dict) -> str | None:
    """Field values are scalars, {raw, html}, or a whole option object."""
    value = entry.get("value")
    if value is None:
        return None
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, dict):
            return str(name.get("raw", ""))
        if name is not None:
            return str(name)
        raw = value.get("raw")
        return None if raw is None else str(raw)
    return str(value)


class IssueFieldBackend(FieldBackend):
    """Organization Issue Fields, the preferred backend.

    Values live on the issue itself, under `issue_field_values`, so there is no
    project item to resolve.

    Note the wire format differs from Projects v2 in both keys: the member is
    `field_id` rather than `id`, and a single-select value must be the option
    **name**, not its id -- GitHub rejects an id outright with "must be a string
    option name". Resolution still goes through the id-keyed inspection, so an
    unknown option is refused before any request is made; only the transmitted
    form differs.
    """

    def __init__(self, gh: GitHub, inspection: Inspection) -> None:
        super().__init__(gh, inspection)
        if inspection.backend != BACKEND_ISSUE_FIELDS:
            raise ValueError(f"inspection selected {inspection.backend!r}")
        self._base = f"repos/{inspection.owner}/{inspection.repo}/issues"

    def read(self, issue_number: int, role: str) -> FieldValue:
        ref = self._field(role)
        payload = self.gh.rest("GET", f"{self._base}/{issue_number}") or {}
        for entry in payload.get("issue_field_values") or []:
            if _entry_field_id(entry) == ref.id:
                return FieldValue(role, ref.name, _issue_field_value(entry))
        return FieldValue(role, ref.name, None)

    def write(self, issue_number: int, role: str, value: str, *,
              operation_id: str | None = None) -> FieldValue:
        ref = self._field(role)
        if ref.options:
            # Validate against the resolved options before sending, even though
            # the name is what travels.
            ref.option_id(value)
        self.gh.rest(
            "PATCH", f"{self._base}/{issue_number}",
            body={"issue_field_values": [{"field_id": int(ref.id), "value": value}]},
            operation_id=operation_id,
        )
        outcome = self.gh.last_outcome
        if outcome == "dry-run":
            return FieldValue(role, ref.name, value)
        return self._verify(issue_number, role, value,
                            skipped=outcome == "skipped-already-applied")


def for_inspection(gh: GitHub, inspection: Inspection) -> FieldBackend:
    """The backend `inspect_target` selected."""
    if not inspection.usable:
        raise ValueError(
            "target is not usable: "
            f"missing={inspection.missing_roles} ambiguities={inspection.ambiguities}"
        )
    if inspection.backend == BACKEND_PROJECT:
        return ProjectFieldBackend(gh, inspection)
    if inspection.backend == BACKEND_ISSUE_FIELDS:
        return IssueFieldBackend(gh, inspection)
    raise NotImplementedError(
        f"backend {inspection.backend!r} is not implemented"
    )
