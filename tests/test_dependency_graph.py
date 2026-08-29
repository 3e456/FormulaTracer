from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

import jsonschema

from cpp_audit.dependency import build_dependency_graph, extract_output_slice
from cpp_audit.expression import extract_expression, render_expression
from tests.graph_fixtures import base_ir, edge, inner_ir, loop_ir, node

ROOT = Path(__file__).resolve().parents[1]


def loop_parts() -> tuple[list[dict], list[dict]]:
    nodes = [node("i-decl", "VarDecl", "LocalVariable", name="i"),
             node("zero", "IntegerLiteral", "Literal", value="0"),
             node("n-ref", "DeclRefExpr", "Load", name="n"),
             node("loop", "ForStmt", "Loop", index="i", lower="0", upper="n", comparison="<"),
             node("i-ref", "DeclRefExpr", "Load", name="i")]
    edges = [edge("i-decl", "loop", "LOOP_BOUND_DEPENDS_ON", "index"),
             edge("zero", "loop", "LOOP_BOUND_DEPENDS_ON", "lower"),
             edge("n-ref", "loop", "LOOP_BOUND_DEPENDS_ON", "upper")]
    return nodes, edges


def indexed(name: str, prefix: str) -> tuple[list[dict], list[dict]]:
    return ([node(f"{prefix}-index", "CXXOperatorCallExpr", "Call", symbol="std::span::operator[]",
                  arg0=name, arg1="i")],
            [edge("i-ref", f"{prefix}-index", "VALUE_DEPENDS_ON", "arg1")])


def map_ir(kind: str = "affine") -> dict:
    nodes, edges = loop_parts()
    x_nodes, x_edges = indexed("x", "x"); y_nodes, y_edges = indexed("y", "y")
    nodes += x_nodes + y_nodes; edges += x_edges + y_edges
    if kind == "affine":
        nodes += [node("a", "DeclRefExpr", "Load", name="a"), node("b", "DeclRefExpr", "Load", name="b"),
                  node("mul", "BinaryOperator", "BinaryOperation", operator="*"),
                  node("body", "BinaryOperator", "BinaryOperation", operator="+")]
        edges += [edge("a", "mul", "VALUE_DEPENDS_ON", "lhs"), edge("x-index", "mul", "VALUE_DEPENDS_ON", "rhs"),
                  edge("mul", "body", "VALUE_DEPENDS_ON", "lhs"), edge("b", "body", "VALUE_DEPENDS_ON", "rhs")]
    elif kind == "two_input":
        other_nodes, other_edges = indexed("other", "other"); nodes += other_nodes; edges += other_edges
        nodes += [node("body", "BinaryOperator", "BinaryOperation", operator="+")]
        edges += [edge("x-index", "body", "VALUE_DEPENDS_ON", "lhs"), edge("other-index", "body", "VALUE_DEPENDS_ON", "rhs")]
    elif kind == "sqrt":
        nodes += [node("body", "CallExpr", "Call", symbol="std::sqrt", arg0="x[i]")]
        edges += [edge("x-index", "body", "VALUE_DEPENDS_ON", "arg0")]
    nodes += [node("store", "BinaryOperator", "Store", effect="WriteMemory", output_base="y", output_index="i", operator="=")]
    edges += [edge("y-index", "store", "WRITES", "lhs"), edge("body", "store", "VALUE_DEPENDS_ON", "value"),
              edge("loop", "store", "CONTROL_GUARDS", "loop")]
    entities = ["std::span::operator[]"] + (["std::sqrt"] if kind == "sqrt" else [])
    return base_ir(f"map_{kind}", nodes, edges, entities)


def if_ir(*, missing_else: bool = False, different_index: bool = False,
          side_effect: bool = False) -> dict:
    nodes, edges = loop_parts(); x_nodes, x_edges = indexed("x", "x"); y_nodes, y_edges = indexed("y", "y")
    nodes += x_nodes + y_nodes + [node("zero-value", "IntegerLiteral", "Literal", value="0"),
        node("condition", "BinaryOperator", "Comparison", effect="WriteMemory" if side_effect else "Pure", operator=">"),
        node("if", "IfStmt", "Conditional"),
        node("true", "BinaryOperator", "Store", effect="WriteMemory", output_base="y", output_index="i", operator="=")]
    edges += x_edges + y_edges + [edge("x-index", "condition", "VALUE_DEPENDS_ON", "lhs"),
        edge("zero-value", "condition", "VALUE_DEPENDS_ON", "rhs"), edge("condition", "if", "CONDITION_DEPENDS_ON", "condition"),
        edge("y-index", "true", "WRITES", "lhs"), edge("x-index", "true", "VALUE_DEPENDS_ON", "value"),
        edge("loop", "true", "CONTROL_GUARDS", "loop"), edge("if", "true", "CONTROL_GUARDS", "true_branch")]
    if not missing_else:
        nodes += [node("else-index", "CXXOperatorCallExpr", "Call", symbol="std::span::operator[]", arg0="y", arg1="j" if different_index else "i"),
                  node("false", "BinaryOperator", "Store", effect="WriteMemory", output_base="y", output_index="j" if different_index else "i", operator="=")]
        edges += [edge("i-ref", "else-index", "VALUE_DEPENDS_ON", "arg1"), edge("else-index", "false", "WRITES", "lhs"),
                  edge("zero-value", "false", "VALUE_DEPENDS_ON", "value"), edge("loop", "false", "CONTROL_GUARDS", "loop"),
                  edge("if", "false", "CONTROL_GUARDS", "false_branch")]
    return base_ir("positive_clamp", nodes, edges, ["std::span::operator[]"])


def explicit_fold_ir() -> dict:
    nodes, edges = loop_parts(); x_nodes, x_edges = indexed("x", "x"); nodes += x_nodes; edges += x_edges
    nodes += [node("init", "FloatingLiteral", "Literal", value="2.0"),
              node("acc-decl", "VarDecl", "LocalVariable", name="acc", initializer_text="2.0"),
              node("acc-prev", "DeclRefExpr", "Load", name="acc"),
              node("update", "CompoundAssignOperator", "Assignment", effect="WriteMemory", operator="+=", lhs_text="acc", rhs_text="x[i]"),
              node("acc-result", "DeclRefExpr", "Load", name="acc"), node("return", "ReturnStmt", "Return")]
    edges += [edge("init", "acc-decl", "DEFINES", "initial_value"), edge("acc-decl", "acc-prev", "READS", "value"),
              edge("acc-prev", "update", "PREVIOUS_ACCUMULATOR_VALUE", "accumulator"), edge("x-index", "update", "VALUE_DEPENDS_ON", "value"),
              edge("loop", "update", "CONTROL_GUARDS", "loop"), edge("update", "acc-decl", "DEFINES", "assigned_value"),
              edge("acc-decl", "acc-result", "READS", "value"), edge("acc-result", "return", "RESULT_OF", "return_value")]
    return base_ir("sum_values", nodes, edges, ["std::span::operator[]"])


def accumulate_ir(multiply: bool = False, reduce: bool = False) -> dict:
    symbol = "std::reduce" if reduce else "std::accumulate"
    arg3 = "std::multiplies<double>{}" if multiply else "std::plus<double>{}"
    nodes = [node("init", "FloatingLiteral", "Literal", value="1.0" if multiply else "2.0"),
             node("call", "CallExpr", "Call", symbol=symbol, arg0="x.begin()", arg1="x.begin() + n",
                  arg2="1.0" if multiply else "2.0", arg3=arg3), node("return", "ReturnStmt", "Return")]
    edges = [edge("init", "call", "VALUE_DEPENDS_ON", "arg2"), edge("call", "return", "RESULT_OF", "return_value")]
    return base_ir("fold_api", nodes, edges, [symbol])


def transform_ir() -> dict:
    nodes = [node("v", "DeclRefExpr", "Load", name="v"),
             node("sqrt", "CallExpr", "Call", symbol="std::sqrt", arg0="v"),
             node("lambda", "LambdaExpr", "FunctionValue"),
             node("transform", "CallExpr", "Call", effect="WriteMemory", symbol="std::transform",
                  output_base="y.begin()", arg0="x.begin()", arg1="x.begin() + n", arg2="y.begin()",
                  arg3="[](double v) { return std::sqrt(v); }")]
    edges = [edge("v", "sqrt", "VALUE_DEPENDS_ON", "arg0"), edge("sqrt", "lambda", "RESULT_OF", "body"),
             edge("lambda", "transform", "VALUE_DEPENDS_ON", "arg3")]
    return base_ir("sqrt_transform", nodes, edges, ["std::sqrt", "std::transform"])


class DependencyGraphTests(unittest.TestCase):
    def test_dependency_and_slice_schemas(self) -> None:
        graph = build_dependency_graph(map_ir()); output_slice = extract_output_slice(graph)
        self.assertEqual("DEPENDENCY_GRAPH_BUILT", graph["status"])
        self.assertEqual("OUTPUT_SLICE_EXTRACTED", output_slice["status"])
        for name, value in (("dependency-graph.schema.json", graph), ("output-slice.schema.json", output_slice)):
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8")); jsonschema.validate(value, schema)

    def test_map_variants(self) -> None:
        for kind, required in (("affine", {"Add", "Multiply"}), ("two_input", {"Add"}), ("sqrt", {"FunctionCall"})):
            with self.subTest(kind=kind):
                result = extract_expression(map_ir(kind)); self.assertEqual("EXPRESSION_EXTRACTED", result["status"])
                self.assertIn("MAP_EXTRACTED", result["extraction_statuses"])
                rendered = render_expression(result, "latex")
                self.assertIn("0\\le i<n", rendered)
                self.assertTrue(all(op in json.dumps(result["outputs"]) for op in required))

    def test_span_size_lowers_to_extent(self) -> None:
        implementation = map_ir()
        size = next(item for item in implementation["nodes"] if item["id"] == "n-ref")
        size.update({"kind": "CXXMemberCallExpr", "resolved_symbol": "std::span::size"})
        size["attributes"] = {"semantic_kind": "Call", "object": "x"}
        implementation["used_standard_entities"].append("std::span::size")
        expression = extract_expression(implementation, ROOT / "registry/std")
        self.assertEqual("EXPRESSION_EXTRACTED", expression["status"])
        domain = expression["outputs"][0]["expression"]["index_domain"]
        self.assertEqual("FreeVariable", domain["upper_exclusive"]["op"])
        self.assertEqual("n", domain["upper_exclusive"]["name"])

    def test_std_transform_lowers_to_map(self) -> None:
        result = extract_expression(transform_ir())
        self.assertEqual("EXPRESSION_EXTRACTED", result["status"])
        self.assertIn("MAP_EXTRACTED", result["extraction_statuses"])
        self.assertIn("sqrt", render_expression(result, "unicode"))

    def test_if_then_else_and_nested_map(self) -> None:
        result = extract_expression(if_ir())
        self.assertTrue({"MAP_EXTRACTED", "IF_THEN_ELSE_EXTRACTED"}.issubset(result["extraction_statuses"]))
        self.assertIn("\\begin{cases}", render_expression(result, "latex"))
        self.assertIn("otherwise", render_expression(result, "unicode"))

    def test_fold_left_explicit_and_accumulate(self) -> None:
        explicit = extract_expression(explicit_fold_ir()); accumulate = extract_expression(accumulate_ir())
        self.assertEqual("FoldLeft", explicit["outputs"][0]["expression"]["op"])
        self.assertEqual("FoldLeft", accumulate["outputs"][0]["expression"]["op"])
        self.assertIn("FOLD_LEFT_EXTRACTED", explicit["extraction_statuses"])
        self.assertIn("\\sum", render_expression(explicit, "latex"))

    def test_fold_left_explicit_assignment_form(self) -> None:
        ir = explicit_fold_ir()
        next(item for item in ir["nodes"] if item["id"] == "update")["attributes"]["operator"] = "="
        ir["nodes"] += [node("acc-rhs", "DeclRefExpr", "Load", name="acc"),
                        node("combine", "BinaryOperator", "BinaryOperation", operator="+")]
        ir["dependency_edges"] = [item for item in ir["dependency_edges"]
                                  if not (item["source_node_id"] == "x-index" and item["target_node_id"] == "update")]
        ir["dependency_edges"] += [edge("acc-decl", "acc-rhs", "READS", "value"),
                                   edge("acc-rhs", "combine", "VALUE_DEPENDS_ON", "lhs"),
                                   edge("x-index", "combine", "VALUE_DEPENDS_ON", "rhs"),
                                   edge("combine", "update", "VALUE_DEPENDS_ON", "value")]
        result = extract_expression(ir)
        self.assertEqual("FOLD_LEFT_EXTRACTED", result["extraction_statuses"][-1])
        self.assertEqual("IndexedValue", result["outputs"][0]["expression"]["body"]["op"])

    def test_accumulate_custom_multiply(self) -> None:
        result = extract_expression(accumulate_ir(multiply=True))
        self.assertEqual("Multiply", result["outputs"][0]["expression"]["operation"])
        self.assertIn("\\prod", render_expression(result, "latex"))

    def test_weighted_sum_regression_uses_graph(self) -> None:
        left, right = extract_expression(loop_ir()), extract_expression(inner_ir())
        self.assertEqual("EXPRESSION_EXTRACTED", left["status"]); self.assertEqual("EXPRESSION_EXTRACTED", right["status"])
        self.assertEqual("TransformReduce", left["outputs"][0]["expression"]["op"])
        self.assertIn("DEPENDENCY_GRAPH_BUILT", left["extraction_statuses"])

    def test_unknown_call_in_slice_fails(self) -> None:
        ir = map_ir(); body = next(node for node in ir["nodes"] if node["id"] == "body")
        body["kind"] = "CallExpr"; body["resolved_symbol"] = "mystery"; body["effect"] = "Unknown"; body["attributes"] = {"semantic_kind": "Call"}
        result = extract_expression(ir)
        self.assertIn("NON_NUMERIC_DEPENDENCY_IN_AUDITED_SLICE", {item["code"] for item in result["diagnostics"]})

    def test_unregistered_standard_call_fails(self) -> None:
        ir = map_ir(); body = next(node for node in ir["nodes"] if node["id"] == "body")
        body["kind"] = "CallExpr"; body["resolved_symbol"] = "std::mystery_numeric"; body["attributes"] = {"semantic_kind": "Call"}
        result = extract_expression(ir)
        self.assertIn("UNRESOLVED_NUMERIC_CALL", {item["code"] for item in result["diagnostics"]})

    def test_dead_unknown_call_is_excluded_from_slice(self) -> None:
        ir = map_ir()
        ir["nodes"].append(node("dead-call", "CallExpr", "Call", effect="Unknown", symbol="debug_mystery"))
        ir["diagnostics"].append({"code": "UNRESOLVED_CALL", "message": "dead debug call", "node_id": "dead-call"})
        result = extract_expression(ir)
        self.assertEqual("EXPRESSION_EXTRACTED", result["status"])
        self.assertNotIn("dead-call", result["output_slice"]["node_ids"])

    def test_branch_fail_closed_cases(self) -> None:
        for ir, code in ((if_ir(side_effect=True), "SIDE_EFFECTING_CONDITION"),
                         (if_ir(different_index=True), "UNSUPPORTED_BRANCH_MERGE"),
                         (if_ir(missing_else=True), "UNSUPPORTED_BRANCH_MERGE")):
            with self.subTest(code=code):
                result = extract_expression(ir); self.assertEqual("EXPRESSION_EXTRACTION_FAILED", result["status"])
                self.assertIn(code, {item["code"] for item in result["diagnostics"]})

    def test_invalid_loop_and_unresolved_edge(self) -> None:
        ir = map_ir(); ir["dependency_edges"] = [item for item in ir["dependency_edges"] if not (item["target_node_id"] == "loop" and item["argument_role"] == "upper")]
        self.assertEqual("DEPENDENCY_GRAPH_INVALID", build_dependency_graph(ir)["status"])
        ir = map_ir(); next(item for item in ir["dependency_edges"] if item["target_node_id"] == "store" and item["argument_role"] == "value")["confidence"] = "UNRESOLVED"
        self.assertIn("UNRESOLVED_OUTPUT_DEPENDENCY", {item["code"] for item in extract_expression(ir)["diagnostics"]})

    def test_cycle_phi_reduce_mutation_and_ambiguous_output_fail(self) -> None:
        ir = map_ir(); ir["dependency_edges"] += [edge("a", "b", "VALUE_DEPENDS_ON", "value"), edge("b", "a", "VALUE_DEPENDS_ON", "value")]
        ir["nodes"] += [node("a", "Opaque", "Intermediate"), node("b", "Opaque", "Intermediate")]
        self.assertIn("UNSUPPORTED_DEPENDENCY_CYCLE", {item["code"] for item in build_dependency_graph(ir)["diagnostics"]})
        phi = map_ir(); phi["nodes"].append(node("phi", "Phi", "PhiLikeMerge")); next(item for item in phi["dependency_edges"] if item["target_node_id"] == "store" and item["argument_role"] == "value")["source_node_id"] = "phi"
        self.assertEqual("EXPRESSION_EXTRACTION_FAILED", extract_expression(phi)["status"])
        self.assertNotIn("FOLD_LEFT_EXTRACTED", extract_expression(accumulate_ir(reduce=True)).get("extraction_statuses", []))
        mutation = map_ir(); mutation["nodes"].append(node("mutation", "BinaryOperator", "Assignment", effect="WriteMemory")); mutation["dependency_edges"].append(edge("body", "mutation", "VALUE_DEPENDS_ON", "value")); next(item for item in mutation["dependency_edges"] if item["target_node_id"] == "store" and item["argument_role"] == "value")["source_node_id"] = "mutation"
        self.assertIn("MAP_BODY_UNSUPPORTED_MUTATION", {item["code"] for item in extract_expression(mutation)["diagnostics"]})
        ambiguous = map_ir(); store2 = deepcopy(next(item for item in ambiguous["nodes"] if item["id"] == "store")); store2["id"] = "store-z"; store2["attributes"]["output_base"] = "z"; ambiguous["nodes"].append(store2); ambiguous["dependency_edges"] += [edge("y-index", "store-z", "WRITES", "lhs"), edge("body", "store-z", "VALUE_DEPENDS_ON", "value"), edge("loop", "store-z", "CONTROL_GUARDS", "loop")]
        self.assertEqual("DEPENDENCY_GRAPH_INVALID", build_dependency_graph(ambiguous)["status"])


if __name__ == "__main__": unittest.main()
