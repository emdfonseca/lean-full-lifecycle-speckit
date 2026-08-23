"""Check registry for the source validator.

Checks are registered functions, not a 600-line procedure. Two things follow:
a check can be run in isolation (`--only`), which is what lets a negative
fixture prove it can actually fail; and every check has a stable id, which is
what lets a requirement reference it as `check:INV-SHELL-ALLOWLIST`.

Check id families:
  INV-*   invariants this bundle chooses to hold
  SEC-*   safety properties; never relaxed
  PUB-*   publishing readiness; warnings until --strict-publish
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Finding:
    check_id: str
    severity: Severity
    subject: str
    message: str

    def __str__(self) -> str:
        return f"[{self.check_id}] {self.subject}: {self.message}"


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    scope: str
    severity: Severity
    strict_publish_only: bool
    fn: Callable[["Ctx"], Iterable[Finding]]


@dataclass
class Ctx:
    root: Path
    inv: object            # lib.inventory.Inventory
    invariants: dict       # tooling/invariants.yml
    strict_publish: bool = False

    def finding(self, check_id: str, subject: str, message: str,
                severity: Severity = "error") -> Finding:
        return Finding(check_id, severity, subject, message)


REGISTRY: dict[str, Check] = {}


def check(check_id: str, title: str, *, scope: str,
          severity: Severity = "error", strict_publish_only: bool = False):
    """Register a check. The function yields Findings; yielding nothing is a pass."""
    def decorator(fn):
        if check_id in REGISTRY:
            raise ValueError(f"duplicate check id: {check_id}")
        REGISTRY[check_id] = Check(
            check_id, title, scope, severity, strict_publish_only, fn
        )
        return fn
    return decorator


def run_checks(ctx: Ctx, only: str | None = None,
               scope: str | None = None) -> tuple[list[Finding], list[str]]:
    """Run matching checks. Returns (findings, ids_executed)."""
    findings: list[Finding] = []
    executed: list[str] = []
    for cid, chk in REGISTRY.items():
        if only and cid != only:
            continue
        if scope and chk.scope != scope:
            continue
        if chk.strict_publish_only and not ctx.strict_publish:
            # Still executed, but its findings downgrade to warnings.
            pass
        executed.append(cid)
        for f in chk.fn(ctx) or ():
            if chk.strict_publish_only and not ctx.strict_publish:
                f = Finding(f.check_id, "warning", f.subject, f.message)
            findings.append(f)
    return findings, executed
