from __future__ import annotations

from typing import Any


def span(line: int = 1) -> dict[str, object]:
    return {"file": "fixture.cpp", "begin_line": line, "begin_column": 1,
            "end_line": line, "end_column": 20}


def node(node_id: str, kind: str, semantic: str, *, effect: str = "Pure",
         symbol: str = "", line: int = 1, **attrs: Any) -> dict[str, Any]:
    return {"id": node_id, "kind": kind, "source_span": span(line), "cpp_type": attrs.pop("cpp_type", "double"),
            "value_category": "prvalue", "constness": "mutable", "resolved_symbol": symbol,
            "effect": effect, "attributes": {"semantic_kind": semantic, **attrs}}


def edge(source: str, target: str, kind: str, role: str, *, confidence: str = "RESOLVED") -> dict[str, Any]:
    return {"edge_id": f"e-{source}-{target}-{kind}-{role}", "kind": kind,
            "source_node_id": source, "target_node_id": target, "argument_role": role,
            "source_span": span(), "confidence": confidence, "derivation": "clang_ast"}


def base_ir(function: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
            entities: list[str] | None = None) -> dict[str, Any]:
    return {"schema_version": "0.1", "dependency_graph_version": "0.1", "standard_version": "cpp20", "source_hash": "a" * 64,
            "function": function, "translation_unit": "fixture.cpp",
            "producer": {"kind": "clang-libtooling", "clang_version": "18.1.0",
                         "compile_command": "clang++ -std=c++20 fixture.cpp",
                         "compilation_database": "build/compile_commands.json"},
            "nodes": nodes, "dependency_edges": edges, "used_standard_entities": entities or [],
            "diagnostics": [], "analysis": {"alias_class": "named_contract:non_aliasing_spans"}}


def loop_ir() -> dict[str, Any]:
    nodes = [
        node("p-quantity", "ParmVarDecl", "FunctionParameter", name="quantity"),
        node("p-factor", "ParmVarDecl", "FunctionParameter", name="factor"),
        node("p-result", "ParmVarDecl", "FunctionParameter", name="result"),
        node("p-regions", "ParmVarDecl", "FunctionParameter", name="regions"),
        node("p-inputs", "ParmVarDecl", "FunctionParameter", name="inputs"),
        node("d-r", "VarDecl", "LocalVariable", name="r"), node("d-i", "VarDecl", "LocalVariable", name="i"),
        node("d-acc", "VarDecl", "LocalVariable", name="acc", initializer_text="0.0"),
        node("zero-r", "IntegerLiteral", "Literal", value="0"), node("zero-i", "IntegerLiteral", "Literal", value="0"),
        node("zero-acc", "FloatingLiteral", "Literal", value="0.0"),
        node("ref-regions", "DeclRefExpr", "Load", name="regions"), node("ref-inputs", "DeclRefExpr", "Load", name="inputs"),
        node("ref-r", "DeclRefExpr", "Load", name="r"), node("ref-i", "DeclRefExpr", "Load", name="i"),
        node("ref-inputs-index", "DeclRefExpr", "Load", name="inputs"),
        node("outer", "ForStmt", "Loop", index="r", lower="0", upper="regions", comparison="<"),
        node("inner", "ForStmt", "Loop", index="i", lower="0", upper="inputs", comparison="<"),
        node("mul-index", "BinaryOperator", "BinaryOperation", operator="*"),
        node("add-index", "BinaryOperator", "BinaryOperation", operator="+"),
        node("q", "CXXOperatorCallExpr", "Call", symbol="std::span::operator[]", arg0="quantity", arg1="r * inputs + i"),
        node("f", "CXXOperatorCallExpr", "Call", symbol="std::span::operator[]", arg0="factor", arg1="i"),
        node("mul", "BinaryOperator", "BinaryOperation", operator="*"),
        node("acc-load", "DeclRefExpr", "Load", name="acc"),
        node("update", "CompoundAssignOperator", "Assignment", effect="WriteMemory", operator="+=", lhs_text="acc", rhs_text="quantity[r*inputs+i]*factor[i]"),
        node("result-index", "CXXOperatorCallExpr", "Call", symbol="std::span::operator[]", arg0="result", arg1="r"),
        node("store", "BinaryOperator", "Store", effect="WriteMemory", operator="=", output_base="result", output_index="r"),
    ]
    edges = [
        edge("d-r", "outer", "LOOP_BOUND_DEPENDS_ON", "index"), edge("zero-r", "outer", "LOOP_BOUND_DEPENDS_ON", "lower"), edge("ref-regions", "outer", "LOOP_BOUND_DEPENDS_ON", "upper"),
        edge("d-i", "inner", "LOOP_BOUND_DEPENDS_ON", "index"), edge("zero-i", "inner", "LOOP_BOUND_DEPENDS_ON", "lower"), edge("ref-inputs", "inner", "LOOP_BOUND_DEPENDS_ON", "upper"),
        edge("ref-r", "mul-index", "VALUE_DEPENDS_ON", "lhs"), edge("ref-inputs-index", "mul-index", "VALUE_DEPENDS_ON", "rhs"),
        edge("mul-index", "add-index", "VALUE_DEPENDS_ON", "lhs"), edge("ref-i", "add-index", "VALUE_DEPENDS_ON", "rhs"),
        edge("add-index", "q", "VALUE_DEPENDS_ON", "arg1"), edge("ref-i", "f", "VALUE_DEPENDS_ON", "arg1"),
        edge("q", "mul", "VALUE_DEPENDS_ON", "lhs"), edge("f", "mul", "VALUE_DEPENDS_ON", "rhs"),
        edge("d-acc", "acc-load", "READS", "value"), edge("acc-load", "update", "PREVIOUS_ACCUMULATOR_VALUE", "accumulator"),
        edge("mul", "update", "VALUE_DEPENDS_ON", "value"), edge("outer", "update", "CONTROL_GUARDS", "loop"), edge("inner", "update", "CONTROL_GUARDS", "loop"),
        edge("zero-acc", "d-acc", "DEFINES", "initial_value"), edge("update", "d-acc", "DEFINES", "assigned_value"),
        edge("ref-r", "result-index", "VALUE_DEPENDS_ON", "arg1"), edge("result-index", "store", "WRITES", "lhs"),
        edge("acc-load", "store", "VALUE_DEPENDS_ON", "value"), edge("outer", "store", "CONTROL_GUARDS", "loop"),
    ]
    return base_ir("weighted_sum_loop", nodes, edges, ["std::span::operator[]"])


def inner_ir() -> dict[str, Any]:
    nodes = [
        node("d-r", "VarDecl", "LocalVariable", name="r"), node("zero", "IntegerLiteral", "Literal", value="0"),
        node("regions", "DeclRefExpr", "Load", name="regions"),
        node("outer", "ForStmt", "Loop", index="r", lower="0", upper="regions", comparison="<"),
        node("first-decl", "VarDecl", "LocalVariable", name="first", initializer_text="quantity.begin() + r * inputs"),
        node("first-ref", "DeclRefExpr", "Load", name="first"),
        node("initial", "FloatingLiteral", "Literal", value="0.0"),
        node("call", "CallExpr", "Call", symbol="std::inner_product", arg0="first", arg1="first + inputs", arg2="factor.begin()", arg3="0.0"),
        node("r-ref", "DeclRefExpr", "Load", name="r"), node("result-index", "CXXOperatorCallExpr", "Call", symbol="std::span::operator[]", arg0="result", arg1="r"),
        node("store", "BinaryOperator", "Store", effect="WriteMemory", operator="=", output_base="result", output_index="r"),
    ]
    edges = [edge("d-r", "outer", "LOOP_BOUND_DEPENDS_ON", "index"), edge("zero", "outer", "LOOP_BOUND_DEPENDS_ON", "lower"), edge("regions", "outer", "LOOP_BOUND_DEPENDS_ON", "upper"),
             edge("first-decl", "first-ref", "READS", "value"), edge("first-ref", "call", "VALUE_DEPENDS_ON", "arg0"), edge("initial", "call", "VALUE_DEPENDS_ON", "arg3"),
             edge("r-ref", "result-index", "VALUE_DEPENDS_ON", "arg1"), edge("result-index", "store", "WRITES", "lhs"), edge("call", "store", "VALUE_DEPENDS_ON", "value"), edge("outer", "store", "CONTROL_GUARDS", "loop")]
    return base_ir("weighted_sum_inner_product", nodes, edges, ["std::inner_product", "std::span::operator[]"])
