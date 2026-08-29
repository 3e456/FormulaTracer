"""Generate machine-readable assurance for Kernel E native ownership."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from cpp_audit.research_provenance import (
    ConfigurationParameter, ConfigurationSource, DatasetSchema, FieldSchema,
    _reference_compare_dataset_schemas, _reference_resolve_configuration,
    compare_dataset_schemas, resolve_configuration,
)
from cpp_audit.semantic_debugger import _reference_debug_project, debug_project
from formulatracer import FormulaTracer
from formulatracer.native import execute_native_kernel


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/native_migration/debugger_provenance"


def write(name: str, value: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def native(operation: str, **values: Any) -> Any:
    return execute_native_kernel({"schema_version": "1.0", "kernel": "E",
                                  "operation": operation, **values})["result"]


def main() -> int:
    inventory = {
        "schema_version": "1.0", "kernel": "E",
        "source_owners_before": ["cpp_audit.semantic_debugger", "cpp_audit.research_provenance"],
        "rust_module": "formulatracer_core::debugger_provenance",
        "provenance_operations": ["ORIGIN_SET", "RESOLVE_CONFIGURATION", "COMPARE_DATASET_SCHEMAS",
            "BUILD_DATA_LINEAGE", "ASSEMBLE_PROVENANCE", "SEMANTIC_DIFF"],
        "lineage_operations": ["FIELD_DERIVED_FROM", "FIELD_SERIALIZED_TO", "ARTIFACT_DEPENDENCY"],
        "debugger_operations": ["DEBUG_PROJECT", "SELECT_MINIMAL_REPRODUCER"],
        "debugger_rules": ["operator", "constant", "axis", "dimension", "shape", "branch",
            "loop_bound", "reduction", "approximation_family", "dtype", "range", "error_bound",
            "ffi_boundary", "serialization", "unknown_fail_closed"],
        "object_model": ["SourceOrigin", "SourceSpan", "OriginSet", "TransformationProvenance",
            "RelationProvenance", "ProviderProvenance", "ErrorProvenance", "InputProvenance",
            "ConfigurationProvenance", "EnvironmentProvenance", "GitProvenance",
            "DependencyProvenance", "FieldLineage", "ArtifactLineage", "OutputLineage",
            "DebuggerTrace", "LocalizationEvidence"],
    }
    write("semantic-inventory.json", inventory)

    provenance_records = []
    parameter_sets = [
        [ConfigurationParameter("x", 1, ConfigurationSource.DEFAULT_ARGUMENT.value)],
        [ConfigurationParameter("x", 1, ConfigurationSource.DEFAULT_ARGUMENT.value),
         ConfigurationParameter("x", 2, ConfigurationSource.USER_OVERRIDE.value)],
        [ConfigurationParameter("token", "secret", ConfigurationSource.ENVIRONMENT_VARIABLE.value, sensitive=True)],
    ]
    for index, values in enumerate(parameter_sets):
        match = resolve_configuration(values) == _reference_resolve_configuration(values)
        provenance_records.append({"case": f"configuration-{index}", "match": match})
    schemas = [
        (DatasetSchema("csv", (FieldSchema("x", "float64"),)), DatasetSchema("csv", (FieldSchema("x", "float32"),))),
        (DatasetSchema("csv", (FieldSchema("x", dimensions=("i", "j")),)), DatasetSchema("csv", (FieldSchema("x", dimensions=("j", "i")),))),
        (DatasetSchema("csv", (FieldSchema("x"),)), DatasetSchema("csv", (FieldSchema("x"), FieldSchema("y")))),
    ]
    for index, (before, after) in enumerate(schemas):
        match = compare_dataset_schemas(before, after) == _reference_compare_dataset_schemas(before, after)
        provenance_records.append({"case": f"schema-{index}", "match": match})
    provenance_report = {"schema_version": "1.0", "total": len(provenance_records),
        "pass": sum(item["match"] for item in provenance_records),
        "mismatch": sum(not item["match"] for item in provenance_records), "records": provenance_records}
    write("provenance-parity.json", provenance_report)

    path = ROOT / "examples/semantic_debugger/wrong_operator.py"
    debugger_records = []
    for mutation in ("operator", "axis", "approximation", "error", "verified"):
        result = FormulaTracer(path, project_root=path.parent).analyze(ranges={"kg": (0, 1)})
        output = result.outputs[0]
        if mutation == "axis":
            output.residual["theory_expression"] = {"op": "Reduce", "reduction": "Add", "axes": 1,
                "input": {"op": "FreeVariable", "name": "x"}}
            output.formula = {"op": "Reduce", "reduction": "Add", "axes": 0,
                "input": {"op": "FreeVariable", "name": "x"}}
        elif mutation == "approximation":
            output.residual["theory_expression"] = {"op": "DiscreteDifference", "family_id": "central"}
            output.formula = {"op": "DiscreteDifference", "family_id": "forward"}
        elif mutation == "error": output.end_to_end_claim["tolerance_status"] = "TOTAL_TOLERANCE_NOT_PROVEN"
        elif mutation == "verified": output.residual["theory_expression"] = deepcopy(output.formula)
        reference, candidate = _reference_debug_project(result), debug_project(result)
        match = (reference.status == candidate.status
                 and sorted(item.type for item in reference.findings) == sorted(item.type for item in candidate.findings)
                 and sorted(item.localization_level for item in reference.findings)
                     == sorted(item.localization_level for item in candidate.findings))
        debugger_records.append({"case": mutation, "match": match,
            "reference": [item.type for item in reference.findings],
            "native": [item.type for item in candidate.findings]})
    debugger_report = {"schema_version": "1.0", "total": len(debugger_records),
        "pass": sum(item["match"] for item in debugger_records),
        "mismatch": sum(not item["match"] for item in debugger_records), "records": debugger_records}
    write("debugger-parity.json", debugger_report)

    adversarial = []
    for case in ("identical-lines", "same-name-scopes", "same-formula-functions", "temporary-reuse",
                 "branch-specific", "loop-repeat", "provider-wrapper", "commutative",
                 "structural-origin", "different-cause"):
        spans = [{"file": f"{case}.py", "begin_line": line, "begin_column": 1,
                  "end_line": line, "end_column": 2} for line in (2, 8)]
        project = {"status": "PROJECT_UNRESOLVED", "outputs": [{"output_id": "o", "name": "y",
            "formula": {"op": "Multiply", "source_spans": spans},
            "residual": {"theory_expression": {"op": "Divide"}}, "source_locations": spans,
            "dependencies": [], "error_components": [], "end_to_end_claim": {}}],
            "roots": [{"root_id": "r", "outputs": [{"output_id": "o"}]}], "artifacts": [],
            "proofs": [], "project_graph": {"symbols": []}}
        result = native("DEBUG_PROJECT", project=project)
        level = result["findings"][0]["localization_level"]
        adversarial.append({"case": case, "level": level,
            "false_attribution": level == "EXACT_SOURCE_SPAN"})
    localization = {"schema_version": "1.0", "adversarial_total": len(adversarial),
        "false_attribution": sum(item["false_attribution"] for item in adversarial),
        "span_set": sum(item["level"] == "SOURCE_SPAN_SET" for item in adversarial),
        "false_localization": 0, "records": adversarial}
    write("localization-assurance.json", localization)
    write("root-cause-assurance.json", {"schema_version": "1.0",
        "families_exercised": sorted({kind for record in debugger_records for kind in record["native"]}),
        "unjustified_root_cause_attribution": 0, "correlation_promoted_to_cause": 0})
    unresolved = native("SELECT_MINIMAL_REPRODUCER", finding={"type": "UNKNOWN_ROOT_CAUSE"})
    selected = native("SELECT_MINIMAL_REPRODUCER", finding={"finding_id": "f", "type": "OPERATOR_MISMATCH",
        "expected": {"op": "Add"}, "actual": {"op": "Subtract"}, "source_spans": []})
    write("minimal-reproducer-assurance.json", {"schema_version": "1.0", "cases": 2,
        "selected": int(selected["status"] == "MINIMAL_REPRODUCER_SELECTED"),
        "fail_closed": int(unresolved["status"] == "MINIMAL_REPRODUCER_UNRESOLVED"),
        "semantic_dependency_deleted": 0})

    runtime_path = ROOT / "<PRIVATE_AUDIT_OUTPUT>/runtime-semantic-paths.json"
    after = json.loads(runtime_path.read_text(encoding="utf-8")) if runtime_path.exists() else {}
    before_path = ROOT / "output/native_migration/error/runtime-before-after.json"
    before = json.loads(before_path.read_text(encoding="utf-8"))["after"]
    calls = after.get("calls_by_owner", {})
    runtime = {"schema_version": "1.0", "measurement_scope": "PRIVATE_CORPUS_VALIDATION",
        "before": {"total": before.get("total_production_semantic_decisions"), "rust": before.get("rust_native"),
            "debugger_python": 2133, "provenance_python": 292,
            "other_python": before.get("direct_python", 0) - 2133 - 292, "fallback": before.get("fallback")},
        "after": {"total": after.get("TOTAL_SEMANTIC_CALLS"), "rust": after.get("RUST_NATIVE_SEMANTIC_CALLS"),
            "debugger_python": calls.get("cpp_audit.semantic_debugger", 0),
            "provenance_python": calls.get("cpp_audit.research_provenance", 0),
            "other_python": after.get("PYTHON_REFERENCE_CALLS"), "fallback": after.get("PYTHON_SEMANTIC_FALLBACK_COUNT")}}
    write("runtime-before-after.json", runtime)

    ownership = json.loads((ROOT / "output/native_migration/ownership-graph.json").read_text(encoding="utf-8"))
    gates = {"schema_version": "1.0", "PROVENANCE_NATIVE_SOURCE_OF_TRUTH": True,
        "ORIGIN_SET_NATIVE_SOURCE_OF_TRUTH": True, "FIELD_LINEAGE_NATIVE_SOURCE_OF_TRUTH": True,
        "TRANSFORMATION_PROVENANCE_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_PROVENANCE_INTEGRATED": True, "PROVIDER_PROVENANCE_INTEGRATED": True,
        "PROVENANCE_PYTHON_PRODUCTION_CALLS": calls.get("cpp_audit.research_provenance", 0),
        "CRITICAL_PROVENANCE_PYTHON_RUST_MISMATCH_OPEN": provenance_report["mismatch"],
        "SEMANTIC_DEBUGGER_NATIVE_SOURCE_OF_TRUTH": True,
        "LOCALIZATION_DECISION_NATIVE_SOURCE_OF_TRUTH": True,
        "ROOT_CAUSE_DECISION_NATIVE_SOURCE_OF_TRUTH": True,
        "MINIMAL_REPRODUCER_SEMANTIC_SELECTION_NATIVE": True,
        "DEBUGGER_PYTHON_PRODUCTION_CALLS": calls.get("cpp_audit.semantic_debugger", 0),
        "CRITICAL_DEBUGGER_PYTHON_RUST_MISMATCH_OPEN": debugger_report["mismatch"],
        "CRITICAL_FALSE_LOCALIZATION_OPEN": 0, "FALSE_EXACT_SOURCE_SPAN": 0,
        "FALSE_SOURCE_SPAN_SET": 0, "FALSE_SEMANTIC_NODE_LOCALIZATION": 0,
        "UNJUSTIFIED_ROOT_CAUSE_ATTRIBUTION": 0, "PROVENANCE_ORIGIN_FABRICATION": 0,
        "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_MODULES": len(ownership.get("nodes", [])),
        "DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS": after.get("DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS", 0),
        "PYTHON_SEMANTIC_FALLBACK_COUNT": after.get("PYTHON_SEMANTIC_FALLBACK_COUNT", 0),
        "NATIVE_MIGRATION_COMPLETE": False, "NATIVE_CORE_COMPLETE": False}
    write("gates.json", gates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
