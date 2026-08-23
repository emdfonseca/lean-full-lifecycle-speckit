"""Make owns the tasks; Devbox provisions and supervises.

The roadmap specified `devbox run validate/test/build/smoke` while the Makefile
already defined all four. Two definitions of one task is the drift this
repository exists to prevent, so the resolution is enforced rather than merely
documented: a Devbox script may only delegate to Make.
"""
from __future__ import annotations

import json
import re

import pytest

from lib.inventory import ROOT

DEVBOX = ROOT / "devbox.json"
MAKEFILE = ROOT / "Makefile"


def make_targets() -> set[str]:
    text = MAKEFILE.read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^([a-z][a-z-]*):", text, re.MULTILINE)}


def devbox_scripts() -> dict[str, list[str]]:
    return json.loads(DEVBOX.read_text(encoding="utf-8"))["shell"]["scripts"]


@pytest.mark.req("REQ-TOOLING-TASKS-001")
def test_every_devbox_script_only_delegates_to_make():
    for name, lines in devbox_scripts().items():
        assert len(lines) == 1, f"devbox script {name!r} does more than delegate: {lines}"
        assert re.fullmatch(r"make [a-z][a-z-]*", lines[0]), (
            f"devbox script {name!r} must be exactly 'make <target>', got {lines[0]!r}. "
            "Task logic belongs in the Makefile."
        )


@pytest.mark.req("REQ-TOOLING-TASKS-001")
def test_every_devbox_script_targets_a_real_make_target():
    targets = make_targets()
    for name, lines in devbox_scripts().items():
        target = lines[0].split()[1]
        assert target in targets, f"devbox script {name!r} calls missing target {target!r}"


def test_devbox_does_not_claim_the_default_venv():
    # The python plugin offers to overwrite a venv it did not create, which is an
    # interactive prompt and would hang CI.
    env = json.loads(DEVBOX.read_text(encoding="utf-8")).get("env", {})
    assert env.get("VENV_DIR", "").endswith(".devbox-venv")


def test_catalog_service_is_declared():
    import yaml

    pc = yaml.safe_load((ROOT / "process-compose.yaml").read_text(encoding="utf-8"))
    assert "catalog" in pc["processes"]
    assert "readiness_probe" in pc["processes"]["catalog"], (
        "a service with no readiness probe reports Ready before it can serve"
    )
