"""The constitution's shape, described once.

Three files described what a constitution principle must look like:
`bootstrap-policy.yml`, which `documents.py` enforces, and two generator
surfaces that said it in their own weaker words. A generator followed the prose
and the checker followed the policy, so a freshly authored constitution failed
the contract its own bundle enforces, on thirteen counts (#145).

The fix is structural, not a better prose edit: the shape section of both
surfaces is rendered from the policy, and `--check` fails when either is stale.
So the tests here are mostly about the *absence* of a second description --
that the rendered text is the policy's own words, and that neither file states
the shape outside the generated region.

Nothing here asserts that an agent obeys a prompt. Nothing in `tests/` runs a
generator, and a slow nondeterministic check would replace the pilot evidence
that already answers that question with something weaker.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys

import pytest

from lib.inventory import ROOT, load_yaml

SCRIPT = ROOT / "scripts/generate_constitution_guidance.py"
PRESET = ROOT / "bundle/components/presets/lean-full-lifecycle-governance"
TARGETS = (PRESET / "commands/speckit.constitution.md",
           PRESET / "templates/constitution-addendum.md")

spec = importlib.util.spec_from_file_location("constitution_guidance", SCRIPT)
gen = importlib.util.module_from_spec(spec)
sys.modules["constitution_guidance"] = gen
spec.loader.exec_module(gen)

POLICY = load_yaml(ROOT / "policy/bootstrap-policy.yml")
CONTRACT = gen.per_principle(POLICY)


def generated(path):
    text = path.read_text(encoding="utf-8")
    m = re.search(re.escape(gen.BEGIN) + r"(.*?)" + re.escape(gen.END),
                  text, re.DOTALL)
    assert m, f"{path.name} carries no generated region"
    return m.group(1)


def handwritten(path):
    text = path.read_text(encoding="utf-8")
    return re.sub(re.escape(gen.BEGIN) + r".*?" + re.escape(gen.END), "",
                  text, flags=re.DOTALL)


# --- derived, not maintained --------------------------------------------------

@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
def test_both_surfaces_are_current():
    result = subprocess.run([sys.executable, str(SCRIPT), "--check"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.name)
def test_a_hand_edit_is_caught(path, tmp_path, monkeypatch):
    original = path.read_text(encoding="utf-8")
    try:
        path.write_text(original.replace("MUST, MUST NOT", "MUST"),
                        encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--check"],
                                cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 1
        assert path.name in result.stderr
    finally:
        path.write_text(original, encoding="utf-8")


@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.name)
def test_the_region_says_it_is_generated(path):
    assert "Do not edit between these markers" in generated(path)


# --- the policy's own words, not a paraphrase ---------------------------------

@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.name)
def test_the_rendered_contract_is_the_policy_text(path):
    # Reflowed, never reworded. A paraphrase would be a fourth description,
    # agreeing with the policy until somebody edits one of them.
    region = " ".join(generated(path).split())
    assert gen.flow(CONTRACT["form"]) in region
    assert gen.flow(CONTRACT["excludes"]) in region


@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.name)
def test_the_rule_first_ordering_reaches_the_generator(path):
    # The twelve-count half of #145: a rule buried behind a preamble.
    assert "No explanatory paragraph before the rule" in generated(path)


@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.name)
def test_every_keyword_the_checker_accepts_is_named(path):
    import importlib.util as iu
    docs_path = (ROOT / "bundle/components/extensions/github-lifecycle/scripts"
                 / "documents.py")
    s = iu.spec_from_file_location("documents_subject", docs_path)
    documents = iu.module_from_spec(s)
    sys.modules["documents_subject"] = documents
    s.loader.exec_module(documents)
    region = generated(path)
    for keyword in documents.NORMATIVE:
        assert keyword in region, f"{keyword} is accepted and never offered"


# --- the substantive half: SHOULD, not MUST -----------------------------------

@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.name)
def test_a_preference_is_written_as_should(path):
    """The defect was not the missing keyword. It was who supplied it.

    Three principles came from a real project's stated intentions, were written
    as opinions, and a validator's refusal caused them to be promoted to
    obligations. `SHOULD` clears the same check without binding anybody.
    """
    region = generated(path)
    assert "SHOULD` when the source material states a preference" in region
    assert "only whoever governs the project may decide" in region


@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
def test_should_actually_satisfies_the_checker():
    # The advice is only safe because this holds. If SHOULD stopped clearing
    # the check, the generated text would be telling authors to fail it.
    import importlib.util as iu
    docs_path = (ROOT / "bundle/components/extensions/github-lifecycle/scripts"
                 / "documents.py")
    s = iu.spec_from_file_location("documents_should", docs_path)
    documents = iu.module_from_spec(s)
    sys.modules["documents_should"] = documents
    s.loader.exec_module(documents)
    assert "SHOULD" in documents.NORMATIVE


# --- no second description survives -------------------------------------------

@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.name)
def test_the_hand_written_half_does_not_describe_the_shape(path):
    """The whole point. A weaker restatement outside the region is the defect.

    `speckit.constitution.md` said rules "MUST be specific enough to review or
    automate" and `constitution-addendum.md` said "concise, actionable
    MUST/SHOULD rules". Both true, neither the contract, and the gap is the bug.
    """
    prose = handwritten(path)
    assert "MUST/SHOULD rules" not in prose
    assert "specific enough to review or automate" not in prose


@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.name)
def test_the_hand_written_half_still_names_the_subjects(path):
    # Shape is policy; what to write about is editorial and stays by hand.
    prose = handwritten(path)
    assert len(prose.strip().splitlines()) > 3


@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
def test_the_generator_refuses_a_policy_with_no_contract():
    with pytest.raises(SystemExit):
        gen.per_principle({"product_documents": {"required": []}})


@pytest.mark.req("REQ-PRODUCT-CONSTITUTION-001")
def test_generate_check_runs_in_the_makefile():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "generate_constitution_guidance.py --check" in text
    assert "generate_constitution_guidance.py\n" in text
