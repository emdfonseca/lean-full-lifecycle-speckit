"""The bundle's own invariants, as registered checks.

Deliberately excluded: manifest shape, semver, required fields, and reference
resolution. `specify bundle validate` owns those and is authoritative;
duplicating them here produced a second, weaker implementation that disagreed
with the real one.

What remains is what the official validator cannot know -- the safety and
composition properties this bundle chooses to hold.
"""
from __future__ import annotations

import ast
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

# The standard library, for deciding whether an import needs declaring.
# `sys.stdlib_module_names` is 3.10+, and this repository's own scripts must
# stay runnable on the floor they declare, so the fallback is not decorative.
try:
    STDLIB_MODULES = frozenset(sys.stdlib_module_names)
except AttributeError:  # pragma: no cover -- only on < 3.10
    STDLIB_MODULES = frozenset({
        "argparse", "ast", "base64", "collections", "contextlib", "copy",
        "csv", "dataclasses", "datetime", "difflib", "enum", "errno",
        "fnmatch", "functools", "glob", "hashlib", "html", "http", "importlib",
        "inspect", "io", "itertools", "json", "logging", "math", "os",
        "pathlib", "platform", "posixpath", "random", "re", "shlex", "shutil",
        "signal", "socket", "string", "subprocess", "sys", "tempfile",
        "textwrap", "time", "traceback", "types", "typing", "unicodedata",
        "urllib", "uuid", "warnings", "zipfile",
    })

# Phrases that can only mean a document budget exists. Stating that length is
# not budgeted is not one of them, which is why these are instructions rather
# than the word itself.
BUDGET_INSTRUCTIONS = (
    "over budget",
    "under budget",
    "within budget",
    "obey the budget",
    "budgets are the point",
    "with the overage",
    "max_lines",
)


def _steps(component) -> list[dict[str, Any]]:
    """Every step in the workflow, descending into switch cases.

    A step is not exempt from a safety invariant for sitting in a branch, and a
    workflow can hold more of its steps inside cases than outside them. Walking
    only the outer list is therefore not a smaller check but an arbitrary one:
    what it covers depends on where an author happened to put a step.
    """
    return list(_flatten(component.manifest.get("steps", []) or []))


def _flatten(steps) -> Iterator[dict[str, Any]]:
    for step in steps:
        if step.get("type") == "switch":
            for case in (step.get("cases") or {}).values():
                yield from _flatten(case)
        else:
            yield step


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


@check("INV-DECLARED-IMPORTS",
       "Every third-party import a shipped script makes is declared",
       scope="extension")
def declared_imports(ctx: Ctx) -> Iterator[Finding]:
    """An undeclared dependency is a script that runs here and nowhere else.

    23 of the extension's 31 scripts import `yaml`, and nothing declared
    PyYAML. `{SCRIPT}` resolves to whichever `python3` the CLI finds, which on a
    normal machine has no PyYAML, so a greenfield pilot got an ImportError from
    every command that reads policy (#132).

    This checks the declaration, not the runtime. Whether the interpreter in
    front of a user satisfies it is not something the suite can assume, and
    checking the declaration is what catches the *next* undeclared import
    rather than this one.
    """
    import ast

    ext = next((c for c in ctx.inv.by_kind("extension")), None)
    if ext is None:
        return
    requires = (ext.manifest.get("requires") or {})
    declared = {str(pkg.get("import_name") or pkg.get("name") or "").lower()
                for pkg in (requires.get("python_packages") or [])}

    scripts_dir = ext.path / "scripts"
    if not scripts_dir.is_dir():
        return
    local = {p.stem for p in scripts_dir.glob("*.py")}

    for path in sorted(scripts_dir.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]] if node.level == 0 else []
            else:
                continue
            for name in names:
                if not name or name in local or name in STDLIB_MODULES:
                    continue
                if name.lower() in declared:
                    continue
                yield ctx.finding(
                    "INV-DECLARED-IMPORTS",
                    f"{path.relative_to(ctx.root)}",
                    f"imports {name!r}, which extension.yml does not declare "
                    f"under requires.python_packages. A script whose "
                    f"dependency is undeclared runs on the author's machine "
                    f"and nowhere else")


@check("INV-RELEASE-LADDER",
       "The shipped version is not behind the next fully verified release",
       scope="bundle")
def release_ladder(ctx: Ctx) -> Iterator[Finding]:
    """A release ladder nothing walks.

    The roadmap declares five releases. What nothing required was that the
    number ever move: 0.1.0 was written once and four rungs' worth of verified
    work accumulated underneath it.

    Only the *next* rung is considered. Reporting every fully verified release
    would have asked for a jump to 0.9.0 while three pilot streams were still
    open -- a ladder is climbed in order, and the rung above the one you have
    not taken says nothing about where you are.

    A rung needs more than its requirements. `gates:` in the same file declares
    the rest -- 0.9.0 asks for four completed pilot streams -- and a rung whose
    gate is not `passed` is silent here.

    Even with both read, this warns rather than refuses. Requirement status and
    a declared gate are what it can see; whether to cut a release is a
    judgement, and a check that refused the build would be making it.
    """
    requirements = load_yaml(ctx.root / "tooling/requirements/requirements.yml") or {}
    reqs = requirements.get("requirements") or []
    if not reqs:
        yield ctx.finding(
            "INV-RELEASE-LADDER", "tooling/requirements/requirements.yml",
            "the requirements list is absent or empty, so this check has nothing to "
            "hold anything to. Refusing rather than passing silently: a "
            "check that no-ops on a missing input reports a coverage it "
            "does not have")
        return

    def parts(version: str) -> tuple[int, ...]:
        try:
            return tuple(int(n) for n in str(version).split("."))
        except ValueError:
            return ()

    shipped = parts(ctx.inv.version)
    if not shipped:
        return

    by_release: dict[str, list[str]] = {}
    for req in reqs:
        release = str(req.get("release") or "").strip()
        if release and parts(release) > shipped:
            by_release.setdefault(release, []).append(
                bool(req.get("verified_by")))
    if not by_release:
        return

    nxt = min(by_release, key=parts)
    # "Every requirement for the next rung cites a test." This read a `status`
    # field, which every requirement set to `verified` -- one value of four, so
    # it distinguished nothing and the rung was "fully verified" by assertion.
    # Citing a test is a claim the traceability check tests against collected
    # pytest nodes, so it can be false.
    if not all(by_release[nxt]):
        return

    # `gates:` declares what a rung needs beyond its requirements -- 0.9.0 asks
    # for four completed pilot streams. A rung with an unmet gate is silent:
    # every requirement passing is not the same as the release being ready, and
    # this file already says so.
    # `met`, not `passed`: requirements.schema.json permits only `pending` and
    # `met`, so comparing against `passed` made every gate read as pending and
    # this check return early every time. It has never fired for 0.9.0 or
    # 1.0.0, the only two releases that declare gates, and nothing noticed
    # because its own negative-case mutator is `pass`.
    pending = [gate for gate in (requirements.get("gates") or [])
               if str(gate.get("release") or "").strip() == nxt
               and str(gate.get("status") or "").strip() != "met"]
    if pending:
        return
    # A warning, not an error. What this knows is which requirements cite a
    # test, and a
    # roadmap exit condition can require more -- 0.9.0 asks for four completed
    # pilots, which no `status` field records. Refusing the build would force a
    # release decision on evidence this check does not have.
    yield ctx.finding(
        "INV-RELEASE-LADDER", "tooling/bundle-meta.yml",
        f"ships {ctx.inv.version} while all {len(by_release[nxt])} requirements for "
        f"{nxt} are verified. Cut it, or record what its exit condition still "
        f"needs", severity="warning")


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
        yield ctx.finding(
            "SEC-UNTRUSTED-NO-COMMAND-INTERPOLATION", "policy/agent-policy.yml",
            "untrusted_inputs is absent or empty, so this check has nothing to "
            "hold anything to. Refusing rather than passing silently: a "
            "check that no-ops on a missing input reports a coverage it "
            "does not have")
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
        yield ctx.finding(
            "INV-BUILD-AFTER-IN-PROGRESS", "policy/state-machine.yml",
            "the In Progress state is absent or empty, so this check has nothing to "
            "hold anything to. Refusing rather than passing silently: a "
            "check that no-ops on a missing input reports a coverage it "
            "does not have")
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


# Directives that change a codebase, as against ones that write a record. The
# verb must open a sentence: `validate-adoption` says "build paths, and absence
# of unrelated changes", where `build` is a noun in a wrapped line and matching
# it would have retiered a step that reads and reports.
CODE_CHANGING = re.compile(
    r"(?:^|(?<=\. ))(Apply|Implement|Build|Remediate|Refactor|Migrate)\b")


# The adapter's own definition, not a second one. github_api.py:37 declares
# WRITE_METHODS and only reads are retried by default, so this is the same set
# the runtime treats as mutating.
GITHUB_WRITE_VERBS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def _writing_functions(tree: ast.AST) -> set[str]:
    """Top-level function names whose body contains a mutating verb literal."""
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and inner.args:
                first = inner.args[0]
                if isinstance(first, ast.Constant) and first.value in GITHUB_WRITE_VERBS:
                    out.add(node.name)
                    break
    return out


def _reaches_a_github_write(scripts: dict[str, Path]) -> set[str]:
    """Script stems that can reach a mutating GitHub call.

    Resolved by which FUNCTION is called across a module boundary, not by which
    module is imported. Import closure alone over-approximates: `triage.py`
    imports `capture` and uses only `search_duplicates`, `has_evidence` and
    `DEFAULT_THRESHOLD`, none of which write, so treating the import as
    reachability would demand `triage` be declared a write-effect command and
    gate every triage step. That would be the check overstating, which is the
    class of defect it exists to catch.
    """
    trees: dict[str, ast.AST] = {}
    writers: dict[str, set[str]] = {}
    aliases: dict[str, dict[str, str]] = {}

    for stem, path in scripts.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        trees[stem] = tree
        writers[stem] = _writing_functions(tree)
        alias: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in scripts:
                        alias[a.asname or a.name] = a.name
        aliases[stem] = alias

    direct = {stem for stem, fns in writers.items() if fns}

    # A module reaches a write when it calls a writing function of another
    # module through its import alias. Iterate to a fixed point so a two-hop
    # path (restructure -> retire -> the PATCH) is found.
    reaching = set(direct)
    for _ in range(len(scripts) + 1):
        grown = set(reaching)
        for stem, tree in trees.items():
            if stem in grown:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                owner = getattr(node.value, "id", None)
                target = aliases.get(stem, {}).get(owner or "")
                if target and node.attr in writers.get(target, set()):
                    grown.add(stem)
                    break
        if grown == reaching:
            break
        reaching = grown
    return reaching


@check("SEC-WRITE-EFFECT-DECLARED",
       "Every script that can reach a GitHub write backs a declared write-effect command",
       scope="bundle")
def write_effect_declared(ctx: Ctx) -> Iterator[Finding]:
    """Derive the writers from source; do not take the list on trust.

    `write_effect_commands` gates approvals. It was hand-maintained and became
    a subset of what actually writes: `retire.py` PATCHed an issue to closed
    while `retire` appeared in neither that list nor `script_backed_commands`,
    so the gate governed a set it did not complete (#150).

    SCOPE, stated because a check that overstates is the defect this repo keeps
    finding: this verifies that a writing script backs AT LEAST ONE declared
    write-effect command. It is script-granular, not command-granular. A script
    backing two commands where only one writes -- `transition_plan.py`, which
    backs `transition` and `plan` -- satisfies it on the strength of the
    writer, and a second undeclared command on the same script would pass.
    Command granularity needs call-graph analysis per subcommand, which this
    does not do.
    """
    declared = set(ctx.invariants.get("write_effect_commands") or [])
    if not declared:
        yield ctx.finding(
            "SEC-WRITE-EFFECT-DECLARED", "tooling/invariants.yml",
            "write_effect_commands is empty or absent, so this check has "
            "nothing to hold scripts to. Refusing rather than passing "
            "silently")
        return

    ext = next(iter(ctx.inv.by_kind("extension")), None)
    if ext is None:
        return
    script_dir = ext.path / "scripts"
    command_dir = ext.path / "commands"
    if not script_dir.is_dir() or not command_dir.is_dir():
        return

    scripts = {p.stem: p for p in sorted(script_dir.glob("*.py"))}
    writers = _reaches_a_github_write(scripts)

    backed: dict[str, set[str]] = {}
    for doc in sorted(command_dir.glob("*.md")):
        match = re.search(r"py:\s*scripts/(\S+)\.py", doc.read_text(encoding="utf-8"))
        if match:
            backed.setdefault(match.group(1), set()).add(
                f"speckit.github-lifecycle.{doc.stem}")

    for stem in sorted(writers):
        commands = backed.get(stem)
        if not commands:
            continue  # a library, backing no command of its own
        if commands & declared:
            continue
        yield ctx.finding(
            "SEC-WRITE-EFFECT-DECLARED", f"scripts/{stem}.py",
            f"reaches a GitHub write and backs {sorted(commands)}, none of "
            f"which is in write_effect_commands, so the approval gate does "
            f"not govern it")


# A gate artifact must open by naming what the approver is deciding. The phrases
# an author can reasonably use for that heading; matched case-insensitively.
DECISION_HEADINGS = ("what you are approving", "what you are deciding",
                     "decisions", "what this gate decides")

# Files a shipped script owns and no prompt may edit; a gate showing one is
# approving a machine-written record rather than authored prose, so requiring a
# decision heading in a writing prompt would have no prompt to require it of.
#
# `/plans/` used to be here. No gate shows a transition plan any more: showing
# one displayed the request -- issue, from, to, and a list of evidence key
# names -- rather than the evidence, which is a signature manufactured rather
# than earned. The exemption went with the practice.
SCRIPT_OWNED_GATE_ARTIFACTS: tuple[str, ...] = ()


@check("INV-GATE-ARTIFACT-STATES-THE-DECISION",
       "A gate whose artifact is authored prose says what is being decided",
       scope="workflow")
def gate_artifact_states_the_decision(ctx: Ctx) -> Iterator[Finding]:
    """The approver must be able to find the decision without reading it all.

    A 196-line adoption plan carried exactly one judgement call -- hold coverage
    at the measured figure rather than the configured one -- assembled from
    seven fragments across five sections, and the `## Approvals` table said the
    gate decides "this file". A second gate named seven blocking questions as
    `Q1`-`Q7` and defined them in an unheaded numbered list, so searching for
    `Q7` returned only the references (#155).

    An approval whose subject cannot be located is not an approval: the person
    approves all of it or none of it, and both are the same shrug.

    SCOPE, stated because a check that overstates is what this repo keeps
    removing: this covers a gate whose `show_file` names authored prose. A gate
    showing a file a shipped script writes is exempt -- nothing a prompt does
    could add a heading to it. A gate showing no file is not covered at all,
    because the artifact it approves comes from outside this bundle.
    """
    for comp in ctx.inv.by_kind("workflow"):
        steps = _steps(comp)
        for gate in steps:
            if gate.get("type") != "gate":
                continue
            shown = str(gate.get("show_file") or "")
            if not shown or any(o in shown for o in SCRIPT_OWNED_GATE_ARTIFACTS):
                continue
            # The step that writes it: the one whose prompt names the same file.
            stem = shown.rsplit("/", 1)[-1].split("{{")[0].strip(" -_.")
            writer = next(
                (s for s in steps
                 if s is not gate and stem and stem in _norm(str(s.get("prompt") or ""))),
                None)
            if writer is None:
                continue
            prompt = _norm(str(writer.get("prompt") or "")).lower()
            if not any(h in prompt for h in DECISION_HEADINGS):
                yield ctx.finding(
                    "INV-GATE-ARTIFACT-STATES-THE-DECISION",
                    f"{comp.id}:{writer.get('id')}",
                    f"writes {shown}, which {gate.get('id')!r} asks a person to "
                    f"approve, and does not instruct it to open by naming the "
                    f"decisions that need judgement")


@check("SEC-REPOSITORY-IDENTITY-DECLARED",
       "The sources of a repository identity are declared, and inspect refuses the rest",
       scope="bundle")
def repository_identity_declared(ctx: Ctx) -> Iterator[Finding]:
    """Identity may not arrive from a source no policy sanctioned.

    During the #104 pilot `inspect` recovered a repository from SECURITY.md,
    CODEOWNERS, a changelog and a links module, then queried GitHub with live
    credentials -- against a clone whose remote had been removed so it could not
    reach upstream. Removing the remote is the documented dissociation method;
    it guarantees nothing while file content is treated as identity.

    SCOPE, stated because a check that overstates is what this repo keeps
    removing: this holds the declaration, not the behaviour. It verifies the
    policy block exists, is mirrored, and that `inspect.md` carries the refusal.
    It cannot police an agent's reasoning, and `test_docs.py` records why a
    check claiming to would be worse than none.
    """
    policy = load_yaml(ctx.root / "policy" / "agent-policy.yml") or {}
    block = policy.get("repository_identity") or {}
    if not block:
        yield ctx.finding(
            "SEC-REPOSITORY-IDENTITY-DECLARED", "policy/agent-policy.yml",
            "declares no repository_identity block, so nothing states where an "
            "identity may come from and file content is as good as a flag")
        return

    if "repository_file_content" not in (block.get("never_a_source") or []):
        yield ctx.finding(
            "SEC-REPOSITORY-IDENTITY-DECLARED", "policy/agent-policy.yml",
            "repository_identity.never_a_source omits repository_file_content, "
            "which is the source that actually reached a live query (#158)")

    if not (block.get("sources") or []):
        yield ctx.finding(
            "SEC-REPOSITORY-IDENTITY-DECLARED", "policy/agent-policy.yml",
            "repository_identity names no sources, so the refusal has nothing "
            "to offer a caller instead")

    ext = next(iter(ctx.inv.by_kind("extension")), None)
    if ext is None:
        return
    doc = ext.path / "commands" / "inspect.md"
    if not doc.is_file():
        return
    text = _norm(doc.read_text(encoding="utf-8")).lower()
    if "contents of the working tree" not in text:
        yield ctx.finding(
            "SEC-REPOSITORY-IDENTITY-DECLARED", "commands/inspect.md",
            "carries no clause refusing an identity derived from the working "
            "tree's contents, so the policy states a rule the command never "
            "repeats to the agent that follows it")


@check("INV-APPLY-STEP-BUDGET",
       "A prompt step that changes a codebase is budgeted to synthesise an artifact",
       scope="workflow")
def apply_step_budget(ctx: Ctx) -> Iterator[Finding]:
    """Read the declared tier against the work the step describes.

    `INV-STEP-TIMEOUT-TIER` checks a tier is *a* tier, which catches a typo and
    nothing else. `targeted-apply-approved-scope` declared `statement` -- 300s,
    "states something, records a decision" -- and spent five minutes applying an
    approved scope to a real repository before the runner killed it (#148).

    Not inference from the step id. That was tried, and the very next step of
    the workflow that prompted it matched no prefix and timed out anyway
    (#117); `bootstrap-policy.yml` records the conclusion. This reads what the
    prompt tells the model to do, which is the thing that actually costs.
    """
    policy = load_yaml(ctx.root / "policy" / "bootstrap-policy.yml") or {}
    tiers = policy.get("step_timeouts") or {}
    synthesis = tiers.get("artifact_synthesis")
    if synthesis is None:
        yield ctx.finding(
            "INV-APPLY-STEP-BUDGET", "policy/bootstrap-policy.yml",
            "step_timeouts declares no artifact_synthesis tier, so this check "
            "has nothing to hold steps to. Refusing rather than passing "
            "silently: a check that no-ops on missing input reports a coverage "
            "it does not have")
        return

    for comp in ctx.inv.by_kind("workflow"):
        for step in _steps(comp):
            kind = step.get("type") or ("command" if step.get("command") else "prompt")
            if kind != "prompt":
                continue
            text = _norm(str(step.get("prompt") or ""))
            match = CODE_CHANGING.search(text)
            if not match:
                continue
            if step.get("timeout") != synthesis:
                yield ctx.finding(
                    "INV-APPLY-STEP-BUDGET", f"{comp.id}:{step.get('id')}",
                    f"tells the model to {match.group(1).lower()}, which builds "
                    f"an artifact from a codebase, but declares "
                    f"{step.get('timeout')!r} rather than the "
                    f"artifact_synthesis tier ({synthesis})")


@check("INV-STEP-TIMEOUT-TIER",
       "Every prompt step declares a timeout from a policy tier",
       scope="workflow")
def step_timeout_tier(ctx: Ctx) -> Iterator[Finding]:
    """No step runs on an unstated default, and no check guesses which are slow.

    The first attempt at this keyed on the step id -- a generative command or a
    `create-` prefix -- and the very next step of the very workflow that
    prompted it, `apply-greenfield-bootstrap`, matched neither and timed out
    (#117). Inferring cost from a name fails at the next name nobody thought
    of.

    So the author declares a tier and this checks the value is one. That is
    reliable in a way inference is not: a step with no timeout, or one with a
    number the policy does not name, is reported, and nobody has to predict
    which ids mean expensive.
    """
    policy = load_yaml(ctx.root / "policy" / "bootstrap-policy.yml") or {}
    tiers = policy.get("step_timeouts") or {}
    if not tiers:
        yield ctx.finding(
            "INV-STEP-TIMEOUT-TIER", "policy/bootstrap-policy.yml",
            "step_timeouts is absent or empty, so this check has nothing to "
            "hold anything to. Refusing rather than passing silently: a "
            "check that no-ops on a missing input reports a coverage it "
            "does not have")
        return
    allowed = {value for value in tiers.values() if isinstance(value, int)}

    for comp in ctx.inv.by_kind("workflow"):
        for step in _steps(comp):
            kind = step.get("type") or ("command" if step.get("command") else "prompt")
            if kind != "prompt":
                continue
            step_id = str(step.get("id") or "")
            declared = step.get("timeout")
            if declared is None:
                yield ctx.finding(
                    "INV-STEP-TIMEOUT-TIER", f"{comp.id}:{step_id}",
                    f"declares no timeout, so it runs on the runner's default; "
                    f"choose a tier from {sorted(allowed)}")
            elif declared not in allowed:
                yield ctx.finding(
                    "INV-STEP-TIMEOUT-TIER", f"{comp.id}:{step_id}",
                    f"declares {declared!r}, which is not a tier "
                    f"bootstrap-policy.yml names: {sorted(allowed)}")


@check("INV-COMMAND-SCRIPT-INVOCATION",
       "A command declares its script and never prescribes a bare interpreter",
       scope="extension")
def command_script_invocation(ctx: Ctx) -> Iterator[Finding]:
    """`python <script>` is not an invocation that works everywhere.

    The greenfield pilot found it three ways on one machine: no `python` on
    PATH, a `python3` too old to parse the scripts' own syntax, and another
    `python3` without PyYAML. Two agents hit it in the same run and invented
    two different workarounds, which is the part that matters -- a workaround
    an agent invents is not a contract, and the next agent invents a different
    one.

    Spec Kit already solved this. A command declares `scripts:` in its front
    matter and writes `{SCRIPT}` in the prose; the CLI substitutes an
    interpreter it resolved (a project `.venv` first, then `python3`, then
    `python`). Prescribing a literal bypasses that resolution.

    Declaring `scripts:` also makes a command addressable as an event handler.
    Without it `resolve_and_run_event_command` finds the template, finds no
    script, and returns 0 -- a guard that permits silently (#99).
    """
    import re

    ext = ctx.inv.extension
    literal = re.compile(r"\b(python3?|py)\s+\.specify/")
    for entry in (ext.manifest.get("provides", {}) or {}).get("commands", []) or []:
        path = ext.path / str(entry.get("file", ""))
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        subject = f"{ext.ref}:{path.name}"

        found = literal.search(text)
        if found:
            yield ctx.finding(
                "INV-COMMAND-SCRIPT-INVOCATION", subject,
                f"prescribes {found.group(0).strip()!r}; write {{SCRIPT}} and "
                f"let the CLI resolve an interpreter")

        front = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        declares = bool(front) and "scripts:" in front.group(1)
        if "{SCRIPT}" in text and not declares:
            yield ctx.finding(
                "INV-COMMAND-SCRIPT-INVOCATION", subject,
                "uses {SCRIPT} but declares no scripts: front matter, so "
                "nothing resolves it")


def _role_candidates(root: Path) -> set[str]:
    """The keys of `inspect_target.ROLE_CANDIDATES`, read as data.

    Parsed rather than imported: a check must not execute extension code, and
    it must not take the role names from the file it is checking either.
    """
    source = (root / "bundle/components/extensions/github-lifecycle/scripts"
              / "inspect_target.py")
    if not source.is_file():
        return set()
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = ([node.target] if isinstance(node, ast.AnnAssign)
                   else getattr(node, "targets", []))
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "ROLE_CANDIDATES":
                value = node.value
                if isinstance(value, ast.Dict):
                    return {k.value for k in value.keys
                            if isinstance(k, ast.Constant)}
    return set()


@check("INV-ROLE-REACHABLE",
       "Every field role a workflow writes is reachable on each claimed backend",
       scope="workflow")
def role_reachable(ctx: Ctx) -> Iterator[Finding]:
    """A declared role with nowhere to live is a workflow that cannot complete.

    `lifecycle-release-outcome` writes Outcome Status at three steps. On the
    organization Issue Fields backend that field cannot exist -- it would land
    on every repository in the organization, and #91 established this bundle
    performs no organization schema mutation. So the workflow is unrunnable
    there, and nothing said so until a pilot reasoned it out (#118).

    This does not require every backend to carry every role. It requires the
    matrix to *say* which it cannot, and why. An unavailable role with no
    recorded reason is the failure: silence reads as support.
    """
    matrix = load_yaml(ctx.root / "tooling" / "compatibility.yml") or {}
    backends = matrix.get("backends") or {}
    if not backends:
        yield ctx.finding(
            "INV-ROLE-REACHABLE", "tooling/compatibility.yml",
            "backends is absent or empty, so this check has nothing to "
            "hold anything to. Refusing rather than passing silently: a "
            "check that no-ops on a missing input reports a coverage it "
            "does not have")
        return

    # The roles the code actually knows, read from the extension source as
    # data. Taking the names from the matrix instead made the check circular:
    # a role present in `ROLE_CANDIDATES` and in no backend row was invisible,
    # which is the one failure worth catching here. Reading the file is not
    # importing it -- this module reads policy the same way -- and it is the
    # difference between comparing the matrix against the system and comparing
    # it against itself.
    known = _role_candidates(ctx.root)
    accounted = {name: set(spec.get("carries") or [])
                 | set((spec.get("unavailable") or {}))
                 for name, spec in backends.items()}
    union = (set().union(*accounted.values()) if accounted else set()) | known

    for role in sorted(known - union):
        yield ctx.finding(
            "INV-ROLE-REACHABLE", f"tooling/compatibility.yml:{role}",
            "is a role the extension resolves and no backend accounts for, so "
            "the matrix is silent about a role that exists")

    for backend, spec in backends.items():
        carries = set(spec.get("carries") or [])
        unavailable = spec.get("unavailable") or {}

        for role in sorted(union - accounted[backend]):
            yield ctx.finding(
                "INV-ROLE-REACHABLE", f"{backend}:{role}",
                f"is accounted for by another backend and not by this one; "
                f"silence reads as support")
        for role, reason in unavailable.items():
            if not str(reason or "").strip():
                yield ctx.finding(
                    "INV-ROLE-REACHABLE", f"{backend}:{role}",
                    "is unavailable with no reason recorded; a reader cannot "
                    "tell what the project loses")
            if role in carries:
                yield ctx.finding(
                    "INV-ROLE-REACHABLE", f"{backend}:{role}",
                    "is listed as both carried and unavailable")
        if unavailable and not str(spec.get("remedy") or "").strip():
            yield ctx.finding(
                "INV-ROLE-REACHABLE", backend,
                "records unavailable roles and no remedy, so a project has no "
                "way to reach them")


@check("INV-BOOTSTRAP-DOCUMENTS",
       "A workflow that bootstraps a project produces the declared documents",
       scope="workflow")
def bootstrap_documents(ctx: Ctx) -> Iterator[Finding]:
    """A document set living in one workflow's prompt is a convention.

    `PRODUCT.md` existed only because greenfield asked for it, so brownfield
    adoption omitted it and three others while writing 937 lines about what the
    code does, and nothing noticed. Declaring the set makes the omission
    checkable; this is the check.

    Both directions are wrong. A workflow that bootstraps and does not produce
    the documents leaves a project nothing can write a spec against. A document
    declared and produced by nobody is a requirement on paper.
    """
    policy = load_yaml(ctx.root / "policy" / "bootstrap-policy.yml") or {}
    contract = policy.get("product_documents") or {}
    required = contract.get("required") or []
    if not required:
        yield ctx.finding(
            "INV-BOOTSTRAP-DOCUMENTS", "policy/bootstrap-policy.yml",
            "the required-documents list is absent or empty, so this check has nothing to "
            "hold anything to. Refusing rather than passing silently: a "
            "check that no-ops on a missing input reports a coverage it "
            "does not have")
        return

    # The non-empty sweep over answers/form/style went. It asserted that
    # strings are non-empty, which nothing meaningful fails: an author writing
    # the contract writes prose in every field, and the check cannot tell prose
    # that means something from prose that does not. What stays is the half
    # that reads a different file than the one declaring the requirement.

    bootstrapping = [comp for comp in ctx.inv.by_kind("workflow")
                     if "bootstrap" in comp.id or "adoption" in comp.id]
    for comp in bootstrapping:
        writes = any(str(step.get("command") or "").endswith(".documents")
                     for step in _steps(comp))
        if not writes:
            yield ctx.finding(
                "INV-BOOTSTRAP-DOCUMENTS", comp.id,
                f"bootstraps a project and never produces the "
                f"{len(required)} declared documents, so the project it "
                f"leaves behind has nothing to write a spec against")


@check("INV-NO-PHANTOM-BUDGET",
       "No shipped surface instructs a document budget the policy does not declare",
       scope="repo")
def no_phantom_budget(ctx: Ctx) -> Iterator[Finding]:
    """An instruction the checker will never enforce.

    `bootstrap-policy.yml` budgeted document length once, and the number was
    wrong for somebody: a constitution set at 200 lines would have meant
    deleting principles from a real one. The budget went; the prose telling
    people to obey it stayed, in the command document and in the `args` of the
    step that writes the documents in both bootstrap routes.

    The command document merely misleads a reader. The workflow `args` are
    worse: they instruct the agent that is writing the documents, which is
    where a document actually gets shortened to fit a number nobody declares.

    Saying "length is not budgeted" is fine and is what the corrected text
    says. What is refused is an instruction to obey one.
    """
    policy = load_yaml(ctx.root / "policy" / "bootstrap-policy.yml") or {}
    required = (policy.get("product_documents") or {}).get("required") or []
    # The check applies only while the policy declares no budget. Reinstating
    # one must make this stop refusing, not require deleting it.
    if any("max_lines" in spec for spec in required):
        return

    scan = [ctx.root / "bundle", ctx.root / "tooling" / "requirements"]
    for base in scan:
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in PLACEHOLDER_SCAN_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8").lower()
            except (UnicodeDecodeError, OSError):
                continue
            for phrase in BUDGET_INSTRUCTIONS:
                if phrase in text:
                    yield ctx.finding(
                        "INV-NO-PHANTOM-BUDGET", str(path.relative_to(ctx.root)),
                        f"says {phrase!r}, but product_documents declares no "
                        f"budget and documents.py measures no length")


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


# A step's own instruction to write nothing. An exemption is honoured only when
# the step it names says this, so an exemption cannot cover a step that asks for
# a write. Prose, not proof -- but a stale or false exemption stops being silent.
READ_ONLY_DECLARATIONS = ("read-only", "read only", "write nothing", "writes nothing")


def _validated_exemptions(ctx: Ctx) -> tuple[set[tuple[str, str]], list[tuple[str, str, str]]]:
    """Exemptions that survive checking, and the reasons the rest did not.

    `read_only_invocations` was declared and honoured by nothing. Making it
    load-bearing without a guard would let two lines of YAML disable an approval
    gate with no one able to tell whether the claim was true -- so each entry is
    checked against the step it names before it suppresses anything.
    """
    good: set[tuple[str, str]] = set()
    problems: list[tuple[str, str, str]] = []
    by_id = {c.id: c for c in ctx.inv.by_kind("workflow")}

    for entry in ctx.invariants.get("read_only_invocations") or []:
        wf, step_id = entry.get("workflow"), entry.get("step")
        command = entry.get("command")
        subject = f"{wf}:{step_id}"
        comp = by_id.get(wf)
        if comp is None:
            problems.append((subject, "names a workflow this bundle does not ship", ""))
            continue
        step = next((s for s in _steps(comp) if s.get("id") == step_id), None)
        if step is None:
            problems.append((subject, "names a step that workflow does not define", ""))
            continue
        if step.get("command") != command:
            problems.append((subject, f"claims to exempt {command!r} but the step "
                                      f"invokes {step.get('command')!r}", ""))
            continue
        args = _norm(_args(step)).lower()
        if not any(phrase in args for phrase in READ_ONLY_DECLARATIONS):
            problems.append((subject, "exempts a step whose own instruction does not "
                                      "say it writes nothing, so the claim cannot be "
                                      "read back from the step it covers", ""))
            continue
        good.add((wf, step_id))
    return good, problems


@check("SEC-EXEMPTION-TRUTHFUL",
       "Every read-only exemption names a step that declares it writes nothing",
       scope="bundle")
def exemption_truthful(ctx: Ctx) -> Iterator[Finding]:
    _, problems = _validated_exemptions(ctx)
    for subject, why, _ in problems:
        yield ctx.finding("SEC-EXEMPTION-TRUTHFUL", subject, why)


@check("SEC-WRITE-BEHIND-GATE", "Every state-mutating step sits behind an approval gate",
       scope="workflow")
def write_behind_gate(ctx: Ctx) -> Iterator[Finding]:
    writes = set(ctx.invariants.get("write_effect_commands", []))
    exempt, _ = _validated_exemptions(ctx)
    for comp in ctx.inv.by_kind("workflow"):
        steps = _steps(comp)
        for i, step in enumerate(steps):
            if step.get("command") not in writes:
                continue
            if (comp.id, step.get("id")) in exempt:
                continue
            if not any(s.get("type") == "gate" for s in steps[:i]):
                yield ctx.finding("SEC-WRITE-BEHIND-GATE", f"{comp.id}:{step.get('id')}",
                                  f"{step['command']} has no prior approval gate")


@check("SEC-TRANSITION-CONTRACT", "Transitions name the state they were approved against",
       scope="workflow")
def transition_contract(ctx: Ctx) -> Iterator[Finding]:
    """A transition must say what it expects the board to be, and be right.

    This required a transition step to name a plan file a prior step wrote.
    The plan file is gone: it claimed to be a durable approval artifact and was
    not -- `.specify/` is gitignored, and the 335 that accumulated were each
    read once, by the apply that ran seconds after writing. What the plan
    genuinely bought was compare-and-swap, and that now rides on `--expect`.

    So the check moves with it, and gets stronger doing so. It used to compare
    one step's string against another step's string, both written by the same
    author in the same commit. It now checks the named state against
    `state-machine.yml`: a transition expecting a state the machine does not
    allow as a source for its target is refused here rather than at run time.
    """
    from .inventory import load_yaml

    transition = "speckit.github-lifecycle.transition"
    machine = load_yaml(ctx.root / "policy/state-machine.yml") or {}
    edges = {}
    for role, spec in machine.items():
        for edge in (spec or {}).get("transitions") or []:
            edges.setdefault(str(edge.get("to")), set()).add(str(edge.get("from")))

    for comp in ctx.inv.by_kind("workflow"):
        for step in _steps(comp):
            if step.get("command") != transition:
                continue
            subject = f"{comp.id}:{step.get('id')}"
            args = _norm(_args(step))
            match = re.search(r"--expect\s+[\"\']?([A-Za-z ]+?)[\"\']?(?:\s*[.;]|\s+--|$)",
                              args)
            if not match:
                yield ctx.finding(
                    "SEC-TRANSITION-CONTRACT", subject,
                    "transition names no --expect, so it will overwrite whatever "
                    "the board holds, including a change this run never saw")
                continue
            expected = match.group(1).strip()
            target = re.search(r"\u2192\s*([A-Za-z ]+?)(?:\s*[.;]|\s+--|$)", args)
            if not target:
                continue        # the target is prose here; --expect is the guard
            legal = edges.get(target.group(1).strip())
            if legal and expected not in legal:
                yield ctx.finding(
                    "SEC-TRANSITION-CONTRACT", subject,
                    f"expects {expected!r}, which state-machine.yml does not allow "
                    f"as a source for {target.group(1).strip()!r}: {sorted(legal)}")


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

    # The non-empty sweep over name/description/sections/id/label/prompt went.
    # Both sides were the same file, written by one author in one commit, so
    # the only failure it could report was that author contradicting themselves
    # mid-edit. What stays compares two files that change independently.

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
        yield ctx.finding(
            "PUB-COMPAT-CLAIM", "docs/compatibility.md",
            "the compatibility matrix is absent or empty, so this check has nothing to "
            "hold anything to. Refusing rather than passing silently: a "
            "check that no-ops on a missing input reports a coverage it "
            "does not have")
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
        yield ctx.finding(
            "INV-SCRIPT-FLAVOUR", "policy/bootstrap-policy.yml",
            "script_flavours.provided is absent or empty, so this check has nothing to "
            "hold anything to. Refusing rather than passing silently: a "
            "check that no-ops on a missing input reports a coverage it "
            "does not have")
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
