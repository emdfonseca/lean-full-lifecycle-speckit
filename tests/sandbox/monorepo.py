"""Building a monorepo of Spec Kit members, for the tests that need one.

Two files need the same fixture and must not share an instance: the
contamination tests in `test_monorepo.py` end by removing the bundle from a
member, and an overlay test that inherited that state would be asserting
against a project somebody already dismantled. So this builds one on request
rather than exposing a shared fixture.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

MEMBERS = ("member_a", "member_b")


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True)


def build(root: Path, base: str, features: dict[str, str]) -> Path:
    """One git root, a Spec Kit project per member, each declaring a feature.

    `base` is a live local catalog. It has to stay live for the caller's whole
    module: `bundle update` re-resolves from the catalog, and against a dead
    server it fails without touching anything, which reads as a pass.
    """
    import local_catalog

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "root"], cwd=root,
        check=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e",
             "PATH": os.environ["PATH"], "HOME": str(root)})

    for member in MEMBERS:
        path = root / member
        path.mkdir(exist_ok=True)
        r = run(["specify", "init", "--here", "--force", "--non-interactive",
                 "--integration", "opencode", "--script", "py"], path)
        assert r.returncode == 0, r.stderr
        local_catalog.register(path, base)
        local_catalog.install_workflows(path)
        assert run(["specify", "bundle", "install", "lean-full-lifecycle"],
                   path).returncode == 0
        feature = features[member]
        (path / feature).mkdir(parents=True, exist_ok=True)
        (path / ".specify" / "feature.json").write_text(
            json.dumps({"feature_directory": feature}), encoding="utf-8")
    return root
