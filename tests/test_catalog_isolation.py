"""Two catalog servers at once, each serving its own build.

The suite takes 2:16, and `tests/sandbox` is 52 of its 1535 tests and 85s of
that time. The work is real -- installing the bundle through the actual
`specify` CLI -- so the way to shorten it is to run those modules concurrently
rather than to fake them.

One thing stopped that. `build_release.main()` empties its output directory
before refilling it, and every caller used the same `dist/`. Six module-scoped
fixtures hold a catalog server open over it, so under `pytest -n` each rebuild
deleted archives the others were still serving and each rewrote `catalogs/`
with its own port. The failure never appeared serially, because each module's
server closed before the next opened (#191).

The port was already per-server via `_free_port()`. The directory was the one
shared thing, and it was shared by construction rather than by accident.
"""
from __future__ import annotations

import json
import urllib.request

import pytest

from lib.inventory import ROOT

import local_catalog


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read()


@pytest.mark.sandbox
@pytest.mark.req("REQ-PACKAGE-CATALOG-002")
def test_a_second_build_does_not_empty_the_first_servers_directory(tmp_path_factory):
    # The reported failure is `FileNotFoundError` on an archive the other
    # server was still serving, and it needs true concurrency to land: a read
    # during a wipe. What is deterministic is the wipe itself, so that is what
    # is asserted.
    #
    # Comparing archive names would not work and was tried: the second build
    # writes the same filenames back, so the list looks untouched even when the
    # directory was emptied under the first server. A marker only the first
    # build's directory holds does distinguish them.
    first = tmp_path_factory.mktemp("dist-a")
    second = tmp_path_factory.mktemp("dist-b")

    with local_catalog.serve(dist=first) as base_a:
        assert sorted(first.glob("*.zip")), "the first server built no archives"
        marker = first / "served-by-the-first.marker"
        marker.write_text("held open", encoding="utf-8")
        with local_catalog.serve(dist=second) as base_b:
            assert base_a != base_b
            assert marker.is_file(), (
                "the second build emptied the first server's directory")


@pytest.mark.sandbox
@pytest.mark.req("REQ-PACKAGE-CATALOG-002")
def test_each_server_serves_its_own_catalog_urls(tmp_path_factory):
    # The quieter half. Even with the files intact, one shared `catalogs/`
    # means both servers hand out download URLs pointing at one port, so a
    # client of the first is silently resolved against the second.
    first = tmp_path_factory.mktemp("dist-a")
    second = tmp_path_factory.mktemp("dist-b")

    with local_catalog.serve(dist=first) as base_a:
        with local_catalog.serve(dist=second) as base_b:
            for base in (base_a, base_b):
                catalog = json.loads(_fetch(f"{base}/catalogs/workflows.json"))
                assert catalog["catalog_url"].startswith(base), (
                    f"{base} serves a catalog naming {catalog['catalog_url']}")
                urls = [entry["url"] for entry in catalog["workflows"].values()]
                assert urls, f"{base} served a catalog with no download urls"
                assert all(url.startswith(base) for url in urls), (
                    f"{base} serves urls pointing elsewhere: "
                    f"{[u for u in urls if not u.startswith(base)][:3]}")


@pytest.mark.req("REQ-PACKAGE-CATALOG-002")
def test_the_published_directory_is_still_the_default():
    # `make build`, `make smoke` and `python scripts/local_catalog.py serve`
    # publish from `dist/`. The parameter exists for concurrent callers; it must
    # not move where a release is built.
    import inspect

    import build_release

    assert local_catalog.DIST == ROOT / "dist"
    for fn in (local_catalog.serve, local_catalog.build_artifacts, build_release.main):
        assert inspect.signature(fn).parameters["dist"].default is None, fn


@pytest.mark.req("REQ-PACKAGE-CATALOG-002")
def test_every_sandbox_server_asks_for_its_own_directory():
    # A module added later that calls `serve()` bare would reintroduce the
    # defect and pass, because serially it still works.
    for path in sorted((ROOT / "tests/sandbox").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        assert "local_catalog.serve()" not in text, (
            f"{path.name} serves from the shared dist/; pass dist=dist_dir")
