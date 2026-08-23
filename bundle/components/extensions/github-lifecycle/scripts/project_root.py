#!/usr/bin/env python3
"""Find the Spec Kit project this command is meant to act on.

Every script in this extension anchored on `Path.cwd()`: a pair of relative
policy candidates, a `--policy-root` defaulting to the working directory, and
no upward search. Run one a directory below a project and it finds no policy.
Run one in a monorepo and it acts on whichever member you were standing in.

Spec Kit already settled this contract, and this mirrors it rather than
inventing a second one. From `specify_cli/_project.py`: `SPECIFY_INIT_DIR`
names the project root -- the directory *containing* `.specify/` -- the path
must exist and must contain that directory, and an invalid value is a hard
error with no fallback to cwd. Their comment gives the reason, which is the
reason here: falling back "would silently operate on the wrong project's
files".

Two additions Spec Kit does not need and this does:

**An upward search**, because these scripts are run from wherever an agent
happens to be, not only from a project root.

**The git root is not the project root.** In a monorepo one git root holds
several members, and stopping the search at `.git` would resolve every member
to the same place.
"""
from __future__ import annotations

import os
from pathlib import Path

MARKER = ".specify"
INIT_DIR = "SPECIFY_INIT_DIR"


class ProjectRootError(Exception):
    """The project could not be resolved. Never resolved to cwd instead."""


def from_environment(env: dict | None = None, cwd: Path | None = None) -> Path | None:
    """Resolve SPECIFY_INIT_DIR, or None when it is unset.

    Strict on purpose, and strict in the same way as the CLI: a value that
    names nothing is an error rather than a hint.
    """
    env = os.environ if env is None else env
    raw = (env.get(INIT_DIR) or "").strip()
    if not raw:
        return None
    root = ((cwd or Path.cwd()) / raw).resolve()
    if not root.is_dir():
        raise ProjectRootError(
            f"{INIT_DIR} does not point to an existing directory: {raw}")
    if not (root / MARKER).is_dir():
        raise ProjectRootError(
            f"{INIT_DIR} is not a Spec Kit project (no {MARKER}/ directory): "
            f"{root}")
    return root


def search_upward(start: Path) -> Path | None:
    """The nearest ancestor containing `.specify/`, or None.

    Nearest, not outermost: in a monorepo the member closest to where the
    command runs is the one it was meant to act on. Stopping at a `.git`
    directory would resolve every member to the git root, which is one project
    the framework has never been installed into.
    """
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / MARKER).is_dir():
            return candidate
    return None


def resolve(explicit: Path | None = None, *, cwd: Path | None = None,
            env: dict | None = None, required: bool = True) -> Path | None:
    """The project root, by precedence: explicit, environment, search.

    An explicit argument wins because a caller that passed one has already
    decided. The environment beats the search for the same reason: somebody
    said which project, so nothing should go looking for a different answer.
    """
    if explicit is not None:
        root = Path(explicit).resolve()
        if required and not (root / MARKER).is_dir():
            raise ProjectRootError(
                f"{root} is not a Spec Kit project (no {MARKER}/ directory)")
        return root

    from_env = from_environment(env, cwd)
    if from_env is not None:
        return from_env

    found = search_upward(cwd or Path.cwd())
    if found is not None:
        return found
    if required:
        raise ProjectRootError(
            f"no Spec Kit project found at or above {(cwd or Path.cwd())}. Run "
            f"this from a project, or set {INIT_DIR} to one.")
    return None


class OutsideProjectError(Exception):
    """A write aimed outside the project the command resolved."""


def ensure_within(root: Path, target: Path) -> Path:
    """Refuse a write outside the resolved project.

    In a monorepo the same relative path means a different file in every
    member, so a command that resolved member_a and writes to
    `../member_b/...` has quietly written into somebody else's project.
    Contamination is silent: it is discovered by a person reading a record
    describing work they never did.

    The refusal names both paths, because "outside the project" without saying
    which project is a message you cannot act on.
    """
    root = Path(root).resolve()
    resolved = Path(target).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise OutsideProjectError(
            f"refusing to write {resolved}: it is outside the resolved project "
            f"{root}. In a monorepo that path belongs to a different member."
        ) from None
    return resolved
