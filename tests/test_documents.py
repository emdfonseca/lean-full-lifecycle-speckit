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

# The same bodies with each entry classified. A section the contract requires
# provenance on is not complete without it, so a "complete project" fixture
# that omitted the marker would be asserting the check away.
MARKED = {
    "table": "| a | b |\n|---|---|\n| **Observed.** x | y |\n",
    "list": "- **Observed.** one\n- **Observed.** two\n",
    "prose": "One sentence. Another one.\n",
}


def body_for(form: str, marked: bool = False) -> str:
    return (MARKED if marked else SAMPLE).get(form, "text\n")


# The contract requires a freshness line on every declared document, so a
# fixture without one is not a complete project (#137).
FRESH = "Last verified: 2026-08-01 (change: fixture)"


def complete(**over):
    out = {}
    for spec in CONTRACT["required"]:
        parts = [f"# {spec['path']}\n{FRESH}\n"]
        classified = set((spec.get("provenance") or {}).get("applies_to") or [])
        for section in spec.get("sections") or []:
            parts.append(f"## {section['name']}\n"
                         + body_for(section.get("form", ""),
                                    section["name"] in classified))
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
    body = (f"# P\n{FRESH}\n**Intent**\nOne.\n"
            "**Users**\n| a | b |\n|---|---|\n| x | y |\n"
            "**Constraints**\n| a | b |\n|---|---|\n| x | y |\n"
            "**Definition of done**\n- x\n**Non-goals**\n- y\n"
            "**Deliberately untested**\n- z\n")
    files = complete(**{"PRODUCT.md": body})
    assert [p for p in docs.check(project(tmp_path, files), CONTRACT)
            if "PRODUCT.md" in p] == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-001")
@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-003")
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
    # Not ownership: who owns an entry is orthogonal to whether it is true yet.
    # The section now says which of its two kinds of content an entry is.
    assert "provenance.remediation" in strategy["answers"]
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
    assert "decision_records" in delegated
    assert "9" in delegated
    assert "Architectural Decisions" not in [s["name"] for s in spec["sections"]]


# --- the decision-record directory -------------------------------------------
#
# It was named in prose as docs/decisions/, this repository's own directory,
# so a target keeping five Nygard ADRs in docs/adr/ was invisible (#141).

RECORD = "# 0001. A decision\n\n## Status\n\nAccepted\n"


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-005")
def test_the_decision_record_directory_is_declared_as_ordered_candidates():
    declared = CONTRACT["decision_records"]["candidates"]
    assert isinstance(declared, list) and len(declared) > 1
    assert declared[0] == "docs/decisions/"
    assert "docs/adr/" in declared


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-005")
def test_no_writer_instruction_names_a_fixed_decision_directory():
    # The two places the contract instructs a writer. The rationale comment
    # above them keeps naming this repository's own directory: that is history.
    arch = next(s for s in CONTRACT["required"]
                if s["path"].endswith("architecture.md"))
    log = next(s for s in CONTRACT["required"]
               if s["path"].endswith("product-decisions.md"))
    instructions = " ".join(arch.get("delegates") or []) + " " + \
        " ".join((log.get("per_entry") or {}).values())
    assert "docs/decisions/" not in instructions
    assert "docs/adr/" not in instructions


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-005")
def test_records_kept_in_docs_adr_are_found_there(tmp_path):
    root = project(tmp_path, {"docs/adr/0001-a.md": RECORD})
    assert docs.decision_records(root, CONTRACT)["resolved"] == "docs/adr/"


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-005")
def test_records_kept_in_docs_decisions_are_still_found_there(tmp_path):
    # Discovery must not break the convention this repository itself uses.
    root = project(tmp_path, {"docs/decisions/0001-a.md": RECORD})
    assert docs.decision_records(root, CONTRACT)["resolved"] == "docs/decisions/"


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-005")
def test_two_candidate_directories_are_reported_not_ranked(tmp_path):
    # Guessing which set of decisions is authoritative belongs to a person.
    root = project(tmp_path, {"docs/decisions/0001-a.md": RECORD,
                              "docs/adr/0001-b.md": RECORD})
    result = docs.decision_records(root, CONTRACT)
    assert result["resolved"] is None
    assert "docs/decisions/" in result["problem"]
    assert "docs/adr/" in result["problem"]
    assert result["problem"] in docs.check(root, CONTRACT)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-005")
def test_a_project_with_no_records_is_told_where_they_will_go(tmp_path):
    # A greenfield project has none by definition, so this is not a failure.
    root = project(tmp_path, complete())
    result = docs.decision_records(root, CONTRACT)
    assert result["problem"] is None
    assert result["resolved"] == CONTRACT["decision_records"]["candidates"][0]
    assert result["resolved"] in result["note"]
    assert docs.check(root, CONTRACT) == []


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-005")
def test_an_empty_candidate_directory_holds_no_records(tmp_path):
    # A directory somebody made is not a set of decisions the project keeps.
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    result = docs.decision_records(tmp_path, CONTRACT)
    assert result["found"] == []
    assert result["resolved"] == "docs/decisions/"


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
    # Stamped for the same reason: these fixtures replace the file wholesale,
    # and a missing stamp would mask the principle problem under test.
    files[CONSTITUTION] = body.replace("# C\n", f"# C\n{FRESH}\n", 1)
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


# --- freshness ---------------------------------------------------------------
#
# Nothing made a stale document visible: one that stopped being true read
# exactly like one that is. The stamp carries a change id as well as a date,
# because a date alone says somebody typed a date.

from datetime import date  # noqa: E402

STAMP = "Last verified: 2026-08-01 (change: abc123)"


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-004")
def test_a_document_with_no_stamp_is_reported(tmp_path):
    files = {k: v.replace(FRESH + "\n", "") for k, v in complete().items()}
    problems = docs.check(project(tmp_path, files), CONTRACT, today=date(2026, 8, 25))
    assert any("carries no" in p and "Last verified" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-004")
def test_a_stamped_document_passes(tmp_path):
    files = {k: f"{STAMP}\n\n{v}" for k, v in complete().items()}
    problems = docs.check(project(tmp_path, files), CONTRACT, today=date(2026, 8, 25))
    assert not any("Last verified" in p for p in problems), problems


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-004")
def test_a_future_stamp_is_refused(tmp_path):
    # It cannot be contradicted, so it claims freshness permanently.
    files = {k: "Last verified: 2099-01-01 (change: abc123)\n\n"
                + v.replace(FRESH + "\n", "")
             for k, v in complete().items()}
    problems = docs.check(project(tmp_path, files), CONTRACT, today=date(2026, 8, 25))
    assert any("in the future" in p for p in problems)


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-004")
def test_a_date_without_a_change_id_is_not_a_stamp(tmp_path):
    # A date alone says somebody typed a date.
    files = {k: "Last verified: 2026-08-01\n\n" + v.replace(FRESH + "\n", "")
             for k, v in complete().items()}
    problems = docs.check(project(tmp_path, files), CONTRACT, today=date(2026, 8, 25))
    assert any("carries no" in p for p in problems)


# --- the two documents the framework already required ------------------------

@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-004")
def test_a_runbook_is_declared():
    # artifact-policy.yml gives a runbook authority: authoritative_operational
    # and Output Done requires operability discharged, while no contract asked
    # anyone to write one.
    paths = {s["path"] for s in CONTRACT["required"]}
    assert ".specify/lifecycle/runbook.md" in paths
    spec = next(s for s in CONTRACT["required"] if s["path"].endswith("runbook.md"))
    names = {s["name"] for s in spec["sections"]}
    assert {"When it breaks", "Rollback"} <= names


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-004")
def test_the_domain_document_asks_what_a_word_does_not_mean():
    spec = next(s for s in CONTRACT["required"] if s["path"].endswith("domain.md"))
    vocab = next(s for s in spec["sections"] if s["name"] == "Vocabulary")
    assert "does not mean" in vocab["answers"].lower(), (
        "the third column is what earns this document")


@pytest.mark.req("REQ-PRODUCT-DOCUMENTS-004")
def test_deliberately_untested_is_a_section_not_a_document():
    paths = {s["path"] for s in CONTRACT["required"]}
    assert not any("testing" in p for p in paths), (
        "the rest of a testing document restates quality-gates.yml")
    product = next(s for s in CONTRACT["required"] if s["path"] == "PRODUCT.md")
    assert "Deliberately untested" in {s["name"] for s in product["sections"]}


# --- architecture provenance: describing the code, or proposing a change ------

ARCH_SPEC = next(
    e for e in yaml.safe_load(
        (ROOT / "policy/bootstrap-policy.yml").read_text(encoding="utf-8")
    )["product_documents"]["required"]
    if e["path"].endswith("architecture.md")
)
MARKERS = ARCH_SPEC["provenance"]["markers"]


def architecture(building="", strategy="", risks="", seams=""):
    """A document carrying only the sections a provenance test needs."""
    def table(rows):
        return "| What | Note |\n|---|---|\n" + "".join(
            f"| {r} | x |\n" for r in rows)

    return docs.sections_of(
        "## Context and scope\n\nIt talks to a disk.\n\n"
        f"## Building blocks\n\n{table(building)}\n"
        "## Solution strategy\n\n"
        + "".join(f"{i}. {s}\n" for i, s in enumerate(strategy, 1))
        + f"\n## Risks and technical debt\n\n{table(risks)}\n"
        f"## Seams\n\n{table(seams)}\n")


def problems(**kwargs):
    return docs.provenance_problems("arch.md", ARCH_SPEC,
                                         architecture(**kwargs))


# AC1 -- an entry that declares neither is reported.

@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_an_unmarked_entry_is_reported():
    found = problems(building=["`Database` holds a connection"])
    assert len(found) == 1
    assert "declares neither Observed nor Intended" in found[0]


@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_the_report_says_why_unmarked_is_not_neutral():
    # Unmarked reads as observed, which is the reading that does harm.
    found = problems(seams=["A seam nobody classified"])
    assert "Unmarked reads as observed" in found[0]


@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_a_marked_entry_passes():
    assert problems(building=["**Observed.** `Database` holds a connection"]) == []


@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_every_claim_bearing_section_is_checked():
    found = problems(building=["a"], strategy=["b"], risks=["c"], seams=["d"])
    assert len(found) == 4
    for title in ARCH_SPEC["provenance"]["applies_to"]:
        assert any(f"{title!r}" in p for p in found)


@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_prose_carries_no_per_entry_claim():
    # `Context and scope` is about the boundary and states no per-entry claim,
    # so it is absent from applies_to rather than exempted by name.
    assert "Context and scope" not in ARCH_SPEC["provenance"]["applies_to"]
    assert docs.entries_of("prose", "It talks to a disk.") == []


@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_a_marker_must_open_the_entry_not_merely_appear_in_it():
    # "As observed elsewhere, the walker..." has classified nothing. Accepting
    # it would make the marker decorative.
    found = problems(building=["The walker, as Observed in the audit, is new"])
    assert len(found) == 1


# AC4 -- a fix under the decisions heading belongs with the fixes.

@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_a_remediation_under_solution_strategy_is_reported():
    found = problems(
        building=["**Observed.** `Database` holds a connection"],
        strategy=["**Intended.** A logging seam exists. There is none."])
    assert len(found) == 1
    assert "is a fix rather than a decision" in found[0]
    assert "'Risks and technical debt'" in found[0]


@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_an_observed_decision_under_solution_strategy_passes():
    assert problems(
        building=["**Observed.** `Database` holds a connection"],
        strategy=["**Observed.** Exceptions propagate out of the transaction"],
    ) == []


@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_an_intended_entry_elsewhere_is_not_a_remediation():
    # Only the decisions heading. An intended risk or seam is ordinary.
    assert problems(
        building=["**Observed.** `Database` holds a connection"],
        risks=["**Intended.** Retire the second backend"],
        seams=["**Intended.** A logging seam"],
    ) == []


# AC5 -- a project with no code is not a project with a gap.

@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_a_document_observing_nothing_passes_with_everything_intended():
    """An empty as-built is the correct state for a project with no code.

    This is why the rule is "intended alongside something observed" rather
    than "intended under Solution strategy": greenfield has nothing to
    remediate, and reporting it would refuse the correct document.
    """
    assert problems(
        building=["**Intended.** Walker"],
        strategy=["**Intended.** The walker never opens a file for writing"],
        risks=["**Intended.** Nothing measured yet"],
        seams=["**Intended.** The reporter"],
    ) == []


@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_one_observed_entry_anywhere_makes_the_document_answerable():
    # The discriminator is the document, not the section: a single observed
    # row is what says this project has code to remediate.
    assert problems(
        seams=["**Observed.** The reporter"],
        strategy=["**Intended.** A logging seam exists. There is none."],
    ) != []


# --- the contract states it, and the mirror carries it ------------------------

@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_the_policy_states_the_form_an_author_writes():
    form = ARCH_SPEC["provenance"]["form"]
    for word in MARKERS.values():
        assert word in form
    assert "table row" in form and "list item" in form


@pytest.mark.req("REQ-PRODUCT-PROVENANCE-001")
def test_solution_strategy_no_longer_answers_two_questions():
    # One heading held arc42 decisions in one stream and a fix list in the
    # other. The contract now says which is which.
    strategy = next(s for s in ARCH_SPEC["sections"]
                    if s["name"] == "Solution strategy")
    assert "provenance.remediation" in strategy["answers"]
