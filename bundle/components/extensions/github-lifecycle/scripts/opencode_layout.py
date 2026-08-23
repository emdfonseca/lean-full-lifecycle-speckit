#!/usr/bin/env python3
"""Find out which OpenCode layout a project uses, before writing near it.

Spec Kit's OpenCode integration writes commands to `.opencode/commands` and
reads `.opencode/command` as a legacy location. Both are live: a project
initialized by an older CLI has the second. Writing an agent config into the
wrong one produces a project where the commands are present and the agent
cannot see them, which is a hard failure to diagnose from the symptom.

Two judgements, both in `bootstrap-policy.yml`:

**Both directories present is reported, not resolved.** That is a project
mid-migration, and choosing one on its behalf hides the migration from the
person who has to finish it.

**Neither present is refused, naming what was looked for.** "No OpenCode
layout" without saying where it looked is a message nobody can act on.

The paths are declared in policy rather than written here: they are somebody
else's, and they move.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/bootstrap-policy.yml",
    "policy/bootstrap-policy.yml",
)

CURRENT = "current"
LEGACY = "legacy"
BOTH = "both"
NONE = "none"


class LayoutError(Exception):
    """No recognised layout. Never resolved to a guess instead."""


def load_policy(root: Path | None = None, integration: str = "opencode") -> dict:
    root = root or project_root.resolve(required=False) or Path.cwd()
    for rel in POLICY_CANDIDATES:
        path = root / rel
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            try:
                return data["integrations"][integration]
            except (KeyError, TypeError):
                raise LayoutError(
                    f"{path} declares no layout for {integration!r}. An "
                    f"integration nobody described is not one to guess at."
                ) from None
    raise FileNotFoundError(
        f"none of {list(POLICY_CANDIDATES)} found; the governance preset must "
        "be installed")


@dataclass
class Layout:
    generation: str
    commands_dir: Path | None
    present: dict[str, str]
    project: Path

    @property
    def usable(self) -> bool:
        return self.generation in (CURRENT, LEGACY)

    def to_dict(self) -> dict:
        return {
            "generation": self.generation,
            "commands_dir": str(self.commands_dir) if self.commands_dir else None,
            "present": self.present,
            "project": str(self.project),
            "usable": self.usable,
        }


def detect(project: Path, policy: dict) -> Layout:
    dirs = policy["commands_dirs"]
    present = {name: rel for name, rel in dirs.items()
               if (project / rel).is_dir()}

    if len(present) > 1:
        # A project mid-migration. Picking one would hide that from the person
        # who has to finish it.
        return Layout(BOTH, None, present, project)
    if CURRENT in present:
        return Layout(CURRENT, project / dirs[CURRENT], present, project)
    if LEGACY in present:
        return Layout(LEGACY, project / dirs[LEGACY], present, project)
    return Layout(NONE, None, present, project)


def require(project: Path, policy: dict) -> Layout:
    """Detect, or raise a refusal that says where it looked."""
    layout = detect(project, policy)
    if layout.generation == NONE:
        looked = ", ".join(str(project / rel)
                           for rel in policy["commands_dirs"].values())
        raise LayoutError(
            f"no OpenCode layout in {project}. Looked for: {looked}.")
    if layout.generation == BOTH:
        found = ", ".join(f"{name} ({rel})" for name, rel in layout.present.items())
        raise LayoutError(
            f"{project} contains both layouts: {found}. This project is part "
            f"way through a migration, and choosing one for it would hide "
            f"that. Finish the move, then run this again.")
    return layout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, "
                         "then the nearest ancestor with a .specify/ directory.")
    ap.add_argument("--integration", default="opencode")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()
    try:
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        policy = load_policy(args.policy_root, args.integration)
        # Detected against the resolved project, not the working directory:
        # in a monorepo the same relative path is a different member's layout.
        layout = detect(args.policy_root, policy)
    except (FileNotFoundError, LayoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(layout.to_dict(), indent=2))
    else:
        print(f"generation: {layout.generation}")
        for name, rel in layout.present.items():
            print(f"  {name}: {rel}")
        if not layout.usable:
            try:
                require(args.policy_root, policy)
            except LayoutError as exc:
                print(f"\n{exc}")
    return 0 if layout.usable else 1


if __name__ == "__main__":
    sys.exit(main())
