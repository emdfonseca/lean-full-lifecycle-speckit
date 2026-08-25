"""The core document set, and the form that keeps it readable.

A brownfield adoption produced four artefacts averaging 234 lines and no
product definition at all. The first fix budgeted lines; that number was wrong
for somebody, and setting the constitution at 200 would have meant deleting
principles from a real one. Form is checked instead: it scales on its own.
"""
from __future__ import annotations

import importlib.util
import sys

import pytest
import yaml

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(SCRIPTS))
_load("project_root")
docs = _load("documents")
CONTRACT = docs.load_contract(ROOT)

SAMPLE = {
    "table": "| a | b |\n|---|---|\n| x | y |\n",
    "list": "- one\n- two\n",
    "prose": "One sentence. Another one.\n",
}


def body_for(form: str) -> str:
    return SAMPLE.get(form, "text\n")


def complete(**over):
    out = {}
    for spec in CONTRACT["required"]:
        parts = [f"# {spec['path']}\n"]
        for section in spec.get("sections") or []:
            parts.append(f"## {section['name']}\n{body_for(section.get('form',''))}")
        if spec.get("per_principle"):
            # A conforming principle: one line stating the rule, then bullets.
            parts.append("## Principles\n### I. A rule\n"
                         "Every changeable fact has one home.\n\n"
                         "- A pull request MUST NOT restate a threshold.\n")
        out[spec["path"]] = "\n".join(parts) or "# doc\n"
    out.update(over)
    return out


def project(tmp_path, files):
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_a_complete_project_reports_nothing(tmp_path):
    assert docs.check(project(tmp_path, complete()), CONTRACT) == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_a_missing_document_names_what_it_answers(tmp_path):
    files = complete()
    del files["PRODUCT.md"]
    problems = docs.check(project(tmp_path, files), CONTRACT)
    assert any("PRODUCT.md is missing" in p and "What this is for" in p
               for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_a_missing_section_names_what_it_answers(tmp_path):
    files = complete(**{"PRODUCT.md": "# P\n## Intent\nOne sentence.\n"})
    problems = docs.check(project(tmp_path, files), CONTRACT)
    assert any("'Users' is missing" in p for p in problems)
    assert any("Who uses it" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_prose_where_a_table_was_asked_for_is_reported(tmp_path):
    # The failure that prompted this: a section of facts written as a
    # paragraph grows without a shape to hold it.
    files = complete(**{"PRODUCT.md":
                        "# P\n## Intent\nOne.\n## Users\nDevelopers and analysts.\n"
                        "## Constraints\n| a | b |\n|---|---|\n| x | y |\n"
                        "## Definition of done\n- x\n## Non-goals\n- y\n"})
    problems = docs.check(project(tmp_path, files), CONTRACT)
    assert any("Users" in p and "declared as a table" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_a_paragraph_where_a_list_was_asked_for_is_reported(tmp_path):
    files = complete(**{"PRODUCT.md":
                        "# P\n## Intent\nOne.\n"
                        "## Users\n| a | b |\n|---|---|\n| x | y |\n"
                        "## Constraints\n| a | b |\n|---|---|\n| x | y |\n"
                        "## Definition of done\nEverything works fine.\n"
                        "## Non-goals\n- y\n"})
    problems = docs.check(project(tmp_path, files), CONTRACT)
    assert any("Definition of done" in p and "declared as a list" in p
               for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_an_empty_section_is_a_heading(tmp_path):
    files = complete(**{"PRODUCT.md":
                        "# P\n## Intent\n\n## Users\n| a | b |\n|---|---|\n| x | y |\n"
                        "## Constraints\n| a | b |\n|---|---|\n| x | y |\n"
                        "## Definition of done\n- x\n## Non-goals\n- y\n"})
    problems = docs.check(project(tmp_path, files), CONTRACT)
    assert any("is empty" in p and "a heading" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_prose_that_runs_long_is_reported(tmp_path):
    files = complete(**{"PRODUCT.md":
                        "# P\n## Intent\n" + "A sentence. " * 9 + "\n"
                        "## Users\n| a | b |\n|---|---|\n| x | y |\n"
                        "## Constraints\n| a | b |\n|---|---|\n| x | y |\n"
                        "## Definition of done\n- x\n## Non-goals\n- y\n"})
    problems = docs.check(project(tmp_path, files), CONTRACT)
    assert any("Intent" in p and "sentences" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_bold_headings_count_as_sections(tmp_path):
    # Both styles occur. Matching one would report a present section as absent,
    # which teaches an author to ignore the check.
    body = ("# P\n**Intent**\nOne.\n**Users**\n| a | b |\n|---|---|\n| x | y |\n"
            "**Constraints**\n| a | b |\n|---|---|\n| x | y |\n"
            "**Definition of done**\n- x\n**Non-goals**\n- y\n")
    files = complete(**{"PRODUCT.md": body})
    assert [p for p in docs.check(project(tmp_path, files), CONTRACT)
            if "PRODUCT.md" in p] == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_no_document_is_budgeted_by_length():
    # A line count is wrong for somebody. The first version set the
    # constitution at 200, which would have meant deleting principles.
    for spec in CONTRACT["required"]:
        assert "max_lines" not in spec, spec["path"]
    assert "max_lines" not in (SCRIPTS / "documents.py").read_text()


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_architecture_separates_observation_from_decision():
    # arc42 names them Building blocks and Solution strategy. The first is
    # what is there, the second is what should change; the gap between them is
    # where specs come from.
    spec = next(s for s in CONTRACT["required"]
                if s["path"].endswith("architecture.md"))
    names = {s["name"] for s in spec["sections"]}
    assert {"Building blocks", "Solution strategy"} <= names
    strategy = next(s for s in spec["sections"] if s["name"] == "Solution strategy")
    assert "owner" in strategy["answers"].lower()
    blocks = next(s for s in spec["sections"] if s["name"] == "Building blocks")
    assert "observed" in blocks["answers"].lower()


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_the_stack_decision_records_what_was_rejected():
    # Usually the missing half: a stack with no rejections records a habit.
    # In ADR form it lives inside Decision as a taken/not-taken table.
    spec = next(s for s in CONTRACT["required"]
                if s["path"].endswith("stack-decision.md"))
    decision = next(s for s in spec["sections"] if s["name"] == "Decision")
    assert "rejected" in decision["answers"].lower()
    assert decision["form"] == "table"


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_every_section_states_what_it_answers():
    for spec in CONTRACT["required"]:
        assert str(spec.get("answers") or "").strip(), spec["path"]
        for section in spec.get("sections") or []:
            assert str(section.get("answers") or "").strip(), \
                f"{spec['path']}:{section['name']}"


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_both_bootstrap_workflows_produce_the_documents():
    for name in ("lifecycle-greenfield-bootstrap", "lifecycle-brownfield-adoption"):
        data = yaml.safe_load(
            (ROOT / f"bundle/components/workflows/{name}/workflow.yml").read_text())
        commands = [str(s.get("command") or "") for s in data["steps"]]
        assert any(c.endswith(".documents") for c in commands), name


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_the_style_rules_are_policy_not_prose_in_the_script():
    assert CONTRACT["style"], "terseness has no declared rules"
    source = (SCRIPTS / "documents.py").read_text()
    for rule in CONTRACT["style"]:
        assert rule[:30] not in source, "a style rule is duplicated in the script"


# --- one shape for both routes -----------------------------------------------

@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_both_routes_share_one_contract():
    # A reader moving between a new project and an adopted one should not have
    # to learn two shapes. There is one contract, so this asserts neither
    # workflow carries a document list of its own.
    for name in ("lifecycle-greenfield-bootstrap", "lifecycle-brownfield-adoption"):
        text = (ROOT / f"bundle/components/workflows/{name}/workflow.yml").read_text()
        for spec in CONTRACT["required"]:
            for section in spec.get("sections") or []:
                assert section["name"] not in text, (
                    f"{name} names the section {section['name']!r} itself; the "
                    f"contract is the only place that should")


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_section_names_follow_a_named_standard():
    # The first version invented every section name, including a decision shape
    # for a project that already had five Nygard ADRs.
    by_path = {s["path"]: s for s in CONTRACT["required"]}
    assert by_path[".specify/lifecycle/architecture.md"]["standard"].startswith("arc42")
    assert by_path[".specify/lifecycle/stack-decision.md"]["standard"] == "Nygard ADR"
    assert by_path[".specify/memory/constitution.md"]["standard"] == "RFC 2119"


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_the_stack_decision_carries_the_four_adr_sections():
    spec = next(s for s in CONTRACT["required"]
                if s["path"].endswith("stack-decision.md"))
    names = [s["name"] for s in spec["sections"]]
    assert names == ["Status", "Context", "Decision", "Consequences"]


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_architecture_delegates_decisions_rather_than_duplicating_them():
    # arc42 section 9 permits this, and a second decision format in one project
    # is the drift the style rules forbid.
    spec = next(s for s in CONTRACT["required"]
                if s["path"].endswith("architecture.md"))
    delegated = " ".join(spec.get("delegates") or [])
    assert "docs/decisions/" in delegated
    assert "9" in delegated
    assert "Architectural Decisions" not in [s["name"] for s in spec["sections"]]


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_seams_is_marked_as_an_addition_not_an_arc42_section():
    # Claiming a bespoke section is part of a standard would misrepresent it.
    spec = next(s for s in CONTRACT["required"]
                if s["path"].endswith("architecture.md"))
    seams = next(s for s in spec["sections"] if s["name"] == "Seams")
    assert "not an arc42 section" in seams["answers"].lower()


# --- per-principle rules -----------------------------------------------------
#
# Declared for the constitution and unenforced until now. A real one turned out
# to have 11 of 23 principles stating nothing normative at all.

CONSTITUTION = ".specify/memory/constitution.md"


def constitution(body: str) -> dict:
    files = complete()
    files[CONSTITUTION] = body
    return files


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_a_principle_with_no_normative_keyword_is_an_opinion(tmp_path):
    body = "# C\n## Principles\n### I. Be nice\nNiceness is generally good.\n"
    problems = docs.check(project(tmp_path, constitution(body)), CONTRACT)
    assert any("states no MUST" in p and "I. Be nice" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_a_rule_stated_in_one_line_then_bullets_passes(tmp_path):
    body = ("# C\n## Principles\n### I. One source per fact\n"
            "Every changeable fact has one home.\n\n"
            "- A pull request MUST NOT restate a threshold.\n"
            "- Docs MUST state what is true now.\n")
    assert [p for p in docs.check(project(tmp_path, constitution(body)), CONTRACT)
            if CONSTITUTION in p] == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_an_explanatory_paragraph_before_the_rule_is_reported(tmp_path):
    # More than one line before the rule means the rule is not yet written and
    # the reader has to extract it.
    body = ("# C\n## Principles\n### I. One source per fact\n"
            "Duplication is the enemy of truth.\n"
            "Teams discover this the hard way.\n"
            "So we have a principle about it.\n\n"
            "- A pull request MUST NOT restate a threshold.\n")
    problems = docs.check(project(tmp_path, constitution(body)), CONTRACT)
    assert any("lines of prose before its first rule" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_a_bulleted_line_is_not_counted_as_preamble(tmp_path):
    # A table or list before the rule is structure, not an essay.
    body = ("# C\n## Principles\n### I. One source per fact\n"
            "Every changeable fact has one home.\n"
            "- Work items: the issue.\n"
            "- Policy: the policy file.\n"
            "- A pull request MUST NOT restate a threshold.\n")
    assert [p for p in docs.check(project(tmp_path, constitution(body)), CONTRACT)
            if CONSTITUTION in p] == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-002")
def test_a_bullet_that_wraps_before_its_keyword_passes(tmp_path):
    # The keyword falls on the bullet's third physical line. Counting the two
    # continuation lines as prose made the passing shape depend on the wrap
    # column: this principle is a list of bullets and no paragraph at all.
    body = ("# C\n## Principles\n### III. Living specifications\n"
            "- Behavior a user can observe is specified before it is claimed\n"
            "  done, in the same change that changes the behavior.\n"
            "- Open uncertainty is recorded rather than resolved by guessing,\n"
            "  and the record names who must answer it.\n"
            "- Discovery records MUST mark each observation as inferred.\n")
    assert [p for p in docs.check(project(tmp_path, constitution(body)), CONTRACT)
            if CONSTITUTION in p] == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-002")
def test_a_wrapped_rule_statement_is_still_two_lines_of_prose(tmp_path):
    # Prose is not folded. This is the rule the preamble count exists to
    # enforce, and the wrapped-bullet fix must not relax it.
    body = ("# C\n## Principles\n### I. One source per fact\n"
            "Duplication is the enemy of truth.\n"
            "Teams discover this the hard way.\n"
            "- A pull request MUST NOT restate a threshold.\n")
    problems = docs.check(project(tmp_path, constitution(body)), CONTRACT)
    assert any("2 lines of prose before its first rule" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-002")
def test_every_ordinal_is_a_list_item_not_just_the_first(tmp_path):
    # Exempting `1.` alone made the second and third steps of a numbered cycle
    # read as an explanatory paragraph.
    body = ("# C\n## Principles\n### IV. Red-Green-Refactor\n"
            "A behavioural change starts with a failing test.\n"
            "1. Write a failing test that names the behaviour.\n"
            "2. Make it pass with the smallest change that does.\n"
            "3. Refactor with the suite green.\n"
            "- The failing test MUST be observed failing.\n")
    assert [p for p in docs.check(project(tmp_path, constitution(body)), CONTRACT)
            if CONSTITUTION in p] == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-002")
def test_a_wrapped_table_row_is_not_prose(tmp_path):
    body = ("# C\n## Principles\n### I. One source per fact\n"
            "Every changeable fact has one home.\n"
            "| Fact | Home |\n"
            "|---|---|\n"
            "| Engineering policy | this constitution and the installed\n"
            "  policy files it points at |\n"
            "- A pull request MUST NOT restate a threshold.\n")
    assert [p for p in docs.check(project(tmp_path, constitution(body)), CONTRACT)
            if CONSTITUTION in p] == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_a_constitution_with_no_principles_is_reported(tmp_path):
    body = "# C\n## Some prose\nNo principles here at all.\n"
    problems = docs.check(project(tmp_path, constitution(body)), CONTRACT)
    assert any("no `###` principles" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_the_keywords_are_rfc_2119():
    assert set(docs.NORMATIVE) == {"MUST NOT", "MUST", "SHOULD NOT", "SHOULD", "MAY"}
