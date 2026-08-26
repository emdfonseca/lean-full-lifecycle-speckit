#!/usr/bin/env python3
"""The single place this extension talks to GitHub.

Built on `gh`, which the extension already declares as a required tool. `gh`
owns authentication, pagination, and the GraphQL endpoint; reimplementing any of
that would duplicate a dependency we already require.

What lives here is the discipline `gh` has no opinion about: distinguishing the
failures a caller must handle from the ones it must not swallow, retrying only
what is safe to retry, refusing to apply a mutation twice, redacting secrets
from the audit trail, and being able to show exactly what would happen without
doing it.

Deliberately absent: an HTTP client, a response-object model, and any auth
handling. If those appear, this has stopped being an adapter.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

__all__ = [
    "GitHub", "GitHubError", "NotFound", "Forbidden", "Conflict",
    "RateLimited", "TransportError", "AuditRecord", "redact",
]

# Mutating verbs. Only reads are retried by default; a mutation is retried only
# when it carries an operation id, so a retry cannot silently double-apply.
WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# Token shapes GitHub issues, plus anything that announces itself as a secret.
import sensitive

REDACTED = sensitive.FALLBACK_MARKER


def redact(text: str) -> str:
    """Strip anything credential-shaped. Applied to everything reaching the audit log.

    The shapes live in `sensitive-data.yml`, not here. Two lists of what a
    credential looks like drift, and the copy that drifts is the one nobody is
    testing. `sensitive.compile_patterns` falls back to a conservative built-in
    set when policy is unreachable, and says so rather than pretending.
    """
    return sensitive.redact(text)


class GitHubError(Exception):
    """Base class. Carries the sanitized stderr, never the raw command."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(redact(message))
        self.status = status


class NotFound(GitHubError):
    """404. Often legitimate -- an unset field, an absent dependency."""


class Forbidden(GitHubError):
    """403 or 401 that is not a rate limit: missing scope, or no permission."""


class Conflict(GitHubError):
    """409, or a read-back that disagrees with what was written."""


class RateLimited(GitHubError):
    """Primary or secondary rate limit. Retryable after a delay."""

    def __init__(self, message: str, *, retry_after: float = 60.0) -> None:
        super().__init__(message, status=429)
        self.retry_after = retry_after


class TransportError(GitHubError):
    """gh itself failed: not installed, not authenticated, or a 5xx."""


@dataclass(frozen=True)
class AuditRecord:
    operation: str
    target: str
    outcome: str
    attempts: int
    dry_run: bool
    operation_id: str | None = None
    detail: str = ""

    def to_json(self) -> str:
        return json.dumps({
            "operation": redact(self.operation),
            "target": redact(self.target),
            "outcome": self.outcome,
            "attempts": self.attempts,
            "dry_run": self.dry_run,
            "operation_id": redact(self.operation_id or "") or None,
            "detail": redact(self.detail)[:2000],
        }, sort_keys=True)


# A type alias is a runtime expression, so `from __future__ import annotations`
# does not defer it and `str | None` is evaluated on import. That made this one
# line the floor for eleven scripts: every module reaching GitHub imports this
# one, and all eleven died here on Python 3.9 while the other twenty ran fine
# (#132). Quoted, it is a string until something asks for it.
Runner = Callable[[Sequence[str], "str | None"], subprocess.CompletedProcess]


def _default_runner(args: Sequence[str], stdin: str | None) -> subprocess.CompletedProcess:
    if shutil.which("gh") is None:
        raise TransportError("gh is not installed; the extension requires it")
    return subprocess.run(list(args), input=stdin, text=True, capture_output=True)


def _classify(returncode: int, stderr: str) -> GitHubError | None:
    """Map a gh failure onto something a caller can branch on.

    Callers must never parse stderr themselves; that is what this exists for.
    """
    if returncode == 0:
        return None
    low = stderr.lower()
    if "rate limit" in low or "secondary rate" in low or "abuse detection" in low:
        retry_after = 60.0
        m = re.search(r"retry after (\d+)", low)
        if m:
            retry_after = float(m.group(1))
        return RateLimited(stderr, retry_after=retry_after)
    if "not found" in low or "404" in low:
        return NotFound(stderr, status=404)
    if "already exists" in low or "409" in low or "conflict" in low:
        return Conflict(stderr, status=409)
    if any(s in low for s in ("forbidden", "403", "401", "bad credentials",
                              "requires authentication", "insufficient")):
        return Forbidden(stderr, status=403)
    return TransportError(stderr)


@dataclass
class GitHub:
    """A thin, auditable wrapper over `gh`.

    Args:
        runner: injected for tests, so nothing here needs a network.
        dry_run: mutations are described and not performed.
        audit_path: JSON-lines audit trail. Every call is recorded, redacted.
        max_attempts: total tries for a retryable failure.
        sleep: injected for tests, so backoff does not make them slow.
    """

    runner: Runner = _default_runner
    dry_run: bool = False
    audit_path: Path | None = None
    max_attempts: int = 3
    sleep: Callable[[float], None] = time.sleep
    _applied: set[str] = field(default_factory=set, init=False, repr=False)
    _audit: list[AuditRecord] = field(default_factory=list, init=False, repr=False)

    @property
    def audit(self) -> list[AuditRecord]:
        return list(self._audit)

    @property
    def last_outcome(self) -> str | None:
        """Outcome of the most recent call, so a caller can tell a skip from a write."""
        return self._audit[-1].outcome if self._audit else None

    # -- public surface -----------------------------------------------------

    def rest(self, method: str, path: str, *, body: dict | None = None,
             paginate: bool = False, jq: str | None = None,
             operation_id: str | None = None) -> Any:
        """One REST call. Pagination is delegated to `gh --paginate`."""
        args = ["gh", "api", "--method", method.upper(), path]
        if paginate:
            args.append("--paginate")
        if jq:
            args += ["--jq", jq]
        stdin = None
        if body is not None:
            args += ["--input", "-"]
            stdin = json.dumps(body)
        return self._invoke(
            args, stdin, operation=f"{method.upper()} {path}",
            target=path, mutating=method.upper() in WRITE_METHODS,
            operation_id=operation_id,
        )

    def graphql(self, query: str, *, variables: dict | None = None,
                mutating: bool = False, operation_id: str | None = None) -> Any:
        """One GraphQL call.

        Required for Issue Fields and Issue Types, which exist in no REST API.
        GraphQL reports errors in a 200 body, so those are surfaced here rather
        than being mistaken for success.
        """
        args = ["gh", "api", "graphql", "-f", f"query={query}"]
        for key, value in (variables or {}).items():
            flag = "-F" if isinstance(value, (int, float, bool)) or _looks_like_id(value) else "-f"
            args += [flag, f"{key}={value}"]
        return self._invoke(
            args, None, operation="graphql",
            target=_operation_name(query), mutating=mutating,
            operation_id=operation_id,
        )

    # -- internals ----------------------------------------------------------

    def _invoke(self, args: Sequence[str], stdin: str | None, *, operation: str,
                target: str, mutating: bool, operation_id: str | None) -> Any:
        if mutating and operation_id and operation_id in self._applied:
            # A retry above this layer must not reapply a mutation that already
            # succeeded. Cross-process safety comes from read-back, not here.
            self._record(operation, target, "skipped-already-applied", 0,
                         operation_id=operation_id)
            return None

        if self.dry_run and mutating:
            self._record(operation, target, "dry-run", 0,
                         operation_id=operation_id, detail=" ".join(args))
            return None

        last: GitHubError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                completed = self.runner(args, stdin)
            except GitHubError as exc:
                self._record(operation, target, "error", attempt, operation_id, str(exc))
                raise
            error = _classify(completed.returncode, completed.stderr or "")
            if error is None:
                payload = _parse(completed.stdout)
                gql_error = _graphql_error(payload)
                if gql_error is not None:
                    self._record(operation, target, "error", attempt, operation_id, gql_error)
                    raise _classify(1, gql_error) or GitHubError(gql_error)
                if mutating and operation_id:
                    self._applied.add(operation_id)
                self._record(operation, target, "ok", attempt, operation_id)
                return payload

            last = error
            if not self._retryable(error, mutating, operation_id) or attempt == self.max_attempts:
                self._record(operation, target, "error", attempt, operation_id, str(error))
                raise error
            self.sleep(self._backoff(attempt, error))

        assert last is not None
        raise last

    @staticmethod
    def _retryable(error: GitHubError, mutating: bool, operation_id: str | None) -> bool:
        if isinstance(error, RateLimited):
            return True
        if isinstance(error, TransportError):
            # A mutation is only safe to retry when an operation id makes the
            # repeat detectable; otherwise a timeout that actually succeeded
            # would be applied twice.
            return not mutating or operation_id is not None
        return False

    @staticmethod
    def _backoff(attempt: int, error: GitHubError) -> float:
        if isinstance(error, RateLimited):
            return error.retry_after
        # Jitter so concurrent workers do not retry in lockstep.
        return min(2 ** (attempt - 1), 8) + random.uniform(0, 0.5)

    def _record(self, operation: str, target: str, outcome: str, attempts: int,
                operation_id: str | None = None, detail: str = "") -> None:
        record = AuditRecord(operation, target, outcome, attempts,
                             self.dry_run, operation_id, detail)
        self._audit.append(record)
        if self.audit_path is not None:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(record.to_json() + "\n")


def _parse(stdout: str) -> Any:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # --paginate emits one JSON document per page, so a multi-document body is
    # split. Anything else is returned whole: --jq can emit a bare scalar, and
    # it can emit multi-line text such as an issue body. Splitting that into
    # lines turned a body into a list and silently corrupted every consumer
    # that expected a string.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    docs = []
    for line in lines:
        try:
            docs.append(json.loads(line))
        except json.JSONDecodeError:
            return text          # not a document stream; it is just text
    if not docs:
        return text
    return docs if len(docs) != 1 else docs[0]


def _graphql_error(payload: Any) -> str | None:
    """GraphQL reports failure in a 200 body; gh exits 0 for those."""
    if isinstance(payload, dict) and payload.get("errors"):
        return json.dumps(payload["errors"])
    return None


def _operation_name(query: str) -> str:
    m = re.search(r"(?:mutation|query)\s+(\w+)", query)
    if m:
        return m.group(1)
    m = re.search(r"\b(\w+)\s*\(", query)
    return m.group(1) if m else "anonymous"


def _looks_like_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("PVT", "PVTI", "PVTF", "I_", "MDU6", "MDQ6"))
