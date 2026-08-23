#!/usr/bin/env python3
"""Find which feature is active, from what declares it.

Nothing in this bundle read either declaring source. In concurrent worktrees --
where two features are checked out at once, which is the whole reason worktrees
exist -- an agent inferring the feature from the branch is choosing between two
right answers by accident, and getting it wrong exactly where it is hardest to
notice.

This mirrors Spec Kit's `get_feature_paths`: `SPECIFY_FEATURE_DIRECTORY` first,
then `.specify/feature.json`, then a hard error naming both. Two details worth
stating because they are easy to get wrong in the other direction:

**The git branch is never consulted.** Spec Kit does not read it either -- its
`get_current_branch()` returns `os.environ.get("SPECIFY_FEATURE", "")`, and the
branch name appears only as a fallback *label* for a feature that has already
resolved. So "changing branches does not switch the feature" is not a rule
layered on top of Spec Kit; it is what Spec Kit does.

**A relative path resolves against the project root**, which Spec Kit's
`get_repo_root` resolves the same way `project_root.resolve` does: the
environment override, then the nearest ancestor with `.specify/`. Not the git
root, and not the working directory.

Reading does not write. Spec Kit persists the environment value into
`feature.json`, and it carries a `no_persist` flag for callers that must not.
Every caller here is a reader, and a read with a side effect on shared project
state is a surprise nobody asked for.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FEATURE_DIR = "SPECIFY_FEATURE_DIRECTORY"
FEATURE_JSON = ".specify/feature.json"
FEATURE_KEY = "feature_directory"


class FeatureContextError(Exception):
    """No feature is declared. Never guessed from the branch instead."""


def _against_project(value: str, project: Path) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (project / candidate)


def from_environment(project: Path, env: dict | None = None) -> Path | None:
    env = os.environ if env is None else env
    raw = (env.get(FEATURE_DIR) or "").strip()
    return _against_project(raw, project) if raw else None


def from_feature_json(project: Path) -> Path | None:
    path = project / FEATURE_JSON
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeatureContextError(
            f"{path} could not be read ({exc.__class__.__name__}). An "
            f"unreadable declaration is not an absent one, so no feature is "
            f"assumed.") from None
    value = str((data or {}).get(FEATURE_KEY) or "").strip()
    if not value:
        raise FeatureContextError(
            f"{path} declares no {FEATURE_KEY!r}. The file exists, so "
            f"something meant to declare a feature and did not.")
    return _against_project(value, project)


def resolve(project: Path, env: dict | None = None,
            required: bool = True) -> Path | None:
    """The active feature directory, or an error naming what would declare one."""
    chosen = from_environment(project, env)
    if chosen is not None:
        # feature.json is deliberately not consulted. Reading it to compare
        # would invite reconciling two answers, and the environment is the one
        # somebody set for this run.
        return chosen

    chosen = from_feature_json(project)
    if chosen is not None:
        return chosen

    if required:
        raise FeatureContextError(
            f"no active feature. Set {FEATURE_DIR}, or run the specify command "
            f"to create {FEATURE_JSON}. The git branch is not consulted: with "
            f"two worktrees checked out it would be a guess between two right "
            f"answers.")
    return None


def source(project: Path, env: dict | None = None) -> str:
    """Which declaration answered, so a report can say rather than imply."""
    if from_environment(project, env) is not None:
        return FEATURE_DIR
    if (project / FEATURE_JSON).is_file():
        return FEATURE_JSON
    return "none"
