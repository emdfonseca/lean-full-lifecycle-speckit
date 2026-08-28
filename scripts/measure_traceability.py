#!/usr/bin/env python3
"""Ask whether a requirement's cited tests actually run the code it names.

`validate_requirements.py` checks that a requirement names tests that exist and
that those tests claim it back. That reciprocity is worth having and it cannot
see inside a test: it reads `node.decorator_list` and never opens a body, so
reducing every cited test to `assert True` still reports "traceability
consistent". The catalogue would say verified and nothing would have run.

This measures instead of asserting. One suite run under `coverage` with
`dynamic_context = test_function` records which test executed which line; this
reads that database and asks, per requirement, whether any cited test executed
the component the requirement names.

**It speaks for executable components only, and says so.** `script:` and
`check:` are code; `policy:`, `command:`, `workflow:`, `extension:` and
`preset:` are files a human reads or manifests a runner consumes, and coverage
has nothing to say about them. A requirement built only from those is reported
`unmeasurable` -- never `passing`, because an absent measurement reading as a
satisfied one is the failure this whole exercise exists to remove.

So this strengthens part of the system rather than replacing it. Node existence
stays the only check for the rest, which is fine: node existence is the half
that already works.

One run, not one per requirement. Per-requirement pytest invocations would not
survive CI, and the contexts database answers every requirement from a single
pass.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from lib.inventory import ROOT  # noqa: E402

CATALOGUE = ROOT / "tooling" / "requirements" / "requirements.yml"
CHECKS = ROOT / "scripts" / "lib" / "checks.py"
DATA_FILE = ROOT / ".coverage"



class MeasurementError(Exception):
    """The measurement could not be made, and was not guessed at."""


def _fn(name: str) -> str:
    """A citation or a coverage context reduced to its test function.

    The two are written differently and must meet in the middle. A requirement
    cites `tests/test_x.py::test_y[param]`; coverage names its context after
    the importable module path, `test_x.test_y`, or
    `sandbox.test_bundle_mechanics.test_y` for a subdirectory. Reducing only
    the pytest form left every comparison false while the coverage database
    was perfectly correct.

    Parametrisation is dropped: a marker sits on the function, so it covers
    every parametrisation, and coverage names the context after the function
    too.
    """
    tail = name.rsplit("::", 1)[-1]
    tail = tail.rsplit(".", 1)[-1]
    return tail.split("[", 1)[0]


def check_ranges(path: Path = CHECKS) -> dict[str, tuple[int, int]]:
    """Each check id mapped to the line range of the function registering it.

    File granularity would be useless here: every check lives in one module, so
    "a test executed checks.py" is true of almost any test that runs the
    validator. The id comes from the `@check("INV-...")` decorator rather than
    from the function name, because the id is what a requirement cites.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, tuple[int, int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            named = getattr(decorator.func, "id", None)
            if named != "check" or not decorator.args:
                continue
            first = decorator.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                out[first.value] = (node.lineno, node.end_lineno or node.lineno)
    return out


def load_contexts(data_file: Path = DATA_FILE) -> dict[str, dict[int, set[str]]]:
    """file -> line -> the test functions that executed it."""
    try:
        import coverage
    except ImportError:  # pragma: no cover - reported, not guessed at
        raise MeasurementError(
            "coverage is not installed. It is in requirements-dev.txt; without "
            "it this measurement cannot be made and must not be reported as "
            "passing.") from None

    if not data_file.is_file():
        raise MeasurementError(
            f"{data_file} does not exist. Run the suite under coverage first: "
            f"`make measure`.")

    data = coverage.CoverageData(basename=str(data_file))
    data.read()
    out: dict[str, dict[int, set[str]]] = {}
    for measured in data.measured_files():
        try:
            relative = str(Path(measured).resolve().relative_to(ROOT))
        except ValueError:
            continue                       # outside the repository; not ours
        lines: dict[int, set[str]] = {}
        for lineno, contexts in (data.contexts_by_lineno(measured) or {}).items():
            named = {_fn(c) for c in contexts if c}
            if named:
                lines[lineno] = named
        out[relative] = lines
    if not out:
        raise MeasurementError(
            f"{data_file} records no files inside {ROOT}. It was written by a "
            f"run that measured something else.")
    return out


def is_measurable(ref: str) -> bool:
    """Whether coverage can say anything about this component at all.

    `script:` is used for any file the repository owns, not only for code:
    README.md, the Makefile, devbox.json and an extension manifest are all
    cited that way. Coverage executes none of them, and reporting a Makefile as
    "cited and not executed" would be the measurement crying wolf -- which is
    worse than not measuring, because people stop reading it.
    """
    kind, _, value = ref.partition(":")
    if kind == "check":
        return True
    return kind == "script" and value.endswith(".py")


def executed_by(contexts: dict[str, dict[int, set[str]]], ref: str,
                ranges: dict[str, tuple[int, int]]) -> set[str]:
    """Which test functions executed the component this reference names."""
    kind, _, value = ref.partition(":")
    if kind == "script":
        return set().union(*contexts.get(value, {}).values()) or set()
    if kind == "check":
        span = ranges.get(value)
        if span is None:
            raise MeasurementError(
                f"check {value!r} has no function in {CHECKS.name}, so nothing "
                f"can be measured for it")
        low, high = span
        lines = contexts.get(str(CHECKS.relative_to(ROOT)), {})
        found: set[str] = set()
        for lineno, tests in lines.items():
            if low <= lineno <= high:
                found |= tests
        return found
    return set()


def measure(contexts: dict[str, dict[int, set[str]]]) -> dict:
    catalogue = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    ranges = check_ranges()
    failures: list[dict] = []
    unmeasurable: list[str] = []
    measured = 0

    for req in catalogue["requirements"]:
        rid = req["id"]
        cited = {_fn(n) for n in req.get("verified_by") or []}
        refs = [r for r in req.get("components") or [] if is_measurable(r)]
        if not refs:
            # Not a pass. The requirement may be perfectly well verified; this
            # measurement simply has nothing to say about it.
            unmeasurable.append(rid)
            continue
        measured += 1
        for ref in refs:
            ran = executed_by(contexts, ref, ranges)
            if not (ran & cited):
                failures.append({
                    "requirement": rid,
                    "component": ref,
                    "detail": (f"no test named in verified_by executed {ref}. "
                               f"{len(ran)} other test(s) did."
                               if ran else
                               f"nothing in the suite executed {ref}."),
                })
    return {"measured": measured, "unmeasurable": unmeasurable,
            "failures": failures,
            "total": len(catalogue["requirements"])}


def render(result: dict) -> str:
    lines = [
        f"{result['measured']} of {result['total']} requirements carry a "
        f"component coverage can speak for.",
        f"{len(result['unmeasurable'])} are unmeasurable: every component "
        f"they name is a policy file, a command, a workflow, a manifest or "
        f"another file coverage does not execute. Unmeasurable is not passing; "
        f"`verified_by` node existence remains their only check.",
    ]
    if result["failures"]:
        lines.append("")
        lines.append(f"{len(result['failures'])} requirement/component pair(s) "
                     f"are cited and not executed:")
        for item in result["failures"]:
            lines.append(f"  {item['requirement']} -> {item['component']}: "
                         f"{item['detail']}")
    else:
        lines.append("")
        lines.append("Every measurable component is executed by a test that "
                     "cites it.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", action="store_true",
                    help="Run the suite under coverage first. Without it an "
                         "existing .coverage database is read.")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--data-file", type=Path, default=DATA_FILE)
    args = ap.parse_args()

    if args.run:
        # The subprocesses the suite spawns must measure themselves, or every
        # `check:` reads as never executed while the suite exercises all of
        # them. `sitecustomize` does that, and `parallel` keeps the data files
        # apart until they are combined.
        env = dict(os.environ)
        env["COVERAGE_PROCESS_START"] = str(
            ROOT / "tooling/coverage-subprocess/.coveragerc")
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT / "tooling/coverage-subprocess")]
            + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        for stale in ROOT.glob(".coverage*"):
            stale.unlink()
        result = subprocess.run(
            [sys.executable, "-m", "coverage", "run", "-m", "pytest", "-q"],
            cwd=ROOT, env=env)
        if result.returncode:
            print("the suite failed; measuring a failed run would report "
                  "coverage nobody should trust", file=sys.stderr)
            return result.returncode
        subprocess.run([sys.executable, "-m", "coverage", "combine"],
                       cwd=ROOT, env=env, capture_output=True)

    try:
        result = measure(load_contexts(args.data_file))
    except MeasurementError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2) if args.format == "json"
          else render(result))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
