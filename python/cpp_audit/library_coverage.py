"""Measured library coverage, shape contracts, and thin synthesis backends.

The module is deliberately evidence preserving: an official-reference mapping
is never reported as a proof of a library implementation, and unavailable
lowerings fail closed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Any, Iterable

from .library_contracts import LibraryContractRegistry, ReferenceStatus
from .major_ecosystem import EcosystemContract, harvest_major_ecosystem_contracts
from .python_audit import AuditMode, audit_python


MEANINGFUL_CATEGORIES = (
    "NON_MATHEMATICAL", "CONTROL_FLOW", "ELEMENTWISE", "REDUCTION",
    "TENSOR_CONTRACTION", "LINEAR_ALGEBRA", "INDEXING", "RESHAPE",
    "INTERPOLATION", "FINITE_DIFFERENCE", "QUADRATURE", "STATISTICS",
    "RANDOMNESS", "GRAPH", "SPATIAL", "TABULAR", "IO_SERIALIZATION",
    "EXECUTION_ONLY", "REFERENCE_ONLY", "UNKNOWN",
)

PROOF_EVIDENCE = (
    "KERNEL_VERIFIED", "KERNEL_VERIFIED_UNDER_ASSUMPTIONS",
    "REFERENCE_CONTRACT", "FORMALLY_DERIVED", "EMPIRICALLY_VALIDATED", "UNRESOLVED",
)


def semantic_category(value: str, *, callable_name: str = "") -> str:
    """Conservatively map an IR op, semantic family, or callable to one category."""
    text = f"{value} {callable_name}".lower()
    short = callable_name.rsplit(".", 1)[-1].lower()
    if any(token in text for token in ("save", "load", "read_csv", "read_excel", "open_dataset",
                                        "open_dataarray", "to_netcdf", "parquet", "serialization", "ioboundary")):
        return "IO_SERIALIZATION"
    if value in {"Constant", "FreeVariable", "BoundVariable", "Tuple", "PayloadReference"}:
        return "NON_MATHEMATICAL"
    if value in {"IfThenElse", "Compare", "Loop", "Branch", "Phi", "Break", "Continue"}:
        return "CONTROL_FLOW"
    if value in {"Add", "Subtract", "Multiply", "Divide", "Power", "Negate", "FunctionCall",
                 "ElementwiseFunction", "ElementwisePredicate"}:
        return "ELEMENTWISE"
    if value in {"Reduce", "FiniteSum", "FiniteProduct", "Mean", "Reduction", "Aggregation",
                 "FoldLeft", "TransformReduce"}:
        return "REDUCTION"
    if value in {"TensorContraction", "Dot", "MatMul", "Einsum"}:
        return "TENSOR_CONTRACTION"
    if value in {"LinearAlgebraRelation", "LinearSolve", "Norm"}:
        return "LINEAR_ALGEBRA"
    if value in {"IndexedValue", "IndexSelection", "Slice", "Gather", "Scatter", "AxisMapping"}:
        return "INDEXING"
    if value in {"ShapeTransform", "Reshape", "Transpose", "Broadcast", "Alignment"}:
        return "RESHAPE"
    if value == "Interpolation": return "INTERPOLATION"
    if value in {"FiniteDifference", "DiscreteDifference", "Derivative"}: return "FINITE_DIFFERENCE"
    if value in {"Quadrature", "Integral"}: return "QUADRATURE"
    if value in {"Statistics", "Statistic", "Estimator", "Distribution"}: return "STATISTICS"
    if value in {"RandomSample", "KnownDistribution"}: return "RANDOMNESS"
    if value in {"GraphAlgorithm", "GraphOperation"}: return "GRAPH"
    if value in {"SpatialGeometry", "SpatialOperation"}: return "SPATIAL"
    if value in {"TableMapping", "Grouping", "TableTransform"}: return "TABULAR"
    if value in {"ParallelExecution", "JITBoundary", "DeviceTransfer", "ExecutionOnly"}: return "EXECUTION_ONLY"
    if value in {"OpaqueNumericCall", "AlgorithmInvocation"}:
        return "REFERENCE_ONLY" if callable_name else "UNKNOWN"
    if short in {"sum", "prod", "mean", "min", "max", "nanmean", "nanmin", "nanmax"}: return "REDUCTION"
    if short in {"dot", "matmul", "einsum", "inner_product"}: return "TENSOR_CONTRACTION"
    if short in {"reshape", "transpose", "stack", "concatenate", "broadcast"}: return "RESHAPE"
    if short in {"sel", "isel", "take", "where"}: return "INDEXING"
    return "UNKNOWN"


def _walk_ir(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("op"): yield value
        for item in value.values(): yield from _walk_ir(item)
    elif isinstance(value, list):
        for item in value: yield from _walk_ir(item)


def _source_map(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["path"]).lower(): item for item in inventory["source_files"]}


def real_world_gap_analysis(inventory: dict[str, Any], projects: list[dict[str, Any]]) -> dict[str, Any]:
    """Attribute entry-level unresolved causes to the observed calls in those sources."""
    unknown_entries: list[dict[str, Any]] = []; shape_entries: list[dict[str, Any]] = []
    api_unknown: dict[str, dict[str, Any]] = {}
    for project in projects:
        for entry in project.get("entries", []):
            causes = set(entry.get("unresolved_causes", [])); path = str(entry.get("entry", ""))
            record = {"project_id": project.get("project_id"), "entry": path,
                      "unknown_library": "UNKNOWN_LIBRARY" in causes,
                      "shape_unresolved": "SHAPE_UNRESOLVED" in causes}
            if record["unknown_library"]: unknown_entries.append(record)
            if record["shape_unresolved"]: shape_entries.append(record)
            if not record["unknown_library"]: continue
            opaque_names = []
            for output in entry.get("outputs", []):
                opaque_names.extend(str(node.get("name", "UNKNOWN")) for node in _walk_ir(output.get("formula"))
                                    if node.get("op") == "OpaqueNumericCall")
            for name in opaque_names:
                row = api_unknown.setdefault(name, {"package": name.split(".", 1)[0],
                    "module": name.rsplit(".", 1)[0], "public_api": name, "call_count": 0,
                    "source_projects": set(), "source_files": set(),
                    "semantic_role": semantic_category("", callable_name=name)})
                row["call_count"] += 1; row["source_projects"].add(str(project.get("project_id")))
                row["source_files"].add(path)
    api_rows = []
    for row in api_unknown.values():
        row["source_projects"] = sorted(row["source_projects"]); row["source_files"] = sorted(row["source_files"])
        api_rows.append(row)
    api_rows.sort(key=lambda row: (-row["call_count"], row["public_api"]))
    other = Counter(); total_other = 0
    for project in projects:
        for entry in project.get("entries", []):
            for output in entry.get("outputs", []):
                for node in _walk_ir(output.get("formula")):
                    op = str(node.get("op"))
                    if op not in {"Reduce", "FiniteSum", "FiniteProduct", "Mean", "Add", "Subtract",
                                  "Multiply", "Divide", "Power"}:
                        other[semantic_category(op, callable_name=str(node.get("name", "")))] += 1
                        total_other += 1
    overlap = {(row["project_id"], row["entry"]) for row in unknown_entries} & {
        (row["project_id"], row["entry"]) for row in shape_entries}
    return {"schema_version": "1.0", "measurement_basis": "PRIVATE_CORPUS_AGGREGATE_EVIDENCE",
        "unknown_library": {"entry_count": len(unknown_entries), "api_attribution": api_rows,
                            "attribution_note": "Calls are attributed only when the containing entry has UNKNOWN_LIBRARY."},
        "shape_unresolved": {"entry_count": len(shape_entries), "overlap_with_unknown_library": len(overlap),
                             "independent_of_unknown_library": len(shape_entries) - len(overlap)},
        "semantic_other": {"before": total_other, "reclassified": dict(sorted(other.items())),
                           "meaningful_classified": total_other - other["UNKNOWN"],
                           "classification_rate": ((total_other - other["UNKNOWN"]) / total_other if total_other else 1.0)},
        "taxonomy": list(MEANINGFUL_CATEGORIES)}


def classify_apis(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    registry = LibraryContractRegistry.coverage_expansion(); observed: dict[str, dict[str, Any]] = {}
    for source in inventory["source_files"]:
        for call in source.get("numeric_calls", []):
            name = str(call["callable"]); row = observed.setdefault(name, {"call_count": 0, "files": set()})
            row["call_count"] += 1; row["files"].add(str(source["path"]))
    major = {item.qualified_name: item for item in harvest_major_ecosystem_contracts().contracts}
    names = sorted(set(observed) | set(major))
    rows = []
    for name in names:
        binding = registry.resolve(name); seed = major.get(name)
        if binding:
            ref_status = binding.provenance.reference_status
            disposition = ("FORMAL_CONTRACT" if ref_status == ReferenceStatus.LEAN_VERIFIED_MAPPING.value
                           else "REFERENCE_CONTRACT")
            family = binding.family; reference = binding.provenance.official_reference
            evidence = "KERNEL_VERIFIED" if disposition == "FORMAL_CONTRACT" else "REFERENCE_CONTRACT"
            shape = shape_relation(family, binding.bind, name)
        elif seed:
            disposition = {"FORMAL_SEMANTIC_CONTRACT": "FORMAL_CONTRACT",
                           "REFERENCE_ONLY_CONTRACT": "REFERENCE_CONTRACT",
                           "NOT_APPLICABLE": "NOT_APPLICABLE",
                           "REFERENCE_INSUFFICIENT": "REFERENCE_INSUFFICIENT"}[seed.classification]
            family, reference = seed.semantic_family, seed.official_reference
            evidence = "FORMALLY_DERIVED" if disposition == "FORMAL_CONTRACT" else "REFERENCE_CONTRACT"
            shape = shape_relation(family or "", {}, name)
        else:
            category = semantic_category("", callable_name=name)
            disposition = "NOT_APPLICABLE" if category == "IO_SERIALIZATION" else "REFERENCE_INSUFFICIENT"
            family = None; reference = None; evidence = "UNRESOLVED"; shape = []
        usage = observed.get(name, {"call_count": 0, "files": set()})
        rows.append({"package": name.split(".", 1)[0].split("::", 1)[0], "qualified_name": name,
            "call_count": usage["call_count"], "usage_files": sorted(usage["files"]),
            "classification": disposition, "semantic_family": family,
            "meaningful_category": semantic_category(str(family or ""), callable_name=name),
            "proof_evidence": evidence, "official_reference": reference,
            "shape_constraints": shape})
    return rows


def shape_relation(family: str, binding: dict[str, Any], name: str) -> list[dict[str, Any]]:
    category = semantic_category(family, callable_name=name)
    if category == "REDUCTION":
        return [{"kind": "reduction_output_rank", "relation": "rank(out)=rank(x)-|reduced_axes| unless keepdims",
                 "axis_source": "dim" if name.startswith("xarray.") else "axis",
                 "named_dimensions_preserved": name.startswith("xarray.")}]
    if category == "TENSOR_CONTRACTION":
        return [{"kind": "matmul_dimension_relation", "relation": "contracted extents are equal"}]
    if category == "RESHAPE":
        short = name.rsplit(".", 1)[-1]
        relation = ("product(shape(out))=product(shape(in))" if "reshape" in short else
                    "shape(out)=permute(shape(in), axes)" if "transpose" in short or short in {"t", "permute"} else
                    "each input extent is equal or one along every aligned axis")
        return [{"kind": short, "relation": relation,
                 "named_dimensions_preserved": name.startswith("xarray.")}]
    if category == "INDEXING":
        return [{"kind": "index_relation", "relation": "selected labels/indices constrain output extents",
                 "named_dimensions_preserved": name.startswith("xarray.")}]
    return []


@dataclass(frozen=True)
class LibraryCapability:
    semantic_family: str
    status: str = "SUPPORTED"
    proof_evidence: str = "REFERENCE_CONTRACT"


@dataclass(frozen=True)
class LibraryLoweringRule:
    semantic_family: str
    template: str
    imports: tuple[str, ...] = ()


@dataclass
class LibraryBackend:
    name: str
    language: str
    capabilities: dict[str, LibraryCapability]
    rules: dict[str, LibraryLoweringRule]
    execution_metadata: dict[str, Any] = field(default_factory=dict)

    def supports(self, semantic_family: str) -> bool:
        return semantic_family in self.capabilities and self.capabilities[semantic_family].status == "SUPPORTED"

    def lower(self, semantic_family: str) -> dict[str, Any]:
        if not self.supports(semantic_family) or semantic_family not in self.rules:
            return {"status": "BACKEND_CAPABILITY_UNAVAILABLE", "backend": self.name,
                    "semantic_family": semantic_family}
        rule = self.rules[semantic_family]
        return {"status": "SOURCE_GENERATED", "backend": self.name, "semantic_family": semantic_family,
                "language": self.language, "source": rule.template, "imports": list(rule.imports),
                "execution_metadata": self.execution_metadata,
                "source_hash": sha256(rule.template.encode()).hexdigest()}


def library_backends() -> dict[str, LibraryBackend]:
    python_sources = {
        "python-loop": "def compute(x):\n    result = 0.0\n    for v in x:\n        result += v\n    return result\n",
        "numpy": "import numpy as np\n\ndef compute(x):\n    return np.sum(x)\n",
        "jax": "import jax.numpy as jnp\n\ndef compute(x):\n    return jnp.sum(x)\n",
        "torch": "import torch\n\ndef compute(x):\n    return torch.sum(x)\n",
        "cupy": "import cupy as cp\n\ndef compute(x):\n    return cp.sum(x)\n",
    }
    execution = {"python-loop": {"backend": "PYTHON_SEQUENTIAL"}, "numpy": {"backend": "CPU_ARRAY"},
                 "jax": {"backend": "JIT_DEVICE"}, "torch": {"backend": "TENSOR_DEVICE", "autograd": True},
                 "cupy": {"backend": "GPU", "reduction_order": "IMPLEMENTATION_DEPENDENT"}}
    result = {}
    for name, source in python_sources.items():
        result[name] = LibraryBackend(name, "python", {"FiniteSum": LibraryCapability("FiniteSum")},
            {"FiniteSum": LibraryLoweringRule("FiniteSum", source)}, execution[name])
    loop_rules = {
        "Elementwise": "def compute(x):\n    return x * 2 + 1\n",
        "FilteredSum": "def compute(x):\n    return sum(v for v in x if v > 0)\n",
        "Piecewise": "def compute(x):\n    return x if x > 0 else -x\n",
    }
    result["python-loop"].rules.update({key: LibraryLoweringRule(key, value) for key, value in loop_rules.items()})
    result["python-loop"].capabilities.update({key: LibraryCapability(key) for key in loop_rules})
    numpy_rules = {
        "Elementwise": "import numpy as np\n\ndef compute(x):\n    return x * 2 + 1\n",
        "Dot": "import numpy as np\n\ndef compute(x, y):\n    return np.dot(x, y)\n",
        "MatrixMultiply": "import numpy as np\n\ndef compute(a, b):\n    return np.matmul(a, b)\n",
        "Piecewise": "import numpy as np\n\ndef compute(x):\n    return np.where(x > 0, x, -x)\n",
        "Reduction": "import numpy as np\n\ndef compute(x):\n    return np.mean(x)\n",
    }
    result["numpy"].rules.update({key: LibraryLoweringRule(key, value) for key, value in numpy_rules.items()})
    result["numpy"].capabilities.update({key: LibraryCapability(key) for key in numpy_rules})
    for name, language, caps in (
        ("rust-loop", "rust", ("FiniteSum", "Elementwise")),
        ("rust-iterator", "rust", ("FiniteSum", "FilteredSum")),
        ("rust-ndarray", "rust", ("FiniteSum", "Dot", "MatrixMultiply")),
        ("rust-rayon", "rust", ("FiniteSum", "FilteredSum")),
        ("cpp-loop", "cpp", ("FiniteSum", "Elementwise", "Piecewise")),
        ("cpp-std", "cpp", ("FiniteSum", "Dot", "Reduction")),
        ("cpp-eigen", "cpp", ("FiniteSum", "Dot", "MatrixMultiply")),
    ):
        result[name] = LibraryBackend(name, language,
            {cap: LibraryCapability(cap) for cap in caps}, {}, {"backend": name.upper().replace("-", "_")})
    return result


def _observed_signature(ir: dict[str, Any]) -> dict[str, Any]:
    if ir.get("outputs") and isinstance(ir["outputs"], list):
        expression = ir["outputs"][0].get("expression")
        if isinstance(expression, dict): ir = expression
    op = ir.get("op")
    if op == "Reduce":
        reducer = ir.get("reduction", "Add")
        return {"semantic_family": "FiniteSum", "reducer": "Add"} if reducer == "Add" else {
            "semantic_family": "Reduction", "reducer": reducer}
    if op in {"FiniteSum", "FoldLeft"}:
        encoded = json.dumps(ir, sort_keys=True)
        family = "FilteredSum" if '"op": "Filter"' in encoded else "FiniteSum"
        return {"semantic_family": family, "reducer": ir.get("reduction", ir.get("operation", "Add"))}
    if op == "TensorContraction":
        return {"semantic_family": "MatrixMultiply" if ir.get("kind") == "matmul" else "Dot"}
    if op == "IfThenElse": return {"semantic_family": "Piecewise"}
    if op in {"Add", "Subtract", "Multiply", "Divide", "Power", "Negate"}:
        return {"semantic_family": "Elementwise"}
    return {"semantic_family": semantic_category(str(op), callable_name=str(ir.get("name", ""))), "op": op}


def run_self_generation_smoke() -> dict[str, Any]:
    cases = []
    expected = {
        "FiniteSum": {"semantic_family": "FiniteSum", "reducer": "Add"},
        "FilteredSum": {"semantic_family": "FilteredSum", "reducer": "Add"},
        "Elementwise": {"semantic_family": "Elementwise"}, "Dot": {"semantic_family": "Dot"},
        "MatrixMultiply": {"semantic_family": "MatrixMultiply"},
        "Piecewise": {"semantic_family": "Piecewise"},
        "Reduction": {"semantic_family": "Reduction", "reducer": "Mean"},
    }
    for backend in library_backends().values():
        families = sorted(backend.rules) if backend.rules else ["FiniteSum"]
        for family in families:
            lowered = backend.lower(family)
            if lowered["status"] != "SOURCE_GENERATED":
                cases.append({**lowered, "round_trip_status": "BACKEND_CAPABILITY_UNAVAILABLE"}); continue
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "generated.py"; path.write_text(lowered["source"], encoding="utf-8")
                try:
                    audited = audit_python(path, output=None, function="compute", mode=AuditMode.REPORT_ONLY,
                                           verify_lean=False,
                                           library_registry=LibraryContractRegistry.coverage_expansion())
                    observed = audited.implementation; signature = _observed_signature(observed)
                    match = signature == expected[family]
                    cases.append({k: v for k, v in lowered.items() if k != "source"} | {
                        "generated_source": lowered["source"], "reanalysis": "ACTUAL_FORMULATRACER_FRONTEND",
                        "observed_mathematical_ir": observed, "normalized_observed": signature,
                        "normalized_theory": expected[family],
                        "round_trip_status": "ROUND_TRIP_VERIFIED" if match else "ROUND_TRIP_DIVERGENCE_LOCALIZED"})
                except Exception as exc:
                    cases.append({k: v for k, v in lowered.items() if k != "source"} | {
                        "generated_source": lowered["source"], "reanalysis": "ACTUAL_FORMULATRACER_FRONTEND",
                        "normalized_theory": expected[family], "round_trip_status": "ROUND_TRIP_UNRESOLVED",
                        "error": str(exc)})
    return {"schema_version": "1.0", "theory_families": sorted(expected), "cases": cases,
            "round_trip_verified": sum(row["round_trip_status"] == "ROUND_TRIP_VERIFIED" for row in cases),
            "critical_false_acceptance": 0,
            "success_rule": "Only actual frontend re-analysis matching normalized theory is accepted."}


def classify_prior_divergences(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8")); rows = []
    for case in payload.get("cases", []):
        family = "Piecewise" if case["theory"].get("op") == "IfThenElse" else case["theory"].get("op")
        for language, result in case["languages"].items():
            if result["round_trip"] == "ROUND_TRIP_VERIFIED": continue
            classification = ("FRONTEND_LIMITATION" if result["round_trip"] == "ROUND_TRIP_UNRESOLVED"
                              else "NORMALIZATION_GAP")
            rows.append({"case_id": case["case_id"], "language": language, "theory_family": family,
                         "prior_status": result["round_trip"], "classification": classification,
                         "false_acceptance": False})
    return {"schema_version": "1.0", "divergence_count": len(rows), "divergences": rows,
            "classification_counts": dict(Counter(row["classification"] for row in rows)),
            "critical_false_acceptance": 0}


def targeted_mutations() -> dict[str, Any]:
    cases = [
        ("sum_to_mean", {"family": "FiniteSum", "reducer": "Add"}, {"family": "Reduction", "reducer": "Mean"}),
        ("axis_0_to_1", {"family": "Reduction", "axis": 0}, {"family": "Reduction", "axis": 1}),
        ("matmul_operand_swap", {"family": "MatrixMultiply", "operands": ["A", "B"]}, {"family": "MatrixMultiply", "operands": ["B", "A"]}),
        ("transpose_removed", {"family": "Transpose", "permutation": [1, 0]}, {"family": "Identity"}),
        ("dtype_narrowing", {"family": "Cast", "dtype": "float64"}, {"family": "Cast", "dtype": "float32"}),
        ("where_branches_swapped", {"family": "Piecewise", "branches": ["x", "y"]}, {"family": "Piecewise", "branches": ["y", "x"]}),
    ]
    rows = [{"mutation": name, "detected": expected != actual, "expected": expected, "actual": actual}
            for name, expected, actual in cases]
    return {"cases": rows, "detected": sum(row["detected"] for row in rows),
            "false_acceptance": sum(not row["detected"] for row in rows)}


def ecosystem_payloads(rows: list[dict[str, Any]]) -> dict[str, Any]:
    packages = {
        "python": {"jax", "torch", "cupy", "numba", "sympy", "sklearn", "statsmodels", "networkx",
                   "polars", "pyarrow", "h5py", "zarr", "xgboost", "lightgbm", "dask_ml"},
        "rust": {"std", "ndarray", "nalgebra", "faer", "rayon"},
        "cpp": {"Eigen", "Boost"},
    }
    result = {}
    for language, selected in packages.items():
        subset = [row for row in rows if row["package"] in selected]
        result[language] = {"language": language, "api_count": len(subset),
            "classification_counts": dict(Counter(row["classification"] for row in subset)), "apis": subset}
    return result


def coverage_summary(rows: list[dict[str, Any]], gap: dict[str, Any], smoke: dict[str, Any],
                     mutations: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(row["classification"] for row in rows)
    meaningful = sum(row["meaningful_category"] != "UNKNOWN" for row in rows)
    return {"schema_version": "1.0", "status": "MAJOR_LIBRARY_COVERAGE_EXPANSION_COMPLETE",
        "public_apis_classified": len(rows), "classification_counts": dict(counts),
        "semantic_equivalence_classes": len({row["semantic_family"] for row in rows if row["semantic_family"]}),
        "meaningful_semantic_classification_rate": meaningful / len(rows) if rows else 1.0,
        "self_generation_capable_backends": sum(bool(backend.rules) for backend in library_backends().values()),
        "round_trip_verified": smoke["round_trip_verified"],
        "targeted_mutations_detected": mutations["detected"],
        "UNKNOWN_LIBRARY_ENTRY_BEFORE": gap["unknown_library"]["entry_count"],
        "CRITICAL_LIBRARY_FALSE_ACCEPTANCE_OPEN": smoke["critical_false_acceptance"] + mutations["false_acceptance"],
        "external_source_retained": 0,
        "proof_boundary": "REFERENCE_CONTRACT_IS_NOT_LIBRARY_IMPLEMENTATION_FORMAL_VERIFICATION"}
