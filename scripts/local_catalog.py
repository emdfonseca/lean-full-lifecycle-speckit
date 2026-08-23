#!/usr/bin/env python3
"""Serve this bundle's components from a local catalog.

A bundle artifact is not a container: `specify bundle install` resolves every
component from a catalog. Without one, nothing here can be installed, updated,
or removed -- so this harness is the prerequisite for testing any of it, not a
release convenience.

Component catalogs (preset, extension, workflow) must be HTTPS, with one
exception: Spec Kit allows plain HTTP for localhost. Bundle catalogs also
accept `file://` and bare paths, but the component catalogs do not, so the
harness serves everything over `http://localhost:<port>` for uniformity.

Usage:
    python scripts/local_catalog.py serve --port 8899
    python scripts/local_catalog.py install --target /path/to/project
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import socket
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
DIST = ROOT / "dist"

# (catalog file, `specify` command group, extra flags). The three component
# groups do not share a signature: preset and extension take --priority and
# --install-allowed (both default to discovery-only), workflow takes neither.
# Bundle catalogs differ again and are registered separately.
COMPONENT_CATALOGS = [
    ("presets.json", "preset", ["--install-allowed", "--priority", "1"]),
    ("extensions.json", "extension", ["--install-allowed", "--priority", "1"]),
    ("workflows.json", "workflow", []),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D102 - silence request logging
        pass


@contextlib.contextmanager
def serve(port: int | None = None, build: bool = True):
    """Build artifacts, point catalogs at localhost, and serve dist/."""
    port = port or _free_port()
    base = f"http://localhost:{port}"

    if build:
        build_artifacts(base)

    handler = functools.partial(_QuietHandler, directory=str(DIST))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield base
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def build_artifacts(base_url: str) -> None:
    """Produce the per-component archives, the bundle zip, and matching catalogs."""
    import build_release
    from generate_catalogs import write_catalogs

    build_release.main()
    subprocess.run(
        ["specify", "bundle", "build", "--path", str(BUNDLE), "--output", str(DIST)],
        check=True,
        capture_output=True,
    )
    write_catalogs(DIST / "catalogs", catalog_root=base_url)


def register(project: Path, base_url: str, name: str = "local-dev") -> None:
    """Point a project's four catalog registries at the local server.

    Caches are cleared first: Spec Kit caches catalog documents per project, and
    a stale entry silently serves the previous download_url.
    """
    for sub in ("presets", "extensions", "workflows"):
        cache = project / ".specify" / sub / ".cache"
        if cache.exists():
            import shutil

            shutil.rmtree(cache)

    for filename, group, extra in COMPONENT_CATALOGS:
        subprocess.run(
            [
                "specify", group, "catalog", "add",
                f"{base_url}/catalogs/{filename}",
                "--name", name,
                *extra,
            ],
            cwd=project, check=True, capture_output=True,
        )

    subprocess.run(
        [
            "specify", "bundle", "catalog", "add",
            f"{base_url}/catalogs/bundles.json",
            "--policy", "install-allowed",
            "--priority", "1",
            "--id", name,
        ],
        cwd=project, check=True, capture_output=True,
    )


def workflow_ids() -> list[str]:
    from lib.inventory import load_inventory

    return [c.id for c in load_inventory().by_kind("workflow")]


def install_workflows(project: Path) -> None:
    """Install the bundle's workflows through the CLI, ahead of `bundle install`.

    Upstream defect (Spec Kit 1.0.1 and main): the bundler installs a workflow
    with `workflow_add(component.id)`, calling a Typer command as a plain
    function. Its `dev` parameter then keeps its `typer.OptionInfo` default,
    which is truthy, so every catalog install takes the `--dev` local-path
    branch and fails with "--dev source must be a workflow YAML file...".
    See bundler/services/primitives.py: `lambda: workflow_add(component.id)`.

    Going through the CLI lets Typer bind dev=False, so the catalog branch runs.
    The workflows are still installed from the catalog -- only the call path
    differs. The cost is bookkeeping: `bundle install` then reports them as
    "already present" and does not attribute them, so `bundle remove` leaves
    them behind. Remove this function once the upstream call passes dev=False.
    """
    for wid in workflow_ids():
        subprocess.run(
            ["specify", "workflow", "add", wid],
            cwd=project, check=True, capture_output=True,
        )


def dev_install(project: Path) -> int:
    """Install every component straight from the source tree, no build or server.

    Faster than the catalog path when iterating on a component's content, and
    the only reason this mode still exists. It is not a substitute for testing
    installation: `--dev` components are never attributed to the bundle, so
    `specify bundle list` reports nothing and `specify bundle remove` is a
    no-op (defect D5). Use `install` for anything that must reflect real user
    behaviour.
    """
    from lib.inventory import load_inventory

    inv = load_inventory()
    owned = inv.meta.get("owned_preset", {}) or {}
    steps: list[list[str]] = []

    for ext in inv.external_preset_refs():
        steps.append(["specify", "preset", "add", ext["id"],
                      "--priority", str(ext.get("priority", 20))])
    for comp in inv.by_kind("preset"):
        steps.append(["specify", "preset", "add", "--dev", str(comp.path),
                      "--priority", str(owned.get("priority", 10))])
    for comp in inv.by_kind("extension"):
        steps.append(["specify", "extension", "add", "--dev", str(comp.path)])
    for comp in inv.by_kind("workflow"):
        steps.append(["specify", "workflow", "add", str(comp.path)])

    for cmd in steps:
        print("+", " ".join(cmd))
        r = subprocess.run(cmd, cwd=project, text=True, capture_output=True)
        if r.returncode != 0:
            sys.stderr.write(r.stdout + r.stderr)
            return r.returncode
    print(f"\nInstalled {len(steps)} components from source into {project}.")
    print("These are --dev installs: the bundle owns none of them (D5). "
          "Use `install` to exercise the real catalog path.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Build and serve until interrupted.")
    p_serve.add_argument("--port", type=int, default=8899)
    p_serve.add_argument("--no-build", action="store_true")

    p_install = sub.add_parser("install", help="Install the bundle into a project.")
    p_install.add_argument("--target", type=Path, required=True)
    p_install.add_argument("--port", type=int, default=None)

    p_dev = sub.add_parser(
        "dev-install",
        help="Install components straight from source: fast, but the bundle owns nothing.",
    )
    p_dev.add_argument("--target", type=Path, required=True)

    args = ap.parse_args()

    if args.cmd == "serve":
        with serve(args.port, build=not args.no_build) as base:
            print(f"Serving {DIST} at {base}")
            print(f"  catalogs: {base}/catalogs/*.json")
            print("Ctrl-C to stop.")
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                print("\nstopped")
        return 0

    target = args.target.resolve()
    if not (target / ".specify").exists():
        print(f"Not a Spec Kit project: {target}", file=sys.stderr)
        return 1

    if args.cmd == "dev-install":
        return dev_install(target)

    with serve(args.port) as base:
        register(target, base)
        install_workflows(target)
        r = subprocess.run(
            ["specify", "bundle", "install", "lean-full-lifecycle"],
            cwd=target, text=True, capture_output=True,
        )
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        return r.returncode


if __name__ == "__main__":
    sys.exit(main())
