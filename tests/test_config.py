"""Reading what the project declared, rather than being told it again.

`config-template.yml` has declared the organization, repository, project
number, field names, and a safety block since 0.1.0, and only `doctor.py` read
it. Every other script took `--repo` and `--project` as required flags, so the
target arrived as an argument an agent composed — which makes a wrong project
number a typo rather than a misconfiguration.
"""
from __future__ import annotations

import importlib.util
import sys

import pytest

from lib.inventory import ROOT

SCRIPTS = ROOT / "bundle/components/extensions/github-lifecycle/scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("project_root")
cfg = _load("config")


def project(tmp_path, **values):
    home = tmp_path / ".specify/extensions/github-lifecycle"
    home.mkdir(parents=True)
    (tmp_path / ".specify").mkdir(exist_ok=True)
    if values:
        import yaml

        (home / "github-lifecycle-config.yml").write_text(
            yaml.safe_dump(values), encoding="utf-8")
    return tmp_path


# --- the config answers when the flag does not --------------------------------

@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_the_repository_is_resolved_from_the_config(tmp_path):
    root = project(tmp_path, organization="acme", repository="widgets",
                   project_number=7)
    target = cfg.resolve_target(root=root, env={})
    assert target.repo == "acme/widgets"
    assert target.project == 7
    assert target.owner == "acme"


@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_an_explicit_flag_wins_over_the_config(tmp_path):
    # A caller that passed one has already decided. A config that quietly
    # overrode it would be worse than no config.
    root = project(tmp_path, organization="acme", repository="widgets",
                   project_number=7)
    target = cfg.resolve_target("other/repo", 9, root=root, env={})
    assert target.repo == "other/repo"
    assert target.project == 9
    assert target.source == "--repo"


@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_the_local_sibling_is_preferred(tmp_path):
    import yaml

    root = project(tmp_path, organization="acme", repository="widgets")
    home = root / ".specify/extensions/github-lifecycle"
    (home / "github-lifecycle-config.local.yml").write_text(
        yaml.safe_dump({"organization": "mine", "repository": "fork"}),
        encoding="utf-8")
    # Spec Kit reads the local sibling first and preserves it across updates,
    # so a person's own value belongs there.
    assert cfg.resolve_target(root=root, env={}).repo == "mine/fork"


@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_the_environment_beats_the_config_and_loses_to_the_flag(tmp_path):
    root = project(tmp_path, organization="acme", repository="widgets")
    env = {cfg.REPO_ENV: "env/repo"}
    assert cfg.resolve_target(root=root, env=env).repo == "env/repo"
    assert cfg.resolve_target("flag/repo", root=root, env=env).repo == "flag/repo"


# --- refusing rather than guessing --------------------------------------------

@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_no_repository_anywhere_is_refused(tmp_path):
    with pytest.raises(cfg.ConfigError) as exc:
        cfg.resolve_target(root=project(tmp_path), env={})
    assert "no repository" in str(exc.value)


@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_the_refusal_names_the_file_to_edit(tmp_path):
    with pytest.raises(cfg.ConfigError) as exc:
        cfg.resolve_target(root=project(tmp_path), env={})
    assert "github-lifecycle-config" in str(exc.value)
    assert cfg.REPO_ENV in str(exc.value)


@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_a_null_repository_is_not_a_repository(tmp_path):
    # The shipped template declares the keys as null. Present-but-null must not
    # resolve to the string "None/None".
    root = project(tmp_path, organization=None, repository=None)
    with pytest.raises(cfg.ConfigError):
        cfg.resolve_target(root=root, env={})


@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_a_malformed_repository_is_refused(tmp_path):
    root = project(tmp_path, repository="widgets")
    with pytest.raises(cfg.ConfigError) as exc:
        cfg.resolve_target(root=root, env={})
    assert "no repository" in str(exc.value) or "owner/name" in str(exc.value)


@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_an_unparseable_config_refuses_rather_than_falling_through(tmp_path):
    # Falling through to the next candidate would silently use a different
    # project's settings.
    root = project(tmp_path)
    home = root / ".specify/extensions/github-lifecycle"
    (home / "github-lifecycle-config.yml").write_text(
        "organization: [unclosed", encoding="utf-8")
    with pytest.raises(cfg.ConfigError) as exc:
        cfg.load(root)
    assert "refusing to fall through" in str(exc.value)


@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_a_missing_project_number_is_none_not_an_error(tmp_path):
    # Not every backend needs one: organization Issue Fields carry state on the
    # issue itself.
    root = project(tmp_path, organization="acme", repository="widgets")
    assert cfg.resolve_target(root=root, env={}).project is None


# --- the rest of the config is reachable --------------------------------------

@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_declared_field_names_are_readable(tmp_path):
    root = project(tmp_path, organization="a", repository="b",
                   fields={"delivery_status": "Lifecycle State"})
    assert cfg.field_names(root)["delivery_status"] == "Lifecycle State"


@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_declared_safety_switches_are_readable(tmp_path):
    root = project(tmp_path, organization="a", repository="b",
                   safety={"infer_output_done_from_closed_issue": False})
    assert cfg.safety(root)["infer_output_done_from_closed_issue"] is False


@pytest.mark.req("REQ-GITHUB-CONFIG-001")
def test_the_scripts_no_longer_require_the_flag():
    # The point of the change: an agent should not have to be told the target
    # before it can do anything.
    for name in ("transition_plan.py", "capture.py", "decompose.py",
                 "relationships.py", "inspect_target.py", "triage.py"):
        source = (SCRIPTS / name).read_text(encoding="utf-8")
        assert '"--repo", required=True' not in source, name
        assert "config.resolve_target" in source, name


# --- a project number belongs to its repository ------------------------------
#
# Carrying it across let a command aimed elsewhere keep this project's board,
# and an explicit project short-circuits discovery, so the repository-scoped
# lookup could not catch it either.

CONFIGURED = """schema_version: "1.0"
organization: acme
repository: widgets
project_number: 3
"""


def _configured(tmp_path):
    d = tmp_path / ".specify/extensions/github-lifecycle"
    d.mkdir(parents=True)
    (d / "github-lifecycle-config.yml").write_text(CONFIGURED, encoding="utf-8")
    return tmp_path


@pytest.mark.req("REQ-GITHUB-CONFIG-002")
def test_the_configured_repository_still_inherits_its_project(tmp_path):
    target = cfg.resolve_target(None, None, _configured(tmp_path), env={})
    assert target.repo == "acme/widgets"
    assert target.project == 3


@pytest.mark.req("REQ-GITHUB-CONFIG-002")
def test_naming_the_same_repository_explicitly_still_inherits(tmp_path):
    target = cfg.resolve_target("acme/widgets", None, _configured(tmp_path), env={})
    assert target.project == 3


@pytest.mark.req("REQ-GITHUB-CONFIG-002")
def test_another_repository_does_not_inherit_the_project(tmp_path):
    # Discovery then finds the board this repository is linked to, or reports
    # that it has none.
    target = cfg.resolve_target("acme/other", None, _configured(tmp_path), env={})
    assert target.repo == "acme/other"
    assert target.project is None


@pytest.mark.req("REQ-GITHUB-CONFIG-002")
def test_naming_both_halves_explicitly_is_honoured(tmp_path):
    # The caller named the repository and the board, so nothing is inherited
    # and nothing is silent -- which is the whole defect. Refusing this would
    # remove a legitimate use to fix a different problem.
    target = cfg.resolve_target("acme/other", 9, _configured(tmp_path), env={})
    assert target.repo == "acme/other"
    assert target.project == 9


@pytest.mark.req("REQ-GITHUB-CONFIG-002")
def test_an_explicit_project_for_the_configured_repository_is_allowed(tmp_path):
    target = cfg.resolve_target("acme/widgets", 9, _configured(tmp_path), env={})
    assert target.project == 9


@pytest.mark.req("REQ-GITHUB-CONFIG-002")
def test_a_config_declaring_no_repository_constrains_nothing(tmp_path):
    d = tmp_path / ".specify/extensions/github-lifecycle"
    d.mkdir(parents=True)
    (d / "github-lifecycle-config.yml").write_text(
        'schema_version: "1.0"\nproject_number: 3\n', encoding="utf-8")
    target = cfg.resolve_target("acme/other", None, tmp_path, env={})
    assert target.project == 3, "a config naming no repository should not gate"
