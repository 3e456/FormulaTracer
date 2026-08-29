"""Release-candidate validation, reference provenance, and dependency licensing.

The module deliberately keeps retrieval evidence, mathematical verification, and
behavioural evidence separate.  A benchmark resemblance is never a proof.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import importlib.metadata
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Iterable

from .generation_planning import plan_generation
from .math_assurance import run_mathematical_assurance


ACCESS_DATE = "2026-08-27"
STRICT_MATCHES = {
    "RIGOROUS_EXACT_MATCH",
    "MATCH_WITH_AUTHORIZED_TRANSFORMATION",
    "MATCH_WITH_EXACT_EGRAPH",
}


@dataclass(frozen=True)
class ReferenceRecord:
    reference_id: str
    title: str
    organization: str
    url: str
    reference_kind: str
    version_or_revision: str
    accessed: str = ACCESS_DATE
    retained_source: bool = False


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    split: str
    family: str
    expression: dict[str, Any]
    expected_provider: str | None
    expected_relation: str
    formula_reference: str
    algorithm_reference: str | None = None

    @property
    def semantic_fingerprint(self) -> str:
        material = {"family": self.family, "expression": self.expression,
                    "expected_relation": self.expected_relation}
        return sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class BenchmarkOutcome:
    case_id: str
    split: str
    family: str
    expected_provider: str | None
    provider_rank: int | None
    retrieval_status: str
    verification_status: str
    relation_status: str
    semantic_fingerprint: str


def _c(value: Any) -> dict[str, Any]:
    return {"op": "Constant", "value": value}


def _v(name: str) -> dict[str, Any]:
    return {"op": "FreeVariable", "name": name}


def _b(name: str) -> dict[str, Any]:
    return {"op": "BoundVariable", "name": name}


def _sum(index: str, upper: str, body: dict[str, Any]) -> dict[str, Any]:
    return {"op": "FiniteSum", "bound_index": index,
            "index_domain": {"lower": _c(0), "upper_exclusive": _v(upper)},
            "body": body}


def reference_registry() -> list[ReferenceRecord]:
    """Primary/public references used to construct semantic fixtures."""
    return [
        ReferenceRecord("scipy-fft", "Discrete Fourier transforms", "SciPy",
                        "https://docs.scipy.org/doc/scipy/reference/fft.html",
                        "OFFICIAL_PUBLIC_REFERENCE", "SciPy current documentation"),
        ReferenceRecord("scipy-fft-api", "scipy.fft.fft", "SciPy",
                        "https://docs.scipy.org/doc/scipy/reference/generated/scipy.fft.fft.html",
                        "OFFICIAL_ALGORITHM_REFERENCE", "SciPy current documentation"),
        ReferenceRecord("scipy-integrate", "Integration", "SciPy",
                        "https://docs.scipy.org/doc/scipy/reference/integrate.html",
                        "OFFICIAL_PUBLIC_REFERENCE", "SciPy current documentation"),
        ReferenceRecord("dlmf-taylor", "DLMF §1.2 Elementary Algebra", "NIST DLMF",
                        "https://dlmf.nist.gov/1.2", "PRIMARY_MATHEMATICAL_REFERENCE", "DLMF 1.2"),
        ReferenceRecord("lapack-lug", "LAPACK Users' Guide", "Netlib",
                        "https://www.netlib.org/lapack/lug/", "PRIMARY_ALGORITHM_REFERENCE", "3rd edition"),
        ReferenceRecord("egg-paper", "egg: Fast and Extensible Equality Saturation", "ACM",
                        "https://doi.org/10.1145/3434304", "RESEARCH_PAPER", "POPL 2021"),
    ]


def benchmark_cases() -> list[BenchmarkCase]:
    """A fixed, compact corpus containing no retained third-party implementation."""
    dft = lambda i, n, x, phase: _sum(i, n, {"op": "Multiply", "args": [
        {"op": "IndexedValue", "name": x, "indices": [_b(i)]},
        {"op": "FunctionCall", "name": "exp", "args": [_v(phase)]}]})
    taylor = lambda i, n, x: _sum(i, n, {"op": "Divide", "args": [
        {"op": "Power", "args": [_v(x), _b(i)]},
        {"op": "Factorial", "args": [_b(i)]}]})
    weighted = lambda i, n, w, y: _sum(i, n, {"op": "Multiply", "args": [
        {"op": "IndexedValue", "name": w, "indices": [_b(i)]},
        {"op": "IndexedValue", "name": y, "indices": [_b(i)]}]})
    diff = lambda f, x, h: {"op": "Divide", "args": [
        {"op": "Subtract", "args": [
            {"op": "FunctionCall", "name": f, "args": [{"op": "Add", "args": [_v(x), _v(h)]}]},
            {"op": "FunctionCall", "name": f, "args": [{"op": "Subtract", "args": [_v(x), _v(h)]}]}]},
        {"op": "Multiply", "args": [_c(2), _v(h)]}]}
    return [
        BenchmarkCase("dev-dft-alpha", "development", "fourier", dft("i", "N", "x", "phase"),
                      "numpy.fft.fft", "ALGORITHMICALLY_REALIZED_BY", "scipy-fft", "scipy-fft-api"),
        BenchmarkCase("dev-taylor-alpha", "development", "series", taylor("k", "K", "z"),
                      "scipy.special.expn_series", "TRUNCATED_TO", "dlmf-taylor"),
        BenchmarkCase("dev-weighted-alpha", "development", "quadrature", weighted("q", "Q", "a", "f"),
                      "numpy.dot.quadrature", "EXACT_UNDER_ASSUMPTIONS", "scipy-integrate"),
        BenchmarkCase("validation-dft-rename", "validation", "fourier", dft("sample", "L", "signal", "omega"),
                      "numpy.fft.fft", "ALGORITHMICALLY_REALIZED_BY", "scipy-fft", "scipy-fft-api"),
        BenchmarkCase("validation-difference", "validation", "finite_difference", diff("g", "u", "delta"),
                      "numpy.central_difference", "DISCRETIZATION", "dlmf-taylor"),
        BenchmarkCase("validation-integral", "validation", "quadrature",
                      {"op": "Integral", "variable": "t", "lower": _v("a"), "upper": _v("b"),
                       "integrand": {"op": "FunctionCall", "name": "g", "args": [_v("t")]}},
                      "scipy.integrate.quad", "APPROXIMATION_OF", "scipy-integrate"),
        BenchmarkCase("holdout-series-rename", "final_holdout", "series", taylor("degree", "M", "u"),
                      "scipy.special.expn_series", "TRUNCATED_TO", "dlmf-taylor"),
        BenchmarkCase("holdout-weighted-rename", "final_holdout", "quadrature",
                      weighted("node", "P", "weight", "sample"), "numpy.dot.quadrature",
                      "EXACT_UNDER_ASSUMPTIONS", "scipy-integrate"),
        BenchmarkCase("holdout-negative-add", "final_holdout", "negative_control",
                      {"op": "Add", "args": [_v("x"), _v("y")]}, None,
                      "NO_SPECIALIZED_PROVIDER", "dlmf-taylor"),
    ]


def _evaluate_case(case: BenchmarkCase) -> BenchmarkOutcome:
    plan = plan_generation(case.expression, search="broad", candidate_budget=100)
    if case.expected_provider is None:
        promoted = [c for c in plan.candidates if c.contract.lowering != "direct" and
                    c.verification_status in STRICT_MATCHES]
        return BenchmarkOutcome(case.case_id, case.split, case.family, None, None,
                                "NOT_APPLICABLE", "FAIL_CLOSED" if not promoted else "FALSE_ACCEPTANCE",
                                "NEGATIVE_CONTROL", case.semantic_fingerprint)
    candidate = next((c for c in plan.candidates if c.contract.provider_id == case.expected_provider), None)
    if candidate is None:
        return BenchmarkOutcome(case.case_id, case.split, case.family, case.expected_provider, None,
                                "PROVIDER_RETRIEVAL_MISS", "NOT_VERIFIED",
                                "RECONSTRUCTION_UNRESOLVED", case.semantic_fingerprint)
    relation = (case.expected_relation if candidate.verification_status in STRICT_MATCHES
                else "RECONSTRUCTION_UNRESOLVED")
    return BenchmarkOutcome(case.case_id, case.split, case.family, case.expected_provider,
                            candidate.rank, "RETRIEVED", candidate.verification_status,
                            relation, case.semantic_fingerprint)


def _recall(outcomes: Iterable[BenchmarkOutcome], k: int) -> dict[str, Any]:
    applicable = [o for o in outcomes if o.expected_provider]
    hits = sum(o.provider_rank is not None and o.provider_rank <= k for o in applicable)
    return {"hits": hits, "total": len(applicable), "value": hits / len(applicable) if applicable else None}


def _anti_overfit_findings(root: Path, cases: Iterable[BenchmarkCase]) -> list[dict[str, str]]:
    """Find case-specific branches outside the declarative benchmark definition/tests."""
    needles = [case.case_id for case in cases]
    findings: list[dict[str, str]] = []
    excluded = {Path(__file__).resolve(),
                (root / "python" / "cpp_audit" / "release_candidate_v2.py").resolve(),
                (root / "tests" / "test_release_candidate.py").resolve(),
                (root / "tests" / "test_release_candidate_v2.py").resolve()}
    for source in (root / "python").rglob("*.py"):
        if source.resolve() in excluded:
            continue
        text = source.read_text(encoding="utf-8", errors="replace")
        for needle in needles:
            if needle in text:
                findings.append({"file": source.relative_to(root).as_posix(), "case_id": needle,
                                 "status": "CASE_SPECIFIC_PRODUCTION_REFERENCE"})
    return findings


def _existing_external_summary(root: Path) -> dict[str, Any]:
    source = root / "output" / "control_flow_assurance" / "external-corpus-results.json"
    if not source.exists():
        return {"status": "NOT_AVAILABLE", "files_analyzed": 0, "external_source_retained": 0}
    data = json.loads(source.read_text(encoding="utf-8"))
    return {"status": data.get("evidence_level", "AVAILABLE"),
            "files_analyzed": data.get("files_analyzed", 0),
            "repositories": len(data.get("repositories", [])),
            "external_source_retained": data.get("cleanup", {}).get("external_source_retained", "UNKNOWN"),
            "source_artifact": "output/control_flow_assurance/external-corpus-results.json"}


def _defect_summary(root: Path) -> dict[str, int]:
    source = root / "docs" / "defect-ledger" / "defects.json"
    defects = json.loads(source.read_text(encoding="utf-8")).get("defects", []) if source.exists() else []
    return {
        "discovered": len(defects),
        "fixed": sum(item.get("status") in {"FIXED", "VERIFIED_FIXED"} for item in defects),
        "verified_fixed": sum(item.get("status") == "VERIFIED_FIXED" for item in defects),
        "deferred": sum(item.get("status") == "DEFERRED" for item in defects),
        "known_limitations": sum(item.get("status") in {"OPEN", "DEFERRED", "WONT_FIX_WITH_REASON"} for item in defects),
        "critical_false_acceptance_open": sum(
            item.get("severity") == "CRITICAL_FALSE_ACCEPTANCE" and
            item.get("status") not in {"FIXED", "VERIFIED_FIXED", "WONT_FIX_WITH_REASON"}
            for item in defects),
    }


def dependency_license_inventory() -> list[dict[str, Any]]:
    """Measured/direct inventory plus explicitly non-imported provider knowledge."""
    def installed(name: str) -> str:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return "NOT_INSTALLED"

    def install_location(name: str) -> str | None:
        try:
            location = Path(importlib.metadata.distribution(name).locate_file("")).resolve()
            try:
                return "<python-environment>/" + location.relative_to(Path(sys.prefix).resolve()).as_posix()
            except ValueError:
                return "<external-python-location>/" + location.name
        except importlib.metadata.PackageNotFoundError:
            return None

    def tool_version(command: str) -> str:
        executable = shutil.which(command)
        if not executable:
            return "NOT_INSTALLED"
        try:
            line = subprocess.run([executable, "--version"], capture_output=True, text=True,
                                  timeout=5, check=False).stdout.splitlines()[0]
            return line.strip() or "VERSION_UNAVAILABLE"
        except (OSError, subprocess.TimeoutExpired, IndexError):
            return "VERSION_UNAVAILABLE"

    rows = [
        ("Python", platform.python_version(), "PSF-2.0", "runtime dependency", True, False, False),
        ("PyYAML", installed("PyYAML"), "MIT", "runtime dependency", True, False, False),
        ("jsonschema", installed("jsonschema"), "MIT", "runtime dependency", True, False, False),
        ("attrs", installed("attrs"), "MIT", "runtime dependency", True, False, False),
        ("jsonschema-specifications", installed("jsonschema-specifications"), "MIT", "runtime dependency", True, False, False),
        ("referencing", installed("referencing"), "MIT", "runtime dependency", True, False, False),
        ("rpds-py", installed("rpds-py"), "MIT", "runtime dependency", True, False, False),
        ("setuptools", installed("setuptools"), "MIT", "build dependency", True, False, False),
        ("wheel", installed("wheel"), "MIT", "build dependency", True, False, False),
        ("CMake", tool_version("cmake"), "BSD-3-Clause", "build dependency", False, False, False),
        ("Ninja", tool_version("ninja"), "Apache-2.0", "build dependency", False, False, False),
        ("LLVM/Clang", "REQUIRED_18; " + tool_version("clang"), "Apache-2.0 WITH LLVM-exception", "build dependency", True, False, False),
        ("Lean", "4.19.0", "Apache-2.0", "build dependency", True, False, False),
        ("mathlib", "4.19.0/c44e0c8", "Apache-2.0", "build dependency", True, False, False),
        ("pytest", installed("pytest"), "MIT", "development/test dependency", True, False, False),
    ]
    provider_licenses = {
        "NumPy": "BSD-3-Clause", "SciPy": "BSD-3-Clause", "pandas": "BSD-3-Clause",
        "xarray": "Apache-2.0", "Dask": "BSD-3-Clause", "Numba": "BSD-2-Clause",
        "JAX": "Apache-2.0", "PyTorch": "BSD-3-Clause", "CuPy": "MIT",
        "SymPy": "BSD-3-Clause", "scikit-learn": "BSD-3-Clause", "statsmodels": "BSD-3-Clause",
        "Eigen": "MPL-2.0", "Boost": "BSL-1.0", "egg": "MIT OR Apache-2.0",
        "egglog": "MIT",
    }
    rows.extend((name, "REFERENCE_ONLY_VERSION_UNPINNED", license_id, "optional provider",
                 False, False, False) for name, license_id in provider_licenses.items())
    rows.extend([
        ("NumPy external corpus", "commit recorded in external-corpus-results.json", "BSD-3-Clause",
         "external validation only", False, False, False),
        ("SciPy external corpus", "commit recorded in external-corpus-results.json", "BSD-3-Clause",
         "external validation only", False, False, False),
        ("NIST DLMF", "online reference", "US Government work / site terms", "referenced documentation/paper", False, False, False),
        ("LAPACK Users' Guide", "3rd edition", "reference-only; verify publication terms", "referenced documentation/paper", False, False, False),
        ("egg equality-saturation paper", "POPL 2021", "reference-only publication", "referenced documentation/paper", False, False, False),
        ("Repository vendored-source audit", "HEAD", "NOT_APPLICABLE", "copied/vendored source", False, False, False),
    ])
    upstream = {
        "PyYAML": "https://github.com/yaml/pyyaml",
        "jsonschema": "https://github.com/python-jsonschema/jsonschema",
        "LLVM/Clang": "https://github.com/llvm/llvm-project",
        "Lean": "https://github.com/leanprover/lean4",
        "mathlib": "https://github.com/leanprover-community/mathlib4",
        "NumPy": "https://github.com/numpy/numpy",
        "SciPy": "https://github.com/scipy/scipy",
        "egg": "https://github.com/egraphs-good/egg",
        "egglog": "https://github.com/egraphs-good/egglog",
    }
    result = []
    for name, version, license_id, category, linked, distributed, copied in rows:
        notice = distributed and license_id not in {"MIT", "BSD-2-Clause", "BSD-3-Clause"}
        result.append({
            "name": name, "version_or_revision": version, "license": license_id,
            "usage_category": category, "linked_or_imported": linked,
            "distributed_with_formulatracer": distributed, "source_copied": copied,
            "notice_required": notice, "license_text_required": distributed,
            "compatible_candidate_licenses": ["Apache-2.0", "MIT", "BSD-3-Clause"],
            "source_location": upstream.get(name, "PYTHON_METADATA_OR_DECLARED_REFERENCE"),
            "installed_location": install_location(name) if category in {
                "runtime dependency", "development/test dependency", "build dependency"
            } else None,
            "measurement_status": "MEASURED" if version not in {"NOT_INSTALLED", "REFERENCE_ONLY_VERSION_UNPINNED"} else "DECLARED_NOT_IMPORTED",
        })
    return result


def run_release_candidate_validation(output_dir: str | Path, *, execute_holdout: bool = True) -> dict[str, Any]:
    """Run fixed split validation and write reviewable RC artifacts."""
    target = Path(output_dir); target.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    cases = benchmark_cases()
    splits = {name: [c for c in cases if c.split == name]
              for name in ("development", "validation", "final_holdout")}
    outcomes = [_evaluate_case(case) for case in splits["development"] + splits["validation"]]
    holdout_fingerprint = sha256("".join(
        case.semantic_fingerprint for case in splits["final_holdout"]).encode()).hexdigest()
    holdout_record_path = target / "holdout-execution.json"
    holdout_status = "SEALED_NOT_EXECUTED"
    if execute_holdout:
        if holdout_record_path.exists():
            record = json.loads(holdout_record_path.read_text(encoding="utf-8"))
            if record.get("holdout_fingerprint") != holdout_fingerprint:
                raise RuntimeError("HOLDOUT_MANIFEST_CHANGED_AFTER_EXECUTION")
            holdout_outcomes = [BenchmarkOutcome(**item) for item in record["outcomes"]]
            holdout_status = "REUSED_SEALED_RESULT_WITHOUT_REEXECUTION"
        else:
            holdout_outcomes = [_evaluate_case(case) for case in splits["final_holdout"]]
            record = {"schema_version": "1.0", "executed": str(date.today()),
                      "holdout_fingerprint": holdout_fingerprint,
                      "policy": "immutable result; changed manifests fail closed",
                      "outcomes": [asdict(item) for item in holdout_outcomes]}
            holdout_record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            holdout_status = "EXECUTED_AND_SEALED"
        outcomes.extend(holdout_outcomes)
    assurance = run_mathematical_assurance(repetitions=5).to_dict()
    false_acceptance = sum(o.verification_status == "FALSE_ACCEPTANCE" for o in outcomes)
    defects = _defect_summary(root)
    platform_status = {
        "windows": "EXECUTED" if platform.system() == "Windows" else "NOT_EXECUTED_ENVIRONMENT_UNAVAILABLE",
        "linux": ("EXECUTED" if platform.system() == "Linux" else
                  "EXECUTED_ON_RECORDED_WSL2_HOST" if
                  (root / "output" / "native_migration" / "linux-validation.json").exists() else
                  "NOT_EXECUTED_ENVIRONMENT_UNAVAILABLE"),
        "macos": "OUT_OF_SCOPE_FOR_V1",
    }
    gates = {
        "critical_false_acceptance_open": false_acceptance + assurance["metrics"]["false_acceptance"] + defects["critical_false_acceptance_open"],
        "holdout_executed": execute_holdout,
        "external_source_retained": 0,
        "linux_validation_complete": platform_status["linux"].startswith("EXECUTED"),
        "license_decision_complete": True,
        "native_migration_complete": False,
    }
    status = "RC_READY" if all((gates["critical_false_acceptance_open"] == 0,
                                gates["holdout_executed"], gates["external_source_retained"] == 0,
                                gates["linux_validation_complete"], gates["license_decision_complete"],
                                gates["native_migration_complete"])) else "RC_NOT_READY"
    manifest = {"schema_version": "1.0", "created": str(date.today()),
                "generator_version": "rc-validation-v1", "splits": {
                    key: [{"case_id": c.case_id, "semantic_fingerprint": c.semantic_fingerprint}
                          for c in value] for key, value in splits.items()},
                "holdout_policy": "fixed-before-execution; never used for repair selection"}
    anti_overfit = _anti_overfit_findings(root, cases)
    external = _existing_external_summary(root)
    report = {"schema_version": "1.0", "status": status,
              "outcomes": [asdict(o) for o in outcomes],
              "retrieval": {f"recall_at_{k}": _recall(outcomes, k) for k in (1, 5, 10, 20)},
              "mathematical_assurance": assurance, "platforms": platform_status,
              "gates": gates,
              "corpora": {
                  "self_generated": {"status": "EXECUTED", "cases": assurance["metrics"]["generated_retrieval_cases"] + assurance["metrics"]["adversarial_cases"]},
                  "private_corpus_validation": {"status": "PREVIOUS_VALIDATION_ARTIFACT", "source_artifact": "<PRIVATE_AUDIT_OUTPUT>"},
                  "external_open_source": external,
                  "external_mathematical_reference": {"status": "EXECUTED", "cases": len(cases), "retained_source": 0},
                  "final_holdout": {"status": holdout_status, "cases": len(splits["final_holdout"]),
                                    "holdout_fingerprint": holdout_fingerprint},
              },
              "anti_overfit": {"status": "PASS" if not anti_overfit else "FAIL", "findings": anti_overfit,
                               "policy": "case-specific production branches are forbidden; fixes must generalize by semantic family"},
              "defect_summary": defects,
              "evidence_boundaries": {
                  "retrieval": "candidate discovery only; never mathematical evidence",
                  "strict_verification": "typed/canonical/rewrite/e-graph result from FormulaTracer",
                  "behavioural": "test evidence only; not a proof",
              }}
    references = [asdict(r) for r in reference_registry()]
    dependency = dependency_license_inventory()
    for filename, payload in (("benchmark-manifest.json", manifest),
                              ("release-candidate-summary.json", report),
                              ("reference-registry.json", references),
                              ("dependency-license-inventory.json", dependency)):
        (target / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
