"""Mathematical expression extraction, normalization, and transformation selection.

Implementation expressions are produced only from validated Clang LibTooling IR.
The deliberately small initial extractor covers the two weighted-sum shapes that
the native frontend currently emits.  Unknown shapes and dependencies fail closed.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
import json
import re

import yaml

from .core import AuditError, SCHEMA_VERSION, load_registry
from .pipeline import load_implementation_ir, validate_clang_ir
from .dependency import build_dependency_graph, extract_output_slice


EXPRESSION_STATUS = {
    "EXPRESSION_EXTRACTED", "EXPRESSION_PARTIALLY_EXTRACTED",
    "EXPRESSION_EXTRACTION_FAILED", "AMBIGUOUS_INDEX_MAPPING",
    "AMBIGUOUS_FORMULA_PARSE", "UNSUPPORTED_CONTROL_FLOW",
    "UNRESOLVED_NUMERIC_CALL", "NON_NUMERIC_DEPENDENCY_IN_AUDITED_SLICE",
}
COMPARISON_STATUS = {
    "EXACT_CANONICAL_MATCH", "EQUIVALENT_BY_EXACT_TRANSFORMATIONS",
    "EXACT_WITH_ASSUMPTIONS", "ALLOWED_APPROXIMATION_MATCH",
    "APPROXIMATION_METHOD_NOT_ALLOWED", "NO_ALLOWED_APPROXIMATION_FOUND",
    "NO_FEASIBLE_TRANSFORMATION", "TRANSFORMATION_SET_CONFLICT",
    "INCOMPARABLE_CANDIDATES", "SELECTION_TIE_REQUIRES_USER",
}


def _native_expression(action: str, **payload: Any) -> dict[str, Any]:
    """Call the sole production semantic owner; map native errors to the public API."""
    from formulatracer.native import NativeContext
    try:
        with NativeContext() as context:
            return context.execute_kernel({"schema_version": "1.0", "kernel": "F",
                "operation": "LEGACY_EXPRESSION", "action": action, **payload})["result"]
    except Exception as exc:
        raise AuditError(str(exc)) from exc


def _stable_id(kind: str, value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{kind}-{sha256(encoded.encode()).hexdigest()[:16]}"


def _constant(value: int | float | str) -> dict[str, Any]:
    return {"op": "Constant", "value": value}


def _variable(name: str, *, bound: bool = False) -> dict[str, Any]:
    return {"op": "BoundVariable" if bound else "FreeVariable", "name": name}


def _source_correspondence(ir: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = ir.get("nodes", [])
    spans = [{"node_id": node["id"], "source_span": node["source_span"]}
             for node in nodes if node.get("id") and node.get("source_span")]
    analysis = ir.get("analysis", {})
    terms = ["output", "reduction", "transform"]
    return [{"term": term, "implementation_nodes": spans} for term in terms]


class _GraphExpressionBuilder:
    def __init__(self, output_slice: dict[str, Any], function: str):
        self.function = function
        self.nodes = {node["id"]: node for node in output_slice["nodes"]}
        self.incoming: dict[str, list[dict[str, Any]]] = {}
        for edge in output_slice["edges"]:
            self.incoming.setdefault(edge["target_node_id"], []).append(edge)

    def attrs(self, node_id: str) -> dict[str, Any]:
        return self.nodes[node_id].get("attributes", {})

    def semantic(self, node_id: str) -> str:
        return str(self.attrs(node_id).get("semantic_kind", ""))

    def sources(self, node_id: str, *, role: str | None = None,
                kind: str | None = None) -> list[str]:
        return [edge["source_node_id"] for edge in self.incoming.get(node_id, [])
                if (role is None or edge.get("argument_role") == role)
                and (kind is None or edge.get("kind") == kind)]

    def one(self, node_id: str, role: str) -> str:
        values = self.sources(node_id, role=role)
        if len(values) != 1:
            raise AuditError(f"UNRESOLVED_OUTPUT_DEPENDENCY: {node_id} needs one {role} edge")
        return values[0]

    def annotate(self, expression: dict[str, Any], *node_ids: str) -> dict[str, Any]:
        unique = list(dict.fromkeys(node_ids))
        expression["source_node_ids"] = unique
        expression["source_spans"] = [self.nodes[node_id]["source_span"] for node_id in unique]
        return expression

    @staticmethod
    def literal(text: Any) -> int | float | str:
        value = str(text)
        try: return int(value)
        except ValueError: pass
        try: return float(value)
        except ValueError: return value

    def expression(self, node_id: str, bound: set[str] | None = None) -> dict[str, Any]:
        bound = bound or set()
        node, attrs = self.nodes[node_id], self.attrs(node_id)
        semantic, kind = self.semantic(node_id), node.get("kind")
        if semantic == "Literal":
            return self.annotate(_constant(self.literal(attrs.get("value"))), node_id)
        if kind == "DeclRefExpr":
            name = str(attrs.get("name") or node.get("resolved_symbol", ""))
            return self.annotate(_variable(name, bound=name in bound), node_id)
        if semantic in {"LocalVariable", "FunctionParameter"}:
            name = str(attrs.get("name"))
            return self.annotate(_variable(name, bound=name in bound), node_id)
        if semantic == "Cast":
            operand = self.expression(self.one(node_id, "operand"), bound)
            if attrs.get("cast_kind") in {"LValueToRValue", "NoOp", "FunctionToPointerDecay", "ArrayToPointerDecay"}:
                operand.setdefault("source_node_ids", []).append(node_id)
                operand.setdefault("source_spans", []).append(node["source_span"])
                return operand
            return self.annotate({"op": "Cast", "cast_kind": attrs.get("cast_kind"), "expression": operand}, node_id)
        if semantic in {"BinaryOperation", "Comparison"}:
            lhs, rhs = self.expression(self.one(node_id, "lhs"), bound), self.expression(self.one(node_id, "rhs"), bound)
            operator = attrs.get("operator")
            operations = {"+": "Add", "-": "Subtract", "*": "Multiply", "/": "Divide",
                          ">": "GreaterThan", ">=": "GreaterEqual", "<": "LessThan", "<=": "LessEqual",
                          "==": "Equal", "!=": "NotEqual"}
            if operator not in operations: raise AuditError(f"UNRESOLVED_OUTPUT_DEPENDENCY: unsupported operator {operator}")
            if semantic == "Comparison":
                return self.annotate({"op": "Compare", "comparison": operations[operator], "args": [lhs, rhs]}, node_id)
            return self.annotate({"op": operations[operator], "args": [lhs, rhs]}, node_id)
        if semantic == "UnaryOperation":
            operand = self.expression(self.one(node_id, "operand"), bound)
            if attrs.get("operator") != "-": raise AuditError("UNRESOLVED_OUTPUT_DEPENDENCY: unsupported unary operation")
            return self.annotate({"op": "Negate", "args": [operand]}, node_id)
        if semantic in {"Assignment", "Store"}:
            return self.expression(self.one(node_id, "value"), bound)
        symbol = node.get("resolved_symbol") or attrs.get("resolved_symbol")
        if semantic == "Load" and (attrs.get("base") or symbol == "std::span::operator[]"):
            name = str(attrs.get("base") or attrs.get("arg0", "value")).replace("&", "").strip()
            index_sources = self.sources(node_id, role="index") or self.sources(node_id, role="arg1")
            index = self.expression(index_sources[0], bound) if index_sources else self.text_expression(attrs.get("index", attrs.get("arg1")), bound)
            result = {"op": "IndexedValue", "name": name, "indices": [index],
                      "original_index": attrs.get("index", attrs.get("arg1"))}
            return self.annotate(self.restore_flat_index(result, bound), node_id)
        if semantic == "Call":
            if symbol == "std::span::size":
                return self.annotate(_variable("n"), node_id)
            if symbol == "std::span::operator[]":
                name = str(attrs.get("arg0", "value")).replace("&", "").strip()
                indices = self.sources(node_id, role="arg1")
                index = self.expression(indices[0], bound) if indices else self.text_expression(attrs.get("arg1"), bound)
                return self.annotate(self.restore_flat_index({"op": "IndexedValue", "name": name,
                    "indices": [index], "original_index": attrs.get("arg1")}, bound), node_id)
            if symbol in {"std::sqrt", "std::abs"}:
                arg = self.sources(node_id, role="arg0")
                value = self.expression(arg[0], bound) if arg else self.text_expression(attrs.get("arg0"), bound)
                return self.annotate({"op": "FunctionCall", "name": symbol.split("::")[-1], "args": [value]}, node_id)
            if symbol == "cpp.iterator.operator+":
                return self.annotate({"op": "Add", "args": [self.expression(self.one(node_id, "arg0"), bound),
                                                               self.expression(self.one(node_id, "arg1"), bound)]}, node_id)
        if semantic == "FunctionValue":
            return self.expression(self.one(node_id, "body"), bound)
        raise AuditError(f"UNRESOLVED_OUTPUT_DEPENDENCY: unsupported slice node {kind}/{semantic}/{symbol}")

    def text_expression(self, text: Any, bound: set[str]) -> dict[str, Any]:
        value = str(text).strip()
        if value in bound: return _variable(value, bound=True)
        parsed = self.literal(value)
        return _constant(parsed) if not isinstance(parsed, str) else _variable(value)

    @staticmethod
    def restore_flat_index(value: dict[str, Any], bound: set[str]) -> dict[str, Any]:
        index = value.get("indices", [{}])[0]
        if index.get("op") != "Add" or len(index.get("args", [])) != 2: return value
        product, tail = index["args"]
        if product.get("op") != "Multiply" or tail.get("op") != "BoundVariable": return value
        row = product.get("args", [{}])[0]
        if row.get("op") not in {"FreeVariable", "BoundVariable"}: return value
        value["indices"] = [row, tail]
        return value

    def guards(self, node_id: str, semantic: str) -> list[str]:
        return [source for source in self.sources(node_id, kind="CONTROL_GUARDS") if self.semantic(source) == semantic]

    def has_side_effect(self, node_id: str, seen: set[str] | None = None) -> bool:
        seen = seen or set()
        if node_id in seen: return False
        seen.add(node_id)
        if self.nodes[node_id].get("effect") not in {"Pure", "ReadMemory"}: return True
        return any(self.has_side_effect(source, seen) for source in self.sources(node_id))

    def loop_domain(self, loop_id: str) -> tuple[str, dict[str, Any]]:
        attrs = self.attrs(loop_id)
        index = str(attrs.get("index"))
        lower_sources, upper_sources = self.sources(loop_id, role="lower"), self.sources(loop_id, role="upper")
        lower = self.expression(lower_sources[0], {index}) if len(lower_sources) == 1 else self.text_expression(attrs.get("lower", 0), {index})
        upper = self.expression(upper_sources[0], {index}) if len(upper_sources) == 1 else self.text_expression(attrs.get("upper"), {index})
        return index, {"lower": lower, "upper_exclusive": upper}

    def store_target(self, store_id: str, bound: set[str]) -> dict[str, Any]:
        attrs = self.attrs(store_id)
        return self.annotate({"op": "IndexedValue", "name": str(attrs.get("output_base")),
                              "indices": [self.text_expression(attrs.get("output_index"), bound)]}, store_id)

    def local_decl(self, load_id: str) -> str | None:
        for source in self.sources(load_id, kind="READS"):
            if self.semantic(source) == "LocalVariable": return source
        return None

    def definitions(self, decl_id: str) -> tuple[str | None, str | None]:
        initial = assignment = None
        for edge in self.incoming.get(decl_id, []):
            source = edge["source_node_id"]
            if edge.get("kind") != "DEFINES": continue
            if self.semantic(source) == "Assignment": assignment = source
            elif edge.get("argument_role") == "initial_value": initial = source
        return initial, assignment

    def fold_from_call(self, call_id: str, bound_index: str = "i") -> dict[str, Any]:
        attrs = self.attrs(call_id)
        symbol = self.nodes[call_id].get("resolved_symbol")
        begin, end = str(attrs.get("arg0", "values.begin()")), str(attrs.get("arg1", "values.end()"))
        name = begin.split(".")[0].replace("&", "").strip()
        upper_match = re.search(r"\+\s*([A-Za-z_]\w*)", end)
        upper = upper_match.group(1) if upper_match else f"{name}.size"
        initial_sources = self.sources(call_id, role="arg2" if symbol == "std::accumulate" else "arg3")
        initial = self.expression(initial_sources[0]) if initial_sources else _constant(self.literal(attrs.get("arg2" if symbol == "std::accumulate" else "arg3", 0)))
        operation = "Multiply" if "multipl" in str(attrs.get("arg3", "")).lower() or "*" in str(attrs.get("arg3", "")) else "Add"
        body = {"op": "IndexedValue", "name": name, "indices": [_variable(bound_index, bound=True)]}
        if symbol == "std::inner_product":
            row_match = re.search(r"([A-Za-z_]\w*)\.begin\(\)\s*\+\s*([A-Za-z_]\w*)\s*\*\s*([A-Za-z_]\w*)",
                                  " ".join(str(self.attrs(node).get("initializer_text", "")) for node in self.nodes))
            factor = str(attrs.get("arg2", "factor.begin()")).split(".")[0]
            quantity, row, upper = row_match.groups() if row_match else ("quantity", "r", upper)
            body = {"op": "Multiply", "args": [
                {"op": "IndexedValue", "name": quantity, "indices": [_variable(row), _variable(bound_index, bound=True)]},
                {"op": "IndexedValue", "name": factor, "indices": [_variable(bound_index, bound=True)]}]}
            return self.annotate({"op": "TransformReduce", "bound_index": bound_index,
                "index_domain": {"lower": _constant(0), "upper_exclusive": _variable(upper)},
                "initial_value": initial, "transform": body, "reduction": "Add",
                "reduction_order": "left_to_right"}, call_id)
        return self.annotate({"op": "FoldLeft", "bound_index": bound_index,
            "index_domain": {"lower": _constant(0), "upper_exclusive": _variable(upper)},
            "initial_value": initial, "operation": operation, "body": body,
            "reduction_order": "left_to_right"}, call_id)

    def extract(self, roots: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        # std::transform is itself an output-producing call.
        if len(roots) == 1 and (self.nodes[roots[0]].get("resolved_symbol") == "std::transform"):
            root, attrs = roots[0], self.attrs(roots[0]); index = "i"
            source = str(attrs.get("arg0", "x.begin()")).split(".")[0]
            target_name = str(attrs.get("arg2", "y.begin()")).split(".")[0]
            upper_match = re.search(r"\+\s*([A-Za-z_]\w*)", str(attrs.get("arg1", "")))
            upper = upper_match.group(1) if upper_match else f"{source}.size"
            lambda_sources = self.sources(root, role="arg3")
            body = self.expression(lambda_sources[0], {index}) if lambda_sources else _variable("unsupported_transform_body")
            parameter = re.search(r"\b(?:double|float|auto)\s+([A-Za-z_]\w*)", str(attrs.get("arg3", "")))
            body = _substitute_free(body, parameter.group(1) if parameter else "v",
                                    {"op": "IndexedValue", "name": source, "indices": [_variable(index, bound=True)]})
            mapping = self.annotate({"op": "Map", "bound_index": index,
                "index_domain": {"lower": _constant(0), "upper_exclusive": _variable(upper)},
                "output": {"op": "IndexedValue", "name": target_name, "indices": [_variable(index, bound=True)]},
                "body": body}, root)
            return [{"target": mapping["output"], "expression": mapping}], ["MAP_EXTRACTED"]

        stores = [root for root in roots if self.semantic(root) == "Store"]
        returns = [root for root in roots if self.semantic(root) == "Return"]
        if returns and stores: raise AuditError("AMBIGUOUS_OUTPUT_LOCATION")
        if returns:
            root = returns[0]; value_id = self.one(root, "return_value")
            while self.semantic(value_id) == "Cast": value_id = self.one(value_id, "operand")
            if self.nodes[value_id].get("resolved_symbol") == "std::accumulate":
                return [{"target": _variable(self.function), "expression": self.fold_from_call(value_id)}], ["FOLD_LEFT_EXTRACTED"]
            decl = self.local_decl(value_id)
            if decl:
                initial_id, assignment = self.definitions(decl)
                if assignment:
                    loops = self.guards(assignment, "Loop")
                    if len(loops) != 1: raise AuditError("UNRESOLVED_OUTPUT_DEPENDENCY: FoldLeft needs one Loop")
                    index, domain = self.loop_domain(loops[0])
                    body = self.expression(self.one(assignment, "value"), {index})
                    initial = self.expression(initial_id) if initial_id else _constant(0)
                    operation = "Add" if self.attrs(assignment).get("operator") in {"+=", "="} else "Multiply"
                    accumulator_name = str(self.attrs(decl).get("name"))
                    if self.attrs(assignment).get("operator") == "=" and body.get("op") in {"Add", "Multiply"}:
                        args = body.get("args", [])
                        if len(args) == 2 and args[0].get("op") == "FreeVariable" and args[0].get("name") == accumulator_name:
                            operation, body = body["op"], args[1]
                    fold = self.annotate({"op": "FoldLeft", "bound_index": index, "index_domain": domain,
                        "initial_value": initial, "operation": operation, "body": body,
                        "reduction_order": "left_to_right"}, loops[0], assignment, decl)
                    return [{"target": _variable(self.function), "expression": fold}], ["FOLD_LEFT_EXTRACTED"]
            return [{"target": _variable(self.function), "expression": self.expression(value_id)}], ["EXPRESSION_EXTRACTED"]

        if not stores: raise AuditError("UNRESOLVED_OUTPUT_DEPENDENCY: no supported output")
        conditionals = {conditional for store in stores for conditional in self.guards(store, "Conditional")}
        loops = {loop for store in stores for loop in self.guards(store, "Loop")}
        if len(loops) != 1: raise AuditError("UNRESOLVED_OUTPUT_DEPENDENCY: Map output needs one direct Loop")
        loop = next(iter(loops)); index, domain = self.loop_domain(loop); bound = {index}
        if conditionals:
            if len(conditionals) != 1: raise AuditError("UNSUPPORTED_BRANCH_MERGE")
            conditional = next(iter(conditionals))
            branches = {edge.get("argument_role"): edge["target_node_id"] for edge in self.nodes_to_edges(conditional, stores)}
            if set(branches) != {"true_branch", "false_branch"}: raise AuditError("UNSUPPORTED_BRANCH_MERGE")
            true_store, false_store = branches["true_branch"], branches["false_branch"]
            if self.attrs(true_store).get("output_index") != self.attrs(false_store).get("output_index"):
                raise AuditError("UNSUPPORTED_BRANCH_MERGE")
            condition_id = self.one(conditional, "condition")
            if self.has_side_effect(condition_id): raise AuditError("SIDE_EFFECTING_CONDITION")
            body = self.annotate({"op": "IfThenElse", "condition": self.expression(condition_id, bound),
                                  "then": self.expression(true_store, bound),
                                  "else": self.expression(false_store, bound)}, conditional, true_store, false_store)
            store = true_store; statuses = ["MAP_EXTRACTED", "IF_THEN_ELSE_EXTRACTED"]
        else:
            if len(stores) != 1: raise AuditError("UNSUPPORTED_BRANCH_MERGE")
            store = stores[0]
            value_id = self.one(store, "value")
            if self.semantic(value_id) in {"Assignment", "Store"}:
                raise AuditError("MAP_BODY_UNSUPPORTED_MUTATION")
            while self.semantic(value_id) == "Cast": value_id = self.one(value_id, "operand")
            symbol = self.nodes[value_id].get("resolved_symbol")
            if symbol == "std::inner_product":
                fold = self.fold_from_call(value_id, "i")
                return [{"target": self.store_target(store, set()), "index_domain": {"index": index, **domain},
                         "expression": fold}], ["TRANSFORM_REDUCE_EXTRACTED"]
            decl = self.local_decl(value_id)
            if decl:
                initial_id, assignment = self.definitions(decl)
                if assignment:
                    inner = [item for item in self.guards(assignment, "Loop") if item != loop]
                    if len(inner) == 1:
                        inner_index, inner_domain = self.loop_domain(inner[0])
                        transform = self.expression(self.one(assignment, "value"), {inner_index})
                        initial = self.expression(initial_id) if initial_id else _constant(0)
                        fold = self.annotate({"op": "TransformReduce", "bound_index": inner_index,
                            "index_domain": inner_domain, "initial_value": initial, "transform": transform,
                            "reduction": "Add", "reduction_order": "left_to_right"}, inner[0], assignment, decl)
                        return [{"target": self.store_target(store, set()), "index_domain": {"index": index, **domain},
                                 "expression": fold}], ["TRANSFORM_REDUCE_EXTRACTED"]
            body = self.expression(store, bound); statuses = ["MAP_EXTRACTED"]
        target = self.store_target(store, bound)
        mapping = self.annotate({"op": "Map", "bound_index": index, "index_domain": domain,
                                 "output": target, "body": body}, loop, store)
        return [{"target": target, "index_domain": {"index": index, **domain}, "expression": mapping}], statuses

    def nodes_to_edges(self, source: str, targets: list[str]) -> list[dict[str, Any]]:
        target_set = set(targets)
        return [edge for target in targets for edge in self.incoming.get(target, [])
                if edge.get("source_node_id") == source and edge.get("target_node_id") in target_set]


def _substitute_free(node: Any, name: str, replacement: dict[str, Any]) -> Any:
    if isinstance(node, list): return [_substitute_free(item, name, replacement) for item in node]
    if not isinstance(node, dict): return node
    if node.get("op") == "FreeVariable" and node.get("name") == name: return deepcopy(replacement)
    return {key: _substitute_free(value, name, replacement) for key, value in node.items()}


def _expression_correspondence(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node: visit(item)
        elif isinstance(node, dict):
            if node.get("op") and node.get("source_node_ids"):
                result.append({"term": node["op"], "implementation_node_ids": node["source_node_ids"],
                               "source_spans": node.get("source_spans", [])})
            for value in node.values(): visit(value)
    visit(outputs)
    return result


def extract_expression(ir: dict[str, Any], registry_root: str | Path = "registry/std") -> dict[str, Any]:
    """Build, validate, and slice the explicit graph before recognizing math."""
    diagnostics = validate_clang_ir(ir, check_all_effects=False, include_frontend_diagnostics=False)
    if diagnostics:
        return {"schema_version": SCHEMA_VERSION, "status": "EXPRESSION_EXTRACTION_FAILED",
                "diagnostics": diagnostics, "outputs": [], "source_correspondence": []}
    graph = build_dependency_graph(ir)
    output_slice = extract_output_slice(graph)
    if output_slice["status"] != "OUTPUT_SLICE_EXTRACTED":
        return {"schema_version": SCHEMA_VERSION, "status": "EXPRESSION_EXTRACTION_FAILED",
                "diagnostics": output_slice["diagnostics"], "outputs": [], "source_correspondence": [],
                "dependency_graph": graph, "output_slice": output_slice}
    reached = set(output_slice["node_ids"])
    relevant_frontend = [item if isinstance(item, dict) else {"code": "FRONTEND_ERROR", "message": str(item)}
                         for item in ir.get("diagnostics", [])
                         if not isinstance(item, dict) or not item.get("node_id") or item.get("node_id") in reached]
    if relevant_frontend:
        return {"schema_version": SCHEMA_VERSION, "status": "EXPRESSION_EXTRACTION_FAILED",
                "diagnostics": relevant_frontend, "outputs": [], "source_correspondence": [],
                "dependency_graph": graph, "output_slice": output_slice}
    registry = load_registry(registry_root, ir.get("standard_version", "cpp20"))
    used_lowerings: dict[str, Any] = {}
    unresolved_calls: list[str] = []
    for node in output_slice["nodes"]:
        symbol = node.get("resolved_symbol") or node.get("attributes", {}).get("resolved_symbol")
        if not isinstance(symbol, str) or not symbol.startswith("std::"): continue
        entry = registry.get(symbol)
        if not entry or not entry.get("lowering"): unresolved_calls.append(symbol)
        else: used_lowerings[symbol] = entry["lowering"]
    if unresolved_calls:
        return {"schema_version": SCHEMA_VERSION, "status": "EXPRESSION_EXTRACTION_FAILED",
                "diagnostics": [{"code": "UNRESOLVED_NUMERIC_CALL",
                                 "message": "registered lowering is required", "symbols": sorted(set(unresolved_calls))}],
                "outputs": [], "source_correspondence": [], "dependency_graph": graph, "output_slice": output_slice}
    try:
        outputs, extraction_statuses = _GraphExpressionBuilder(output_slice, ir["function"]).extract(output_slice["output_node_ids"])
    except AuditError as exc:
        message = str(exc); code = message.split(":", 1)[0] if message.split(":", 1)[0].isupper() else "UNRESOLVED_OUTPUT_DEPENDENCY"
        return {"schema_version": SCHEMA_VERSION, "status": "EXPRESSION_EXTRACTION_FAILED",
                "diagnostics": [{"code": code, "message": message}], "outputs": [],
                "source_correspondence": [], "dependency_graph": graph, "output_slice": output_slice}
    payload = {"schema_version": SCHEMA_VERSION, "status": "EXPRESSION_EXTRACTED",
               "extraction_statuses": ["DEPENDENCY_GRAPH_BUILT", "OUTPUT_SLICE_EXTRACTED", *extraction_statuses],
               "numeric_domain": {"category": "binary_floating_point", "radix": 2,
                                  "precision": 53, "rounding": "implementation_environment",
                                  "supports_nan": True, "supports_infinity": True,
                                  "supports_signed_zero": True},
               "outputs": outputs, "source_correspondence": _expression_correspondence(outputs),
               "dependency_graph": graph, "output_slice": output_slice,
               "registry_lowerings": used_lowerings,
               "provenance": {"implementation_ir_source_hash": ir["source_hash"],
                              "function": ir["function"], "producer": ir["producer"]}, "diagnostics": []}
    payload["expression_id"] = _stable_id("expression", outputs)
    return payload


def load_formula(path: str | Path) -> dict[str, Any]:
    """Parse the authoritative structured YAML/JSON formula representation."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise AuditError(f"AMBIGUOUS_FORMULA_PARSE: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise AuditError("AMBIGUOUS_FORMULA_PARSE: formula must be a versioned mapping")
    formula = data.get("formula")
    if not isinstance(formula, dict) or not isinstance(formula.get("outputs"), list) or not formula["outputs"]:
        raise AuditError("AMBIGUOUS_FORMULA_PARSE: formula.outputs must be a non-empty list")
    for output in formula["outputs"]:
        if not isinstance(output, dict) or not isinstance(output.get("target"), dict) or not isinstance(output.get("expression"), dict):
            raise AuditError("AMBIGUOUS_FORMULA_PARSE: each output needs target and expression objects")
    result = {"schema_version": SCHEMA_VERSION, "status": "EXPRESSION_EXTRACTED",
              "outputs": deepcopy(formula["outputs"]), "assumptions": data.get("assumptions", []),
              "numeric_domain": data.get("numeric_domain", {"category": "exact_real"}),
              "source_correspondence": [], "diagnostics": []}
    result["expression_id"] = _stable_id("human-expression", result["outputs"])
    return result


def _rename_bound(node: Any, old: str, new: str) -> Any:
    if isinstance(node, list):
        return [_rename_bound(item, old, new) for item in node]
    if not isinstance(node, dict):
        return node
    result = {key: _rename_bound(value, old, new) for key, value in node.items()}
    if result.get("op") == "BoundVariable" and result.get("name") == old:
        result["name"] = new
    return result


def _normalize_node(node: Any, trace: list[dict[str, Any]], depth: int = 0) -> Any:
    if isinstance(node, list):
        return [_normalize_node(item, trace, depth) for item in node]
    if not isinstance(node, dict):
        return node
    current = {key: _normalize_node(value, trace, depth) for key, value in node.items()
               if key not in {"original_index", "source_node_ids", "source_spans", "source_span",
                              "operator_span", "callable_span", "argument_spans", "keyword_spans", "condition_span"}}
    op = current.get("op")
    if op in {"FiniteSum", "TransformReduce", "FoldLeft", "Map", "Scan"} and current.get("bound_index"):
        old, new = str(current["bound_index"]), f"_i{depth}"
        if old != new:
            current = _rename_bound(current, old, new)
            current["bound_index"] = new
            trace.append({"rule_id": "alpha_rename", "before": old, "after": new})
        depth += 1
    if op == "TransformReduce" and current.get("reduction") == "Add" and current.get("reduction_order") == "left_to_right":
        finite = {"op": "FiniteSum", "bound_index": current["bound_index"],
                  "index_domain": current["index_domain"], "body": current["transform"],
                  "reduction_order": "left_to_right"}
        initial = current.get("initial_value")
        if initial == _constant(0) or initial == _constant(0.0):
            trace.append({"rule_id": "finite_sum_normalization", "kind": "exact"})
            current = finite
        else:
            current = {"op": "Add", "args": [initial, finite]}
            trace.append({"rule_id": "finite_sum_normalization", "kind": "exact"})
    if current.get("op") in {"Add", "Multiply"} and isinstance(current.get("args"), list):
        identity = 0 if current["op"] == "Add" else 1
        args = [arg for arg in current["args"] if arg != _constant(identity) and arg != _constant(float(identity))]
        if len(args) != len(current["args"]):
            trace.append({"rule_id": "neutral_element_elimination", "kind": "exact"})
        if len(args) == 1:
            current = args[0]
        else:
            current["args"] = args
    return current


def normalize_exact(expression: dict[str, Any]) -> dict[str, Any]:
    return _native_expression("NORMALIZE_EXACT", expression=expression)


def compare_exact(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return _native_expression("COMPARE_EXACT", left=left, right=right)


def load_transformation_rule(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rule = data.get("rule") if isinstance(data, dict) else None
    required = {"id", "kind", "source_pattern", "target_template"}
    if not isinstance(rule, dict) or required - rule.keys() or rule["kind"] not in {"exact", "exact_under_assumptions", "approximation"}:
        raise AuditError(f"invalid TransformationRule: {path}")
    # 0.1 migration: these numbers were selection heuristics, never proved
    # mathematical error bounds.  Keep old registries loadable without
    # promoting the metadata to proof-grade evidence.
    if rule.get("kind") == "approximation" and "error_bound" in rule:
        rule.setdefault("selection_error_estimate", rule.pop("error_bound"))
        rule.setdefault("proof_status", "UNPROVEN_SELECTION_METADATA")
    return rule


def load_transformation_set(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    item = data.get("transformation_set") if isinstance(data, dict) else None
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(item, dict):
        raise AuditError(f"invalid TransformationSet: {path}")
    required = {"id", "version", "exact_rules", "approximation_rules", "hard_constraints",
                "objectives", "selection_policy", "provenance"}
    if required - item.keys():
        raise AuditError(f"TransformationSet missing: {', '.join(sorted(required - item.keys()))}")
    conflict = set(item.get("approximation_rules", [])) & set(item.get("forbidden_rules", []))
    if conflict:
        raise AuditError("TRANSFORMATION_SET_CONFLICT: " + ", ".join(sorted(conflict)))
    return item


@dataclass(frozen=True)
class Candidate:
    rule_id: str
    feasible: bool
    rejection_reasons: list[str] = field(default_factory=list)
    observables: list[str] = field(default_factory=list)
    cost: dict[str, Any] = field(default_factory=dict)
    selection_error_estimate: float | None = None


def select_transformation(transformation_set: dict[str, Any], rules: Iterable[dict[str, Any]],
                          required_observables: Iterable[str] = (),
                          selection_profile: str = "minimum_cost") -> dict[str, Any]:
    """Filter and rank through the native semantic kernel."""
    return _native_expression("SELECT_TRANSFORMATION", transformation_set=transformation_set,
                              rules=list(rules), required_observables=list(required_observables),
                              selection_profile=selection_profile)


def _render_node(node: Any, latex: bool) -> str:
    if not isinstance(node, dict): return str(node)
    op = node.get("op")
    if op == "Constant": return str(node.get("value"))
    if op in {"FreeVariable", "BoundVariable"}: return str(node.get("name"))
    if op == "IndexedValue":
        indices = ",".join(_render_node(x, latex) for x in node.get("indices", []))
        return f"{node.get('name')}_{{{indices}}}" if latex else f"{node.get('name')}[{indices}]"
    if op in {"Add", "Subtract", "Multiply", "Divide", "FloorDivide", "Modulo", "Power",
              "BitAnd", "BitOr", "BitXor", "ShiftLeft", "ShiftRight", "LogicalAnd", "LogicalOr"}:
        symbols = {"Add": "+", "Subtract": "-", "Multiply": r"\," if latex else " ×",
                   "Divide": "/", "FloorDivide": "//", "Modulo": r"\bmod" if latex else "mod",
                   "Power": "^", "BitAnd": r"\mathbin{\&}" if latex else "&",
                   "BitOr": "|", "BitXor": r"\oplus" if latex else "xor",
                   "ShiftLeft": r"\ll" if latex else "<<", "ShiftRight": r"\gg" if latex else ">>",
                   "LogicalAnd": r"\land" if latex else "and", "LogicalOr": r"\lor" if latex else "or"}
        return f" {symbols[op]} ".join(_render_node(x, latex) for x in node.get("args", []))
    if op == "Negate": return "-" + _render_node(node.get("args", [node.get("expression")])[0], latex)
    if op in {"BitNot", "LogicalNot"}:
        name = "bitnot" if op == "BitNot" else "not"
        return rf"\operatorname{{{name}}}({_render_node(node['args'][0], latex)})" if latex else f"{name}({_render_node(node['args'][0], latex)})"
    if op == "Compare":
        symbols = {"GreaterThan": ">", "GreaterEqual": r"\ge" if latex else "≥",
                   "LessThan": "<", "LessEqual": r"\le" if latex else "≤", "Equal": "=", "NotEqual": r"\ne" if latex else "≠"}
        return f"{_render_node(node['args'][0], latex)} {symbols.get(node.get('comparison'), '?')} {_render_node(node['args'][1], latex)}"
    if op == "Cast": return _render_node(node.get("expression") or (node.get("args") or [{}])[0], latex)
    if op == "IfThenElse":
        condition = _render_node(node["condition"], latex)
        yes, no = _render_node(node["then"], latex), _render_node(node["else"], latex)
        if latex: return rf"\begin{{cases}} {yes}, & {condition} \\ {no}, & \text{{otherwise}} \end{{cases}}"
        return f"{{ {yes} if {condition}; {no} otherwise }}"
    if op == "Predicate": return _render_node(node.get("expression"), latex)
    if op == "Select":
        condition_node = node["condition"].get("expression", node["condition"])
        condition = _render_node(condition_node, latex)
        yes, no = _render_node(node["then"], latex), _render_node(node["else"], latex)
        if latex: return rf"\begin{{cases}} {yes}, & {condition} \\ {no}, & \text{{otherwise}} \end{{cases}}"
        return f"Select({condition}; {yes}; {no})"
    if op in {"Indicator", "Minimum", "Maximum", "Clamp", "RotateLeft", "RotateRight",
              "BitFieldExtract", "BitFieldInsert", "PopCount", "LeadingZeros", "TrailingZeros",
              "BitTest", "RealPart", "ImagPart", "Conjugate", "Argument", "Magnitude",
              "Quotient", "DivMod", "EncodeBits", "DecodeBits"}:
        args = node.get("args", [])
        if op == "Indicator": args = [node.get("predicate")]
        elif not args and "value" in node: args = [node.get("value")]
        rendered = ",".join(_render_node(item, latex) for item in args)
        return rf"\operatorname{{{op}}}({rendered})" if latex else f"{op}({rendered})"
    if op == "Filter":
        source = _render_node(node.get("iterable"), latex); predicate = _render_node(node.get("predicate"), latex)
        return (rf"\operatorname{{Filter}}_{{{node.get('bound_index')}}}({source};{predicate})" if latex
                else f"Filter({node.get('bound_index')} in {source}; {predicate})")
    if op == "Map" and "iterable" in node:
        source, body = _render_node(node.get("iterable"), latex), _render_node(node.get("body"), latex)
        return (rf"\operatorname{{Map}}_{{{node.get('bound_index')}}}({source};{body})" if latex
                else f"Map({node.get('bound_index')} in {source}; {body})")
    if op == "IndexedStateUpdate":
        indices = ",".join(_render_node(x, latex) for x in node.get("indices", []))
        value = _render_node(node.get("value"), latex)
        return (rf"\operatorname{{Update}}({node.get('target')},[{indices}],{value})" if latex
                else f"IndexedStateUpdate({node.get('target')}[{indices}] := {value})")
    if op in {"AttributeStateUpdate", "SequenceStateUpdate"}:
        return f"{op}({node.get('target', node.get('kind'))}; {_render_node(node.get('value'), latex)})"
    if op == "LoopInvocation": return f"LoopInvocation[{node.get('kind')}]({node.get('termination_status', 'preserved')})"
    if op == "ExceptionChoice":
        choices = [_render_node(node.get("try"), latex)] + [_render_node(x, latex) for x in node.get("handlers", [])]
        return f"ExceptionChoice({'; '.join(choices)})"
    if op == "FiniteSum":
        domain, index = node["index_domain"], node["bound_index"]
        lower, upper = _render_node(domain["lower"], latex), _render_node(domain["upper_exclusive"], latex)
        body = _render_node(node["body"], latex)
        return (rf"\sum_{{{index}={lower}}}^{{{upper}-1}} {body}" if latex
                else f"Σ({index}={lower}..{upper}-1) {body}")
    if op == "FiniteProduct":
        domain, index = node["index_domain"], node["bound_index"]
        lower, upper = _render_node(domain["lower"], latex), _render_node(domain["upper_exclusive"], latex)
        body = _render_node(node["body"], latex)
        return (rf"\prod_{{{index}={lower}}}^{{{upper}-1}} {body}" if latex
                else f"Π({index}={lower}..{upper}-1) {body}")
    if op == "TransformReduce":
        domain, index = node["index_domain"], node["bound_index"]
        lower, upper = _render_node(domain["lower"], latex), _render_node(domain["upper_exclusive"], latex)
        body, initial = _render_node(node["transform"], latex), _render_node(node["initial_value"], latex)
        folded = (rf"\sum_{{{index}={lower}}}^{{{upper}-1}} {body}" if latex
                  else f"Σ({index}={lower}..{upper}-1) {body}")
        return folded if initial in {"0", "0.0"} else f"{initial} + {folded}"
    if op == "FoldLeft":
        if "index_domain" not in node:
            source, body = _render_node(node.get("iterable"), latex), _render_node(node.get("body"), latex)
            return (rf"\operatorname{{Fold}}_{{{node.get('bound_index')}}}({source};{body})" if latex
                    else f"FoldLeft({node.get('bound_index')} in {source}; {body})")
        domain, index = node["index_domain"], node["bound_index"]
        lower, upper = _render_node(domain["lower"], latex), _render_node(domain["upper_exclusive"], latex)
        body, initial = _render_node(node["body"], latex), _render_node(node["initial_value"], latex)
        if node.get("operation") == "Add":
            folded = (rf"\sum_{{{index}={lower}}}^{{{upper}-1}} {body}" if latex else f"Σ({index}={lower}..{upper}-1) {body}")
            return folded if initial in {"0", "0.0"} else f"{initial} + {folded}"
        folded = (rf"\prod_{{{index}={lower}}}^{{{upper}-1}} {body}" if latex else f"Π({index}={lower}..{upper}-1) {body}")
        return folded if initial in {"1", "1.0"} else f"{initial} × {folded}"
    if op == "Derivative":
        return (rf"\frac{{d}}{{d{node['variable']}}} {_render_node(node['expression'], latex)}" if latex
                else f"d/d{node['variable']} {_render_node(node['expression'], latex)}")
    if op == "Integral":
        body = _render_node(node.get("expression", {}), latex)
        domain = node.get("domain", {})
        lower, upper = _render_node(domain.get("lower", {}), latex), _render_node(domain.get("upper", {}), latex)
        variable = node.get("variable", "x")
        return (rf"\int_{{{lower}}}^{{{upper}}} {body}\,d{variable}" if latex
                else f"Integral[{lower}..{upper}] {body} d{variable}")
    if op == "Quadrature":
        method = str(node.get("method", "quadrature"))
        return (rf"\operatorname{{{method}}}_{{{_render_node(node.get('partition'), latex)}}}({_render_node(node.get('step_size'), latex)})"
                if latex else f"{method}[partition={_render_node(node.get('partition'), latex)}, h={_render_node(node.get('step_size'), latex)}]")
    if op in {"Interpolation", "Extrapolation"}:
        method = str(node.get("method", op.lower()))
        query = _render_node(node.get("query_point", {}), latex)
        return (rf"\operatorname{{{method}}}({query})" if latex else f"{method}({query})")
    if op == "DiscreteDifference":
        source = _render_node(node.get("input", {}), latex)
        axis = node.get("dimension", node.get("axis", "?"))
        return (rf"\Delta_{{{axis}}} {source}" if latex else f"DiscreteDifference[{axis}]({source})")
    if op == "FunctionCall":
        return f"{node['name']}({', '.join(_render_node(x, latex) for x in node.get('args', []))})"
    if op == "OpaqueNumericCall":
        return f"OpaqueNumericCall[{node.get('name', '?')}]({', '.join(_render_node(x, latex) for x in node.get('args', []))})"
    if op == "Reduce":
        axis = node.get("dimensions", node.get("axes", "all"))
        return f"{node.get('reduction', 'Reduce')}[{axis}]({_render_node(node.get('input'), latex)})"
    if op == "TensorContraction":
        return f"{node.get('kind', 'contract')}({', '.join(_render_node(x, latex) for x in node.get('args', []))})"
    if op == "Distribution":
        return f"{node.get('name', 'distribution')}({', '.join(_render_node(x, latex) for x in node.get('positional_parameters', []))})"
    if op == "RandomSample":
        return f"Sample[{_render_node(node.get('distribution', {}), latex)}; shape={node.get('shape', '?')}]"
    return f"{node.get('name', op)}({', '.join(_render_node(x, latex) for x in node.get('args', []))})"


def render_expression(expression: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(expression, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if output_format not in {"latex", "unicode", "markdown"}:
        raise AuditError(f"unsupported expression format: {output_format}")
    latex = output_format == "latex"
    equations = []
    for output in expression["outputs"]:
        value = output["expression"]
        if value.get("op") == "Map" and "index_domain" in value:
            domain, index = value["index_domain"], value["bound_index"]
            lower, upper = _render_node(domain["lower"], latex), _render_node(domain["upper_exclusive"], latex)
            constraint = (rf",\quad {lower}\le {index}<{upper}" if latex else f", {lower} ≤ {index} < {upper}")
            equations.append(f"{_render_node(value['output'], latex)} = {_render_node(value['body'], latex)}{constraint}")
        else:
            equations.append(f"{_render_node(output['target'], latex)} = {_render_node(value, latex)}")
    if output_format == "markdown":
        return "# Extracted expression\n\n```text\n" + "\n".join(equations) + "\n```\n"
    return "\n".join(equations) + "\n"


def expression_report(implementation: dict[str, Any], human: dict[str, Any], comparison: dict[str, Any],
                      transformation_set: dict[str, Any] | None = None,
                      selection: dict[str, Any] | None = None) -> str:
    lines = ["# Expression audit report", "", f"Status: **{comparison['status']}**", "",
             "## Extracted implementation formula", "", "```text",
             render_expression(implementation, "unicode").strip(), "```", "",
             "## Parsed human formula", "", "```text", render_expression(human, "unicode").strip(), "```", "",
             "## Exact canonical formulas", "", "```json",
             json.dumps({"implementation": comparison["implementation"], "human": comparison["human"]},
                        indent=2, sort_keys=True, ensure_ascii=False), "```", "",
             "## Selected TransformationSet", "",
             f"`{transformation_set['id']}@{transformation_set['version']}`" if transformation_set else "None", "",
             "## Approximation selection", "", "```json", json.dumps(selection or {"status": "not_requested"},
                        indent=2, sort_keys=True, ensure_ascii=False), "```", "",
             "## Numeric representation", "", f"`{implementation.get('numeric_domain', {})}`", "",
             "## Source correspondence", "", "```json",
             json.dumps(implementation.get("source_correspondence", []), indent=2, ensure_ascii=False), "```", "",
             "## Remaining obligations", "", "- Clang/compiler/standard-library contracts remain in the trust boundary.",
             "- IEEE-754 error bounds are not proven by this foundation.", "", "## Trust boundary", "",
             "Clang AST and name resolution, the compiler, registered standard numeric API contracts, CPU, and runtime are trusted.", ""]
    return "\n".join(lines)


def expression_from_file(path: str | Path, registry_root: str | Path = "registry/std") -> dict[str, Any]:
    return extract_expression(load_implementation_ir(path), registry_root)
