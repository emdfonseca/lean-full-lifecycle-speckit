#!/usr/bin/env python3
"""Validate this bundle's own invariants.

Authoritative structural validation belongs to the official CLI:

    specify bundle validate --path bundle/ --offline

(the online form resolves references against the *project* containing the
manifest, so it cannot pass from a source checkout).

This validator covers only what the official one cannot know: the safety and
composition properties this bundle chooses to hold. Checks are registered in
lib/checks.py with stable ids, so each can be run alone and each can be cited
from a requirement.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import checks as _checks  # noqa: F401,E402  (registers the checks)
from lib.inventory import ROOT, load_inventory, load_yaml  # noqa: E402
from lib.registry import REGISTRY, Ctx, run_checks  # noqa: E402


def build_ctx(strict_publish: bool) -> Ctx:
    return Ctx(
        root=ROOT,
        inv=load_inventory(),
        invariants=load_yaml(ROOT / "tooling" / "invariants.yml"),
        strict_publish=strict_publish,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict-publish", action="store_true",
                    help="Promote publishing warnings to errors.")
    ap.add_argument("--only", metavar="CHECK_ID",
                    help="Run a single check (used by the negative fixtures).")
    ap.add_argument("--scope", help="Run only checks in this scope.")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--list-checks", action="store_true",
                    help="Print the registry; requirements cite these ids.")
    args = ap.parse_args()

    if args.list_checks:
        rows = [
            {"id": c.id, "title": c.title, "scope": c.scope,
             "severity": c.severity, "strict_publish_only": c.strict_publish_only}
            for c in REGISTRY.values()
        ]
        if args.format == "json":
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                print(f"{r['id']:32} {r['scope']:10} {r['title']}")
        return 0

    if args.only and args.only not in REGISTRY:
        print(f"unknown check id: {args.only}", file=sys.stderr)
        return 2

    ctx = build_ctx(args.strict_publish)
    findings, executed = run_checks(ctx, only=args.only, scope=args.scope)

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if args.format == "json":
        print(json.dumps({
            "executed": executed,
            "errors": [f.__dict__ for f in errors],
            "warnings": [f.__dict__ for f in warnings],
        }, indent=2))
        return 1 if errors else 0

    for f in warnings:
        print(f"WARNING {f}")
    for f in errors:
        print(f"ERROR   {f}")
    print(f"\n{len(executed)} checks run, {len(errors)} errors, {len(warnings)} warnings")
    if errors:
        return 1
    print("Bundle invariants hold. "
          "Run `specify bundle validate --path bundle/ --offline` for structural validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
