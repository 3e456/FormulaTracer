from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import unittest

import jsonschema
from cpp_audit.core import load_spec
from cpp_audit.pipeline import (canonical_graph_interpret, human_reference,
                                implementation_ir_interpret, normalize_clang_ir,
                                validate_clang_ir)

ROOT = Path(__file__).resolve().parents[1]
SPEC = load_spec(ROOT / "examples/weighted_sum/algorithm.yaml")
REGISTRY = ROOT / "registry/std"


def span() -> dict[str, object]:
    return {"file": "weighted_sum.cpp", "begin_line": 1, "begin_column": 1,
            "end_line": 1, "end_column": 8}


def node(kind: str = "ForStmt", effect: str = "Pure") -> dict[str, object]:
    return {"id": f"{kind}-0123456789abcdef", "kind": kind, "source_span": span(),
            "cpp_type": "void", "value_category": "statement", "constness": "not_applicable",
            "resolved_symbol": "", "effect": effect, "attributes": {}}


def loop_ir() -> dict[str, object]:
    return {"schema_version": "0.1", "dependency_graph_version": "0.1", "standard_version": "cpp20", "source_hash": "a" * 64,
            "function": "weighted_sum_loop", "translation_unit": "weighted_sum_loop.cpp",
            "producer": {"kind": "clang-libtooling", "clang_version": "test",
                         "compile_command": "clang++ -std=c++20 -c weighted_sum_loop.cpp",
                         "compilation_database": "build/compile_commands.json"},
            "nodes": [node()], "used_standard_entities": ["std::span::operator[]"], "diagnostics": [],
            "dependency_edges": [],
            "analysis": {"style": "explicit_loop", "outer_index": "r", "outer_bound": "regions",
                         "outer_condition": "<", "inner_index": "i", "inner_bound": "inputs",
                         "inner_condition": "<", "accumulator_initial": "0.0",
                         "quantity_index": "r * inputs + i", "factor_index": "i",
                         "transform_operation": "Multiply", "reduction_operation": "Add",
                         "result_index": "r", "store_position": "after_inner_loop",
                         "alias_class": "named_contract:non_aliasing_spans"}}


def inner_ir() -> dict[str, object]:
    result = loop_ir()
    result["function"] = "weighted_sum_inner_product"
    result["used_standard_entities"] = ["std::inner_product", "std::span::begin", "std::span::operator[]"]
    result["analysis"] = {"style": "inner_product", "outer_index": "r", "outer_bound": "regions",
                          "outer_condition": "<", "resolved_callee": "std::inner_product",
                          "range_begin": "first", "range_end": "first + inputs",
                          "factor_begin": "factor.begin()", "initial_value": "0.0",
                          "row_begin": "quantity.begin() + r * inputs", "result_index": "r",
                          "transform_operation": "Multiply", "reduction_operation": "Add",
                          "store_position": "after_inner_loop",
                          "alias_class": "named_contract:non_aliasing_spans"}
    return result


class ClangPipelineTests(unittest.TestCase):
    def test_clang_provenance_is_mandatory(self) -> None:
        ir = loop_ir(); ir["producer"]["kind"] = "python-regex"
        self.assertIn("NON_CLANG_PROVENANCE", {x["code"] for x in validate_clang_ir(ir)})

    def test_missing_span_and_unknown_effect_fail_closed(self) -> None:
        ir = loop_ir(); ir["nodes"][0].pop("source_span"); ir["nodes"][0]["effect"] = "Unknown"
        codes = {x["code"] for x in validate_clang_ir(ir)}
        self.assertTrue({"MISSING_SOURCE_SPAN", "UNKNOWN_EFFECT"}.issubset(codes))

    def test_positive_loop_and_inner_normalize_to_same_graph(self) -> None:
        loop = normalize_clang_ir(loop_ir(), SPEC, REGISTRY)
        inner = normalize_clang_ir(inner_ir(), SPEC, REGISTRY)
        self.assertEqual("PASS", loop.status); self.assertEqual("PASS", inner.status)
        loop_graph, inner_graph = deepcopy(loop.canonical_graph), deepcopy(inner.canonical_graph)
        loop_graph.pop("provenance"); inner_graph.pop("provenance")
        self.assertEqual(loop_graph, inner_graph)

    def test_required_mutations_fail(self) -> None:
        cases = {
            "short bound": ("inner_bound", "inputs - 1", "LOOP_BOUND_MISMATCH"),
            "inclusive bound": ("inner_condition", "<=", "LOOP_CONDITION_MISMATCH"),
            "factor r": ("factor_index", "r", "FACTOR_INDEX_MISMATCH"),
            "transpose": ("quantity_index", "i * regions + r", "ROW_MAJOR_INDEX_MISMATCH"),
            "initial one": ("accumulator_initial", "1.0", "INITIAL_VALUE_MISMATCH"),
            "addition": ("transform_operation", "Add", "TRANSFORM_MISMATCH"),
            "result i": ("result_index", "i", "OUTPUT_INDEX_MISMATCH"),
            "inner store": ("store_position", "inside_inner_loop", "STORE_POSITION_MISMATCH"),
            "alias": ("obvious_alias", "quantity=result", "FORBIDDEN_ALIAS"),
        }
        for name, (field, value, code) in cases.items():
            with self.subTest(name=name):
                ir = loop_ir(); ir["analysis"][field] = value
                result = normalize_clang_ir(ir, SPEC, REGISTRY)
                self.assertIsNone(result.canonical_graph)
                self.assertIn(code, {item["code"] for item in result.diagnostics})

    def test_inner_product_mutations_fail(self) -> None:
        cases = {"reduce": ("resolved_callee", "std::reduce", "WRONG_OVERLOAD"),
                 "bad end": ("range_end", "first + inputs - 1", "ITERATOR_RANGE_MISMATCH"),
                 "bad initial": ("initial_value", "1.0", "INITIAL_VALUE_MISMATCH")}
        for name, (field, value, code) in cases.items():
            with self.subTest(name=name):
                ir = inner_ir(); ir["analysis"][field] = value
                result = normalize_clang_ir(ir, SPEC, REGISTRY)
                self.assertIn(code, {item["code"] for item in result.diagnostics})

    def test_unresolved_call_and_narrowing_fail(self) -> None:
        for code in ("UNRESOLVED_CALL", "UNKNOWN_IMPLICIT_CAST"):
            with self.subTest(code=code):
                ir = loop_ir(); ir["diagnostics"] = [{"code": code, "message": "frontend rejected node",
                    "specification": "resolved", "implementation": "bad", "source": "x.cpp:1"}]
                self.assertEqual("FAILED", normalize_clang_ir(ir, SPEC, REGISTRY).status)

    def test_independent_interpreters_agree(self) -> None:
        ir = loop_ir(); result = normalize_clang_ir(ir, SPEC, REGISTRY)
        quantity, factor = [[1, 2, 3], [4, 5, 6]], [7, 8, 9]
        implementation = implementation_ir_interpret(ir, quantity, factor)
        canonical = canonical_graph_interpret(result.canonical_graph, quantity, factor)
        human = human_reference(quantity, factor)
        self.assertEqual([50.0, 122.0], implementation)
        self.assertEqual(implementation, canonical); self.assertEqual(canonical, human)

    def test_global_coverage_is_not_faked(self) -> None:
        usage = normalize_clang_ir(inner_ir(), SPEC, REGISTRY).registry_usage
        self.assertEqual("GLOBAL_COVERAGE_NOT_AVAILABLE", usage["global_coverage"])
        self.assertEqual(3, usage["used_standard_entity_count"])
        self.assertEqual(0, usage["unclassified_used_entity_count"])

    def test_implementation_and_canonical_schemas(self) -> None:
        implementation = loop_ir()
        canonical = normalize_clang_ir(implementation, SPEC, REGISTRY).canonical_graph
        implementation_schema = json.loads((ROOT / "schemas/implementation-ir.schema.json").read_text(encoding="utf-8"))
        canonical_schema = json.loads((ROOT / "schemas/semantic-graph.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(implementation, implementation_schema)
        jsonschema.validate(canonical, canonical_schema)


if __name__ == "__main__":
    unittest.main()
