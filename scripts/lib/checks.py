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
from pathlib import Path
from typing import Any, Iterator

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
