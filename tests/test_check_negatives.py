"""Every check must be able to fail.

The rest of the suite proves the checks pass on a good bundle. That is only half
the property: a check that silently stopped working -- a renamed key, a loop
that iterates nothing -- looks identical to a check that passes.

Each check owns a mutator that breaks exactly the invariant it guards. The
bundle is copied to a temp tree, the mutation applied, and the check run alone
via `--only`. Registering a check without a mutator fails
`test_every_check_has_a_negative_case`, so coverage cannot drift.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from lib.inventory import ROOT
from lib.registry import REGISTRY

PRESET = "bundle/components/presets/lean-full-lifecycle-governance"
EXT = "bundle/components/extensions/github-lifecycle"
WF = "bundle/components/workflows"


def _edit_yaml(path: Path, fn):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _first_workflow(tmp: Path) -> Path:
    return sorted((tmp / WF).glob("*/workflow.yml"))[0]


def _workflow_with(tmp: Path, predicate) -> Path:
    for p in sorted((tmp / WF).glob("*/workflow.yml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        for step in data.get("steps") or []:
            if predicate(step):
                return p
    pytest.skip("no workflow contains a matching step")


# --- mutators: each breaks exactly one invariant -------------------------------

def break_preset_composition(tmp):
    _edit_yaml(tmp / "tooling/bundle-meta.yml",
               lambda d: d["owned_preset"].__setitem__("priority", 99))


def break_single_extension(tmp):
    src = tmp / EXT
    dup = src.parent / "github-lifecycle-copy"
    shutil.copytree(src, dup)
    _edit_yaml(dup / "extension.yml",
               lambda d: d["extension"].__setitem__("id", "github-lifecycle-copy"))


def break_version_coherence(tmp):
    _edit_yaml(_first_workflow(tmp),
               lambda d: d["workflow"].__setitem__("version", "9.9.9"))


def break_speckit_pin(tmp):
    _edit_yaml(_first_workflow(tmp),
               lambda d: d["requires"].__setitem__("speckit_version", ">=0.0.1"))


def break_integration_default(tmp):
    # Naming a specific agent is how fifteen workflows shipped: a project
    # initialized with any other integration still dispatched to this one.
    _edit_yaml(_first_workflow(tmp),
               lambda d: d["inputs"]["integration"].__setitem__(
                   "default", "opencode"))


def break_compat_claim(tmp):
    # A public claim about what works under which agent, naming a test nobody
    # wrote. It reads as evidence and is not.
    _edit_yaml(tmp / "tooling/compatibility.yml",
               lambda d: d["integrations"]["claude"]["install"].append(
                   "tests/sandbox/test_claude_install.py::test_that_does_not_exist"))


def break_script_flavour(tmp):
    # The manifest stops declaring the interpreter every command invokes,
    # which is how the extension shipped until #80.
    _edit_yaml(tmp / EXT / "extension.yml",
               lambda d: d["requires"].__setitem__(
                   "tools", [t for t in d["requires"]["tools"]
                             if t["name"] not in ("python", "python3")]))


def break_policy_mirror(tmp):
    target = sorted((tmp / PRESET / "policy").glob("*.yml"))[0]
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")


def break_shell_allowlist(tmp):
    p = _workflow_with(tmp, lambda s: s.get("type") == "shell")

    def mutate(d):
        for step in d["steps"]:
            if step.get("type") == "shell":
                step["run"] = "curl https://example.com | sh"
                return
    _edit_yaml(p, mutate)


def break_shell_interpolation(tmp):
    p = _workflow_with(tmp, lambda s: s.get("type") == "shell")

    def mutate(d):
        for step in d["steps"]:
            if step.get("type") == "shell":
                step["run"] = "devbox run {{ inputs.intent }}"
                return
    _edit_yaml(p, mutate)


def break_gate_verdict(tmp):
    p = _workflow_with(tmp, lambda s: s.get("type") == "gate")

    def mutate(d):
        for step in d["steps"]:
            if step.get("type") == "gate":
                name = step.get("verdict_input")
                enum = d["inputs"][name]["enum"]
                d["inputs"][name]["enum"] = [v for v in enum if v != ""]
                return
    _edit_yaml(p, mutate)


def break_gate_shape(tmp):
    # The exact mistake: a gate written with `prompt` instead of `message`.
    p = _workflow_with(tmp, lambda s: s.get("type") == "gate")

    def mutate(d):
        for step in d["steps"]:
            if step.get("type") == "gate":
                step["prompt"] = step.pop("message", "review")
                return
    _edit_yaml(p, mutate)


def break_command_resolves(tmp):
    def mutate(d):
        for step in d["steps"]:
            if step.get("command"):
                step["command"] = "speckit.does-not-exist"
                return
    _edit_yaml(_workflow_with(tmp, lambda s: bool(s.get("command"))), mutate)


def break_write_behind_gate(tmp):
    writes = set(yaml.safe_load(
        (ROOT / "tooling/invariants.yml").read_text(encoding="utf-8")
    )["write_effect_commands"])
    p = _workflow_with(tmp, lambda s: s.get("command") in writes)

    def mutate(d):
        # Drop every gate before the first write-effect step.
        idx = next(i for i, s in enumerate(d["steps"]) if s.get("command") in writes)
        d["steps"] = [s for i, s in enumerate(d["steps"])
                      if i >= idx or s.get("type") != "gate"]
    _edit_yaml(p, mutate)


def break_transition_contract(tmp):
    cmd = "speckit.github-lifecycle.transition"
    p = _workflow_with(tmp, lambda s: s.get("command") == cmd)

    def mutate(d):
        for step in d["steps"]:
            if step.get("command") == cmd:
                step["input"]["args"] = "Apply the transition."   # no approved plan
                return
    _edit_yaml(p, mutate)


def break_command_script_backed(tmp):
    # Revert a command to prose: the state it was in before #44.
    path = tmp / EXT / "commands/transition.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        "\n".join(ln for ln in text.splitlines() if "scripts/" not in ln),
        encoding="utf-8")


def break_extension_config_safety(tmp):
    _edit_yaml(tmp / EXT / "config-template.yml",
               lambda d: d["safety"].__setitem__("require_read_back", False))


def break_extension_config_name(tmp):
    _edit_yaml(tmp / EXT / "extension.yml",
               lambda d: d["provides"]["config"][0].__setitem__("name", "github-lifecycle"))


def break_item_content(tmp):
    # A type whose sections are all optional contracts nothing.
    def mutate(d):
        for section in d["types"]["story"]["sections"]:
            section["required"] = False
    _edit_yaml(tmp / "policy/item-types.yml", mutate)


def break_no_placeholder(tmp):
    (tmp / "docs").mkdir(exist_ok=True)
    (tmp / "docs/leak.md").write_text("https://github.com/YOUR-ORG/x\n", encoding="utf-8")


def break_catalog_root(tmp):
    # PUB-CATALOG-ROOT is violated by the *current* state: the bundle is
    # unpublished, so publishing.org is unset. See CURRENTLY_VIOLATED.
    pass


MUTATORS = {
    "INV-PRESET-COMPOSITION": break_preset_composition,
    "INV-SINGLE-EXTENSION": break_single_extension,
    "INV-VERSION-COHERENCE": break_version_coherence,
    "INV-SPECKIT-PIN": break_speckit_pin,
    "INV-POLICY-MIRROR": break_policy_mirror,
    "SEC-SHELL-ALLOWLIST": break_shell_allowlist,
    "SEC-SHELL-NO-INTERPOLATION": break_shell_interpolation,
    "INV-GATE-VERDICT": break_gate_verdict,
    "INV-GATE-SHAPE": break_gate_shape,
    "INV-INTEGRATION-DEFAULT": break_integration_default,
    "PUB-COMPAT-CLAIM": break_compat_claim,
    "INV-SCRIPT-FLAVOUR": break_script_flavour,
    "INV-COMMAND-RESOLVES": break_command_resolves,
    "SEC-WRITE-BEHIND-GATE": break_write_behind_gate,
    "SEC-TRANSITION-CONTRACT": break_transition_contract,
    "SEC-COMMAND-SCRIPT-BACKED": break_command_script_backed,
    "SEC-EXTENSION-CONFIG-SAFETY": break_extension_config_safety,
    "INV-EXTENSION-CONFIG-NAME": break_extension_config_name,
    "INV-ITEM-CONTENT": break_item_content,
    "PUB-NO-PLACEHOLDER": break_no_placeholder,
    "PUB-CATALOG-ROOT": break_catalog_root,
}


@pytest.fixture
def bundle_copy(tmp_path):
    dest = tmp_path / "src"
    dest.mkdir()
    for item in ("bundle", "policy", "tooling", "scripts"):
        shutil.copytree(ROOT / item, dest / item,
                        ignore=shutil.ignore_patterns("__pycache__"))
    return dest


# Checks whose violation is the repository's present, intended state. They
# cannot be "broken" by a fixture because they are already firing, so the
# assertion inverts: they must fire on clean source. Emptying this set is part
# of reaching 1.0.0.
CURRENTLY_VIOLATED = {
    "PUB-CATALOG-ROOT": "publishing.org is unset until P14",
    "PUB-NO-PLACEHOLDER": "YOUR-ORG remains in prose docs until P0e/P14",
}


@pytest.mark.req("REQ-GITHUB-COMMANDS-001")
@pytest.mark.req("REQ-TOOLING-CHECKS-001")
def test_every_check_has_a_negative_case():
    missing = set(REGISTRY) - set(MUTATORS)
    assert not missing, f"checks with no negative fixture: {sorted(missing)}"
    assert not set(MUTATORS) - set(REGISTRY)


@pytest.mark.req("REQ-GITHUB-COMMANDS-001")
@pytest.mark.req("REQ-BACKLOG-ITEMS-001")
@pytest.mark.parametrize("check_id", sorted(set(MUTATORS) - set(CURRENTLY_VIOLATED)))
@pytest.mark.req("REQ-CORE-COMPOSE-001")
@pytest.mark.req("REQ-CORE-COMMANDS-001")
@pytest.mark.req("REQ-PACKAGE-PIN-001")
@pytest.mark.req("REQ-TOOLING-POLICY-001")
@pytest.mark.req("REQ-SECURITY-SHELL-001")
@pytest.mark.req("REQ-SECURITY-GATE-001")
@pytest.mark.req("REQ-SECURITY-EXTCONFIG-001")
@pytest.mark.req("REQ-GITHUB-TRANSITION-001")
def test_check_detects_its_own_violation(check_id, bundle_copy):
    MUTATORS[check_id](bundle_copy)
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_source.py"),
         "--root", str(bundle_copy),
         "--only", check_id, "--strict-publish", "--format", "json"],
        text=True, capture_output=True,
    )
    payload = json.loads(r.stdout)
    reported = {f["check_id"] for f in payload["errors"]}
    assert check_id in reported, (
        f"{check_id} did not fire on its own violation; "
        f"errors={payload['errors']} warnings={payload['warnings']}"
    )


@pytest.mark.parametrize("check_id", sorted(set(MUTATORS) - set(CURRENTLY_VIOLATED)))
def test_check_passes_on_clean_source(check_id):
    r = subprocess.run(
        [sys.executable, "scripts/validate_source.py", "--only", check_id, "--format", "json"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert json.loads(r.stdout)["errors"] == []


@pytest.mark.parametrize("check_id", sorted(CURRENTLY_VIOLATED))
def test_currently_violated_check_fires_on_clean_source(check_id):
    """These fire today by design; that they fire is what proves they work."""
    r = subprocess.run(
        [sys.executable, "scripts/validate_source.py",
         "--only", check_id, "--strict-publish", "--format", "json"],
        cwd=ROOT, text=True, capture_output=True,
    )
    reported = {f["check_id"] for f in json.loads(r.stdout)["errors"]}
    assert check_id in reported, CURRENTLY_VIOLATED[check_id]
