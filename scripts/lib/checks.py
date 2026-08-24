"""The bundle's own invariants, as registered checks.

Deliberately excluded: manifest shape, semver, required fields, and reference
resolution. `specify bundle validate` owns those and is authoritative;
duplicating them here produced a second, weaker implementation that disagreed
with the real one.

What remains is what the official validator cannot know -- the safety and
composition properties this bundle chooses to hold.
"""
from __future__ import annotations

import re
import sys

from pathlib import Path
from typing import Any, Iterator

from .inventory import ROOT, load_yaml
from .registry import Ctx, Finding, check

PLACEHOLDER_SCAN_SUFFIXES = {".md", ".yml", ".yaml", ".json", ".py"}
PLACEHOLDER_EXCLUDED_DIRS = {
    "dist", ".git", ".venv", ".specify", ".claude", "__pycache__", "evidence",
}
PLACEHOLDER = "YOUR-ORG"


def _steps(component) -> list[dict[str, Any]]:
    return component.manifest.get("steps", []) or []


def _args(step: dict) -> str:
    return str((step.get("input") or {}).get("args", ""))


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------

@check("INV-PRESET-COMPOSITION", "Owned preset layers over the external preset",
       scope="bundle")
def preset_composition(ctx: Ctx) -> Iterator[Finding]:
    meta = ctx.inv.meta
    owned = meta.get("owned_preset", {}) or {}
    externals = ctx.inv.external_preset_refs()
    if not externals:
        yield ctx.finding("INV-PRESET-COMPOSITION", "bundle-meta.yml",
                          "no external preset declared to compose over")
        return
    # Lower priority number wins, so the appending preset must sort ahead of
    # the one it appends to, or it has nothing to layer onto.
    for ext in externals:
        if owned.get("priority", 10) >= ext.get("priority", 20):
            yield ctx.finding(
                "INV-PRESET-COMPOSITION", "bundle-meta.yml",
                f"owned preset priority {owned.get('priority')} must be lower than "
                f"external '{ext['id']}' priority {ext.get('priority')}")
    if owned.get("strategy") != "append":
        yield ctx.finding("INV-PRESET-COMPOSITION", "bundle-meta.yml",
                          f"owned preset strategy must be append, got {owned.get('strategy')!r}")


@check("INV-SINGLE-EXTENSION", "The bundle ships exactly one extension", scope="bundle")
def single_extension(ctx: Ctx) -> Iterator[Finding]:
    exts = ctx.inv.by_kind("extension")
    if len(exts) != 1:
        yield ctx.finding("INV-SINGLE-EXTENSION", "bundle",
                          f"expected exactly one extension, found {len(exts)}: "
                          f"{[e.id for e in exts]}")


@check("INV-VERSION-COHERENCE", "Component versions match the bundle version",
       scope="bundle")
def version_coherence(ctx: Ctx) -> Iterator[Finding]:
    for comp in ctx.inv.components:
        if comp.version != ctx.inv.version:
            yield ctx.finding("INV-VERSION-COHERENCE", comp.ref,
                              f"version {comp.version} differs from bundle "
                              f"{ctx.inv.version}")


@check("INV-SPECKIT-PIN", "Every manifest declares the one supported Spec Kit range",
       scope="bundle")
def speckit_pin(ctx: Ctx) -> Iterator[Finding]:
    want = ctx.inv.speckit_version
    for comp in ctx.inv.components:
        got = (comp.manifest.get("requires", {}) or {}).get("speckit_version")
        if got != want:
            yield ctx.finding("INV-SPECKIT-PIN", comp.ref,
                              f"speckit_version {got!r} != {want!r}")


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------

@check("INV-POLICY-MIRROR", "Preset policy is a byte-identical mirror of canonical policy",
       scope="policy")
def policy_mirror(ctx: Ctx) -> Iterator[Finding]:
    canonical = {p.name: p for p in ctx.inv.policies}
    if not canonical:
        yield ctx.finding("INV-POLICY-MIRROR", "policy/", "no canonical policy files found")
        return
    mirror_dir = ctx.inv.preset.path / "policy"
    if not mirror_dir.is_dir():
        yield ctx.finding("INV-POLICY-MIRROR", str(mirror_dir), "preset policy mirror missing")
        return
    mirror = {p.name: p for p in mirror_dir.glob("*.yml")}
    for name in sorted(set(canonical) - set(mirror)):
        yield ctx.finding("INV-POLICY-MIRROR", f"policy/{name}", "missing from preset mirror")
    for name in sorted(set(mirror) - set(canonical)):
        yield ctx.finding("INV-POLICY-MIRROR", f"preset policy/{name}", "not in canonical policy")
    for name in sorted(set(canonical) & set(mirror)):
        if canonical[name].read_bytes() != mirror[name].read_bytes():
            yield ctx.finding("INV-POLICY-MIRROR", f"policy/{name}",
                              "preset mirror differs from canonical copy")


# --------------------------------------------------------------------------
# Workflow safety
# --------------------------------------------------------------------------

@check("SEC-SHELL-ALLOWLIST", "Workflow shell steps run only allowlisted commands",
       scope="workflow")
def shell_allowlist(ctx: Ctx) -> Iterator[Finding]:
    allowed = set(ctx.invariants.get("allowed_shell", []))
    for comp in ctx.inv.by_kind("workflow"):
        for step in _steps(comp):
            if step.get("type") != "shell":
                continue
            run = str(step.get("run", "")).strip()
            if run not in allowed:
                yield ctx.finding("SEC-SHELL-ALLOWLIST", f"{comp.id}:{step.get('id')}",
                                  f"shell command {run!r} is not allowlisted")


@check("SEC-SHELL-NO-INTERPOLATION", "Workflow shell steps interpolate nothing",
       scope="workflow")
def shell_no_interpolation(ctx: Ctx) -> Iterator[Finding]:
    # An interpolated shell step would let workflow inputs, or agent output,
    # decide what executes.
    for comp in ctx.inv.by_kind("workflow"):
        for step in _steps(comp):
            if step.get("type") != "shell":
                continue
            run = str(step.get("run", ""))
            if "{{" in run or "}}" in run:
                yield ctx.finding("SEC-SHELL-NO-INTERPOLATION",
                                  f"{comp.id}:{step.get('id')}",
                                  "shell command contains template interpolation")


@check("SEC-UNTRUSTED-NO-COMMAND-INTERPOLATION",
       "No workflow step interpolates untrusted text into a command",
       scope="workflow")
def untrusted_no_command_interpolation(ctx: Ctx) -> Iterator[Finding]:
    """The enforceable half of "untrusted input never authorizes an action".

    No Python check stops prompt injection reaching an agent's context, and
    a check that claimed to would be worse than none. What is checkable is
    narrower and real: text that arrives from an issue body, a comment or a
    log must not be interpolated into the argument string of a command step.

    Parallel to SEC-SHELL-NO-INTERPOLATION, which guards `type: shell`. This
    guards command steps, where the interpolated value becomes the
    instruction an agent acts on.

    A step naming the issue *reference* -- `inputs.issue_ref` -- is fine and
    is how nearly every step addresses its work. What is refused is
    interpolating the untrusted *content*.
    """
    import re

    # ctx.root, not the module ROOT: a check that reads the real tree cannot
    # be exercised against a mutated copy, which is how its negative test works.
    policy = load_yaml(ctx.root / "policy" / "agent-policy.yml") or {}
    sources = {str(s) for s in (policy.get("untrusted_inputs") or [])}
    if not sources:
        return
    # `{{ ... issue_body ... }}` and friends: the untrusted source named
    # inside an interpolation, not merely mentioned in prose.
    pattern = re.compile(
        r"\{\{[^}]*\b(" + "|".join(re.escape(s) for s in sorted(sources)) + r")\b[^}]*\}\}")
    for comp in ctx.inv.by_kind("workflow"):
        for step in _steps(comp):
            if step.get("type") in ("shell", "gate"):
                continue          # shell has its own check; a gate shows, it does not execute
            args = str(((step.get("input") or {}).get("args")) or "")
            prompt = str(step.get("prompt") or "")
            for field_name, text in (("input.args", args), ("prompt", prompt)):
                found = pattern.search(text)
                if found:
                    yield ctx.finding(
                        "SEC-UNTRUSTED-NO-COMMAND-INTERPOLATION",
                        f"{comp.id}:{step.get('id')}:{field_name}",
                        f"interpolates {found.group(1)!r}, which agent-policy.yml "
                        f"lists as an untrusted input")


@check("INV-BUILD-AFTER-IN-PROGRESS",
       "A workflow transitions an item to In Progress before it implements it",
       scope="workflow")
def build_after_in_progress(ctx: Ctx) -> Iterator[Finding]:
    """The ordering `state-machine.yml` implies and nothing asserted.

    `Ready -> In Progress` takes the evidence `work_started`, which only means
    something if work has not already started. A workflow that implemented
    before transitioning would make that evidence retroactive, and a
    transition asserted after the fact is not evidence.

    `lifecycle-story-delivery` has this order today. It held by construction
    rather than by assertion, so reordering the file would have broken the
    guarantee with nothing failing -- which is the shape of defect #93 is
    about, one layer up.

    Steps are identified by what they do, not by their id: a step is the
    transition if it invokes the transition command and names the start state,
    and the build if it invokes an implementing command. Matching on
    `id: transition-in-progress` would let a rename defeat the check.
    """
    machine = load_yaml(ctx.root / "policy" / "state-machine.yml") or {}
    start = None
    for edge in (machine.get("delivery_status") or {}).get("transitions") or []:
        if "work_started" in (edge.get("evidence") or []):
            start = edge["to"]
    if not start:
        return

    building = {"speckit.implement"}
    for comp in ctx.inv.by_kind("workflow"):
        steps = list(_steps(comp))
        transition_at = build_at = None
        for index, step in enumerate(steps):
            command = str(step.get("command") or "")
            args = str(((step.get("input") or {}).get("args")) or "")
            if (command.endswith(".transition") and start in args
                    and transition_at is None):
                transition_at = index
            if command in building and build_at is None:
                build_at = index
        if build_at is None or transition_at is None:
            # A workflow that does not build, or does not transition, has no
            # ordering to get wrong. Reported by nothing: not every workflow
            # is a delivery workflow.
            continue
        if transition_at > build_at:
            yield ctx.finding(
                "INV-BUILD-AFTER-IN-PROGRESS",
                f"{comp.id}:{steps[build_at].get('id')}",
                f"implements at step {build_at} but only reaches {start!r} at "
                f"step {transition_at}. The evidence `work_started` would be "
                f"asserted after the work started.")


@check("INV-GATE-VERDICT", "Every gate declares a verdict input allowing an empty default",
       scope="workflow")
def gate_verdict(ctx: Ctx) -> Iterator[Finding]:
    for comp in ctx.inv.by_kind("workflow"):
        inputs = comp.manifest.get("inputs", {}) or {}
        for step in _steps(comp):
            if step.get("type") != "gate":
                continue
            name = step.get("verdict_input")
            subject = f"{comp.id}:{step.get('id')}"
            if not name:
                yield ctx.finding("INV-GATE-VERDICT", subject, "gate declares no verdict_input")
                continue
            spec = inputs.get(name)
            if spec is None:
                yield ctx.finding("INV-GATE-VERDICT", subject,
                                  f"verdict_input {name!r} is not a declared input")
                continue
            enum = spec.get("enum")
            if not enum:
                yield ctx.finding("INV-GATE-VERDICT", subject,
                                  f"verdict input {name!r} declares no enum")
            elif "" not in enum:
                # The empty value is the un-answered state; without it the gate
                # cannot represent "not yet decided" and defaults to a verdict.
                yield ctx.finding("INV-GATE-VERDICT", subject,
                                  f"verdict input {name!r} enum lacks the empty default")


@check("INV-GATE-SHAPE", "Gates carry the fields the runner requires",
       scope="workflow")
def gate_shape(ctx: Ctx) -> Iterator[Finding]:
    # Found by installing a workflow rather than by validating it: the runner
    # rejects a gate with no `message`, and a gate written with `prompt`
    # instead passed every local check while being unusable.
    for comp in ctx.inv.by_kind("workflow"):
        for step in _steps(comp):
            if step.get("type") != "gate":
                continue
            subject = f"{comp.id}:{step.get('id')}"
            if not str(step.get("message", "")).strip():
                yield ctx.finding("INV-GATE-SHAPE", subject,
                                  "gate has no 'message'; the runner refuses it")
            options = step.get("options") or []
            if "approve" not in options or "reject" not in options:
                yield ctx.finding("INV-GATE-SHAPE", subject,
                                  f"gate options {options!r} must offer approve and reject")
            if step.get("on_reject") != "abort":
                yield ctx.finding("INV-GATE-SHAPE", subject,
                                  f"on_reject is {step.get('on_reject')!r}; a rejected "
                                  f"gate must stop the run")
            if "prompt" in step:
                yield ctx.finding("INV-GATE-SHAPE", subject,
                                  "gate uses 'prompt'; the runner reads 'message'")


@check("INV-COMMAND-RESOLVES", "Every workflow step references a provided command",
       scope="workflow")
def command_resolves(ctx: Ctx) -> Iterator[Finding]:
    provided = ctx.inv.provided_commands()
    for comp in ctx.inv.by_kind("workflow"):
        for step in _steps(comp):
            cmd = step.get("command")
            if cmd and cmd not in provided:
                yield ctx.finding("INV-COMMAND-RESOLVES", f"{comp.id}:{step.get('id')}",
                                  f"command {cmd!r} is provided by no component")


@check("SEC-WRITE-BEHIND-GATE", "Every state-mutating step sits behind an approval gate",
       scope="workflow")
def write_behind_gate(ctx: Ctx) -> Iterator[Finding]:
    writes = set(ctx.invariants.get("write_effect_commands", []))
    for comp in ctx.inv.by_kind("workflow"):
        steps = _steps(comp)
        for i, step in enumerate(steps):
            if step.get("command") not in writes:
                continue
            if not any(s.get("type") == "gate" for s in steps[:i]):
                yield ctx.finding("SEC-WRITE-BEHIND-GATE", f"{comp.id}:{step.get('id')}",
                                  f"{step['command']} has no prior approval gate")


@check("SEC-TRANSITION-CONTRACT", "Transitions apply a named, previously planned change",
       scope="workflow")
def transition_contract(ctx: Ctx) -> Iterator[Finding]:
    plan_cmd = ctx.invariants.get("plan_command")
    transition = "speckit.github-lifecycle.transition"
    for comp in ctx.inv.by_kind("workflow"):
        steps = _steps(comp)
        for i, step in enumerate(steps):
            if step.get("command") != transition:
                continue
            subject = f"{comp.id}:{step.get('id')}"
            args = _args(step)
            if "Approved plan:" not in args:
                yield ctx.finding("SEC-TRANSITION-CONTRACT", subject,
                                  "transition does not name an approved plan")
                continue
            match = re.search(r"Approved plan:\s*(.+?\.md)", args, flags=re.DOTALL)
            if not match:
                yield ctx.finding("SEC-TRANSITION-CONTRACT", subject,
                                  "approved plan path is not explicit")
                continue
            wanted = _norm(match.group(1))
            planned = []
            for prior in steps[:i]:
                if prior.get("command") != plan_cmd:
                    continue
                m = re.search(r"Write exactly\s*(.+?\.md)", _args(prior), flags=re.DOTALL)
                if m:
                    planned.append(_norm(m.group(1)))
            if not planned:
                yield ctx.finding("SEC-TRANSITION-CONTRACT", subject,
                                  "no prior plan step writes a plan file")
            elif wanted not in planned:
                yield ctx.finding("SEC-TRANSITION-CONTRACT", subject,
                                  f"plan path {wanted!r} matches no prior plan {planned!r}")


# --------------------------------------------------------------------------
# Extension safety
# --------------------------------------------------------------------------

@check("SEC-EXTENSION-CONFIG-SAFETY", "Extension config template keeps its safety defaults",
       scope="extension")
def extension_config_safety(ctx: Ctx) -> Iterator[Finding]:
    from .inventory import load_yaml

    required = ctx.invariants.get("extension_config_safety", {}) or {}
    ext = ctx.inv.extension
    template = ext.path / "config-template.yml"
    if not template.is_file():
        yield ctx.finding("SEC-EXTENSION-CONFIG-SAFETY", ext.ref, "config template missing")
        return
    safety = (load_yaml(template).get("safety", {}) or {})
    for key, want in required.items():
        if safety.get(key) != want:
            yield ctx.finding("SEC-EXTENSION-CONFIG-SAFETY", f"{ext.ref}:{key}",
                              f"expected {want!r}, got {safety.get(key)!r}")


@check("SEC-NO-ORG-SCHEMA-MUTATION",
       "No script mutates an organization's Issue Field schema",
       scope="extension")
def no_org_schema_mutation(ctx: Ctx) -> Iterator[Finding]:
    """docs/security.md claims the bundle performs no organization schema
    mutation. This is what makes that a checked fact rather than a sentence.

    It replaced `allow_organization_schema_mutation: false`, a config default
    no code read. A switch that gates nothing is the same defect as a scenario
    that tests nothing, and the honest form of the promise is a check that the
    path does not exist.

    Reading `orgs/<org>/issue-fields` is fine and is how the backend discovers
    whether the organization carries a delivery-state field at all. Writing to
    it is what nothing here does.
    """
    import re

    ext = ctx.inv.extension
    # A write is a non-GET method aimed at the organization issue-fields
    # collection. Matched on the same line, because these calls are written as
    # one `gh.rest(method, url)` expression throughout the extension.
    write = re.compile(
        r"""(?ix)
        (POST|PATCH|PUT|DELETE)      # a mutating method
        .*?
        orgs/ [^"'\s]* /? issue[-_]fields
        """)
    for script in sorted((ext.path / "scripts").glob("*.py")):
        for number, line in enumerate(
                script.read_text(encoding="utf-8").splitlines(), 1):
            if write.search(line):
                yield ctx.finding(
                    "SEC-NO-ORG-SCHEMA-MUTATION",
                    f"{script.name}:{number}",
                    "writes to an organization Issue Field schema; "
                    "docs/security.md says the bundle performs none")


@check("SEC-COMMAND-SCRIPT-BACKED",
       "Commands that reach GitHub invoke a script rather than describe calls",
       scope="extension")
def command_script_backed(ctx: Ctx) -> Iterator[Finding]:
    import re

    required = set(ctx.invariants.get("script_backed_commands", []) or [])
    if not required:
        return
    ext = ctx.inv.extension
    for entry in (ext.manifest.get("provides", {}) or {}).get("commands", []) or []:
        short = str(entry.get("name", "")).rsplit(".", 1)[-1]
        if short not in required:
            continue
        path = ext.path / str(entry.get("file", ""))
        if not path.is_file():
            yield ctx.finding("SEC-COMMAND-SCRIPT-BACKED", f"{ext.ref}:{short}",
                              "command file missing")
            continue
        text = path.read_text(encoding="utf-8")
        invoked = re.findall(r"scripts/([A-Za-z_][A-Za-z0-9_]*\.py)", text)
        if not invoked:
            yield ctx.finding(
                "SEC-COMMAND-SCRIPT-BACKED", f"{ext.ref}:{short}",
                "invokes no script; the agent is left to decide how to reach "
                "the API, which the deterministic adapter exists to prevent")
            continue
        for script in set(invoked):
            if not (ext.path / "scripts" / script).is_file():
                yield ctx.finding("SEC-COMMAND-SCRIPT-BACKED",
                                  f"{ext.ref}:{short}",
                                  f"invokes {script!r}, which does not exist")


@check("INV-EXTENSION-CONFIG-NAME", "Extension config targets a name Spec Kit preserves",
       scope="extension")
def extension_config_name(ctx: Ctx) -> Iterator[Finding]:
    # Spec Kit only scaffolds, backs up, and restores top-level *-config.yml or
    # *-config.local.yml. Any other target is silently never created.
    ext = ctx.inv.extension
    for entry in (ext.manifest.get("provides", {}) or {}).get("config", []) or []:
        name = str(entry.get("name", ""))
        if "/" in name or "\\" in name or not name.endswith(
            ("-config.yml", "-config.local.yml")
        ):
            yield ctx.finding("INV-EXTENSION-CONFIG-NAME", f"{ext.ref}:{name}",
                              "config target must be a top-level *-config.yml file")


# --------------------------------------------------------------------------
# Backlog item contract
# --------------------------------------------------------------------------

@check("INV-ITEM-CONTENT", "Every item type defines the content it requires",
       scope="policy")
def item_content(ctx: Ctx) -> Iterator[Finding]:
    from .inventory import load_yaml

    policy_path = ctx.root / "policy" / "item-types.yml"
    if not policy_path.is_file():
        yield ctx.finding("INV-ITEM-CONTENT", "policy/item-types.yml", "missing")
        return
    policy = load_yaml(policy_path)

    types = policy.get("types") or {}
    if not types:
        yield ctx.finding("INV-ITEM-CONTENT", "policy/item-types.yml", "defines no types")
        return

    for type_id, spec in types.items():
        subject = f"item-type:{type_id}"
        for key in ("name", "description", "sections"):
            if not spec.get(key):
                yield ctx.finding("INV-ITEM-CONTENT", subject, f"missing {key!r}")
        # A type whose sections are all optional imposes no contract at all.
        sections = spec.get("sections") or []
        if sections and not any(sec.get("required") for sec in sections):
            yield ctx.finding("INV-ITEM-CONTENT", subject,
                              "no section is required, so the type contracts nothing")
        for sec in sections:
            for key in ("id", "label", "prompt"):
                if not sec.get(key):
                    yield ctx.finding("INV-ITEM-CONTENT",
                                      f"{subject}:{sec.get('id', '?')}",
                                      f"section missing {key!r}")

    # Severity is scoped to Bug by github-schema.yml; the two must agree.
    schema = load_yaml(ctx.root / "policy" / "github-schema.yml")
    severity = ((schema.get("issue_fields") or {}).get("Severity") or {})
    applies = {str(x).lower() for x in (severity.get("applies_to") or [])}
    carries = {t for t, spec in types.items() if spec.get("carries_severity")}
    if applies and applies != carries:
        yield ctx.finding("INV-ITEM-CONTENT", "policy",
                          f"Severity applies_to {sorted(applies)} in github-schema.yml "
                          f"but carries_severity is set on {sorted(carries)}")

    verdict = policy.get("readiness_verdict") or {}
    if not verdict.get("fields"):
        yield ctx.finding("INV-ITEM-CONTENT", "readiness_verdict",
                          "state-machine.yml requires this evidence; its shape is undefined")


# --------------------------------------------------------------------------
# Publishing
# --------------------------------------------------------------------------

@check("PUB-NO-PLACEHOLDER", "No publishing placeholder remains in the source",
       scope="repo", strict_publish_only=True)
def no_placeholder(ctx: Ctx) -> Iterator[Finding]:
    for path in sorted(ctx.root.rglob("*")):
        if not path.is_file() or path.suffix not in PLACEHOLDER_SCAN_SUFFIXES:
            continue
        if PLACEHOLDER_EXCLUDED_DIRS.intersection(path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if PLACEHOLDER in text:
            yield ctx.finding("PUB-NO-PLACEHOLDER", str(path.relative_to(ctx.root)),
                              f"contains {PLACEHOLDER}")


@check("PUB-CATALOG-ROOT", "Catalogs point at a real published root",
       scope="repo", strict_publish_only=True)
def catalog_root(ctx: Ctx) -> Iterator[Finding]:
    pub = (ctx.inv.meta.get("publishing", {}) or {})
    if not pub.get("org"):
        yield ctx.finding("PUB-CATALOG-ROOT", "tooling/bundle-meta.yml",
                          "publishing.org is unset; catalogs emit UNSET download URLs")


@check("INV-INTEGRATION-DEFAULT", "No workflow names a specific agent",
       scope="workflow")
def integration_default(ctx: Ctx) -> Iterator[Finding]:
    # Fifteen workflows shipped with `default: opencode`, so a project
    # initialized with any other agent still dispatched to that one. Spec Kit's
    # engine resolves the `auto` sentinel to the project's configured
    # integration at run time and exempts it from enum validation specifically.
    #
    # Registered rather than fixed once: the next workflow is written by
    # copying its neighbour, and that is how the default would come back.
    expected = ctx.invariants["integration_default"]
    for comp in ctx.inv.by_kind("workflow"):
        spec = ((comp.manifest.get("inputs") or {}).get("integration") or {})
        if "default" not in spec:
            continue
        default = spec["default"]
        if default != expected:
            yield ctx.finding(
                "INV-INTEGRATION-DEFAULT", comp.id,
                f"integration default is {default!r}; must be {expected!r} so "
                f"the project's own integration is used")


@check("PUB-COMPAT-CLAIM", "Every compatibility claim names a test that exists",
       scope="bundle")
def compat_claims(ctx: Ctx) -> Iterator[Finding]:
    # The matrix is a public claim about what works under which agent. A row
    # naming a test that does not exist is the same failure as an over-claimed
    # coverage rating: it reads as evidence and is not.
    import subprocess

    # ctx.root, not the module ROOT: a check that reads the real tree cannot be
    # exercised by a negative fixture, which copies the tree and breaks the
    # copy. The first version of this check did exactly that and its fixture
    # could not make it fail.
    matrix = ctx.root / "tooling/compatibility.yml"
    if not matrix.is_file():
        return
    compat = load_yaml(matrix)

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "--no-header", "-p", "no:cacheprovider"],
        cwd=ctx.root, capture_output=True, text=True)
    known = {line.strip() for line in collected.stdout.splitlines()
             if "::" in line}
    if not known:
        yield ctx.finding("PUB-COMPAT-CLAIM", "tooling/compatibility.yml",
                          "could not collect the test suite, so no claim was "
                          "verified; an unverified matrix is not a checked one")
        return

    capabilities = set(compat["capabilities"])
    for integration, entries in (compat["integrations"] or {}).items():
        for capability, tests in (entries or {}).items():
            subject = f"compatibility:{integration}.{capability}"
            if capability not in capabilities:
                yield ctx.finding("PUB-COMPAT-CLAIM", subject,
                                  f"{capability!r} is not a declared capability")
            for node in tests or []:
                if node not in known:
                    yield ctx.finding(
                        "PUB-COMPAT-CLAIM", subject,
                        f"claims {node}, which the suite does not collect")


@check("INV-SCRIPT-FLAVOUR", "Commands invoke only a script flavour the extension ships",
       scope="extension")
def script_flavour(ctx: Ctx) -> Iterator[Finding]:
    # Every command here invokes a Python script, and the manifest did not say
    # so: `requires.tools` listed `gh` alone. A project that chose `--script sh`
    # got no warning until a command failed.
    #
    # The rule is not "be portable". It is "reference only what you ship, and
    # declare what you need" -- reimplementing thirteen scripts in shell would
    # produce a second copy that drifts, and the drifting one is untested.
    policy = load_yaml(ctx.root / "policy/bootstrap-policy.yml")
    flavours = policy.get("script_flavours") or {}
    provided = set(flavours.get("provided") or [])
    if not provided:
        return

    suffixes = {"py": ".py", "sh": ".sh", "ps1": ".ps1"}
    allowed = {suffixes[f] for f in provided if f in suffixes}

    for comp in ctx.inv.by_kind("extension"):
        scripts = comp.path / "scripts"
        shipped = {p.name for p in scripts.glob("*")} if scripts.is_dir() else set()
        needs_python = False
        for entry in comp.manifest["provides"]["commands"]:
            doc = comp.path / entry["file"]
            if not doc.is_file():
                continue
            text = doc.read_text(encoding="utf-8")
            for match in re.finditer(r"scripts/([A-Za-z0-9_.-]+\.(?:py|sh|ps1))",
                                     text):
                name = match.group(1)
                subject = f"{comp.id}:{entry['name']}"
                if Path(name).suffix not in allowed:
                    yield ctx.finding(
                        "INV-SCRIPT-FLAVOUR", subject,
                        f"invokes {name}, a flavour this extension does not "
                        f"ship (provides {sorted(provided)})")
                elif name not in shipped:
                    yield ctx.finding(
                        "INV-SCRIPT-FLAVOUR", subject,
                        f"invokes {name}, which is not in scripts/")
                if Path(name).suffix == ".py":
                    needs_python = True

        declared = {t["name"] for t in (comp.manifest["requires"].get("tools") or [])}
        if needs_python and not declared & {"python", "python3"}:
            yield ctx.finding(
                "INV-SCRIPT-FLAVOUR", comp.id,
                "commands invoke Python scripts and requires.tools does not "
                "declare python; a project learns the dependency when a "
                "command fails")
