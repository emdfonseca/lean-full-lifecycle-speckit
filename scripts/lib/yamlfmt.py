"""Deterministic YAML emission for generated and round-tripped files.

PyYAML emits anchors/aliases (`&id001` / `*id001`) whenever the same object is
referenced twice. The workflow manifests already carry them from a prior
round-trip, and they are a liability for anything byte-compared: inserting one
input renumbers every anchor and produces a large spurious diff.
"""
from __future__ import annotations

import yaml


class NoAliasDumper(yaml.SafeDumper):
    """Expand every repeated node inline instead of emitting an alias."""

    def ignore_aliases(self, data) -> bool:  # noqa: D102, ANN001
        return True


def dump(data, **kwargs) -> str:
    opts = {
        "Dumper": NoAliasDumper,
        "sort_keys": False,
        "default_flow_style": False,
        "width": 100,
        "allow_unicode": True,
        "indent": 2,
    }
    opts.update(kwargs)
    return yaml.dump(data, **opts)
