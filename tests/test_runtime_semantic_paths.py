from __future__ import annotations

import pytest

from formulatracer import (NativeCallError, execute_native_kernel,
                           observe_python_semantic_runtime,
                           semantic_execution_scope,
                           reset_semantic_runtime_metrics, semantic_runtime_snapshot)
from cpp_audit.interval import Interval
from formulatracer.native import native_available


pytestmark = pytest.mark.skipif(not native_available(), reason="native core not built")


def test_native_runtime_path_is_measured_by_kernel_without_fallback():
    reset_semantic_runtime_metrics()
    execute_native_kernel({"schema_version": "1.0", "kernel": "A",
                           "operation": "SUPPORTS_STRUCTURE",
                           "domain": "NATURAL", "structure": "RING"})
    execute_native_kernel({"schema_version": "1.0", "kernel": "B",
                           "operation": "EQUAL",
                           "left": {"op": "Constant", "value": 1},
                           "right": {"op": "Constant", "value": 1}})
    snapshot = semantic_runtime_snapshot()
    assert snapshot["TOTAL_SEMANTIC_CALLS"] == 2
    assert snapshot["RUST_NATIVE_SEMANTIC_CALLS"] == 2
    assert snapshot["PYTHON_REFERENCE_CALLS"] == 0
    assert snapshot["PYTHON_SEMANTIC_FALLBACK_COUNT"] == 0
    assert snapshot["calls_by_kernel"]["A"] == 1
    assert snapshot["calls_by_kernel"]["B"] == 1
    assert snapshot["calls_by_scope"]["PRODUCTION"] == 2
    assert snapshot["calls_by_owner"]["semantic_kernel"] == 2
    assert all(event["request_id"] and event["result_id"] for event in snapshot["events"])


def test_unsupported_native_operation_is_measured_and_never_falls_back():
    reset_semantic_runtime_metrics()
    with pytest.raises(NativeCallError, match="unsupported native component"):
        execute_native_kernel({"schema_version": "1.0", "kernel": "A",
                               "operation": "NOT_IMPLEMENTED"})
    snapshot = semantic_runtime_snapshot()
    assert snapshot["UNSUPPORTED_COUNT"] == 1
    assert snapshot["PYTHON_SEMANTIC_FALLBACK_COUNT"] == 0
    assert snapshot["fallback_by_kernel"] == {kernel: 0 for kernel in "ABCDEF"}


def test_production_observer_exposes_native_interval_ownership():
    reset_semantic_runtime_metrics()
    with observe_python_semantic_runtime():
        assert Interval(0.0, 1.0).resolved
    snapshot = semantic_runtime_snapshot()
    assert snapshot["PYTHON_REFERENCE_CALLS"] == 0
    assert snapshot["calls_by_kernel"]["C"] == snapshot["RUST_NATIVE_SEMANTIC_CALLS"]
    assert snapshot["RUST_NATIVE_SEMANTIC_CALLS"] >= 2
    assert snapshot["PYTHON_SEMANTIC_FALLBACK_COUNT"] == 0
    assert all(event["semantic_owner"] == "RUST_CORE" for event in snapshot["events"])


def test_validation_oracle_calls_are_separate_from_production_gate():
    reset_semantic_runtime_metrics()
    with semantic_execution_scope("DIFFERENTIAL_VALIDATION"):
        execute_native_kernel({"schema_version": "1.0", "kernel": "A",
                               "operation": "SUPPORTS_STRUCTURE",
                               "domain": "REAL", "structure": "FIELD"})
    with observe_python_semantic_runtime(execution_scope="REFERENCE_ORACLE"):
        assert Interval(0.0, 1.0).resolved
    snapshot = semantic_runtime_snapshot()
    assert snapshot["paths_by_scope"]["PRODUCTION"]["RUST_NATIVE"] == 0
    assert snapshot["paths_by_scope"]["REFERENCE_ORACLE"]["PYTHON_REFERENCE"] == 0
    assert snapshot["paths_by_scope"]["REFERENCE_ORACLE"]["RUST_NATIVE"] >= 2
    assert snapshot["paths_by_scope"]["DIFFERENTIAL_VALIDATION"]["RUST_NATIVE"] == 1


def test_observer_counts_owner_boundaries_not_nested_same_module_helpers():
    reset_semantic_runtime_metrics()
    value = Interval(0.0, 1.0)
    with observe_python_semantic_runtime():
        assert value.resolved
        assert not value.singleton
    snapshot = semantic_runtime_snapshot()
    operations = snapshot["calls_by_operation"]
    assert not any("<genexpr>" in operation for operation in operations)
    assert snapshot["PYTHON_REFERENCE_CALLS"] == 0
    assert sum(operations.values()) == snapshot["RUST_NATIVE_SEMANTIC_CALLS"]
    assert set(operations) == {"semantic_kernel:LEGACY_INTERVAL"}


def test_observer_excludes_presentation_and_plain_object_construction():
    reset_semantic_runtime_metrics()
    with observe_python_semantic_runtime():
        value = Interval(0.0, 1.0)
        value.to_dict()
    snapshot = semantic_runtime_snapshot()
    assert snapshot["PYTHON_REFERENCE_CALLS"] == 0
    assert snapshot["RUST_NATIVE_SEMANTIC_CALLS"] == 1
    assert snapshot["calls_by_operation"] == {"semantic_kernel:LEGACY_INTERVAL": 1}
