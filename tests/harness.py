"""Walk a workflow's steps without a model, so its shape can be tested.

Every workflow test until now read the YAML and asserted a step existed, a gate
preceded a write, or a prompt contained a sentence. The P12 coverage map showed
what that bought: the adversarial pass refuted claim after claim with one
sentence — *delete that clause and every cited test still passes*.

This runs a workflow instead. It needs no model, because the two things a model
does are the two things it deliberately will not do:

**A gate consults a scripted verdict.** The caller decides in advance what the
human says, which is the only part of a gate a test cares about.

**A prompt step is recorded, never simulated.** What the workflow asked for is
captured; whether prose was followed needs a model and belongs to pilots. A
harness that invented a plausible result would manufacture exactly the false
confidence the map exposed.

**Command steps really execute**, but only where the caller supplies the
invocation. Our command steps carry `input.args` written for an agent -- "Plan
issue #142 ... Write exactly ..." -- and no command line can be derived from
that. So the caller passes the invocation for the commands its test is about,
and the rest are recorded like prompts. The harness never guesses one.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lib.inventory import ROOT, load_yaml

WORKFLOWS = ROOT / "bundle/components/workflows"
EXTENSION_SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"

APPROVE = "approve"
REJECT = "reject"

# What a step did, kept distinct so a test can tell execution from observation.
EXECUTED = "executed"
RECORDED = "recorded"
GATED = "gated"


class WorkflowError(Exception):
    """The workflow could not be run as written."""


@dataclass
class Visit:
    step_id: str
    kind: str          # prompt | gate | command | shell | switch
    outcome: str       # executed | recorded | gated
    detail: str = ""
    args: str = ""


@dataclass
class Run:
    visits: list[Visit] = field(default_factory=list)
    aborted_at: str | None = None
    reason: str = ""

    @property
    def step_ids(self) -> list[str]:
        return [v.step_id for v in self.visits]

    @property
    def completed(self) -> bool:
        return self.aborted_at is None

    def executed(self) -> list[str]:
        return [v.step_id for v in self.visits if v.outcome == EXECUTED]

    def recorded(self) -> list[str]:
        return [v.step_id for v in self.visits if v.outcome == RECORDED]

    def asked_for(self, step_id: str) -> str:
        """What the step asked for, or what it produced if it executed."""
        for visit in self.visits:
            if visit.step_id == step_id:
                # An executed command's output is the interesting half; for
                # everything else it is the instruction.
                return visit.args if visit.outcome == EXECUTED \
                    else (visit.detail or visit.args)
        raise KeyError(f"{step_id} was not visited; visited {self.step_ids}")


def load(workflow_id: str) -> dict:
    path = WORKFLOWS / workflow_id / "workflow.yml"
    if not path.is_file():
        raise WorkflowError(f"no workflow {workflow_id!r} at {path}")
    return load_yaml(path)


_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\.([a-z_0-9]+)\s*\}\}")


def render(text: str, inputs: dict, run_id: str) -> str:
    """Substitute the two namespaces the workflows use. Nothing else."""
    def swap(match: re.Match) -> str:
        namespace, name = match.group(1), match.group(2)
        if namespace == "inputs":
            return str(inputs.get(name, match.group(0)))
        if namespace == "context" and name == "run_id":
            return run_id
        return match.group(0)

    return _PLACEHOLDER.sub(swap, text or "")


def resolve_inputs(workflow: dict, given: dict) -> dict:
    """Declared defaults, overridden by what the caller passed."""
    resolved = {}
    for name, spec in (workflow.get("inputs") or {}).items():
        spec = spec or {}
        if name in given:
            value = given[name]
        elif "default" in spec:
            value = spec["default"]
        elif spec.get("required"):
            raise WorkflowError(f"input {name!r} is required and was not given")
        else:
            value = ""
        enum = spec.get("enum")
        # `auto` is exempt from enum membership in Spec Kit itself; anything
        # else outside the enum is an authoring error the runner would reject.
        if enum and value not in enum and value != "auto":
            raise WorkflowError(
                f"input {name!r} is {value!r}, not one of {enum}")
        resolved[name] = value
    return resolved


def run(workflow_id: str, *, inputs: dict | None = None,
        verdicts: dict | None = None, invocations: dict | None = None,
        project: Path | None = None, expect_steps: list[str] | None = None,
        run_id: str = "test-run") -> Run:
    """Walk the workflow.

    `verdicts` maps a gate's step id to `approve` or `reject`; a gate with no
    verdict is an error rather than an assumed approval.
    `invocations` maps a command name to argv; a command without one is
    recorded, never invented.
    """
    workflow = load(workflow_id)
    values = resolve_inputs(workflow, inputs or {})
    verdicts = verdicts or {}
    invocations = invocations or {}
    project = project or ROOT
    result = Run()

    if expect_steps is not None:
        present = set(_all_step_ids(workflow["steps"]))
        missing = [s for s in expect_steps if s not in present]
        if missing:
            # A workflow that changed shape fails loudly. Skipping would let a
            # renamed step read as a passing test.
            raise WorkflowError(
                f"{workflow_id} does not contain {missing}; it has "
                f"{sorted(present)}")

    _walk(workflow["steps"], values, verdicts, invocations, project, result,
          run_id)
    return result


def _all_step_ids(steps: list[dict]) -> list[str]:
    out = []
    for step in steps:
        out.append(step.get("id"))
        for case in (step.get("cases") or {}).values():
            out.extend(_all_step_ids(case))
    return [s for s in out if s]


def _walk(steps, values, verdicts, invocations, project, result, run_id) -> bool:
    for step in steps:
        step_id = step.get("id", "<unnamed>")
        kind = step.get("type") or ("command" if step.get("command") else "prompt")

        if kind == "switch":
            expression = render(step["expression"], values, run_id)
            case = (step.get("cases") or {}).get(expression)
            if case is None:
                raise WorkflowError(
                    f"{step_id}: no case for {expression!r}; cases are "
                    f"{sorted(step.get('cases') or {})}")
            result.visits.append(
                Visit(step_id, kind, RECORDED, detail=f"took case {expression}"))
            if not _walk(case, values, verdicts, invocations, project, result,
                         run_id):
                return False
            continue

        if kind == "gate":
            if step_id not in verdicts:
                # An unscripted gate is not an approval. Defaulting to one
                # would make every gate invisible to the test that forgot it.
                raise WorkflowError(
                    f"{step_id} is a gate and no verdict was scripted for it")
            verdict = verdicts[step_id]
            result.visits.append(
                Visit(step_id, kind, GATED, detail=verdict,
                      args=render(step.get("message", ""), values, run_id)))
            if verdict == REJECT:
                result.aborted_at = step_id
                result.reason = f"gate {step_id} rejected"
                return False
            continue

        if kind == "command":
            name = step["command"]
            argv = invocations.get(name)
            args = render((step.get("input") or {}).get("args", ""), values,
                          run_id)
            if argv is None:
                result.visits.append(
                    Visit(step_id, kind, RECORDED, detail=name, args=args))
                continue
            completed = subprocess.run(
                [sys.executable, *argv], cwd=project, capture_output=True,
                text=True)
            result.visits.append(
                Visit(step_id, kind, EXECUTED, detail=name,
                      args=(completed.stdout + completed.stderr)[:2000]))
            if completed.returncode != 0:
                # A refusal from a real script stops the run, the same way it
                # would stop an agent following the command.
                result.aborted_at = step_id
                result.reason = (f"{name} refused: "
                                 f"{(completed.stderr or completed.stdout).strip()[:300]}")
                return False
            continue

        if kind == "shell":
            result.visits.append(
                Visit(step_id, kind, RECORDED, detail=step.get("run", "")))
            continue

        result.visits.append(
            Visit(step_id, kind, RECORDED,
                  args=render(step.get("prompt", ""), values, run_id)))
    return True
