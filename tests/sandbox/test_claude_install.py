"""Installing the bundle into a project that uses Claude Code.

Every sandbox test to date initializes with `--integration opencode`, so
"supports Claude Code" was an assertion. The layouts differ in more than a
directory name: OpenCode writes one `.md` per command under
`.opencode/commands`, Claude Code writes a directory per command under
`.claude/skills`, each holding a `SKILL.md`, and the command name is
flattened -- `speckit.github-lifecycle.refine` becomes
`speckit-github-lifecycle-refine`.

A bundle that assumed the first shape would install without error and leave a
project with no commands.
"""
from __future__ import annotations

import subprocess

import pytest

from lib.inventory import ROOT, load_inventory, load_yaml

pytestmark = [pytest.mark.sandbox, pytest.mark.requires_specify]

EXTENSION = "github-lifecycle"
INTEGRATIONS = load_yaml(
    ROOT / "policy/bootstrap-policy.yml")["integrations"]


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True)


def declared_commands() -> set[str]:
    """Every command the extension manifest declares."""
    inv = load_inventory()
    extension = next(c for c in inv.by_kind("extension") if c.id == EXTENSION)
    return {entry["name"] for entry in extension.manifest["provides"]["commands"]}


def on_disk(command: str, integration: str) -> str:
    """What the command is called in that integration's layout.

    They differ in naming as well as in shape. Claude Code flattens
    `speckit.github-lifecycle.refine` to `speckit-github-lifecycle-refine`;
    OpenCode keeps the dots. Assuming one convention is the second way a
    bundle can look installed and not be.
    """
    separator = INTEGRATIONS[integration]["command_name_separator"]
    return command.replace(".", separator)


def installed_commands(project, integration: str) -> set[str]:
    if integration == "claude":
        root = project / ".claude" / "skills"
        return {p.name for p in root.iterdir()
                if p.is_dir() and (p / "SKILL.md").is_file()} if root.is_dir() \
            else set()
    root = project / ".opencode" / "commands"
    return {p.stem for p in root.glob("*.md")} if root.is_dir() else set()


def missing_commands(project, integration: str) -> set[str]:
    """Declared but absent. Named rather than counted."""
    present = installed_commands(project, integration)
    return {c for c in declared_commands()
            if on_disk(c, integration) not in present}


def build_project(root, base, integration: str):
    import local_catalog

    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    r = run(["specify", "init", "--here", "--force", "--non-interactive",
             "--integration", integration, "--script", "py"], root)
    assert r.returncode == 0, r.stderr
    local_catalog.register(root, base)
    local_catalog.install_workflows(root)
    r = run(["specify", "bundle", "install", "lean-full-lifecycle"], root)
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    return root


@pytest.fixture(scope="module")
def projects(tmp_path_factory, dist_dir):
    """One project per integration, plus one holding both.

    The catalog server stays up for the module so a later removal is a real
    operation rather than a failure that happens to leave things tidy.
    """
    import local_catalog

    base_dir = tmp_path_factory.mktemp("claude-install")
    with local_catalog.serve(dist=dist_dir) as base:
        out = {name: build_project(base_dir / name, base, name)
               for name in ("claude", "opencode")}
        both = build_project(base_dir / "both", base, "claude")
        assert run(["specify", "init", "--here", "--force", "--non-interactive",
                    "--integration", "opencode", "--script", "py"],
                   both).returncode == 0
        assert run(["specify", "bundle", "install", "lean-full-lifecycle"],
                   both).returncode == 0
        out["both"] = both
        yield out, base


# --- AC1: the install succeeds and matches the opencode case ------------------

@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
def test_the_bundle_installs_into_a_claude_project(projects):
    got, _ = projects
    listed = run(["specify", "bundle", "list"], got["claude"]).stdout
    assert "lean-full-lifecycle" in listed


@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
def test_the_component_count_matches_the_opencode_case(projects):
    import re

    got, _ = projects

    def count(project):
        out = run(["specify", "bundle", "list"], project).stdout
        m = re.search(r"(\d+) components", out)
        assert m, out
        return int(m.group(1))

    assert count(got["claude"]) == count(got["opencode"])


# --- AC2 / AC6: every command lands, and a missing one is named ---------------

@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
def test_every_declared_command_is_present_in_the_claude_layout(projects):
    got, _ = projects
    assert missing_commands(got["claude"], "claude") == set()


@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
def test_each_command_is_a_directory_holding_a_skill_file(projects):
    # The shape, not just the name: a flat `.md` per command would pass a
    # name-only check and leave Claude Code with nothing to read.
    got, _ = projects
    skills = got["claude"] / ".claude" / "skills"
    for command in declared_commands():
        entry = skills / on_disk(command, "claude")
        assert entry.is_dir(), command
        assert (entry / "SKILL.md").is_file(), command


@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
def test_a_command_that_did_not_land_is_named(projects):
    # The check has to be able to fail, or "every command is present" means
    # only that nothing looked.
    got, _ = projects
    victim = sorted(declared_commands())[0]
    entry = got["claude"] / ".claude" / "skills" / on_disk(victim, "claude")
    skill = entry / "SKILL.md"
    kept = skill.read_text(encoding="utf-8")
    skill.unlink()
    try:
        assert missing_commands(got["claude"], "claude") == {victim}
    finally:
        skill.write_text(kept, encoding="utf-8")


@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
def test_the_opencode_layout_still_receives_its_commands(projects):
    got, _ = projects
    assert missing_commands(got["opencode"], "opencode") == set()


# --- AC3: the workflows resolve -----------------------------------------------

@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
def test_a_workflow_resolves_under_claude(projects):
    got, _ = projects
    r = run(["specify", "workflow", "resolve", "lifecycle-story-delivery"],
            got["claude"])
    assert r.returncode == 0, r.stderr
    assert "verify" in r.stdout


@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
def test_the_workflows_are_listed_under_claude(projects):
    got, _ = projects
    listed = run(["specify", "workflow", "list"], got["claude"]).stdout
    assert "lifecycle-refine" in listed


# --- AC4: one project, both integrations --------------------------------------

@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
def test_a_project_with_both_integrations_populates_both(projects):
    # Spec Kit marks the Claude integration multi-install-safe. A claim like
    # that is worth what a test says about it.
    got, _ = projects
    assert missing_commands(got["both"], "claude") == set()
    assert missing_commands(got["both"], "opencode") == set()


# --- AC5: removal takes back what it installed --------------------------------

@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
def test_removing_the_bundle_removes_its_commands(projects):
    got, _ = projects
    before = installed_commands(got["claude"], "claude")
    assert before

    r = run(["specify", "bundle", "remove", "lean-full-lifecycle"],
            got["claude"])
    # A failed removal leaves everything in place, which would pass a
    # "commands are gone" assertion for the wrong reason if it were inverted.
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"

    after = installed_commands(got["claude"], "claude")
    ours = {on_disk(c, "claude") for c in declared_commands()}
    assert not (after & ours), sorted(after & ours)


@pytest.mark.req("REQ-CORE-CLAUDEINST-001")
@pytest.mark.parametrize("integration", sorted(INTEGRATIONS))
def test_the_naming_convention_is_declared_rather_than_inferred(integration):
    # Both facts about somebody else's layout live in policy, next to the
    # directories #72 already reads from there.
    spec = INTEGRATIONS[integration]
    assert spec["command_name_separator"] in {".", "-"}
    assert spec["command_layout"] in {"file_per_command",
                                      "directory_per_command"}
