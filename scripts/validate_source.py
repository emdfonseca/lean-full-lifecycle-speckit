#!/usr/bin/env python3
"""Structural and safety validator for the bundle source.

This complements, but does not replace, the official command:

    specify bundle validate --path bundle/ --offline
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
# The packaged surface. Everything outside it is development tooling: Spec Kit
# packages the whole bundle directory and honours no ignore file.
BUNDLE = ROOT / "bundle"

# Directories the publishing-placeholder scan never walks: build output, VCS
# and tool state, the local virtualenv, and agent scratch.
_SCAN_EXCLUDED = {"dist", ".git", ".venv", ".specify", ".claude", "__pycache__"}
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

ALLOWED_SHELL = {
    "devbox run verify",
    "devbox run release-verify",
}

CORE_COMMANDS = {
    "speckit.constitution",
    "speckit.specify",
    "speckit.clarify",
    "speckit.plan",
    "speckit.checklist",
    "speckit.tasks",
    "speckit.analyze",
    "speckit.implement",
    "speckit.converge",
}

EXTENSION_COMMANDS = {
    "speckit.github-lifecycle.inspect",
    "speckit.github-lifecycle.plan",
    "speckit.github-lifecycle.transition",
    "speckit.github-lifecycle.capture",
    "speckit.github-lifecycle.link",
    "speckit.github-lifecycle.doctor",
}

REQUIRED_POLICY = {
    "framework.yml",
    "state-machine.yml",
    "github-schema.yml",
    "risk-policy.yml",
    "quality-gates.yml",
    "model-routing.yml",
    "agent-policy.yml",
    "artifact-policy.yml",
    "exception-policy.yml",
    "outcome-policy.yml",
}


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_yaml(path: Path, result: Validation) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result.error(f"{path.relative_to(ROOT)}: invalid YAML: {exc}")
        return {}
    if not isinstance(value, dict):
        result.error(f"{path.relative_to(ROOT)}: expected a mapping")
        return {}
    return value


def load_json(path: Path, result: Validation) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result.error(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        result.error(f"{path.relative_to(ROOT)}: expected an object")
        return {}
    return value


def check_id(value: Any, label: str, result: Validation) -> None:
    if not isinstance(value, str) or not ID.fullmatch(value):
        result.error(f"{label}: invalid lowercase-hyphenated id: {value!r}")


def check_version(value: Any, label: str, result: Validation) -> None:
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        result.error(f"{label}: invalid semantic version: {value!r}")


def validate_bundle(result: Validation) -> dict[str, Any]:
    data = load_yaml(BUNDLE / "bundle.yml", result)
    if data.get("schema_version") != "1.0":
        result.error("bundle.yml: schema_version must be 1.0")

    bundle = data.get("bundle", {})
    check_id(bundle.get("id"), "bundle.id", result)
    check_version(bundle.get("version"), "bundle.version", result)

    provides = data.get("provides", {})
    preset_refs = provides.get("presets", [])
    extension_refs = provides.get("extensions", [])
    workflow_refs = provides.get("workflows", [])

    preset_ids = [
        entry.get("id") for entry in preset_refs if isinstance(entry, dict)
    ]
    if preset_ids != ["lean", "lean-full-lifecycle-governance"]:
        result.error(
            "bundle.yml: presets must compose official lean then governance"
        )

    by_id = {
        entry.get("id"): entry
        for entry in preset_refs
        if isinstance(entry, dict)
    }
    lean = by_id.get("lean", {})
    governance = by_id.get("lean-full-lifecycle-governance", {})
    if lean.get("priority") != 20 or lean.get("strategy") != "replace":
        result.error(
            "bundle.yml: official lean must use priority 20 / replace"
        )
    if (
        governance.get("priority") != 10
        or governance.get("strategy") != "append"
    ):
        result.error(
            "bundle.yml: governance must use priority 10 / append"
        )

    if [
        entry.get("id")
        for entry in extension_refs
        if isinstance(entry, dict)
    ] != ["github-lifecycle"]:
        result.error(
            "bundle.yml: github-lifecycle must be the only extension"
        )

    expected_workflows = sorted(
        path.parent.name
        for path in (BUNDLE / "components/workflows").glob("*/workflow.yml")
    )
    actual_workflows = sorted(
        entry.get("id")
        for entry in workflow_refs
        if isinstance(entry, dict)
    )
    if actual_workflows != expected_workflows:
        result.error(
            f"bundle.yml: workflow refs differ: "
            f"{actual_workflows} != {expected_workflows}"
        )

    bundle_version = bundle.get("version")
    component_refs = [
        *preset_refs[1:],
        *extension_refs,
        *workflow_refs,
    ]
    for entry in component_refs:
        if entry.get("version") != bundle_version:
            result.error(
                f"bundle.yml: {entry.get('id')} version differs from bundle"
            )

    return data


def validate_policy(result: Validation) -> None:
    root_policy = ROOT / "policy"
    preset_policy = (
        ROOT
        / "bundle/components/presets/lean-full-lifecycle-governance/policy"
    )

    root_files = {path.name for path in root_policy.glob("*.yml")}
    preset_files = {path.name for path in preset_policy.glob("*.yml")}

    if root_files != REQUIRED_POLICY:
        result.error(
            f"policy/: expected {sorted(REQUIRED_POLICY)}, "
            f"found {sorted(root_files)}"
        )
    if preset_files != REQUIRED_POLICY:
        result.error(
            "governance preset policy/: expected canonical policy copy"
        )

    for name in sorted(REQUIRED_POLICY):
        root_path = root_policy / name
        preset_path = preset_policy / name
        if not root_path.is_file() or not preset_path.is_file():
            continue
        load_yaml(root_path, result)
        load_yaml(preset_path, result)
        if root_path.read_bytes() != preset_path.read_bytes():
            result.error(
                f"policy/{name}: root and installed preset copies differ"
            )


def validate_preset(result: Validation) -> None:
    base = BUNDLE / "components/presets/lean-full-lifecycle-governance"
    manifest = load_yaml(base / "preset.yml", result)
    preset = manifest.get("preset", {})
    check_id(preset.get("id"), "preset.id", result)
    check_version(preset.get("version"), "preset.version", result)

    contributions = manifest.get("provides", {}).get("templates", [])
    names: set[tuple[str, str]] = set()
    for entry in contributions:
        key = (str(entry.get("type")), str(entry.get("name")))
        if key in names:
            result.error(f"preset.yml: duplicate contribution {key}")
        names.add(key)

        path = base / str(entry.get("file", ""))
        if not path.is_file():
            result.error(
                f"preset.yml: missing contribution file {entry.get('file')}"
            )
        if entry.get("strategy") != "append":
            result.error(
                f"preset.yml: contribution {key} must be append-only"
            )

    commands = {
        name for contribution_type, name in names
        if contribution_type == "command"
    }
    expected = {
        "speckit.constitution",
        "speckit.specify",
        "speckit.clarify",
        "speckit.checklist",
        "speckit.plan",
        "speckit.tasks",
        "speckit.analyze",
        "speckit.implement",
        "speckit.converge",
    }
    if commands != expected:
        result.error(
            f"preset.yml: command set mismatch: {sorted(commands)}"
        )


def validate_extension(result: Validation) -> None:
    base = BUNDLE / "components/extensions/github-lifecycle"
    manifest = load_yaml(base / "extension.yml", result)
    extension = manifest.get("extension", {})
    check_id(extension.get("id"), "extension.id", result)
    check_version(extension.get("version"), "extension.version", result)

    description = extension.get("description", "")
    if not isinstance(description, str) or len(description) >= 100:
        result.error(
            "extension.yml: description must be a string under 100 characters"
        )

    commands = manifest.get("provides", {}).get("commands", [])
    seen: set[str] = set()
    for entry in commands:
        name = str(entry.get("name"))
        if name in seen:
            result.error(f"extension.yml: duplicate command {name}")
        seen.add(name)
        if name not in EXTENSION_COMMANDS:
            result.error(f"extension.yml: unexpected command {name}")

        path = base / str(entry.get("file", ""))
        if not path.is_file():
            result.error(
                f"extension.yml: missing command file {entry.get('file')}"
            )

    if seen != EXTENSION_COMMANDS:
        result.error(
            f"extension.yml: command set mismatch: {sorted(seen)}"
        )

    for entry in manifest.get("provides", {}).get("config", []):
        path = base / str(entry.get("template", ""))
        if not path.is_file():
            result.error(
                f"extension.yml: missing config template "
                f"{entry.get('template')}"
            )

    config = load_yaml(base / "config-template.yml", result)
    safety = config.get("safety", {})
    for key in (
        "require_approved_plan_for_write",
        "require_read_back",
    ):
        if safety.get(key) is not True:
            result.error(
                f"config-template.yml: safety.{key} must be true"
            )
    if safety.get("allow_organization_schema_mutation") is not False:
        result.error(
            "config-template.yml: organization schema mutation must default false"
        )
    if safety.get("infer_output_done_from_closed_issue") is not False:
        result.error(
            "config-template.yml: closure must not imply Output Done"
        )


def prior_steps(
    steps: list[dict[str, Any]],
    index: int,
) -> list[dict[str, Any]]:
    return steps[:index]


def validate_transition_contract(
    workflow_id: str,
    steps: list[dict[str, Any]],
    index: int,
    result: Validation,
) -> None:
    step = steps[index]
    args = str(step.get("input", {}).get("args", ""))
    if "Approved plan:" not in args:
        result.error(
            f"{workflow_id}:{step.get('id')}: transition lacks approved plan"
        )

    earlier = prior_steps(steps, index)
    plans = [
        candidate
        for candidate in earlier
        if candidate.get("command") == "speckit.github-lifecycle.plan"
    ]
    gates = [
        candidate
        for candidate in earlier
        if candidate.get("type") == "gate"
    ]
    if not plans:
        result.error(
            f"{workflow_id}:{step.get('id')}: no prior lifecycle plan step"
        )
    if not gates:
        result.error(
            f"{workflow_id}:{step.get('id')}: no prior approval gate"
        )

    plan_path_match = re.search(
        r"Approved plan:\s*(.+?\.md)",
        args,
        flags=re.DOTALL,
    )
    if not plan_path_match:
        result.error(
            f"{workflow_id}:{step.get('id')}: "
            "approved plan path is not explicit"
        )
        return

    def normalize_path(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip())

    plan_path = normalize_path(plan_path_match.group(1))
    prior_plan_paths: list[str] = []
    for candidate in plans:
        candidate_args = str(
            candidate.get("input", {}).get("args", "")
        )
        match = re.search(
            r"Write exactly\s*(.+?\.md)",
            candidate_args,
            flags=re.DOTALL,
        )
        if match:
            prior_plan_paths.append(
                normalize_path(match.group(1))
            )

    if plan_path not in prior_plan_paths:
        result.error(
            f"{workflow_id}:{step.get('id')}: transition plan path "
            f"{plan_path!r} does not match prior plan paths "
            f"{prior_plan_paths!r}"
        )


def validate_workflows(result: Validation) -> None:
    for path in sorted(
        (BUNDLE / "components/workflows").glob("*/workflow.yml")
    ):
        data = load_yaml(path, result)
        workflow = data.get("workflow", {})
        workflow_id = path.parent.name

        if workflow.get("id") != workflow_id:
            result.error(
                f"{path.relative_to(ROOT)}: id must equal directory"
            )
        check_id(workflow.get("id"), f"{workflow_id}.id", result)
        check_version(
            workflow.get("version"),
            f"{workflow_id}.version",
            result,
        )

        inputs = data.get("inputs", {})
        steps = data.get("steps", [])
        if not isinstance(steps, list) or not steps:
            result.error(
                f"{workflow_id}: steps must be a non-empty list"
            )
            continue

        step_ids: set[str] = set()
        for index, step in enumerate(steps):
            step_id = step.get("id")
            if not isinstance(step_id, str) or not step_id:
                result.error(
                    f"{workflow_id}: every step requires an id"
                )
                continue
            if step_id in step_ids:
                result.error(
                    f"{workflow_id}: duplicate step id {step_id}"
                )
            step_ids.add(step_id)

            if step.get("type") == "gate":
                verdict = step.get("verdict_input")
                if verdict not in inputs:
                    result.error(
                        f"{workflow_id}:{step_id}: "
                        f"undeclared verdict input {verdict}"
                    )
                options = inputs.get(verdict, {}).get("enum", [])
                if "" not in options:
                    result.error(
                        f"{workflow_id}:{step_id}: "
                        "gate verdict enum must include empty string"
                    )

            if step.get("type") == "shell":
                run = str(step.get("run", ""))
                if "{{" in run or "}}" in run:
                    result.error(
                        f"{workflow_id}:{step_id}: "
                        "shell interpolation is forbidden"
                    )
                if run not in ALLOWED_SHELL:
                    result.error(
                        f"{workflow_id}:{step_id}: "
                        f"unapproved fixed shell command {run!r}"
                    )

            if "command" in step:
                command = str(step["command"])
                if command not in CORE_COMMANDS | EXTENSION_COMMANDS:
                    result.error(
                        f"{workflow_id}:{step_id}: "
                        f"unknown command {command}"
                    )
                if command == "speckit.github-lifecycle.transition":
                    validate_transition_contract(
                        workflow_id,
                        steps,
                        index,
                        result,
                    )

        if not (path.parent / "README.md").is_file():
            result.error(f"{workflow_id}: missing README.md")


def validate_catalogs(
    result: Validation,
    strict_publish: bool,
) -> None:
    expected_version = load_yaml(
        BUNDLE / "bundle.yml",
        result,
    ).get("bundle", {}).get("version")

    for path in sorted((ROOT / "catalogs").glob("*.json")):
        data = load_json(path, result)
        if data.get("schema_version") != "1.0":
            result.error(
                f"{path.relative_to(ROOT)}: schema_version must be 1.0"
            )

        text = path.read_text(encoding="utf-8")
        if "YOUR-ORG" in text:
            message = (
                f"{path.relative_to(ROOT)}: "
                "contains YOUR-ORG publishing placeholder"
            )
            if strict_publish:
                result.error(message)
            else:
                result.warn(message)

        for collection_name in (
            "presets",
            "extensions",
            "workflows",
            "bundles",
        ):
            for item in data.get(collection_name, {}).values():
                if item.get("version") != expected_version:
                    result.error(
                        f"{path.relative_to(ROOT)}: "
                        f"{item.get('id')} version differs from bundle"
                    )


def validate_docs(
    result: Validation,
    strict_publish: bool,
) -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file() or _SCAN_EXCLUDED.intersection(path.parts):
            continue
        if path.suffix not in {
            ".md",
            ".yml",
            ".yaml",
            ".json",
            ".py",
        }:
            continue

        text = path.read_text(encoding="utf-8")
        if "YOUR-ORG" in text:
            message = (
                f"{path.relative_to(ROOT)}: "
                "contains YOUR-ORG publishing placeholder"
            )
            if strict_publish:
                result.error(message)
            elif path.parts[0] != "catalogs":
                result.warn(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-publish", action="store_true")
    args = parser.parse_args()

    result = Validation()
    validate_bundle(result)
    validate_policy(result)
    validate_preset(result)
    validate_extension(result)
    validate_workflows(result)
    validate_catalogs(result, args.strict_publish)
    validate_docs(result, args.strict_publish)

    print(f"Errors: {len(result.errors)}")
    for error in result.errors:
        print(f"ERROR: {error}")
    print(f"Warnings: {len(result.warnings)}")
    for warning in sorted(set(result.warnings)):
        print(f"WARNING: {warning}")

    if result.errors:
        return 1

    print("Source structure and safety invariants are internally consistent.")
    print("Run `specify bundle validate --path bundle/ --offline` before publishing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
