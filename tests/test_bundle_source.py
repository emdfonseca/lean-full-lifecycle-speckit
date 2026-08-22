from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class BundleSourceTests(unittest.TestCase):
    def test_source_validator(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate_source.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bundle_references_local_components(self) -> None:
        bundle = yaml.safe_load(
            (ROOT / "bundle.yml").read_text(encoding="utf-8")
        )
        provides = bundle["provides"]

        self.assertEqual(
            [entry["id"] for entry in provides["presets"]],
            ["lean", "lean-full-lifecycle-governance"],
        )
        self.assertTrue(
            (
                ROOT
                / "components/presets/"
                "lean-full-lifecycle-governance/preset.yml"
            ).exists()
        )
        self.assertTrue(
            (
                ROOT
                / "components/extensions/github-lifecycle/extension.yml"
            ).exists()
        )

        for ref in provides["workflows"]:
            path = (
                ROOT
                / "components/workflows"
                / ref["id"]
                / "workflow.yml"
            )
            self.assertTrue(path.exists(), ref["id"])

    def test_workflow_shell_steps_are_fixed(self) -> None:
        allowed = {"devbox run verify", "devbox run release-verify"}
        for path in (ROOT / "components/workflows").glob("*/workflow.yml"):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            for step in workflow["steps"]:
                if step.get("type") != "shell":
                    continue
                run = step["run"]
                self.assertNotIn("{{", run)
                self.assertIn(run, allowed)

    def test_gate_inputs_are_declared(self) -> None:
        for path in (ROOT / "components/workflows").glob("*/workflow.yml"):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            inputs = workflow["inputs"]
            for step in workflow["steps"]:
                if step.get("type") != "gate":
                    continue
                verdict = step["verdict_input"]
                self.assertIn(verdict, inputs)
                self.assertIn("", inputs[verdict]["enum"])

    def test_transition_commands_have_prior_plans_and_gates(self) -> None:
        for path in (ROOT / "components/workflows").glob("*/workflow.yml"):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            steps = workflow["steps"]
            for index, step in enumerate(steps):
                if (
                    step.get("command")
                    != "speckit.github-lifecycle.transition"
                ):
                    continue
                args = step["input"]["args"]
                self.assertIn("Approved plan:", args)
                prior = steps[:index]
                self.assertTrue(
                    any(
                        candidate.get("command")
                        == "speckit.github-lifecycle.plan"
                        for candidate in prior
                    ),
                    f"{path.parent.name}:{step['id']}",
                )
                self.assertTrue(
                    any(
                        candidate.get("type") == "gate"
                        for candidate in prior
                    ),
                    f"{path.parent.name}:{step['id']}",
                )

    def test_root_and_installed_policy_copies_match(self) -> None:
        root_policy = ROOT / "policy"
        preset_policy = (
            ROOT
            / "components/presets/"
            "lean-full-lifecycle-governance/policy"
        )
        root_files = sorted(
            path.name for path in root_policy.glob("*.yml")
        )
        preset_files = sorted(
            path.name for path in preset_policy.glob("*.yml")
        )
        self.assertEqual(root_files, preset_files)
        self.assertEqual(len(root_files), 10)

        for name in root_files:
            self.assertEqual(
                (root_policy / name).read_bytes(),
                (preset_policy / name).read_bytes(),
                name,
            )

    def test_catalogs_parse(self) -> None:
        for path in (ROOT / "catalogs").glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], "1.0")

    def test_dev_installer_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/install_dev.py"),
                    "--target",
                    tmp,
                    "--integration",
                    "opencode",
                    "--dry-run",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                result.stdout + result.stderr,
            )
            self.assertIn("specify init --here", result.stdout)
            self.assertIn("lifecycle-story-delivery", result.stdout)


if __name__ == "__main__":
    unittest.main()
