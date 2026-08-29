from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from formulatracer import diff_library_versions, harvest_major_ecosystem_contracts


ROOT = Path(__file__).resolve().parents[1]


def test_major_languages_packages_and_deterministic_classification():
    report = harvest_major_ecosystem_contracts()
    packages = {item.package for item in report.contracts}
    assert {"jax", "torch", "cupy", "numba", "sympy", "sklearn", "statsmodels", "networkx",
            "polars", "pyarrow", "h5py", "zarr", "xgboost", "lightgbm", "dask_ml",
            "std", "ndarray", "nalgebra", "faer", "rayon", "Eigen", "Boost"} <= packages
    assert set(report.coverage.by_language) == {"python", "rust", "cpp"}
    assert report.coverage.total == len(report.contracts) >= 90
    assert report.coverage.total == sum((report.coverage.formal_semantic_contract,
                                         report.coverage.reference_only_contract,
                                         report.coverage.not_applicable,
                                         report.coverage.reference_insufficient))


def test_family_reuse_and_execution_metadata_remain_separate():
    report = harvest_major_ecosystem_contracts()
    by_name = {item.qualified_name: item for item in report.contracts}
    assert by_name["jax.numpy.sum"].mathematical_ir == "Reduction(Add)"
    assert by_name["torch.sum"].mathematical_ir == "Reduction(Add)"
    assert by_name["cupy.sum"].mathematical_ir == "Reduction(Add)"
    assert by_name["jax.numpy.sum"].execution_metadata["backend"] == "JIT_DEVICE"
    assert by_name["cupy.sum"].execution_metadata["backend"] == "GPU"
    assert by_name["rayon::iter::ParallelIterator::sum"].execution_metadata["reduction_order"] == "REORDERABLE"


def test_ml_contracts_are_reference_semantics_not_model_theory_proofs():
    report = harvest_major_ecosystem_contracts()
    fit = next(item for item in report.contracts if item.qualified_name == "sklearn.Estimator.fit")
    assert fit.semantic_family == "EstimatorConstruction"
    assert fit.classification == "REFERENCE_ONLY_CONTRACT"
    assert fit.family_reuse == "NEW_FAMILY_REQUIRED"


def test_version_diff_limits_review_to_impacted_contracts():
    old = [{"qualified_name": "lib.sum", "signature": "sum(x)", "reference_hash": "a",
            "semantics": "add", "semantic_family": "Reduction", "contract_id": "old-sum"},
           {"qualified_name": "lib.old", "signature": "old(x)", "reference_hash": "a", "semantics": "x"}]
    new = [{"qualified_name": "lib.sum", "signature": "sum(x, axis=None)", "reference_hash": "b",
            "semantics": "add", "semantic_family": "Reduction", "contract_id": "new-sum"},
           {"qualified_name": "lib.new", "signature": "new(x)", "reference_hash": "a", "semantics": "x"}]
    diff = diff_library_versions("lib", "1", "2", old, new)
    assert diff.summary["SIGNATURE_CHANGED"] == 1
    assert diff.summary["API_ADDED"] == 1 and diff.summary["API_REMOVED"] == 1
    assert diff.status == "CONTRACT_REVIEW_REQUIRED"


def test_ecosystem_schema(tmp_path: Path):
    report = harvest_major_ecosystem_contracts(); payload = report.to_dict()
    schema = json.loads((ROOT / "schemas" / "major-ecosystem-report.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    report.write_json(tmp_path / "ecosystem.json")
