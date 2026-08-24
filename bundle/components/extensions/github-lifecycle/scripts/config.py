"""Read what the project already declared, instead of being told it again.

`config-template.yml` declares the organization, the repository, the project
number, every field name, and a safety block. Spec Kit scaffolds it as
`github-lifecycle-config.yml` at install. Only `doctor.py` ever read it: every
other script took `--repo` and `--project` as required flags, so an agent had
to be told the target before it could do anything, and told again each time.

That is not only tedious. It means the values arrive as arguments an agent
composed, so a wrong project number is a typo rather than a misconfiguration,
and nothing is in a position to refuse it.

Resolution order, and the reason for it:

**An explicit flag wins.** A caller that passed one has already decided, and a
config that quietly overrode it would be worse than no config.

**Then the scaffolded config**, `.local.yml` first — Spec Kit reads the local
sibling first and preserves it across updates, so that is where a person's own
value belongs.

**Then a refusal that names the file.** Falling back to a guess is how a
command ends up acting on somebody else's project.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

import project_root

EXTENSION = "github-lifecycle"
CANDIDATES = (
    f".specify/extensions/{EXTENSION}/{EXTENSION}-config.local.yml",
    f".specify/extensions/{EXTENSION}/{EXTENSION}-config.yml",
    f".specify/extensions/{EXTENSION}/config-template.yml",
)
# The source checkout, where the extension is authored rather than installed.
SOURCE = f"bundle/components/extensions/{EXTENSION}/config-template.yml"

REPO_ENV = "GITHUB_LIFECYCLE_REPO"
PROJECT_ENV = "GITHUB_LIFECYCLE_PROJECT"


class ConfigError(Exception):
    """The target could not be resolved, and was not guessed at."""


@dataclass
class Target:
    repo: str
    project: int | None
    source: str

    @property
    def owner(self) -> str:
        return self.repo.partition("/")[0]


def load(root: Path | None = None) -> tuple[dict, str | None]:
    """The scaffolded config and where it came from, or ({}, None)."""
    root = root or project_root.resolve(required=False) or Path.cwd()
    for rel in (*CANDIDATES, SOURCE):
        path = root / rel
        if not path.is_file():
            continue
        try:
            return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}), rel
        except yaml.YAMLError as exc:
            # An unreadable config is not an absent one. Continuing to the next
            # candidate would silently use a different project's settings.
            raise ConfigError(
                f"{rel} could not be parsed ({exc.__class__.__name__}); "
                f"refusing to fall through to another source") from None
    return {}, None


def resolve_target(repo: str | None = None, project: int | None = None,
                   root: Path | None = None,
                   env: dict | None = None) -> Target:
    """Where a command should act."""
    env = os.environ if env is None else env
    config, origin = load(root)

    chosen_repo = repo or env.get(REPO_ENV) or None
    if not chosen_repo:
        owner = config.get("organization")
        name = config.get("repository")
        if owner and name:
            chosen_repo = f"{owner}/{name}"
        elif name and "/" in str(name):
            chosen_repo = str(name)
    if not chosen_repo:
        raise ConfigError(
            f"no repository. Pass --repo, set {REPO_ENV}, or set "
            f"`organization` and `repository` in "
            f"{origin or CANDIDATES[1]}. Guessing one would risk acting on "
            f"another project.")
    if "/" not in chosen_repo:
        raise ConfigError(f"--repo must be owner/name, got {chosen_repo!r}")

    # A configured project_number is a fact about the configured repository's
    # board, not about whatever repository this invocation names. Carrying it
    # across let a command aimed elsewhere keep this project's board, and an
    # explicit project short-circuits discovery entirely -- so the
    # repository-scoped lookup could not catch it either.
    configured_repo = _configured_repo(config)
    elsewhere = bool(configured_repo) and chosen_repo != configured_repo

    chosen_project = project
    if chosen_project is None and env.get(PROJECT_ENV):
        chosen_project = int(env[PROJECT_ENV])
    if chosen_project is None and config.get("project_number") is not None:
        if elsewhere:
            # Dropped, not inherited. Discovery then finds the board this
            # repository is actually linked to, or reports that it has none.
            chosen_project = None
        else:
            chosen_project = int(config["project_number"])
    # An explicit --project alongside an explicit --repo is honoured. The
    # caller named both halves, so nothing is inherited and nothing is silent
    # -- which is the whole defect. Only the carried-over case is dropped.

    where = "--repo" if repo else (REPO_ENV if env.get(REPO_ENV) else origin)
    return Target(chosen_repo, chosen_project, where or "argument")


def _configured_repo(config: dict) -> str | None:
    """The repository the config declares, in owner/name form."""
    owner = config.get("organization")
    name = config.get("repository")
    if owner and name:
        return f"{owner}/{name}"
    if name and "/" in str(name):
        return str(name)
    return None


def field_names(root: Path | None = None) -> dict:
    """The field names this project declared, if it declared any."""
    config, _ = load(root)
    return dict(config.get("fields") or {})


def safety(root: Path | None = None) -> dict:
    """The safety switches the config claims to control."""
    config, _ = load(root)
    return dict(config.get("safety") or {})
