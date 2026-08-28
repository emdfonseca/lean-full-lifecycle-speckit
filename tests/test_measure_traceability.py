"""Measuring whether a cited test runs the component it claims to verify.

`validate_requirements.py` reads decorators and never opens a test body, so
every cited test could be `assert True` and the catalogue would still report
"traceability consistent". This measures instead, and the tests here are built
on synthetic coverage data rather than on a real run: a real run takes two and a
half minutes, and a fixture that stages exactly one situation is the only way to
assert what happens when a test is gutted.

The property that matters most is the third: a requirement coverage cannot
speak for must report `unmeasurable`, never `passing`. An absent measurement
reading as a satisfied one would recreate, one layer up, the defect this
removes.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from lib.inventory import ROOT

SCRIPT = ROOT / "scripts/measure_traceability.py"

spec = importlib.util.spec_from_file_location("measure_traceability", SCRIPT)
measure = importlib.util.module_from_spec(spec)
sys.modules["measure_traceability"] = measure
spec.loader.exec_module(measure)


def contexts(mapping):
    """{relative path: {line: {test function}}}, the shape load_contexts returns."""
    return {path: {line: set(tests) for line, tests in lines.items()}
            for path, lines in mapping.items()}


def catalogue(tmp_path, requirements):
    import yaml
    path = tmp_path / "requirements.yml"
    path.write_text(yaml.safe_dump({"requirements": requirements}),
                    encoding="utf-8")
    return path


@pytest.fixture
def measured(monkeypatch, tmp_path):
    """Run the measurement against a catalogue and coverage we control."""
    def run(requirements, coverage_map, ranges=None):
        monkeypatch.setattr(measure, "CATALOGUE",
                            catalogue(tmp_path, requirements))
        monkeypatch.setattr(measure, "check_ranges",
                            lambda *a, **k: ranges or {})
        return measure.measure(contexts(coverage_map))
    return run


# AC1 -- a cited test that never runs the component is a failure, by name.

@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_a_component_no_cited_test_executes_is_reported(measured):
    result = measured(
        [{"id": "REQ-X-001", "components": ["script:scripts/thing.py"],
          "verified_by": ["tests/test_a.py::test_one"]}],
        {"scripts/thing.py": {4: {"test_other"}}})
    assert len(result["failures"]) == 1
    assert result["failures"][0]["requirement"] == "REQ-X-001"
    assert result["failures"][0]["component"] == "script:scripts/thing.py"


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_the_report_distinguishes_untested_from_uncited(measured):
    # "nothing ran it" and "the wrong tests ran it" are different problems and
    # lead to different fixes.
    nobody = measured(
        [{"id": "REQ-X-001", "components": ["script:scripts/thing.py"],
          "verified_by": ["tests/test_a.py::test_one"]}], {})
    assert "nothing in the suite executed" in nobody["failures"][0]["detail"]

    others = measured(
        [{"id": "REQ-X-001", "components": ["script:scripts/thing.py"],
          "verified_by": ["tests/test_a.py::test_one"]}],
        {"scripts/thing.py": {4: {"test_other"}}})
    assert "1 other test(s) did" in others["failures"][0]["detail"]


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_a_cited_test_that_runs_the_component_passes(measured):
    assert measured(
        [{"id": "REQ-X-001", "components": ["script:scripts/thing.py"],
          "verified_by": ["tests/test_a.py::test_one"]}],
        {"scripts/thing.py": {4: {"test_one"}}})["failures"] == []


# AC2 -- the failure the current system provably cannot catch.

@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_a_test_gutted_to_assert_true_is_caught(measured):
    """The reason for the whole change.

    `validate_requirements.py` reads `node.decorator_list` and never opens a
    body, so a cited test reduced to `assert True` still reports traceability
    consistent. A gutted test executes nothing, so it appears in no context for
    the component -- which is exactly what this reports.
    """
    result = measured(
        [{"id": "REQ-X-001", "components": ["script:scripts/thing.py"],
          "verified_by": ["tests/test_a.py::test_gutted"]}],
        {"scripts/thing.py": {4: {"test_something_else"}}})
    assert result["failures"]


# AC3 -- unmeasurable is not passing.

@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_a_requirement_with_no_executable_component_is_unmeasurable(measured):
    result = measured(
        [{"id": "REQ-X-001",
          "components": ["policy:state-machine.yml",
                         "command:speckit.x.y",
                         "workflow:lifecycle-z"],
          "verified_by": ["tests/test_a.py::test_one"]}], {})
    assert result["unmeasurable"] == ["REQ-X-001"]
    assert result["failures"] == []
    assert result["measured"] == 0


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_unmeasurable_is_reported_separately_from_passing(measured):
    # Counted apart, so "no failures" can never be read as "all verified".
    result = measured(
        [{"id": "REQ-A", "components": ["policy:p.yml"],
          "verified_by": ["tests/t.py::test_a"]},
         {"id": "REQ-B", "components": ["script:scripts/thing.py"],
          "verified_by": ["tests/t.py::test_b"]}],
        {"scripts/thing.py": {1: {"test_b"}}})
    assert result["measured"] == 1
    assert result["unmeasurable"] == ["REQ-A"]
    assert result["total"] == 2


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_a_non_python_file_cited_as_a_script_is_unmeasurable(measured):
    # `script:` names any file the repository owns -- README.md, the Makefile,
    # devbox.json, an extension manifest. Coverage executes none of them, and
    # reporting a Makefile as "cited and not executed" is the measurement
    # crying wolf.
    result = measured(
        [{"id": "REQ-X-001",
          "components": ["script:Makefile", "script:README.md",
                         "script:bundle/x/extension.yml"],
          "verified_by": ["tests/t.py::test_a"]}], {})
    assert result["unmeasurable"] == ["REQ-X-001"]
    assert result["failures"] == []


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_the_render_states_that_unmeasurable_is_not_passing():
    text = measure.render({"measured": 1, "total": 2, "unmeasurable": ["REQ-A"],
                           "failures": []})
    assert "Unmeasurable is not passing" in text


# --- check: components are asked at function granularity ----------------------

@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_a_check_is_measured_by_its_own_function_not_its_file(measured):
    """Every check lives in one module, so file granularity would say nothing.

    A test that ran any check would count as running all thirty-four.
    """
    ranges = {"INV-A": (10, 20), "INV-B": (30, 40)}
    rel = str(measure.CHECKS.relative_to(ROOT))
    result = measured(
        [{"id": "REQ-X-001", "components": ["check:INV-B"],
          "verified_by": ["tests/t.py::test_a"]}],
        {rel: {15: {"test_a"}}},          # ran INV-A's lines, not INV-B's
        ranges=ranges)
    assert result["failures"]

    result = measured(
        [{"id": "REQ-X-001", "components": ["check:INV-B"],
          "verified_by": ["tests/t.py::test_a"]}],
        {rel: {35: {"test_a"}}},
        ranges=ranges)
    assert result["failures"] == []


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_every_registered_check_maps_to_a_function():
    # Read from the real file: a check whose range cannot be found is measured
    # against nothing, and would pass by accident.
    ranges = measure.check_ranges()
    import json
    import subprocess
    rows = json.loads(subprocess.run(
        [sys.executable, "scripts/validate_source.py", "--list-checks",
         "--format", "json"], cwd=ROOT, text=True, capture_output=True).stdout)
    assert {r["id"] for r in rows} <= set(ranges)


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_an_unknown_check_is_refused_rather_than_passed(measured):
    with pytest.raises(measure.MeasurementError):
        measured([{"id": "REQ-X-001", "components": ["check:INV-NOPE"],
                   "verified_by": ["tests/t.py::test_a"]}], {}, ranges={})


# --- the two naming conventions must meet -------------------------------------

@pytest.mark.req("REQ-TOOLING-MEASURE-001")
@pytest.mark.parametrize("written,expected", [
    ("tests/test_x.py::test_one", "test_one"),
    ("tests/test_x.py::test_one[param]", "test_one"),
    ("test_x.test_one", "test_one"),
    ("sandbox.test_bundle_mechanics.test_one", "test_one"),
    ("test_one", "test_one"),
])
def test_a_citation_and_a_context_reduce_to_the_same_name(written, expected):
    """They are written differently and must meet in the middle.

    A requirement cites a pytest node id; coverage names its context after the
    importable module path. Reducing only the pytest form left every comparison
    false while the coverage database was perfectly correct.
    """
    assert measure._fn(written) == expected


# --- refusals -----------------------------------------------------------------

@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_an_absent_database_is_refused_not_reported_as_clean(tmp_path):
    with pytest.raises(measure.MeasurementError) as exc:
        measure.load_contexts(tmp_path / "nothing")
    assert "does not exist" in str(exc.value)


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_the_measurement_is_not_wired_into_validate():
    # It runs the whole suite under coverage. Putting that in `validate` would
    # make every source check pay for it.
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "measure:" in text
    validate = text.split("validate:")[1].split("\n\n")[0]
    assert "measure_traceability" not in validate


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_subprocess_coverage_is_configured():
    """Without it every `check:` reads as never executed.

    Tests here drive scripts through `subprocess.run` because the refusal text
    is what a reader sees, and `dynamic_context` needs a pytest frame the
    spawned process does not have.
    """
    rc = (ROOT / "tooling/coverage-subprocess/.coveragerc").read_text(
        encoding="utf-8")
    assert "context = ${COVERAGE_CONTEXT}" in rc
    site = (ROOT / "tooling/coverage-subprocess/sitecustomize.py").read_text(
        encoding="utf-8")
    assert "process_startup" in site
    conftest = (ROOT / "tests/conftest.py").read_text(encoding="utf-8")
    assert "COVERAGE_CONTEXT" in conftest


# AC4 -- the two systems run alongside and their disagreement is recorded.

RECORD = ROOT / "docs/evidence/traceability-measurement.md"


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_the_disagreement_between_the_two_systems_is_recorded():
    """Markers come out on evidence, not on faith.

    #171's own risk note asks for a release of both running alongside before
    anything is removed. This document is what that release reads.
    """
    text = RECORD.read_text(encoding="utf-8")
    assert "make measure" in text
    assert "Removing the markers" in text
    assert "Not yet" in text


@pytest.mark.req("REQ-TOOLING-MEASURE-001")
def test_the_record_says_what_each_system_can_and_cannot_answer():
    text = RECORD.read_text(encoding="utf-8")
    assert "Neither is a superset of the other" in text
    # The reach is measured rather than claimed.
    assert "80" in text and "45" in text
