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

from github_api import Conflict, GitHub, NotFound  # noqa: E402
from inspect_target import BACKEND_PROJECT, Inspection  # noqa: E402


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


def for_inspection(gh: GitHub, inspection: Inspection) -> FieldBackend:
    """The backend `inspect_target` selected."""
    if not inspection.usable:
        raise ValueError(
            "target is not usable: "
            f"missing={inspection.missing_roles} ambiguities={inspection.ambiguities}"
        )
    if inspection.backend == BACKEND_PROJECT:
        return ProjectFieldBackend(gh, inspection)
    raise NotImplementedError(
        f"backend {inspection.backend!r} is not implemented yet"
    )
