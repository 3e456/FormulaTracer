from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from cpp_audit.research_provenance import (
    ConfigurationParameter,
    ConfigurationSource,
    DatasetSchema,
    FieldSchema,
    _reference_compare_dataset_schemas,
    _reference_resolve_configuration,
    compare_dataset_schemas,
    resolve_configuration,
)
from cpp_audit.semantic_debugger import _reference_debug_project, debug_project
from formulatracer import FormulaTracer
from formulatracer.native import execute_native_kernel


ROOT = Path(__file__).resolve().parents[1]


def project(name: str = "wrong_operator.py"):
    path = ROOT / "examples" / "semantic_debugger" / name
    return FormulaTracer(path, project_root=path.parent).analyze(ranges={"kg": (0, 1)})


@pytest.mark.parametrize("parameters", [
    [ConfigurationParameter("x", 1, ConfigurationSource.DEFAULT_ARGUMENT.value)],
    [ConfigurationParameter("x", 1, ConfigurationSource.DEFAULT_ARGUMENT.value),
     ConfigurationParameter("x", 2, ConfigurationSource.USER_OVERRIDE.value)],
    [ConfigurationParameter("token", "secret", ConfigurationSource.ENVIRONMENT_VARIABLE.value, sensitive=True)],
])
def test_configuration_python_rust_parity(parameters):
    assert resolve_configuration(parameters) == _reference_resolve_configuration(parameters)


@pytest.mark.parametrize("before,after", [
    (DatasetSchema("csv", (FieldSchema("x", "float64"),)),
     DatasetSchema("csv", (FieldSchema("x", "float32"),))),
    (DatasetSchema("csv", (FieldSchema("x", "float64", dimensions=("i", "j")),)),
     DatasetSchema("csv", (FieldSchema("x", "float64", dimensions=("j", "i")),))),
    (DatasetSchema("csv", (FieldSchema("x"),)), DatasetSchema("csv", (FieldSchema("x"), FieldSchema("y")))),
])
def test_schema_python_rust_parity(before, after):
    assert compare_dataset_schemas(before, after) == _reference_compare_dataset_schemas(before, after)


@pytest.mark.parametrize("mutation", ["operator", "axis", "approximation", "error", "verified"])
def test_debugger_python_rust_semantic_parity(mutation):
    result = project()
    output = result.outputs[0]
    if mutation == "axis":
        output.residual["theory_expression"] = {"op": "Reduce", "reduction": "Add", "axes": 1,
            "input": {"op": "FreeVariable", "name": "x"}}
        output.formula = {"op": "Reduce", "reduction": "Add", "axes": 0,
            "input": {"op": "FreeVariable", "name": "x"}}
    elif mutation == "approximation":
        output.residual["theory_expression"] = {"op": "DiscreteDifference", "family_id": "central"}
        output.formula = {"op": "DiscreteDifference", "family_id": "forward"}
    elif mutation == "error":
        output.end_to_end_claim["tolerance_status"] = "TOTAL_TOLERANCE_NOT_PROVEN"
    elif mutation == "verified":
        output.residual["theory_expression"] = deepcopy(output.formula)
    reference = _reference_debug_project(result)
    native = debug_project(result)
    assert native.status == reference.status
    assert sorted(item.type for item in native.findings) == sorted(item.type for item in reference.findings)
    assert sorted(item.localization_level for item in native.findings) == sorted(item.localization_level for item in reference.findings)
    assert all(item.localization_level != "FALSE_LOCALIZATION" for item in native.findings)


@pytest.mark.parametrize("operation", ["UNION", "INTERSECTION", "PROJECTION"])
def test_origin_set_operations_are_native_and_stable(operation):
    first = {"file": "a.py", "begin_line": 1, "end_line": 1}
    second = {"file": "a.py", "begin_line": 2, "end_line": 2}
    result = execute_native_kernel({"schema_version": "1.0", "kernel": "E", "operation": "ORIGIN_SET",
        "set_operation": operation, "left": [first, second, first], "right": [second], "path": "a.py"})["result"]
    assert result["status"] in {"COMPLETE", "UNRESOLVED"}
    assert len(result["origins"]) == len({str(item) for item in result["origins"]})


@pytest.mark.parametrize("case", [
    "identical-lines", "same-name-scopes", "same-formula-functions", "temporary-reuse",
    "branch-specific", "loop-repeat", "provider-wrapper", "commutative", "structural-origin", "different-cause",
])
def test_adversarial_ambiguous_origins_never_claim_exact(case):
    spans = [
        {"file": f"{case}.py", "begin_line": 2, "begin_column": 1, "end_line": 2, "end_column": 2},
        {"file": f"{case}.py", "begin_line": 8, "begin_column": 1, "end_line": 8, "end_column": 2},
    ]
    payload = {"status": "PROJECT_UNRESOLVED", "end_to_end_status": "END_TO_END_UNRESOLVED",
        "outputs": [{"output_id": "o", "name": "y", "formula": {"op": "Multiply", "source_spans": spans},
            "residual": {"theory_expression": {"op": "Divide"}}, "source_locations": spans,
            "dependencies": [], "error_components": [], "end_to_end_claim": {}}],
        "roots": [{"root_id": "r", "outputs": [{"output_id": "o"}]}], "artifacts": [],
        "proofs": [], "project_graph": {"symbols": []}}
    result = execute_native_kernel({"schema_version": "1.0", "kernel": "E",
        "operation": "DEBUG_PROJECT", "project": payload})["result"]
    finding = result["findings"][0]
    assert finding["localization_level"] == "SOURCE_SPAN_SET"
    assert result["localization_metrics"]["false_localization"] == 0


def test_missing_origin_and_reproducer_dependency_fail_closed():
    result = execute_native_kernel({"schema_version": "1.0", "kernel": "E",
        "operation": "SELECT_MINIMAL_REPRODUCER", "finding": {"type": "UNKNOWN_ROOT_CAUSE"}})["result"]
    assert result["status"] == "MINIMAL_REPRODUCER_UNRESOLVED"
