"""Who runs each command, and the two ways that could stop being true.

A flat list of thirty-two commands says nothing about which are yours. The tier
fixes that only while two things hold, and they fail differently.

The tier is metadata a manifest carries. The description is what an agent
actually renders in a flattened command list. A tier a reader cannot see from
that list would be an annotation rather than a front door, so both are asserted
and the second is the one that reaches anybody.

The last tests here guard the story's own out-of-scope clause: this change was
text and metadata, and a command name or a workflow step reference that moved
would break every project that installed the bundle.
"""
from __future__ import annotations

import re

import pytest
import yaml

from lib.inventory import ROOT, load_inventory
from lib.checks import COMMAND_TIERS, TIER_CLAUSE

EXTENSIONS = ROOT / "bundle/components/extensions"


@pytest.fixture(scope="module")
def inv():
    return load_inventory()


def commands(inv):
    for ext in inv.extensions:
        for entry in (ext.manifest.get("provides", {}) or {}).get("commands", []) or []:
            yield ext, entry


# --- every command says who runs it -------------------------------------------

@pytest.mark.req("REQ-CORE-TIERS-001")
def test_every_command_declares_a_tier(inv):
    missing = [e["name"] for _, e in commands(inv) if e.get("tier") is None]
    assert not missing, f"commands with no tier: {missing}"


@pytest.mark.req("REQ-CORE-TIERS-001")
def test_every_tier_is_one_of_the_four(inv):
    unknown = {e.get("tier") for _, e in commands(inv)} - COMMAND_TIERS
    assert not unknown, f"tiers outside the allowlist: {sorted(unknown)}"


@pytest.mark.req("REQ-CORE-TIERS-001")
def test_the_description_says_who_before_it_says_what(inv):
    # The property that reaches a reader: the tier is invisible in a flattened
    # command list, and the description is not.
    for _, entry in commands(inv):
        clause = TIER_CLAUSE[entry["tier"]]
        assert entry["description"].startswith(clause), (
            f"{entry['name']} description does not open with {clause!r}")


@pytest.mark.req("REQ-CORE-TIERS-001")
def test_the_driver_tier_spans_both_extensions(inv):
    # A tier says who calls a command, not which manifest it sits in. The five
    # work verbs and the board status command are one front door.
    drivers = {e["name"] for _, e in commands(inv) if e["tier"] == "driver"}
    assert "speckit.github-lifecycle.status" in drivers
    assert {f"speckit.work.{v}" for v in
            ("status", "start", "continue", "change", "finish")} <= drivers


@pytest.mark.req("REQ-CORE-TIERS-001")
def test_every_tier_is_used_by_something(inv):
    # An unused tier is a fifth category waiting to be invented.
    assert {e["tier"] for _, e in commands(inv)} == COMMAND_TIERS


# --- the README a person reads agrees with the manifest -----------------------

@pytest.mark.req("REQ-CORE-TIERS-001")
def test_each_readme_lists_the_commands_its_manifest_declares(inv):
    for ext in inv.extensions:
        readme = (ext.path / "README.md").read_text(encoding="utf-8")
        for entry in (ext.manifest.get("provides", {}) or {}).get("commands", []) or []:
            assert f"`{entry['name']}`" in readme, (
                f"{ext.id}/README.md omits {entry['name']}")
            assert f"`{entry['tier']}`" in readme


# --- nothing was renamed ------------------------------------------------------

# The names as they stood before tiering. Written out rather than derived: a
# list generated from the manifest would agree with any rename it described,
# which is the one thing this must not do. 178 references across 33 files, and
# a rename breaks every project that installed the bundle.
#
# A subset check, not equality. Adding a command is ordinary and breaks nobody;
# losing or renaming one breaks every installed project. A rename is both at
# once, and the subset catches its removal half.
FROZEN = {
    "speckit.github-lifecycle." + verb for verb in (
        "inspect board documents plan transition capture link readiness "
        "decompose retire restructure triage risk discover disposal "
        "claude-config opencode-config opencode-layout models ratchet "
        "sensitive exception verify-bootstrap mismatch outcome doctor status"
    ).split()
} | {
    "speckit.work." + verb
    for verb in ("status", "start", "continue", "change", "finish")
}


@pytest.mark.req("REQ-CORE-TIERS-001")
def test_no_command_was_renamed(inv):
    current = {e["name"] for _, e in commands(inv)}
    assert FROZEN <= current, f"names lost or renamed: {sorted(FROZEN - current)}"


@pytest.mark.req("REQ-CORE-TIERS-001")
def test_every_workflow_step_still_resolves(inv):
    referenced = {
        step["command"]
        for comp in inv.by_kind("workflow")
        for step in _walk(comp.manifest.get("steps") or [])
        if step.get("command")
    }
    assert referenced <= inv.provided_commands()
    # And that every frozen name a workflow relies on is still provided. A
    # rename would leave the step resolving to nothing.
    assert FROZEN & referenced <= inv.provided_commands()


def _walk(steps):
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        yield step
        for case in (step.get("cases") or {}).values():
            yield from _walk(case)
        yield from _walk(step.get("steps"))


@pytest.mark.req("REQ-CORE-TIERS-001")
def test_the_manifests_still_parse_after_being_rewritten(inv):
    # The tiering pass rewrote every command entry in place. A block swallowed
    # by that edit -- the config target, the tags -- parses as valid YAML and
    # is simply gone, which no schema would catch.
    gh = yaml.safe_load(
        (EXTENSIONS / "github-lifecycle/extension.yml").read_text(encoding="utf-8"))
    assert gh["provides"]["config"] == [
        {"name": "github-lifecycle-config.yml", "template": "config-template.yml"}]
    assert gh["tags"]
    work = yaml.safe_load(
        (EXTENSIONS / "work/extension.yml").read_text(encoding="utf-8"))
    assert work["tags"]
    assert work["requires"]["python_packages"]


@pytest.mark.req("REQ-CORE-TIERS-001")
def test_the_front_matter_carries_the_clause_because_that_is_what_agents_render(inv):
    """The list a person reads every day comes from the command file.

    A dev install settled this: `specify extension add` prints the manifest
    description once, and the skill or command file it writes carries the
    *front matter* description. Tiering only the manifest would have left every
    rendered command list exactly as flat as before.
    """
    for ext, entry in commands(inv):
        front = re.match(r"^---\n(.*?)\n---\n",
                         (ext.path / entry["file"]).read_text(encoding="utf-8"),
                         re.DOTALL)
        assert front, f"{entry['file']} has no front matter"
        declared = re.search(r"^description:[ \t]*(.*)$", front.group(1),
                             re.MULTILINE)
        assert declared, f"{entry['file']} declares no description"
        assert declared.group(1).strip() == entry["description"].strip()
        assert declared.group(1).startswith(TIER_CLAUSE[entry["tier"]])
