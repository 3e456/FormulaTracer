"""Family-level contracts for major scientific ecosystems and version diffs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


DETERMINISTIC_CLASSIFICATIONS = {"FORMAL_SEMANTIC_CONTRACT", "REFERENCE_ONLY_CONTRACT",
                                 "NOT_APPLICABLE", "REFERENCE_INSUFFICIENT"}


@dataclass
class EcosystemContract:
    contract_id: str
    language: str
    package: str
    version: str
    qualified_name: str
    semantic_family: str | None
    mathematical_ir: str | None
    execution_metadata: dict[str, Any]
    classification: str
    family_reuse: str
    official_reference: str
    reference_status: str = "OFFICIAL_PUBLIC_REFERENCE"


@dataclass
class EcosystemCoverage:
    total: int
    formal_semantic_contract: int
    reference_only_contract: int
    not_applicable: int
    reference_insufficient: int
    existing_family_reuse: int
    new_semantic_families_required: list[str]
    by_language: dict[str, int]
    by_package: dict[str, int]


@dataclass
class MajorEcosystemReport:
    contracts: list[EcosystemContract]
    coverage: EcosystemCoverage
    status: str
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"contracts": [asdict(item) for item in self.contracts], "coverage": asdict(self.coverage),
                "status": self.status, "provenance": self.provenance}
    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=True) + "\n"
    def write_json(self, path: str | Path) -> Path:
        target = Path(path); target.write_text(self.to_json(), encoding="utf-8"); return target


@dataclass
class ContractImpact:
    qualified_name: str
    change: str
    old_contract_id: str | None
    new_contract_id: str | None
    affected_semantic_family: str | None
    review_status: str
    reason: str


@dataclass
class LibraryVersionDiff:
    package: str
    old_version: str
    new_version: str
    impacts: list[ContractImpact]
    summary: dict[str, int]
    status: str

    def to_dict(self) -> dict[str, Any]: return asdict(self)


_REFERENCES = {
    "jax": "https://docs.jax.dev/en/latest/jax.numpy.html",
    "torch": "https://docs.pytorch.org/docs/stable/torch.html",
    "cupy": "https://docs.cupy.dev/en/stable/reference/index.html",
    "numba": "https://numba.readthedocs.io/en/stable/reference/index.html",
    "sympy": "https://docs.sympy.org/latest/reference/index.html",
    "sklearn": "https://scikit-learn.org/stable/api/index.html",
    "statsmodels": "https://www.statsmodels.org/stable/api.html",
    "networkx": "https://networkx.org/documentation/stable/reference/index.html",
    "polars": "https://docs.pola.rs/api/python/stable/reference/index.html",
    "pyarrow": "https://arrow.apache.org/docs/python/api.html",
    "h5py": "https://docs.h5py.org/en/stable/high/dataset.html",
    "zarr": "https://zarr.readthedocs.io/en/stable/api.html",
    "xgboost": "https://xgboost.readthedocs.io/en/stable/python/python_api.html",
    "lightgbm": "https://lightgbm.readthedocs.io/en/stable/Python-API.html",
    "dask_ml": "https://ml.dask.org/modules/api.html",
    "std": "https://en.cppreference.com/w/cpp/algorithm",
    "ndarray": "https://docs.rs/ndarray/latest/ndarray/",
    "nalgebra": "https://docs.rs/nalgebra/latest/nalgebra/",
    "faer": "https://docs.rs/faer/latest/faer/",
    "rayon": "https://docs.rs/rayon/latest/rayon/",
    "Eigen": "https://eigen.tuxfamily.org/dox/",
    "Boost": "https://www.boost.org/doc/libs/release/libs/math/doc/html/index.html",
}

_EXECUTION = {
    "jax": {"backend": "JIT_DEVICE", "array_model": "IMMUTABLE", "autodiff": True},
    "torch": {"backend": "TENSOR_DEVICE", "autograd": True, "device": "CPU_OR_ACCELERATOR"},
    "cupy": {"backend": "GPU", "reduction_order": "IMPLEMENTATION_DEPENDENT"},
    "numba": {"backend": "JIT_CPU_OR_CUDA", "compiler_boundary": True},
    "rayon": {"backend": "PARALLEL_CPU", "reduction_order": "REORDERABLE"},
    "Eigen": {"backend": "NATIVE_CPP", "vectorization": "IMPLEMENTATION_DEPENDENT"},
    "std": {"backend": "NATIVE_CPP", "execution_policy": "POLICY_DEPENDENT"},
}

_PY_TENSOR = {
    "jax": "jax.numpy", "torch": "torch", "cupy": "cupy",
}


def _id(value: Any) -> str:
    return "ecosystem-contract:" + sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def _contract(language: str, package: str, name: str, family: str | None, ir: str | None,
              classification: str = "FORMAL_SEMANTIC_CONTRACT", reuse: str = "EXISTING_FAMILY_REUSED") -> EcosystemContract:
    if classification not in DETERMINISTIC_CLASSIFICATIONS: raise ValueError("NON_DETERMINISTIC_CONTRACT_CLASSIFICATION")
    qualified = name if name.startswith(package + ".") or name.startswith(package + "::") or package in {"std", "Eigen", "Boost"} else f"{package}.{name}"
    return EcosystemContract(_id([language, package, qualified, family, classification]), language, package,
        "UNVERIFIED", qualified, family, ir, dict(_EXECUTION.get(package, {"backend": "LIBRARY_DEFINED"})),
        classification, reuse, _REFERENCES[package])


def harvest_major_ecosystem_contracts() -> MajorEcosystemReport:
    contracts = []
    for package, prefix in _PY_TENSOR.items():
        for name, family, ir in [
            ("sum", "Reduction", "Reduction(Add)"), ("prod", "Reduction", "Reduction(Multiply)"),
            ("mean", "Reduction", "Mean"), ("matmul", "TensorContraction", "TensorContraction"),
            ("dot", "TensorContraction", "Dot"), ("reshape", "ShapeTransform", "Reshape"),
            ("transpose", "ShapeTransform", "Transpose"), ("where", "Selection", "IfThenElse"),
            ("abs", "ElementaryFunction", "Abs"), ("sqrt", "ElementaryFunction", "Sqrt"),
            ("log", "ElementaryFunction", "Log"), ("exp", "ElementaryFunction", "Exp")]:
            contracts.append(_contract("python", package, f"{prefix}.{name}", family, ir))
    contracts += [_contract("python", "jax", name, family, ir, "REFERENCE_ONLY_CONTRACT", "NEW_FAMILY_REQUIRED")
                  for name, family, ir in [("jax.grad", "AutodiffBoundary", "Derivative"),
                                           ("jax.jit", "JITBoundary", "IdentityOnMathematicalSemantics"),
                                           ("jax.device_put", "DeviceTransfer", "IdentityOnValues")]]
    contracts += [_contract("python", "torch", name, family, ir, "REFERENCE_ONLY_CONTRACT", "NEW_FAMILY_REQUIRED")
                  for name, family, ir in [("torch.autograd.grad", "AutodiffBoundary", "Derivative"),
                                           ("torch.compile", "JITBoundary", "IdentityOnMathematicalSemantics"),
                                           ("torch.Tensor.to", "DeviceTransfer", "IdentityOrCast")]]
    contracts += [_contract("python", "numba", name, "JITBoundary", "IdentityOnMathematicalSemantics",
                            "REFERENCE_ONLY_CONTRACT", "NEW_FAMILY_REQUIRED") for name in ("numba.jit", "numba.njit", "numba.vectorize")]
    contracts.append(_contract("python", "numba", "numba.prange", "ParallelExecution", "FiniteIteration",
                               "REFERENCE_ONLY_CONTRACT", "NEW_FAMILY_REQUIRED"))
    for name, family, ir in [("sympy.simplify", "SymbolicAlgebra", "EquivalentExpression"),
                             ("sympy.diff", "SymbolicAlgebra", "Derivative"),
                             ("sympy.integrate", "SymbolicAlgebra", "Integral"),
                             ("sympy.solve", "RootFindingRelation", "SolutionSet")]:
        contracts.append(_contract("python", "sympy", name, family, ir, "REFERENCE_ONLY_CONTRACT", "NEW_FAMILY_REQUIRED"))
    estimator_packages = {"sklearn": ("fit", "predict", "transform", "score"),
                          "statsmodels": ("fit", "predict"), "xgboost": ("fit", "predict"),
                          "lightgbm": ("fit", "predict"), "dask_ml": ("fit", "predict", "transform", "score")}
    families = {"fit": ("EstimatorConstruction", "Estimator"), "predict": ("Predictor", "Predictor"),
                "transform": ("Transformer", "Transformer"), "score": ("Metric", "Metric")}
    for package, methods in estimator_packages.items():
        for method in methods:
            family, ir = families[method]
            contracts.append(_contract("python", package, f"{package}.Estimator.{method}", family, ir,
                                       "REFERENCE_ONLY_CONTRACT", "NEW_FAMILY_REQUIRED"))
    for name in ("networkx.shortest_path", "networkx.pagerank", "networkx.connected_components"):
        contracts.append(_contract("python", "networkx", name, "GraphAlgorithm", "GraphRelation",
                                   "REFERENCE_ONLY_CONTRACT", "NEW_FAMILY_REQUIRED"))
    for package, names in {"polars": ("DataFrame.select", "DataFrame.group_by", "DataFrame.join", "DataFrame.write_parquet"),
                           "pyarrow": ("Table.select", "Table.join", "parquet.write_table"),
                           "h5py": ("File", "Dataset.__getitem__", "Dataset.__setitem__"),
                           "zarr": ("open", "Array.__getitem__", "Array.__setitem__")}.items():
        for name in names:
            io = any(token in name.lower() for token in ("write", "file", "open", "setitem"))
            contracts.append(_contract("python", package, f"{package}.{name}", "IOBoundary" if io else "TableTransform",
                "OutputSink" if io else "TableRelation", "REFERENCE_ONLY_CONTRACT", "NEW_FAMILY_REQUIRED"))
    rust = {
        "std": [("std::iter::Iterator::sum", "Reduction", "Reduction(Add)"),
                ("std::iter::Iterator::product", "Reduction", "Reduction(Multiply)")],
        "ndarray": [("ndarray::ArrayBase::sum", "Reduction", "Reduction(Add)"),
                    ("ndarray::ArrayBase::dot", "TensorContraction", "Dot"),
                    ("ndarray::ArrayBase::t", "ShapeTransform", "Transpose")],
        "nalgebra": [("nalgebra::Matrix::mul", "TensorContraction", "MatMul"),
                     ("nalgebra::Matrix::transpose", "ShapeTransform", "Transpose")],
        "faer": [("faer::Mat::mul", "TensorContraction", "MatMul"),
                 ("faer::Mat::transpose", "ShapeTransform", "Transpose")],
        "rayon": [("rayon::iter::ParallelIterator::sum", "Reduction", "Reduction(Add)"),
                  ("rayon::iter::ParallelIterator::map", "Map", "Map")],
    }
    for package, records in rust.items():
        contracts += [_contract("rust", package, name, family, ir) for name, family, ir in records]
    cpp = {
        "std": [("std::accumulate", "Reduction", "FoldLeft"), ("std::reduce", "Reduction", "Reduction"),
                ("std::transform_reduce", "Reduction", "TransformReduce"), ("std::inner_product", "TensorContraction", "Dot")],
        "Eigen": [("Eigen::MatrixBase::sum", "Reduction", "Reduction(Add)"),
                  ("Eigen::MatrixBase::prod", "Reduction", "Reduction(Multiply)"),
                  ("Eigen::MatrixBase::operator*", "TensorContraction", "MatMul"),
                  ("Eigen::DenseBase::reshaped", "ShapeTransform", "Reshape")],
        "Boost": [("boost::math::normal_distribution", "KnownDistribution", "Normal"),
                  ("boost::math::quadrature::trapezoidal", "Quadrature", "Quadrature")],
    }
    for package, records in cpp.items(): contracts += [_contract("cpp", package, name, family, ir) for name, family, ir in records]
    by_language = {}; by_package = {}
    for item in contracts:
        by_language[item.language] = by_language.get(item.language, 0) + 1
        by_package[item.package] = by_package.get(item.package, 0) + 1
    counts = {status: sum(item.classification == status for item in contracts) for status in DETERMINISTIC_CLASSIFICATIONS}
    new = sorted({item.semantic_family for item in contracts if item.family_reuse == "NEW_FAMILY_REQUIRED" and item.semantic_family})
    coverage = EcosystemCoverage(len(contracts), counts["FORMAL_SEMANTIC_CONTRACT"], counts["REFERENCE_ONLY_CONTRACT"],
        counts["NOT_APPLICABLE"], counts["REFERENCE_INSUFFICIENT"],
        sum(item.family_reuse == "EXISTING_FAMILY_REUSED" for item in contracts), new, by_language, by_package)
    digest = sha256(json.dumps([asdict(item) for item in contracts], sort_keys=True).encode()).hexdigest()
    return MajorEcosystemReport(contracts, coverage, "DETERMINISTIC_CLASSIFICATION_COMPLETE",
        {"harvester": "OFFICIAL_PUBLIC_REFERENCE_SEED_HARVEST", "catalog_hash": digest,
         "versions": "UNVERIFIED_UNLESS_PINNED_BY_CALLER"})


def diff_library_versions(package: str, old_version: str, new_version: str,
                          old: Iterable[Mapping[str, Any]], new: Iterable[Mapping[str, Any]]) -> LibraryVersionDiff:
    before = {str(item["qualified_name"]): item for item in old}; after = {str(item["qualified_name"]): item for item in new}
    impacts = []
    for name in sorted(before.keys() | after.keys()):
        left, right = before.get(name), after.get(name)
        if left is None: change, reason = "API_ADDED", "Public API was added."
        elif right is None: change, reason = "API_REMOVED", "Public API was removed."
        elif left.get("signature") != right.get("signature"): change, reason = "SIGNATURE_CHANGED", "Public signature changed."
        elif not left.get("deprecated") and right.get("deprecated"): change, reason = "DEPRECATED", "API became deprecated."
        elif left.get("semantics") != right.get("semantics"): change, reason = "SEMANTICS_POTENTIALLY_CHANGED", "Reference semantics changed."
        elif left.get("reference_hash") != right.get("reference_hash"): change, reason = "REFERENCE_CHANGED", "Reference text changed."
        else: change, reason = "UNCHANGED", "No contract-relevant public change was detected."
        family = (right or left).get("semantic_family")
        review = "NO_REVIEW_REQUIRED" if change == "UNCHANGED" else "CONTRACT_REVIEW_REQUIRED"
        impacts.append(ContractImpact(name, change, left.get("contract_id") if left else None,
            right.get("contract_id") if right else None, family, review, reason))
    summary = {change: sum(item.change == change for item in impacts) for change in
               ("API_ADDED", "API_REMOVED", "SIGNATURE_CHANGED", "DEPRECATED", "REFERENCE_CHANGED",
                "SEMANTICS_POTENTIALLY_CHANGED", "UNCHANGED")}
    status = "CONTRACT_REVIEW_REQUIRED" if any(item.review_status == "CONTRACT_REVIEW_REQUIRED" for item in impacts) else "UNCHANGED"
    return LibraryVersionDiff(package, old_version, new_version, impacts, summary, status)
