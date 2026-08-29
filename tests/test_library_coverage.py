from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from cpp_audit.library_contracts import LibraryContractRegistry
from cpp_audit.library_coverage import (classify_prior_divergences, library_backends,
                                        run_self_generation_smoke, semantic_category,
                                        shape_relation, targeted_mutations)
from cpp_audit.semantic_debugger import _compare
from cpp_audit.python_audit import AuditMode, audit_python


ROOT = Path(__file__).resolve().parents[1]


def test_private_corpus_gap_contracts_are_resolved_without_promoting_io_to_math():
    registry = LibraryContractRegistry.coverage_expansion()
    for name in ("numpy.load", "numpy.save", "xarray.open_dataset", "pandas.read_csv",
                 "rasterio.features.features.rasterize", "numpy.minimum.reduceat"):
        assert registry.resolve(name) is not None
    assert semantic_category("", callable_name="numpy.load") == "IO_SERIALIZATION"


def test_shape_relations_keep_named_dimensions_and_fail_closed_elsewhere():
    relation = shape_relation("Reduction", {"reducer": "add"}, "xarray.DataArray.sum")
    assert relation[0]["axis_source"] == "dim"
    assert relation[0]["named_dimensions_preserved"] is True
    assert shape_relation("AlgorithmInvocation", {}, "unknown.call") == []


def test_backend_capabilities_are_queryable_and_unavailable_lowerings_fail_closed():
    backends = library_backends()
    assert backends["numpy"].supports("FiniteSum")
    assert backends["numpy"].supports("MatrixMultiply")
    assert backends["numpy"].lower("FilteredSum")["status"] == "BACKEND_CAPABILITY_UNAVAILABLE"
    assert backends["rust-ndarray"].supports("MatrixMultiply")


def test_self_generation_uses_actual_frontend_and_mutations_are_detected():
    result = run_self_generation_smoke()
    attempted = [row for row in result["cases"] if row["round_trip_status"] != "BACKEND_CAPABILITY_UNAVAILABLE"]
    assert attempted and all(row["reanalysis"] == "ACTUAL_FORMULATRACER_FRONTEND" for row in attempted)
    assert result["critical_false_acceptance"] == 0
    mutation = targeted_mutations()
    assert mutation["detected"] == 6 and mutation["false_acceptance"] == 0


def test_prior_six_divergences_are_deterministically_classified():
    report = classify_prior_divergences(ROOT / "output" / "control_flow_assurance" / "generated-valid-results.json")
    assert report["divergence_count"] == 6
    assert set(report["classification_counts"]) <= {"FRONTEND_LIMITATION", "NORMALIZATION_GAP"}
    assert report["critical_false_acceptance"] == 0


def test_reference_contract_axis_keyword_mutation_is_not_silently_accepted():
    before = {"op": "Statistics", "name": "nan_mean", "args": [], "keywords": {"axis": "0"}}
    after = {"op": "Statistics", "name": "nan_mean", "args": [], "keywords": {"axis": "1"}}
    differences = _compare(before, after)
    assert differences and differences[0]["type"] == "AXIS_MISMATCH"


def test_torch_reduction_dim_and_keepdim_are_preserved_for_mutation_assurance(tmp_path: Path):
    source = tmp_path / "torch_reduction.py"
    source.write_text("import torch\ndef compute(x):\n    return torch.sum(x, dim=1, keepdim=True)\n", encoding="utf-8")
    result = audit_python(source, function="compute", mode=AuditMode.REPORT_ONLY,
                          verify_lean=False, library_registry=LibraryContractRegistry.coverage_expansion())
    expression = result.implementation["outputs"][0]["expression"]
    constraint = expression["shape_constraints"][0]
    assert constraint["axis"] == 1
    assert constraint["keepdims"] is True


def test_library_coverage_summary_schema_with_synthetic_payload():
    payload = {
        "schema_version": "1.0",
        "status": "MAJOR_LIBRARY_COVERAGE_EXPANSION_COMPLETE",
        "public_apis_classified": 1,
        "classification_counts": {"FORMALIZED": 1},
        "semantic_equivalence_classes": 1,
        "meaningful_semantic_classification_rate": 1.0,
        "self_generation_capable_backends": 1,
        "round_trip_verified": 1,
        "CRITICAL_LIBRARY_FALSE_ACCEPTANCE_OPEN": 0,
        "external_source_retained": 0,
        "private_corpus_before_after": {
            "before": "PRIVATE",
            "after": "PRIVATE",
            "data_file_content_read": False,
            "corpus_modified": False,
        },
        "self_audit_readiness": {"backends": ["numpy"]},
    }
    schema = json.loads((ROOT / "schemas/library-coverage-summary.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
