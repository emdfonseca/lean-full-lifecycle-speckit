#!/usr/bin/env python3
"""Keep production data out, and keep credentials out of what we write down.

Coverage used to be scattered: `agent-policy.yml` denies production access,
`quality-gates.yml` requires secret detection, `risk-policy.yml` escalates
regulated data. The only implemented redaction covered the GitHub adapter's
audit trail. Nothing covered the records the workflows themselves write --
discovery, disposal, outcome, plans -- which is where production data actually
lands during a brownfield adoption.

Three judgements, all in `sensitive-data.yml`:

**Production data is denied by default, and a refusal cites its rule.** A
generic denial teaches nobody which rule they met or how it is lifted.

**A finding names the record and the field, never the value.** A report that
quotes the secret has copied it somewhere new -- into an issue, a log, a
transcript -- which is the harm the scan exists to prevent.

**Redaction is not authorization.** It happens after the read. Treating it as
permission is what makes a denial policy decorative.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_root  # noqa: E402
import yaml  # noqa: E402

POLICY_CANDIDATES = (
    ".specify/presets/lean-full-lifecycle-governance/policy/sensitive-data.yml",
    "policy/sensitive-data.yml",
)

# Used only when the policy cannot be loaded. Deliberately conservative and
# deliberately flagged: `Patterns.from_policy` is False, and every result
# carries it. Falling back silently would be the same mistake as an unreadable
# repository reading as empty.
FALLBACK_SHAPES = (
    ("github_token", r"gh[pousr]_[A-Za-z0-9]{16,}"),
    ("labelled_secret",
     r"(?i)\b(authorization|bearer|token|secret|password)\b\s*[:=]\s*\S+"),
)
FALLBACK_MARKER = "[redacted]"


def load_policy(root: Path | None = None) -> dict:
    root = root or project_root.resolve(required=False) or Path.cwd()
    for rel in POLICY_CANDIDATES:
        path = root / rel
        if path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"none of {list(POLICY_CANDIDATES)} found; the governance preset must "
        "be installed")


@dataclass
class Patterns:
    shapes: list[tuple[str, re.Pattern]]
    marker: str
    from_policy: bool


def compile_patterns(root: Path | None = None) -> Patterns:
    try:
        policy = load_policy(root)
    except (FileNotFoundError, KeyError, yaml.YAMLError):
        return Patterns([(i, re.compile(p)) for i, p in FALLBACK_SHAPES],
                        FALLBACK_MARKER, from_policy=False)
    shapes = [(s["id"], re.compile(s["pattern"]))
              for s in policy["credential_shapes"]]
    return Patterns(shapes, policy["redaction"]["marker"], from_policy=True)


@dataclass
class Finding:
    record: str
    field: str
    shape: str

    def __str__(self) -> str:
        # The value is deliberately absent. Naming it here would copy the
        # secret into whatever reads this.
        return (f"{self.record}: field {self.field!r} carries something shaped "
                f"like a {self.shape}. The value is not repeated here.")


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    patterns_from_policy: bool = True

    @property
    def clean(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict:
        return {
            "clean": self.clean,
            "findings": [
                {"record": f.record, "field": f.field, "shape": f.shape,
                 "message": str(f)} for f in self.findings],
            "patterns_from_policy": self.patterns_from_policy,
        }


def _walk(value, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _walk(item, f"{prefix}[{i}]")
    else:
        yield prefix, value


def scan(record, name: str, patterns: Patterns | None = None) -> ScanResult:
    patterns = patterns or compile_patterns()
    result = ScanResult(patterns_from_policy=patterns.from_policy)
    for field_path, value in _walk(record):
        text = str(value)
        if patterns.marker in text:
            # Already redacted. Flagging it would report the fix as the fault.
            continue
        for shape, pattern in patterns.shapes:
            if pattern.search(text):
                result.findings.append(Finding(name, field_path, shape))
                break
    return result


def redact(text: str, patterns: Patterns | None = None) -> str:
    """Replace anything credential-shaped with a marker a reader can see.

    Visible on purpose. A silent redaction leaves evidence that reads as
    complete and is not.
    """
    patterns = patterns or compile_patterns()
    for _, pattern in patterns.shapes:
        text = pattern.sub(
            lambda m: (m.group(0).split(":")[0] + ": " + patterns.marker)
            if ":" in m.group(0) and "://" not in m.group(0)
            else patterns.marker,
            text)
    return text


def authorization_problems(source: str, authorization: dict | None,
                           policy: dict) -> list[str]:
    """Decide whether this read of production data may happen.

    Redaction is not consulted here on purpose. It happens after the read, and
    treating it as permission is what makes a denial policy decorative.
    """
    rules = policy["production_data"]
    if source not in rules["denied_sources"]:
        return []
    cite = f"{rules['rule_id']}: {rules['rule'].strip()}"
    if not authorization:
        return [f"reading {source!r} is denied. {cite}"]
    auth = rules["authorization"]
    missing = [f for f in auth["required_fields"] if not authorization.get(f)]
    if missing:
        return [f"reading {source!r} is denied: the authorization does not "
                f"record {missing}. {cite}"]
    who = authorization.get("authorized_by")
    if who not in auth["authorities"]:
        return [f"reading {source!r} is denied: {who!r} is not one of "
                f"{auth['authorities']}. {cite}"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", type=Path,
                    help="Evidence record to scan for credential shapes.")
    ap.add_argument("--source", help="Data source an agent proposes to read.")
    ap.add_argument("--authorization", type=Path,
                    help="Authorization record for that read.")
    ap.add_argument("--policy-root", type=Path, default=None,
                    help="Spec Kit project root. Defaults to SPECIFY_INIT_DIR, then the nearest ancestor with a .specify/ directory.")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()
    try:
        args.policy_root = project_root.resolve(
            args.policy_root, required=False) or Path.cwd()
    except project_root.ProjectRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        policy = load_policy(args.policy_root)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problems: list[str] = []
    payload: dict = {}
    if args.source:
        auth = (yaml.safe_load(args.authorization.read_text(encoding="utf-8"))
                if args.authorization else None)
        problems = authorization_problems(args.source, auth, policy)
        payload["authorization"] = {"source": args.source,
                                    "permitted": not problems,
                                    "refusals": problems}

    if args.record:
        data = yaml.safe_load(args.record.read_text(encoding="utf-8"))
        result = scan(data, args.record.name, compile_patterns(args.policy_root))
        payload["scan"] = result.to_dict()
        problems += [str(f) for f in result.findings]

    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        for problem in problems:
            print(f"REFUSED {problem}")
        print(f"\n{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
