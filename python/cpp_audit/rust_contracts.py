"""Language-specific public-reference contracts for Rust numeric APIs.

These contracts map public Rust symbols to the same language-neutral semantic
families used by Python/C++. They never imply that similarly named APIs in
different languages share a contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any


@dataclass(frozen=True)
class RustLibraryContract:
    crate_name: str
    crate_version: str
    public_symbol: str
    official_reference: str
    contract_version: str
    semantic_family: str
    mathematical_operation: str
    execution_semantics: dict[str, Any]
    resolution_status: str = "REFERENCE_CONTRACT_RESOLVED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RustLibraryContractRegistry:
    """Small reviewed seed registry; unknown crate APIs remain opaque."""

    def __init__(self) -> None:
        std = "https://doc.rust-lang.org/std/iter/trait.Iterator.html"
        ndarray = "https://docs.rs/ndarray/latest/ndarray/struct.ArrayBase.html"
        rayon = "https://docs.rs/rayon/latest/rayon/iter/trait.ParallelIterator.html"
        nalgebra = "https://docs.rs/nalgebra/latest/nalgebra/base/struct.Matrix.html"
        self._contracts: dict[tuple[str, str], RustLibraryContract] = {}
        for symbol, family, operation in (
            ("Iterator::map", "MAP", "Map"), ("Iterator::filter", "FILTER", "Filter"),
            ("Iterator::fold", "REDUCTION", "FoldLeft"), ("Iterator::reduce", "REDUCTION", "Reduce"),
            ("Iterator::sum", "REDUCTION", "FiniteSum"),
            ("Iterator::product", "REDUCTION", "FiniteProduct"),
            ("Iterator::collect", "REPRESENTATION_MAPPING", "Collect"),
            ("Iterator::zip", "ALIGNMENT", "Zip"), ("Iterator::enumerate", "INDEX_SELECTION", "Enumerate"),
        ):
            self._add("std", "toolchain", symbol, std, family, operation)
        for scalar in ("f32", "f64"):
            for method, operation in (("abs", "Abs"), ("sqrt", "Sqrt"), ("ln", "Log"),
                                      ("exp", "Exp"), ("powi", "Power"), ("powf", "Power")):
                self._add("std", "toolchain", f"{scalar}::{method}",
                          f"https://doc.rust-lang.org/std/primitive.{scalar}.html#method.{method}",
                          "ELEMENTARY_FUNCTION", operation)
        for symbol, family, operation in (
            ("ArrayBase::sum", "REDUCTION", "FiniteSum"),
            ("ArrayBase::mean", "STATISTICS", "Mean"),
            ("ArrayBase::mapv", "MAP", "Map"),
            ("ArrayBase::dot", "TENSOR_CONTRACTION", "TensorContraction"),
            ("ArrayBase::shape", "SHAPE_QUERY", "Shape"),
            ("ArrayBase::sum_axis", "REDUCTION", "FiniteSum"),
            ("ArrayBase::mean_axis", "STATISTICS", "Mean"),
            ("ArrayBase::slice", "INDEX_SELECTION", "IndexSelection"),
        ):
            self._add("ndarray", "*", symbol, ndarray, family, operation)
        for symbol, operation in (("Matrix::dot", "TensorContraction"), ("Matrix::norm", "Norm"),
                                  ("Matrix::add", "Add"), ("Matrix::mul", "TensorContraction")):
            self._add("nalgebra", "*", symbol, nalgebra, "LINEAR_ALGEBRA_RELATION", operation)
        for crate in ("faer",):
            for symbol, operation in (("Mat::norm_l2", "Norm"), ("Mat::mul", "TensorContraction")):
                self._add(crate, "*", symbol, f"https://docs.rs/{crate}/latest/{crate}/", "LINEAR_ALGEBRA_RELATION", operation)
        for symbol, operation in (("ParallelIterator::map", "Map"), ("ParallelIterator::reduce", "Reduce"),
                                  ("ParallelIterator::sum", "FiniteSum")):
            self._add("rayon", "*", symbol, rayon, "PARALLEL_EXECUTION", operation,
                      {"policy": "PARALLEL_REORDERABLE", "reduction_order": "UNSPECIFIED",
                       "floating_point_order_difference": True})

    def _add(self, crate: str, version: str, symbol: str, reference: str, family: str,
             operation: str, execution: dict[str, Any] | None = None) -> None:
        self._contracts[(crate, symbol)] = RustLibraryContract(crate, version, symbol, reference,
            "rust-contract-v1", family, operation, dict(execution or {}))

    def resolve(self, crate: str, public_symbol: str) -> RustLibraryContract | None:
        return self._contracts.get((crate, public_symbol))

    def all(self) -> list[RustLibraryContract]:
        return list(self._contracts.values())

    @property
    def registry_hash(self) -> str:
        raw = json.dumps([item.to_dict() for item in self.all()], sort_keys=True).encode()
        return sha256(raw).hexdigest()

    def coverage(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.all(): counts[item.crate_name] = counts.get(item.crate_name, 0) + 1
        return {"status": "RUST_CONTRACT_SEED_COVERAGE", "counts": counts,
                "total": sum(counts.values()), "registry_hash": self.registry_hash}
