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
    spec = next(s for s in CONTRACT["required"]
                if s["path"].endswith("architecture.md"))
    names = {s["name"] for s in spec["sections"]}
    assert {"As built", "Intended"} <= names
    intended = next(s for s in spec["sections"] if s["name"] == "Intended")
    assert "owner" in intended["answers"].lower()


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_the_stack_decision_records_what_was_rejected():
    # Usually the missing half: a stack with no rejections records a habit.
    spec = next(s for s in CONTRACT["required"]
                if s["path"].endswith("stack-decision.md"))
    assert "Rejected" in {s["name"] for s in spec["sections"]}


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
