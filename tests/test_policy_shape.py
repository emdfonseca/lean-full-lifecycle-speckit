"""Policy files that must agree with each other, and artifacts that must not collide."""
from __future__ import annotations

import pytest

from lib.inventory import ROOT, load_yaml


@pytest.mark.req("REQ-GITHUB-FIELDS-001")
def test_the_schema_and_the_state_machine_agree_on_delivery_status():
    # github-schema.yml omitted Retired, which state-machine.yml declares. A
    # config field that contradicts a sibling policy file is worse than an
    # inert one: a reader cannot tell which is authoritative.
    machine = load_yaml(ROOT / "policy/state-machine.yml")
    schema = load_yaml(ROOT / "policy/github-schema.yml")
    declared = [str(v) for v in machine["delivery_status"]["values"]]
    listed = [str(v) for v in schema["issue_fields"]["Delivery Status"]["values"]]
    assert listed == declared, (
        f"github-schema.yml lists {listed}, state-machine.yml declares {declared}")


@pytest.mark.req("REQ-PACKAGE-ARTIFACT-001")
def test_every_workflow_artifact_is_scoped_to_its_run():
    # bugfix-assessment.md carried no run id, so two bugfix runs overwrote each
    # other's assessment -- the one artifact its gate shows.
    import re
    bad = []
    for f in sorted((ROOT / "bundle/components/workflows").glob("*/workflow.yml")):
        text = f.read_text(encoding="utf-8")
        for path in re.findall(r"\.specify/lifecycle/[\w./{}\s-]*?\.md", text):
            flat = " ".join(path.split())
            if "{{" in flat or flat.endswith("/lifecycle/release-readiness.md") \
               or flat.endswith("rollout-plan.md") or flat.endswith("incident-record.md") \
               or "brownfield-" in flat or "greenfield-" in flat:
                continue
            bad.append(f"{f.parent.name}: {flat}")
    assert not bad, f"artifacts two runs would overwrite: {bad}"
