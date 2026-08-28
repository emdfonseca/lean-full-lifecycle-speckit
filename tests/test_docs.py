"""Documentation claims that a test can actually hold to.

Most documentation cannot be tested, and pretending otherwise produces
ceremony. What *is* testable is the shape of a status document: that it
distinguishes verified from unverified rather than implying everything works.
"""
from __future__ import annotations

import re

import json

import pytest

from lib.inventory import ROOT, load_yaml


@pytest.mark.req("REQ-DOCS-TRUTH-001")
def test_validation_states_unverified_areas():
    text = (ROOT / "VALIDATION.md").read_text(encoding="utf-8")
    assert "## Not verified" in text, "VALIDATION.md must say what has not been verified"
    section = text.split("## Not verified", 1)[1].split("##", 1)[0]
    assert len(section.strip()) > 100, "the unverified section is a stub"


@pytest.mark.req("REQ-DOCS-TRUTH-001")
def test_validation_names_the_platform_it_was_run_on():
    text = (ROOT / "VALIDATION.md").read_text(encoding="utf-8")
    assert re.search(r"Spec Kit `?\d+\.\d+\.\d+", text), "no Spec Kit version recorded"


@pytest.mark.parametrize("doc", ["README.md", "VALIDATION.md", "INSTALL-LOCAL.md",
                                 "docs/installation.md", "docs/publishing.md"])
def test_no_doc_recommends_the_unusable_validate_form(doc):
    # `bundle validate` resolves references against the project containing the
    # manifest, so the online form can never pass from a source checkout.
    text = (ROOT / doc).read_text(encoding="utf-8")
    for line in text.splitlines():
        if "bundle validate" in line and "--path" in line:
            assert "--offline" in line, f"{doc}: {line.strip()!r} cannot pass from a checkout"


@pytest.mark.parametrize("doc", ["README.md", "VALIDATION.md", "INSTALL-LOCAL.md",
                                 "docs/installation.md", "docs/publishing.md",
                                 "scripts/README.md"])
def test_no_doc_references_a_deleted_script(doc):
    text = (ROOT / doc).read_text(encoding="utf-8")
    assert "install_dev.py" not in text, f"{doc} references a script that no longer exists"


@pytest.mark.req("REQ-SECURITY-UNTRUSTED-001")
def test_no_workflow_interpolates_untrusted_content_into_a_command():
    # The enforceable half of "untrusted input never authorizes an action".
    # No Python check stops prompt injection reaching an agent's context, and
    # one claiming to would be worse than none.
    import subprocess
    import sys as _sys

    result = subprocess.run(
        [_sys.executable, str(ROOT / "scripts/validate_source.py"),
         "--only", "SEC-UNTRUSTED-NO-COMMAND-INTERPOLATION", "--format", "json"],
        capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload["errors"] == [], payload["errors"]


@pytest.mark.req("REQ-SECURITY-UNTRUSTED-001")
def test_the_issue_reference_is_still_usable():
    # A check that refused `inputs.issue_ref` would refuse nearly every step
    # in the bundle. What is untrusted is the content, not the address.
    delivery = load_yaml(
        ROOT / "bundle/components/workflows/lifecycle-story-delivery/workflow.yml")
    text = json.dumps(delivery)
    assert "inputs.issue_ref" in text


def test_the_extension_declares_no_spec_kit_hooks():
    """ADR 0005: `hooks:` is agent instruction that cannot refuse.

    Unmarked by a requirement on purpose. A spike answers a question and
    delivers no behaviour, so there is nothing to require -- but the answer is
    worth holding in place. Declaring hooks later must mean revisiting the ADR
    rather than noticing afterwards that the bundle reads as though it enforces
    four guarantees it does not.
    """
    manifest = load_yaml(
        ROOT / "bundle/components/extensions/github-lifecycle/extension.yml")
    assert not manifest.get("hooks"), (
        "the extension declares hooks; ADR 0005 says it declares none, so "
        "either the ADR is superseded or this is an oversight")
    adr = ROOT / "docs/decisions/0005-no-spec-kit-hooks.md"
    assert adr.is_file()
    assert "Status: accepted" in adr.read_text(encoding="utf-8")


def test_the_hooks_decision_does_not_silently_cover_events():
    # The two mechanisms share a word and differ entirely: hooks format a
    # message, events propagate an exit code. An ADR read as settling both
    # would close a question #99 exists to answer.
    adr = (ROOT / "docs/decisions/0005-no-spec-kit-hooks.md").read_text(
        encoding="utf-8")
    assert "#99" in adr, "the ADR does not point at the events spike"
    assert "is not decided here" in adr


# --- the interpreter the shipped scripts need --------------------------------
#
# A greenfield pilot resolved `{SCRIPT}` to a `python3` with no PyYAML, and
# every command that reads policy died at import. Eleven more died on one
# module-level type alias, which `from __future__ import annotations` does not
# defer because a type alias is a runtime expression.

EXT_MANIFEST = ROOT / "bundle/components/extensions/github-lifecycle/extension.yml"
EXT_SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"


@pytest.mark.req("REQ-PACKAGE-INTERPRETER-001")
def test_the_extension_declares_what_its_scripts_need():
    requires = load_yaml(EXT_MANIFEST)["requires"]
    assert requires.get("python_min"), "no python_min declared"
    names = {p["import_name"] for p in requires["python_packages"]}
    assert "yaml" in names, "PyYAML is imported by most scripts and undeclared"


@pytest.mark.req("REQ-PACKAGE-INTERPRETER-001")
def test_no_shipped_script_evaluates_a_pep_604_union_at_import():
    # A type alias is evaluated on import. This is the line that made eleven
    # scripts unimportable below the declared floor while twenty ran fine.
    import ast

    # `re.IGNORECASE | re.MULTILINE` is also a module-level BitOr and is fine on
    # every version, so the test looks for the type-union shape specifically:
    # an operand that is `None` or a builtin type name.
    TYPEISH = {"str", "int", "float", "bool", "bytes", "list", "dict",
               "tuple", "set", "Path", "Sequence", "Callable"}

    def is_type_operand(node):
        if isinstance(node, ast.Constant) and node.value is None:
            return True
        if isinstance(node, ast.Name) and node.id in TYPEISH:
            return True
        return isinstance(node, ast.Subscript)

    offenders = []
    for path in sorted(EXT_SCRIPTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:                      # module level only
            if not isinstance(node, ast.Assign):
                continue
            for sub in ast.walk(node.value):
                if (isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr)
                        and (is_type_operand(sub.left) or is_type_operand(sub.right))):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        f"module-level PEP 604 union evaluated at import: {offenders}. "
        f"Quote it, or the declared python_min is not the real floor")


@pytest.mark.req("REQ-PACKAGE-INTERPRETER-001")
def test_an_optional_dependency_says_what_its_absence_costs():
    requires = load_yaml(EXT_MANIFEST)["requires"]
    for pkg in requires["python_packages"]:
        assert str(pkg.get("why") or "").strip(), f"{pkg['name']} declares no why"
        if not pkg.get("required"):
            assert "without it" in pkg["why"].lower(), (
                f"{pkg['name']} is optional and does not say what is lost")


# --- a stated count is a claim about the tree ---------------------------------

# The documents that describe what the bundle ships today. A count here is a
# claim about the inventory and can therefore be wrong.
DESCRIBE_WHAT_SHIPS = (
    "README.md",
    "CLAUDE.md",
    "docs/architecture.md",
    "docs/component-boundaries.md",
)

WORKFLOW_COUNT = re.compile(
    r"\b(?:(\d+)|(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen))\s+(?:lifecycle\s+)?workflows\b",
    re.I)
WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen".split())}


def _stated_counts(text):
    for m in WORKFLOW_COUNT.finditer(text):
        digit, word = m.group(1), m.group(2)
        yield int(digit) if digit else WORDS[word.lower()], m.group(0)


@pytest.mark.req("REQ-DOCS-TRUTH-001")
def test_no_document_states_a_workflow_count_the_tree_contradicts():
    """A doc that miscounts what ships is drift, and it is checkable.

    Not a prose assertion: the two sides change independently. The number is
    written by a person, the inventory is what is on disk, and the check fails
    without anybody touching the file it reads.

    Scoped to the documents that describe the shipped bundle. Two kinds are
    deliberately out. `docs/evidence/` records what was true when a run
    happened, and editing a dated measurement to match today falsifies it. The
    roadmap and plan-corrections describe an intended inventory -- "scaling to
    15 workflows" is a plan, not a claim about the tree -- and holding a plan
    to today's count would forbid planning.
    """
    shipped = len([d for d in (ROOT / "bundle/components/workflows").iterdir()
                   if (d / "workflow.yml").is_file()])
    wrong = []
    for rel in DESCRIBE_WHAT_SHIPS:
        doc = ROOT / rel
        for count, phrase in _stated_counts(doc.read_text(encoding="utf-8")):
            if count != shipped:
                wrong.append(f"{rel}: {phrase!r}")
    assert not wrong, (
        f"the tree ships {shipped} workflows; these say otherwise: {wrong}")

