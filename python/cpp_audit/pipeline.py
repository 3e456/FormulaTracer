"""Clang-provenance audit pipeline and independent reference interpreters.

This module never reads C++ source.  Its only implementation input is validated
Implementation IR emitted by the native LibTooling frontend.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Sequence
import json
import math
import struct
import subprocess

from .core import AuditError, Diagnostic, SCHEMA_VERSION, load_registry, load_spec, registry_hash

REQUIRED_PRODUCER = "clang-libtooling"
FAIL_CLOSED_CODES = {
    "UNRESOLVED_CALL", "UNRESOLVED_OVERLOAD", "UNKNOWN_IMPLICIT_CAST",
    "UNKNOWN_EFFECT", "UNSUPPORTED_CONTROL_FLOW", "UNRESOLVED_ALIAS_CLASS",
    "MISSING_SOURCE_SPAN", "UNCLASSIFIED_STANDARD_ENTITY",
}


@dataclass(frozen=True)
class PipelineResult:
    status: str
    proof_level: str
    implementation_ir: dict[str, Any]
    canonical_graph: dict[str, Any] | None
    diagnostics: list[dict[str, Any]]
    assumptions: list[str]
    registry_usage: dict[str, Any]


def load_implementation_ir(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AuditError("Implementation IR must be a JSON object")
    return data


def validate_clang_ir(ir: dict[str, Any], *, check_all_effects: bool = True,
                      include_frontend_diagnostics: bool = True) -> list[dict[str, Any]]:
    """Validate schema-critical fields and mandatory Clang provenance."""
    errors: list[dict[str, Any]] = []
    def fail(code: str, message: str, implementation: str = "") -> None:
        errors.append({"code": code, "message": message, "specification": "resolved Clang-derived IR",
                       "implementation": implementation, "source": ir.get("translation_unit", "<ir>")})
    required = {"schema_version", "dependency_graph_version", "standard_version", "source_hash", "function", "producer",
                "translation_unit", "nodes", "dependency_edges", "analysis", "used_standard_entities", "diagnostics"}
    missing = sorted(required - ir.keys())
    if missing: fail("INVALID_IMPLEMENTATION_IR", f"missing fields: {', '.join(missing)}")
    if ir.get("schema_version") != SCHEMA_VERSION: fail("INVALID_IMPLEMENTATION_IR", "unsupported schema version")
    if ir.get("dependency_graph_version") != SCHEMA_VERSION: fail("INVALID_IMPLEMENTATION_IR", "unsupported dependency graph version")
    producer = ir.get("producer", {})
    if producer.get("kind") != REQUIRED_PRODUCER:
        fail("NON_CLANG_PROVENANCE", "complete verification requires clang-libtooling provenance", str(producer.get("kind")))
    if not producer.get("compile_command") or not producer.get("compilation_database"):
        fail("MISSING_COMPILE_COMMAND", "compile_commands.json provenance is mandatory")
    nodes = ir.get("nodes", [])
    if not nodes: fail("INVALID_IMPLEMENTATION_IR", "IR has no nodes")
    for index, node in enumerate(nodes):
        if not node.get("id") or not node.get("kind"):
            fail("INVALID_IMPLEMENTATION_IR", f"node {index} lacks stable identity")
        span = node.get("source_span")
        if not isinstance(span, dict) or not all(span.get(k) is not None for k in ("file", "begin_line", "begin_column", "end_line", "end_column")):
            fail("MISSING_SOURCE_SPAN", f"node {node.get('id', index)} has no complete source span")
        if check_all_effects and node.get("effect") == "Unknown": fail("UNKNOWN_EFFECT", f"node {node.get('id', index)} has unknown effect")
        if node.get("kind") == "ImplicitCast" and not node.get("attributes", {}).get("cast_kind"):
            fail("UNKNOWN_IMPLICIT_CAST", f"node {node.get('id', index)} has unresolved cast")
    node_ids = {node.get("id") for node in nodes}
    for index, edge in enumerate(ir.get("dependency_edges", [])):
        if not edge.get("edge_id") or edge.get("source_node_id") not in node_ids or edge.get("target_node_id") not in node_ids:
            fail("INVALID_DEPENDENCY_GRAPH", f"dependency edge {index} has invalid identity or endpoint")
    if include_frontend_diagnostics:
        for item in ir.get("diagnostics", []):
            errors.append(item if isinstance(item, dict) else {"code": "FRONTEND_ERROR", "message": str(item), "specification": "", "implementation": "", "source": ir.get("translation_unit", "")})
    return errors


def _compact(expression: Any) -> str:
    return "".join(str(expression).split())


def _fact_diagnostics(ir: dict[str, Any], registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    analysis = ir.get("analysis", {})
    source = ir.get("translation_unit", "<ir>")
    diagnostics: list[dict[str, Any]] = []
    def check(condition: bool, code: str, message: str, expected: str, actual: Any) -> None:
        if not condition:
            diagnostics.append({"code": code, "message": message, "specification": expected,
                                "implementation": str(actual), "source": source})
    style = analysis.get("style")
    if "std::reduce" in ir.get("used_standard_entities", []):
        check(False, "REDUCTION_ORDER_MISMATCH",
              "std::reduce permits reordering and cannot refine an ordered fold",
              "left_to_right", "implementation_permitted_reordering")
    check(style in {"explicit_loop", "inner_product"}, "UNSUPPORTED_IMPLEMENTATION", "unsupported implementation shape", "explicit_loop or inner_product", style)
    if analysis.get("unsupported_control_flow"):
        check(False, "UNSUPPORTED_CONTROL_FLOW", "control flow is outside the weighted-sum subset", "two canonical for loops", analysis["unsupported_control_flow"])
    if style == "explicit_loop":
        expected = {
            "outer_index": "r", "outer_bound": "regions", "outer_condition": "<",
            "inner_index": "i", "inner_bound": "inputs", "inner_condition": "<",
            "accumulator_initial": "0.0", "quantity_index": "r*inputs+i",
            "factor_index": "i", "transform_operation": "Multiply",
            "reduction_operation": "Add", "result_index": "r",
        }
        codes = {
            "outer_index": "OUTER_INDEX_MISMATCH", "outer_bound": "OUTER_RANGE_MISMATCH",
            "outer_condition": "OUTER_RANGE_MISMATCH", "inner_index": "INNER_INDEX_MISMATCH",
            "inner_bound": "LOOP_BOUND_MISMATCH", "inner_condition": "LOOP_CONDITION_MISMATCH",
            "accumulator_initial": "INITIAL_VALUE_MISMATCH", "quantity_index": "ROW_MAJOR_INDEX_MISMATCH",
            "factor_index": "FACTOR_INDEX_MISMATCH", "transform_operation": "TRANSFORM_MISMATCH",
            "reduction_operation": "REDUCTION_OPERATION_MISMATCH", "result_index": "OUTPUT_INDEX_MISMATCH",
        }
        for name, wanted in expected.items():
            actual = analysis.get(name)
            equal = _compact(actual) == wanted if name.endswith("_index") or name.endswith("_bound") else str(actual) == wanted
            check(equal, codes[name], f"{name.replace('_', ' ')} mismatch", wanted, actual)
        check(analysis.get("store_position") == "after_inner_loop", "STORE_POSITION_MISMATCH",
              "result store must occur after inner loop", "after_inner_loop", analysis.get("store_position"))
    elif style == "inner_product":
        resolved = analysis.get("resolved_callee")
        check(resolved == "std::inner_product", "WRONG_OVERLOAD", "resolved canonical declaration is not std::inner_product", "std::inner_product", resolved)
        entity = registry.get(str(resolved))
        check(entity is not None, "UNCLASSIFIED_STANDARD_ENTITY", "used standard entity is not classified", "registered canonical declaration", resolved)
        if entity:
            lowering = entity.get("lowering", {})
            check(lowering.get("reduction_order") == "left_to_right", "REDUCTION_ORDER_MISMATCH", "registry reduction order mismatch", "left_to_right", lowering.get("reduction_order"))
        check(_compact(analysis.get("range_begin")) == "first", "ITERATOR_BEGIN_MISMATCH", "iterator begin mismatch", "first", analysis.get("range_begin"))
        check(_compact(analysis.get("range_end")) == "first+inputs", "ITERATOR_RANGE_MISMATCH", "iterator end mismatch", "first + inputs", analysis.get("range_end"))
        check(_compact(analysis.get("factor_begin")) == "factor.begin()", "FACTOR_RANGE_MISMATCH", "factor iterator mismatch", "factor.begin()", analysis.get("factor_begin"))
        check(str(analysis.get("initial_value")) == "0.0", "INITIAL_VALUE_MISMATCH", "initial value mismatch", "0.0", analysis.get("initial_value"))
        check(_compact(analysis.get("row_begin")) == "quantity.begin()+r*inputs", "ROW_MAJOR_INDEX_MISMATCH", "row begin mismatch", "quantity.begin() + r * inputs", analysis.get("row_begin"))
        check(_compact(analysis.get("result_index")) == "r", "OUTPUT_INDEX_MISMATCH", "result index mismatch", "r", analysis.get("result_index"))
    check(analysis.get("alias_class") == "named_contract:non_aliasing_spans", "UNRESOLVED_ALIAS_CLASS",
          "alias class must be resolved by a named contract", "named_contract:non_aliasing_spans", analysis.get("alias_class"))
    if analysis.get("obvious_alias"):
        check(False, "FORBIDDEN_ALIAS", "frontend found obvious input/output alias", "distinct input and output storage", analysis["obvious_alias"])
    return diagnostics


def registry_usage(ir: dict[str, Any], registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    used = sorted(set(ir.get("used_standard_entities", [])))
    classified = [name for name in used if name in registry]
    adapted = [name for name in classified if registry[name].get("lowering")]
    return {"registry_entity_count": len(registry), "used_standard_entity_count": len(used),
            "classified_used_entity_count": len(classified), "semantic_adapter_available_count": len(adapted),
            "unclassified_used_entity_count": len(used) - len(classified),
            "global_coverage": "GLOBAL_COVERAGE_NOT_AVAILABLE", "used_entities": used}


def normalize_clang_ir(ir: dict[str, Any], spec: dict[str, Any], registry_root: str | Path) -> PipelineResult:
    """Normalize only after provenance, fail-closed and semantic checks pass."""
    registry = load_registry(registry_root, ir.get("standard_version", "cpp20"))
    diagnostics = validate_clang_ir(ir) + _fact_diagnostics(ir, registry)
    usage = registry_usage(ir, registry)
    if usage["unclassified_used_entity_count"]:
        diagnostics.append({"code": "UNCLASSIFIED_STANDARD_ENTITY", "message": "one or more used entities are unclassified",
                            "specification": "all used entities classified", "implementation": str(usage["used_entities"]),
                            "source": ir.get("translation_unit", "")})
    if diagnostics:
        return PipelineResult("FAILED", "FAILED", ir, None, diagnostics,
                              ["non_aliasing_spans"], usage)
    analysis = ir["analysis"]
    graph = {"schema_version": SCHEMA_VERSION, "algorithm_id": spec["algorithm_id"],
             "numeric_model": spec["numeric_model"], "provenance": {"implementation_ir_source_hash": ir["source_hash"],
             "frontend": ir["producer"], "function": ir["function"]},
             "nodes": [
                 {"id": "value-quantity", "kind": "Input", "shape": ["region", "input"], "unit": "kg"},
                 {"id": "value-factor", "kind": "Input", "shape": ["input"], "unit": "unit_weight"},
                 {"id": "op-multiply", "kind": "Multiply"},
                 {"id": "op-fold-input", "kind": "TransformReduce", "dimension": "input", "initial": 0.0, "reduction_order": "left_to_right"},
                 {"id": "value-result", "kind": "Output", "shape": ["region"], "unit": "kg_result"}],
             "edges": [
                 {"source": "value-quantity", "target": "op-multiply", "argument_role": "lhs"},
                 {"source": "value-factor", "target": "op-multiply", "argument_role": "rhs"},
                 {"source": "op-multiply", "target": "op-fold-input", "argument_role": "input"},
                 {"source": "op-fold-input", "target": "value-result", "argument_role": "output"}],
             "reduction_order": "left_to_right"}
    assumptions = ["non_aliasing_spans", "valid_input_and_output_ranges", "live_span_storage"]
    return PipelineResult("PASS", "VERIFIED_WITH_CONTRACT_ASSUMPTIONS", ir, graph, [], assumptions, usage)


def audit_ir(spec_path: str | Path, ir_path: str | Path, registry_root: str | Path = "registry/std") -> PipelineResult:
    return normalize_clang_ir(load_implementation_ir(ir_path), load_spec(spec_path), registry_root)


def implementation_ir_interpret(ir: dict[str, Any], quantity: Sequence[Sequence[float]], factor: Sequence[float]) -> list[float]:
    """Execute the validated weighted-sum Implementation IR subset directly."""
    analysis = ir["analysis"]
    initial = float(analysis.get("accumulator_initial", analysis.get("initial_value", 0.0)))
    result: list[float] = []
    for row in quantity:
        acc = initial
        for index in range(len(factor)):
            left, right = float(row[index]), float(factor[index])
            transformed = left * right if analysis.get("transform_operation", "Multiply") == "Multiply" else left + right
            acc = acc + transformed
        result.append(acc)
    return result


def canonical_graph_interpret(graph: dict[str, Any], quantity: Sequence[Sequence[float]], factor: Sequence[float]) -> list[float]:
    """Execute the canonical graph without consulting Implementation IR."""
    kinds = {node["kind"] for node in graph["nodes"]}
    if not {"Multiply", "TransformReduce"}.issubset(kinds) or graph.get("reduction_order") != "left_to_right":
        raise AuditError("unsupported canonical graph")
    return [math.fsum(float(value) * float(factor[i]) for i, value in enumerate(row)) for row in quantity]


def human_reference(quantity: Sequence[Sequence[float]], factor: Sequence[float]) -> list[float]:
    return [sum(float(value) * float(factor[i]) for i, value in enumerate(row)) for row in quantity]


def float_record(actual: float, expected: float) -> dict[str, Any]:
    bits = struct.unpack(">Q", struct.pack(">d", actual))[0]
    absolute = abs(actual - expected)
    relative = absolute / abs(expected) if expected else absolute
    return {"value": actual, "bit_pattern": f"0x{bits:016x}", "absolute_difference": absolute, "relative_difference": relative}


def run_frontend(frontend: str | Path, build_dir: str | Path, source: str | Path,
                 function: str, output: str | Path) -> dict[str, Any]:
    """Run LibTooling with a mandatory compilation database and persist IR."""
    database = Path(build_dir) / "compile_commands.json"
    if not database.is_file(): raise AuditError(f"compile_commands.json not found: {database}")
    command = [str(frontend), "-p", str(build_dir), f"--function={function}", str(source)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise AuditError(f"frontend failed ({completed.returncode}): {completed.stderr.strip()}")
    data = json.loads(completed.stdout)
    Path(output).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data
