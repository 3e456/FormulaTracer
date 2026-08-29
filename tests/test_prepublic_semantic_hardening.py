from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from formulatracer.native import execute_native_kernel, native_available
from tools import check_maintenance


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not native_available(), reason="native core not built")


def request(operation: str, action: str, **facts):
    return execute_native_kernel({"schema_version":"1.0", "kernel":"C",
                                  "operation":operation, "action":action, **facts})["result"]


def labeled(provider="xarray", labels=(0, 1, 2), name="x"):
    return {"container_kind":"LABELED_ARRAY", "provider":provider,
            "value_ir":{"op":"FreeVariable","name":name},
            "dimensions":[{"name":"time","length":len(labels)}],
            "coordinates":{"time":list(labels)}, "dtype":"float64"}


def test_labeled_alignment_and_missingness_are_first_class():
    result = request("LABELED_DATA", "BINARY", left=labeled(labels=(0,1),name="x"),
                     right=labeled(labels=(1,2),name="y"), alignment="OUTER",
                     missing_policy="CONDITIONAL_FALLBACK",
                     value_operation={"op":"Add","args":["x","y"]})
    assert result["status"] == "FULL_RECONSTRUCTION"
    assert result["value_semantics"]["op"] == "Piecewise"
    assert result["alignment_semantics"]["kind"] == "OUTER"


def test_dask_unknown_backend_and_tree_mutation_fail_closed():
    unknown = request("PROVIDER_EXECUTION", "DASK_ANALYZE", operation_kind="SUM",
                      dtype="float64", chunk_counts=[4], split_every=2, axis=0)
    assert unknown["status"] == "PARTIAL_RECONSTRUCTION"
    assert unknown["error_certificate"]["certified"] is False
    mutation = request("PROVIDER_EXECUTION", "COMPARE_REDUCTION_TREES",
                       left_tree=[[0,1],[2,3]], right_tree=[[[0,1],2],3])
    assert mutation["same_execution_order"] is False
    assert mutation["exact_promotion"] is False


def test_scipy_callback_and_error_estimate_are_not_proof():
    result = request("PROVIDER_EXECUTION", "NUMERICAL_RELATION",
                     problem_kind="DEFINITE_INTEGRAL", problem={"op":"Integral"},
                     algorithm="QUADPACK", callback_ir={"op":"Power","base":"x","exponent":2},
                     returned_approximation="y_hat", error_estimate="abserr",
                     official_reference="https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.quad.html")
    assert result["status"] == "FULL_RECONSTRUCTION"
    assert result["exact_promotion"] is False
    assert result["error_evidence"]["kind"] == "LIBRARY_RETURNED_ESTIMATE"
    assert result["error_evidence"]["certified"] is False


def test_coverage_artifacts_share_corpus_and_preserve_safety():
    base = json.loads((ROOT/"output/prepublic_semantic_upgrade/baseline-coverage.json").read_text())
    final = json.loads((ROOT/"output/prepublic_semantic_upgrade/final-coverage.json").read_text())
    delta = json.loads((ROOT/"output/prepublic_semantic_upgrade/coverage-delta.json").read_text())
    assert base["corpus"] == final["corpus"]
    assert base["case_count"] == final["case_count"] == 23
    assert delta["full_delta"] > 0
    assert delta["false_acceptance_delta"] == 0
    assert delta["false_exact_promotion"] == 0
    assert delta["false_certified_promotion"] == 0


def test_operational_gate_fails_closed_when_stderr_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        check_maintenance.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr=None),
    )
    assert check_maintenance.operational_gate() == [
        "synthetic operational audit failed: no stderr captured"
    ]


def test_operational_gate_supplies_repository_python_path(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        payload = {
            "exact": {"comparison_match": True},
            "relational": {"relation": "DISCRETIZATION_OF"},
            "unresolved": {"operation": "OpaqueNumericCall"},
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(check_maintenance.subprocess, "run", fake_run)
    assert check_maintenance.operational_gate() == []
    assert str((ROOT / "python").resolve()) in captured["env"]["PYTHONPATH"]
