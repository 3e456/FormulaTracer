"""Deterministic maintenance gates for API, docs, metadata, privacy, and fixtures."""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> object:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def python_exports() -> set[str]:
    tree = ast.parse((ROOT / "python/formulatracer/__init__.py").read_text(encoding="utf-8"))
    exports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            exports.update(
                item.value for item in node.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return exports


def c_symbols() -> set[str]:
    header = (ROOT / "include/formulatracer.h").read_text(encoding="utf-8")
    return set(re.findall(r"\b(ft_[A-Za-z0-9_]+)\s*\(", header))


def rust_symbols() -> set[str]:
    result: set[str] = set()
    pattern = re.compile(r"^pub\s+(?:struct|enum|fn)\s+([A-Za-z0-9_]+)", re.MULTILINE)
    for path in (ROOT / "rust/formulatracer-core/src").glob("*.rs"):
        result.update(pattern.findall(path.read_text(encoding="utf-8")))
    return result


def cpp_symbols() -> set[str]:
    return set(re.findall(r"^class\s+([A-Za-z0-9_]+)\s*\{",
                          (ROOT / "include/formulatracer.hpp").read_text(encoding="utf-8"), re.MULTILINE))


def api_gate() -> list[str]:
    policy = load("maintenance/api-policy.json")
    baseline = load("output/public_docs/public-api-inventory.json")
    failures: list[str] = []
    exports = python_exports()
    stable = set(policy["python"]["stable"])
    missing = sorted(stable - exports)
    if missing:
        failures.append(f"missing stable Python exports: {missing}")
    current = {("Python", name) for name in exports}
    current.update(("C", name) for name in c_symbols())
    current.update(("Rust", name) for name in rust_symbols())
    current.update(("C++", name) for name in cpp_symbols())
    recorded = {(item["language"], item["symbol"]) for item in baseline["items"]
                if item["language"] in {"Python", "C", "C++", "Rust"}}
    added = sorted(current - recorded)
    removed = sorted(recorded - current)
    if added:
        failures.append(f"unreviewed public API additions: {added}")
    if removed:
        failures.append(f"public API removals: {removed}")
    if "#define FT_ABI_VERSION 1u" not in (ROOT / "include/formulatracer.h").read_text(encoding="utf-8"):
        failures.append("Stable C ABI v1 declaration changed")
    return failures


def metadata_gate() -> list[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    workspace = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]
    policy = load("maintenance/api-policy.json")
    failures = []
    if project["version"] != policy["project_version"] or workspace["version"] != project["version"]:
        failures.append("Python/Cargo/project policy versions disagree")
    if project["requires-python"] != ">=3.10":
        failures.append("Python support metadata drifted from >=3.10")
    if workspace["rust-version"] != "1.85":
        failures.append("Rust MSRV drifted from 1.85")
    if project["license"] != workspace["license"] or project["license"] != "Apache-2.0":
        failures.append("license metadata is inconsistent")
    return failures


def docs_gate() -> list[str]:
    sys.path.insert(0, str(ROOT / "tools"))
    from public_release_audit import validate_links
    links = validate_links()
    failures = [f"broken documentation link: {item}" for item in links["broken_internal_links"]]
    for required in ("README.md", "README.ja.md", "MAINTENANCE.md",
                     "docs/api-compatibility.md", "docs/operational-workflow.md",
                     "docs/release-checklist.md"):
        if not (ROOT / required).is_file():
            failures.append(f"missing maintenance document: {required}")
    return failures


def privacy_gate() -> list[str]:
    completed = subprocess.run(
        [sys.executable, "tools/repository_sanitization_scan.py", "--scope", "current", "--summary-only"],
        cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if completed.returncode:
        return ["repository sanitization scan failed to execute"]
    report = json.loads(completed.stdout)
    hits = report["current"]["hit_count"]
    return [] if hits == 0 else [f"tracked-tree privacy scan found {hits} hit(s)"]


def operational_gate() -> list[str]:
    environment = os.environ.copy()
    python_path = str((ROOT / "python").resolve())
    if environment.get("PYTHONPATH"):
        python_path = os.pathsep.join((python_path, environment["PYTHONPATH"]))
    environment["PYTHONPATH"] = python_path
    completed = subprocess.run(
        [sys.executable, "examples/operational_audit/run_example.py"], cwd=ROOT,
        env=environment, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )
    if completed.returncode:
        stderr = completed.stderr or "no stderr captured"
        return [f"synthetic operational audit failed: {stderr[-500:]}"]
    report = json.loads(completed.stdout)
    expected = {
        "exact": report["exact"].get("comparison_match") is True,
        "relational": report["relational"].get("relation") == "DISCRETIZATION_OF",
        "unresolved": report["unresolved"].get("operation") == "OpaqueNumericCall",
    }
    return [f"operational fixture failed: {name}" for name, passed in expected.items() if not passed]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operational", action="store_true")
    args = parser.parse_args()
    gates = {
        "api": api_gate(), "metadata": metadata_gate(), "docs": docs_gate(),
        "privacy": privacy_gate(),
    }
    if args.operational:
        gates["operational"] = operational_gate()
    failures = [message for messages in gates.values() for message in messages]
    print(json.dumps({"schema_version": "1.0", "status": "PASS" if not failures else "FAIL",
                      "gates": gates, "failures": failures}, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
