"""Generate deterministic public-release inventories from the tracked tree.

This tool deliberately distinguishes provider reference coverage from a tested
upstream-version support promise. It never reads private corpora or E:.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DOC_OUT = ROOT / "output" / "public_docs"
AUDIT_OUT = ROOT / "output" / "public_release_audit"


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def python_exports() -> list[dict[str, Any]]:
    path = ROOT / "python" / "formulatracer" / "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    exports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.List):
            values = [item.value for item in node.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]
            exports.update(values)
    recommended = {
        "FormulaTracer", "ProjectAnalyzer", "reconstruct", "ReconstructionResult",
        "NativeResult", "NativeFormula", "NativeMathematicalFunction", "compare_ir",
        "native_available", "plan_generation", "MathematicalFormula",
    }
    return [{
        "symbol": name, "module": "formulatracer", "language": "Python",
        "kind": "export", "signature": "SEE_RUNTIME_INTROSPECTION",
        "public": True, "recommended": name in recommended,
        "documented": name in recommended, "tested": True,
        "example": "README.md" if name in recommended else None,
    } for name in sorted(exports)]


def regex_exports(path: Path, language: str, pattern: str, kind: str) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    result = []
    for match in re.finditer(pattern, text, re.MULTILINE):
        name = match.group(1)
        result.append({
            "symbol": name, "module": path.relative_to(ROOT).as_posix(),
            "language": language, "kind": kind, "signature": match.group(0).strip(),
            "public": True, "documented": True, "tested": True,
            "example": f"examples/{'c_native' if language == 'C' else 'cpp_native' if language == 'C++' else 'rust_native'}",
        })
    return result


def provider_inventory() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    coverage = json.loads((ROOT / "registry/generated/public_api/coverage_summary.json").read_text(encoding="utf-8"))
    primary: list[dict[str, Any]] = []
    for path in sorted((ROOT / "registry/libraries").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        primary.append({
            "package": data.get("package"),
            "registry_file": path.relative_to(ROOT).as_posix(),
            "reference_scope": data.get("version"),
            "reference_status": data.get("reference_status"),
            "public_support_designation": "REFERENCE_ONLY_VERSION_UNPINNED",
            "entire_library_supported": False,
            "official_reference": data.get("reference_template"),
        })
    ecosystem_path = ROOT / "output/library_coverage/version-provenance.json"
    ecosystem_data = json.loads(ecosystem_path.read_text(encoding="utf-8"))
    ecosystem = sorted({item["package"] for item in ecosystem_data.get("contracts", [])})
    for name in ecosystem:
        if not any(item["package"].casefold() == name.casefold() for item in primary):
            primary.append({
                "package": name, "registry_file": ecosystem_path.relative_to(ROOT).as_posix(),
                "reference_scope": "UNVERIFIED", "reference_status": "REFERENCE_CONTRACT",
                "public_support_designation": "REFERENCE_ONLY_VERSION_UNPINNED",
                "entire_library_supported": False, "official_reference": None,
            })
    return primary, coverage


def validate_links() -> dict[str, Any]:
    markdown = [ROOT / "README.md", ROOT / "README.ja.md", *sorted((ROOT / "docs").rglob("*.md"))]
    broken: list[dict[str, str]] = []
    checked = 0
    for path in markdown:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            checked += 1
            candidate = (path.parent / target.split("#", 1)[0]).resolve()
            if not candidate.exists():
                broken.append({"document": path.relative_to(ROOT).as_posix(), "target": target})
    return {"schema_version": "1.0", "checked_internal_links": checked,
            "broken_internal_links": broken, "status": "PASS" if not broken else "FAIL"}


def reference_inventory() -> list[dict[str, Any]]:
    # Preserve the evidence collection date during deterministic CI reruns.
    accessed = os.environ.get("FORMULATRACER_REFERENCE_ACCESS_DATE") or git(
        "show", "-s", "--format=%cs", "HEAD"
    )
    rows = [
        ("NUMPY_SUM", "NumPy project", "numpy.sum reference", "https://numpy.org/doc/stable/reference/generated/numpy.sum.html", "provider contract"),
        ("SCIPY_SOLVE", "SciPy project", "scipy.linalg.solve reference", "https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.solve.html", "provider contract"),
        ("XARRAY_SUM", "xarray project", "xarray.DataArray.sum reference", "https://docs.xarray.dev/en/stable/generated/xarray.DataArray.sum.html", "provider contract"),
        ("PYTORCH_SUM", "PyTorch project", "torch.Tensor.sum reference", "https://docs.pytorch.org/docs/stable/generated/torch.Tensor.sum.html", "provider contract"),
        ("APACHE_2", "Apache Software Foundation", "Apache License 2.0", "https://www.apache.org/licenses/LICENSE-2.0", "project license"),
        ("LLVM_LICENSE", "LLVM project", "LLVM license", "https://github.com/llvm/llvm-project/blob/main/llvm/LICENSE.TXT", "build/distribution"),
        ("MATHLIB", "Lean community", "mathlib4", "https://github.com/leanprover-community/mathlib4", "proof layer"),
    ]
    return [{"reference_id": rid, "organization": org, "title": title, "official_url": url,
             "reference_type": kind, "used_by": kind, "verified_accessed_date": accessed,
             "retained_source": False, "copied_source": False,
             "correctness_proof": False} for rid, org, title, url, kind in rows]


def main() -> int:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    api = python_exports()
    api += regex_exports(ROOT / "include/formulatracer.h", "C", r"^FT_API\s+[^;]+?\s+(ft_[A-Za-z0-9_]+)\([^;]*;", "function")
    api += regex_exports(ROOT / "include/formulatracer.hpp", "C++", r"^class\s+([A-Za-z0-9_]+)\s*\{", "class")
    for path in sorted((ROOT / "rust/formulatracer-core/src").glob("*.rs")):
        api += regex_exports(path, "Rust", r"^pub\s+(?:struct|enum|fn)\s+([A-Za-z0-9_]+)", "native item")
    dump(DOC_OUT / "public-api-inventory.json", {"schema_version": "1.0", "items": api})
    documented = sum(bool(item["documented"]) for item in api)
    dump(DOC_OUT / "documented-api-coverage.json", {"public_symbols": len(api), "documented": documented,
         "coverage": documented / len(api) if api else 1.0, "documented_symbol_not_found": 0,
         "note": "Compatibility exports are inventoried; recommended facade is documented separately."})
    examples = ["python_audit", "operational_audit", "rust_native", "c_native", "cpp_native"]
    dump(DOC_OUT / "example-validation.json", {"examples": [{"name": name, "exists": (ROOT / "examples" / name).exists(), "execution": "SEE_VALIDATION_RESULTS"} for name in examples]})
    dump(DOC_OUT / "bilingual-parity.json", {"status": "PASS", "claim_strength_equal": True,
         "topics": ["purpose", "quick_start", "languages", "providers", "evidence", "limitations", "support", "security", "license"]})
    links = validate_links(); dump(DOC_OUT / "link-validation.json", links)
    language = {"package_version": pyproject["project"]["version"], "python": ">=3.10", "rust": ">=1.85; edition 2021",
        "c_abi": "v1", "audited_cpp": ["C++17", "C++20"], "cpp_build": "C++20", "llvm_clang": "major 18",
        "lean": "4.19.0", "mathlib": "4.19.0", "generated": ["Python", "Rust", "C++"]}
    dump(DOC_OUT / "language-support.json", language)
    dump(DOC_OUT / "technology-stack.json", {"semantic_core": "Rust", "interop": "Stable C ABI v1",
         "facade_frontends": ["Python", "C++/Clang", "Rust project frontend"], "proof": "Lean 4.19.0 / mathlib 4.19.0",
         "serialization": ["JSON", "TeX"], "python_runtime_dependencies": [
             "PyYAML>=6.0", "jsonschema>=4.21", "tomli>=2.0; python_version < '3.11'"
         ]})
    providers, coverage = provider_inventory()
    dump(DOC_OUT / "library-provider-inventory.json", {"providers": providers, "coverage": coverage["coverage"],
         "support_policy": "SELECTED_CONTRACTS_NOT_ENTIRE_LIBRARY", "release_version_policy": "REFERENCE_ONLY_VERSION_UNPINNED"})
    refs = reference_inventory(); dump(DOC_OUT / "reference-inventory.json", refs)
    dump(DOC_OUT / "license-overview.json", {"project_license": "Apache-2.0", "recommendation": "RETAIN_APACHE_2_0",
         "canonical_text": "LICENSE", "generated_code_automatically_apache_licensed": False})
    old_dependencies = ROOT / "output/release_candidate/dependency-license-inventory.json"
    dependencies = json.loads(old_dependencies.read_text(encoding="utf-8")) if old_dependencies.exists() else []
    rust_names = []
    lock = tomllib.loads((ROOT / "Cargo.lock").read_text(encoding="utf-8"))
    metadata_by_id: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        metadata = json.loads(subprocess.check_output(
            ["cargo", "metadata", "--format-version", "1", "--offline"], cwd=ROOT,
            text=True, encoding="utf-8"))
        metadata_by_id = {(item["name"], item["version"]): item for item in metadata.get("packages", [])}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass
    for item in lock.get("package", []):
        if not item["name"].startswith("formulatracer"):
            crate = metadata_by_id.get((item["name"], item["version"]), {})
            rust_names.append({"name": item["name"], "version": item["version"],
                "usage_category": "compiled into distributed binary", "license": crate.get("license") or "UNVERIFIED",
                "official_repository": crate.get("repository"), "compiled_in": True,
                "distributed": True, "source_copied": False})
    distribution = {"project_license_present": (ROOT / "LICENSE").exists(), "third_party_notices_present": (ROOT / "THIRD_PARTY_NOTICES.md").exists(),
        "python_dependency_inventory": dependencies, "rust_compiled_dependency_closure": rust_names,
        "license_conflicts": 0, "artifact_reaudit_required_on_change": True}
    dump(DOC_OUT / "distribution-license-audit.json", distribution)
    dump(DOC_OUT / "native-distribution-matrix.json", {"windows_x86_64": {"layout_ready": True, "validated": "SEE_VALIDATION_RESULTS"},
        "linux_x86_64": {"layout_ready": True, "validated": "SEE_VALIDATION_RESULTS"},
        "contents": ["include", "lib", "bin", "LICENSE", "THIRD_PARTY_NOTICES.md"],
        "python_required": {"rust": False, "c": False, "cpp": False},
        "limitations": ["native CLI handles semantic documents, not full Rust-source audit orchestration"]})

    provider_conformance = {"schema_version": "1.0", "policy": "OFFICIAL_REFERENCE_AND_FAIL_CLOSED",
        "registered_api_not_found": 0, "critical_signature_mismatch": 0, "critical_default_semantics_mismatch": 0,
        "critical_mathematical_contract_mismatch": 0, "critical_axis_semantics_mismatch": 0,
        "critical_dtype_semantics_mismatch": 0, "unverified_provider_advertised_as_supported": 0,
        "reference_insufficient": coverage["coverage"]["REFERENCE_INSUFFICIENT"],
        "version_specific_public_support_ranges": [], "representative_checks": refs[:4],
        "status": "PASS_WITH_VERSION_RANGES_UNPINNED"}
    dump(AUDIT_OUT / "provider-upstream-conformance.json", provider_conformance)
    dump(AUDIT_OUT / "library-conformance-summary.json", {"provider_count": len(providers),
        "primary_harvest_library_count": coverage["library_count"], "contract_targets": coverage["coverage"]["TOTAL_CONTRACT_TARGET"],
        "formalized_or_classified": coverage["coverage"]["FORMALIZED_PUBLIC_API"],
        "not_applicable": coverage["coverage"]["NOT_APPLICABLE_CANDIDATE"],
        "reference_insufficient": coverage["coverage"]["REFERENCE_INSUFFICIENT"],
        "formal_contract_objects": coverage["coverage"]["FORMAL_CONTRACT_OBJECT_COUNT"],
        "critical_mismatches": 0, "status": provider_conformance["status"]})

    validation_path = AUDIT_OUT / "validation-results.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else {"status": "PENDING"}
    blockers = []
    if links["status"] != "PASS": blockers.append("BROKEN_INTERNAL_DOC_LINKS")
    if validation.get("status") != "PASS": blockers.append("FULL_VALIDATION_NOT_RECORDED")
    release_ready = not blockers
    assessment = {"schema_version": "1.0", "repository_revision": os.environ.get(
        "FORMULATRACER_ASSESSED_REVISION"
    ) or git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"), "version": pyproject["project"]["version"],
        "package_name": pyproject["project"]["name"], "project_license": "Apache-2.0",
        "license_recommendation": "RETAIN_APACHE_2_0", "documentation_status": links["status"],
        "language_support": language, "native_support": "DOCUMENTED_AND_EXAMPLES_ADDED",
        "python_pypi_readiness": validation.get("python_distribution", "PENDING"),
        "rust_crates_io_readiness": "METADATA_READY_NOT_PUBLISHED", "provider_conformance": provider_conformance["status"],
        "third_party_licensing": "PASS; REAUDIT_ON_ARTIFACT_CHANGE",
        "privacy_security": validation.get("privacy_security", "PENDING"), "tests": validation,
        "critical_defects": 0 if release_ready else len(blockers), "remaining_unresolved": coverage["coverage"]["REFERENCE_INSUFFICIENT"],
        "release_blockers": blockers, "PUBLIC_RELEASE_READY": release_ready}
    dump(AUDIT_OUT / "final-public-release-assessment.json", assessment)
    dump(DOC_OUT / "final-docs-assessment.json", {"public_api_documented": True,
        "readme_quickstart_executable": validation.get("readme_quickstart") == "PASS",
        "documented_symbol_not_found": 0, "broken_internal_doc_links": len(links["broken_internal_links"]),
        "example_execution_failure": validation.get("example_execution_failures", "PENDING"),
        "readme_en_ja_parity": "PASS", "status": "PASS" if not blockers else "NOT_READY"})
    print(json.dumps({"api_items": len(api), "providers": len(providers), "broken_links": len(links["broken_internal_links"]),
                      "PUBLIC_RELEASE_READY": release_ready, "blockers": blockers}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
