"""The core document set, and the budgets that keep it readable.

A brownfield adoption produced four artefacts averaging 234 lines and no
product definition at all. Length is the one quality property a script can
judge, so it is the one enforced here; the rest is stated for a person.
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


def project(tmp_path, files):
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


def complete(**over):
    out = {}
    for spec in CONTRACT["required"]:
        heads = "\n".join(f"## {s}" for s in (spec.get("sections") or []))
        out[spec["path"]] = f"# Doc\n{heads}\nx\n"
    out.update(over)
    return out


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
def test_a_document_over_budget_names_the_overage(tmp_path):
    # The budget is a maximum somebody chose. Not truncated, not warned about.
    spec = next(s for s in CONTRACT["required"] if s["path"] == "PRODUCT.md")
    heads = "\n".join(f"## {s}" for s in spec["sections"])
    files = complete(**{"PRODUCT.md": "# P\n" + heads + "\nx\n" * spec["max_lines"]})
    problems = docs.check(project(tmp_path, files), CONTRACT)
    assert any("against a budget of" in p and "PRODUCT.md" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_a_log_has_no_budget(tmp_path):
    # product-decisions grows by design; each entry is bounded instead.
    spec = next(s for s in CONTRACT["required"]
                if s["path"].endswith("product-decisions.md"))
    assert spec["max_lines"] == 0
    files = complete(**{spec["path"]: "# Log\n" + "entry\n" * 500})
    assert docs.check(project(tmp_path, files), CONTRACT) == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_a_missing_section_is_named(tmp_path):
    files = complete(**{"PRODUCT.md": "# P\n## Intent\nx\n"})
    problems = docs.check(project(tmp_path, files), CONTRACT)
    assert any("missing the section" in p and "Users" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_bold_headings_count_as_sections(tmp_path):
    # Both styles occur; matching only one would report a present section as
    # absent, which teaches an author to ignore the check.
    spec = next(s for s in CONTRACT["required"] if s["path"] == "PRODUCT.md")
    body = "# P\n" + "\n".join(f"**{s}**" for s in spec["sections"]) + "\nx\n"
    files = complete(**{"PRODUCT.md": body})
    assert [p for p in docs.check(project(tmp_path, files), CONTRACT)
            if "PRODUCT.md" in p] == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_architecture_separates_observation_from_decision():
    # As built is evidence; Intended is a decision with an owner. The gap
    # between them is where specs come from.
    spec = next(s for s in CONTRACT["required"]
                if s["path"].endswith("architecture.md"))
    assert "As built" in spec["sections"] and "Intended" in spec["sections"]


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_every_declared_document_states_what_it_answers():
    for spec in CONTRACT["required"]:
        assert str(spec.get("answers") or "").strip(), spec["path"]


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
def test_both_bootstrap_workflows_produce_the_documents():
    # The defect: the set lived in one workflow's prompt, so the other omitted
    # four of five and nothing noticed.
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
