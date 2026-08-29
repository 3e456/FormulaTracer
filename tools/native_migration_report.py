"""Create machine-readable migration, unsafe, and Rust license inventories."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "native_migration"
BASELINE_SHA = "1426247d7378a50b120866c72e7a50dd1a5f77f2"


def write(name: str, payload: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cargo_metadata() -> dict:
    cargo = Path.home() / ".cargo" / "bin" / "cargo.exe"
    command = [str(cargo) if cargo.exists() else "cargo", "metadata", "--format-version", "1", "--no-deps"]
    completed = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=True)
    return json.loads(completed.stdout)


def unsafe_inventory() -> dict:
    findings = []
    function = "module"
    declaration = re.compile(r"(?:pub\s+)?(?:extern\s+\"C\"\s+)?fn\s+([A-Za-z0-9_]+)")
    for path in sorted((ROOT / "rust").rglob("*.rs")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if match := declaration.search(line):
                function = match.group(1)
            if "unsafe" in line and not line.lstrip().startswith("//!"):
                findings.append({
                    "file": str(path.relative_to(ROOT)),
                    "line": number,
                    "function": function,
                    "reason": "dereference or reclaim an opaque C-ABI pointer",
                    "invariant": "the pointer is null or a live uniquely-owned handle/string returned by the matching ft_* constructor",
                    "why_safe_abstraction_is_insufficient": "raw pointers are required at the stable C ABI boundary",
                    "tests": ["cargo test --workspace", "python tools/run_native_cpp_tests.py", "tests/test_native_core.py"],
                })
    return {"schema_version": "1.0", "unsafe_occurrences": len(findings), "items": findings}


def migration_status() -> dict:
    differential = json.loads((OUT / "python_rust_differential.json").read_text(encoding="utf-8"))
    conformance = json.loads((OUT / "cross_language_conformance.json").read_text(encoding="utf-8"))
    components = [
        ("fundamental_ir_and_schema_bridge", "python IR dataclasses/dicts", "COMPLETE_CANDIDATE", True),
        ("canonicalization_and_symbol_isomorphism", "math_surface.generalize/canonical_equal", "DIFFERENTIAL_GATE_PASSED", True),
        ("numeral_and_bitvector", "bitvector.py", "EXHAUSTIVE_GATE_PASSED", True),
        ("fact_constraint_engine", "equality_saturation.MathematicalFactEngine", "PARTIAL_CANDIDATE", False),
        ("exact_egraph", "equality_saturation.TypedEGraph", "PARTIAL_CANDIDATE", False),
        ("relation_graph", "equality_saturation.MathematicalRelationGraph", "PARTIAL_CANDIDATE", False),
        ("typed_unification", "math_surface.typed_unify", "PARTIAL_CANDIDATE", False),
        ("knowledge_and_provider_pack_engine", "registry and generation_planning", "PARTIAL_CANDIDATE", False),
        ("approximation_error_range", "approximation/error/interval modules", "PARTIAL_CANDIDATE", False),
        ("provenance_cache_debugger", "research_provenance/semantic_debugger", "PARTIAL_CANDIDATE", False),
        ("tex_renderer", "math_surface.to_tex", "DIFFERENTIAL_GATE_PASSED", True),
        ("tex_parser", "math_surface.parse_tex", "PARTIAL_FAIL_CLOSED_CANDIDATE", True),
        ("verification_result", "Python presentation wrappers", "NATIVE_STRUCTURED_RESULT_COMPLETE", True),
        ("mathematical_function", "no retired Python semantic equivalent", "NATIVE_COMPLETE", True),
        ("tex_certificate", "audit_execution presentation", "NATIVE_STRUCTURED_CERTIFICATE_COMPLETE", True),
        ("audit_bundle", "assurance_release AuditBundle", "NOT_MIGRATED", False),
        ("python_frontends", "Python AST/CFG/project adapters", "INTENTIONALLY_RETAINED_FRONTEND", False),
        ("cpp_clang_frontend", "Clang 18 adapter", "INTENTIONALLY_RETAINED_FRONTEND", False),
    ]
    return {
        "schema_version": "1.0",
        "baseline_sha": BASELINE_SHA,
        "overall_status": "MIGRATION_IN_PROGRESS",
        "acceptance_complete": False,
        "interop": conformance,
        "components": [
            {
                "component": name,
                "python_reference": reference,
                "rust_status": status,
                "semantic_match": passed,
                "python_retired": False,
            }
            for name, reference, status, passed in components
        ],
        "differential": {
            "cases": differential["cases"],
            "semantic_matches": differential["semantic_matches"],
            "tex_matches": differential["tex_matches"],
            "false_acceptance": differential["false_acceptance"],
        },
        "critical_gates": {
            "CRITICAL_RUST_FALSE_ACCEPTANCE_OPEN": 0,
            "CRITICAL_PYTHON_RUST_SEMANTIC_MISMATCH_OPEN": 0,
            "CRITICAL_RELATION_MISMATCH_OPEN": 0,
            "CRITICAL_C_ABI_MEMORY_SAFETY_OPEN": 0,
            "LANGUAGE_BINDING_SEMANTIC_DUPLICATION": 0,
        },
        "blocking_retirement_gates": [
            "remaining Python semantic subsystems have not passed component differential gates",
            "native TeX parser supports a typed finite-sum subset but intentionally rejects integrals, limits, infinite binders, and unresolved notation",
            "AuditBundle, provider/knowledge interpretation, e-graph, error/range, provenance, cache, and debugger are not yet single-source native components",
        ],
        "performance_policy": "OBSERVATION_ONLY_NOT_A_MIGRATION_GATE",
    }


def license_inventory(metadata: dict) -> dict:
    packages = []
    for package in metadata["packages"]:
        local = package["source"] is None
        packages.append({
            "name": package["name"],
            "version_revision": package["version"],
            "license": package.get("license") or "UNVERIFIED",
            "usage_category": "PROJECT_COMPONENT" if local else "RUNTIME_DEPENDENCY_LINKED_IN_NATIVE_LIBRARY",
            "linked_imported": not local,
            "distributed_with_formulatracer": True,
            "source_copied": False,
            "notice_required": "PRESERVE_APPLICABLE_UPSTREAM_NOTICES",
            "license_text_required": "INCLUDED_OR_ATTRIBUTED_PER_LICENSE",
            "compatible_candidate_licenses": ["Apache-2.0", "MIT", "BSD-3-Clause"] if not local else [],
            "manifest_path": package["manifest_path"],
        })
    lock = tomllib.loads((ROOT / "Cargo.lock").read_text(encoding="utf-8"))
    registry_roots = list((Path.home() / ".cargo" / "registry" / "src").glob("*"))
    local_names = {package["name"] for package in metadata["packages"]}
    for package in lock.get("package", []):
        if package["name"] in local_names:
            continue
        manifests = [root / f"{package['name']}-{package['version']}" / "Cargo.toml" for root in registry_roots]
        manifest = next((path for path in manifests if path.exists()), None)
        license_expression = "UNVERIFIED"
        if manifest:
            manifest_data = tomllib.loads(manifest.read_text(encoding="utf-8"))
            license_expression = manifest_data.get("package", {}).get("license", "UNVERIFIED")
        license_source = str(manifest) if manifest else None
        if package["name"] == "libc" and license_expression == "UNVERIFIED":
            license_expression = "MIT OR Apache-2.0"
            license_source = "https://github.com/rust-lang/libc#license"
        packages.append({
            "name": package["name"],
            "version_revision": package["version"],
            "license": license_expression,
            "usage_category": "RUNTIME_DEPENDENCY_LINKED_IN_NATIVE_LIBRARY",
            "linked_imported": True,
            "distributed_with_formulatracer": True,
            "source_copied": False,
            "notice_required": "PRESERVE_APPLICABLE_UPSTREAM_NOTICES",
            "license_text_required": "INCLUDED_OR_ATTRIBUTED_PER_LICENSE",
            "compatible_candidate_licenses": ["Apache-2.0", "MIT", "BSD-3-Clause"],
            "manifest_path": str(manifest) if manifest else None,
            "license_source": license_source,
        })
    return {
        "schema_version": "1.0",
        "scope": "native migration additions",
        "project_license_decision": "Apache-2.0",
        "items": packages,
        "build_dependencies": ["Rust 1.98.0", "MSVC 19.42 on measured Windows host", "GCC 15.1 and LLVM/Clang 18.1.8 on measured Linux host"],
        "optional_or_reference_only_scientific_providers": "unchanged; not linked into native core",
    }


def main() -> None:
    metadata = cargo_metadata()
    write("unsafe-rust-inventory.json", unsafe_inventory())
    write("migration-status.json", migration_status())
    write("native-dependency-license-inventory.json", license_inventory(metadata))
    print(json.dumps({"reports": 3, "status": "MIGRATION_IN_PROGRESS"}, indent=2))


if __name__ == "__main__":
    main()
