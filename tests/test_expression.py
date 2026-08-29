from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import jsonschema
import yaml

from cpp_audit.core import AuditError
from cpp_audit.expression import (compare_exact, extract_expression, load_formula,
                                  load_transformation_rule, load_transformation_set,
                                  normalize_exact, render_expression,
                                  select_transformation)
from tests.graph_fixtures import inner_ir, loop_ir

ROOT = Path(__file__).resolve().parents[1]


class ExpressionTests(unittest.TestCase):
    def test_loop_and_inner_product_extract_same_formula(self) -> None:
        loop, inner = extract_expression(loop_ir()), extract_expression(inner_ir())
        self.assertEqual("EXPRESSION_EXTRACTED", loop["status"])
        self.assertEqual(normalize_exact(loop)["canonical_expression"],
                         normalize_exact(inner)["canonical_expression"])

    def test_human_formula_matches_with_alpha_rename_trace(self) -> None:
        formula = load_formula(ROOT / "examples/weighted_sum/formula.yaml")
        result = compare_exact(extract_expression(loop_ir()), formula)
        self.assertTrue(result["match"])
        self.assertEqual("EQUIVALENT_BY_EXACT_TRANSFORMATIONS", result["status"])
        rule_ids = {item["rule_id"] for item in result["human"]["rewrite_trace"]}
        self.assertIn("alpha_rename", rule_ids)
        self.assertIn("finite_sum_normalization", rule_ids)

    def test_render_all_formats(self) -> None:
        expression = normalize_exact(extract_expression(loop_ir()))["canonical_expression"]
        for output_format in ("latex", "unicode", "markdown", "json"):
            with self.subTest(output_format=output_format):
                self.assertTrue(render_expression(expression, output_format).strip())
        self.assertIn("\\sum", render_expression(expression, "latex"))
        self.assertIn("Σ", render_expression(expression, "unicode"))

    def test_source_correspondence_is_preserved(self) -> None:
        correspondence = extract_expression(loop_ir())["source_correspondence"]
        self.assertTrue({"TransformReduce", "Multiply", "IndexedValue"}.issubset({item["term"] for item in correspondence}))
        self.assertTrue(correspondence[0]["implementation_node_ids"])

    def test_unresolved_dependencies_fail_closed(self) -> None:
        ir = loop_ir(); ir["dependency_edges"] = [edge for edge in ir["dependency_edges"] if edge["target_node_id"] != "store" or edge["kind"] != "VALUE_DEPENDS_ON"]
        result = extract_expression(ir)
        self.assertEqual("EXPRESSION_EXTRACTION_FAILED", result["status"])
        self.assertIn("INVALID_DEPENDENCY_GRAPH", {item["code"] for item in result["diagnostics"]})

    def test_frontend_diagnostic_reaches_slice_failure(self) -> None:
        ir = loop_ir(); ir["diagnostics"] = [{"code": "UNRESOLVED_CALL", "message": "mystery"}]
        result = extract_expression(ir)
        self.assertEqual("EXPRESSION_EXTRACTION_FAILED", result["status"])
        self.assertIn("UNRESOLVED_CALL", {item["code"] for item in result["diagnostics"]})

    def test_expression_schema(self) -> None:
        schema = json.loads((ROOT / "schemas/expression-ir.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(extract_expression(loop_ir()), schema)

    def test_transformation_schemas_and_minimum_cost(self) -> None:
        set_path = ROOT / "registry/transformations/sets/scientific_default.yaml"
        set_schema = json.loads((ROOT / "schemas/transformation-set.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(yaml.safe_load(set_path.read_text(encoding="utf-8")), set_schema)
        transformation_set = load_transformation_set(set_path)
        rules = []
        rule_schema = json.loads((ROOT / "schemas/transformation-rule.schema.json").read_text(encoding="utf-8"))
        for rule_id in transformation_set["approximation_rules"]:
            path = ROOT / "registry/transformations/rules" / f"{rule_id}.yaml"
            jsonschema.validate(yaml.safe_load(path.read_text(encoding="utf-8")), rule_schema)
            rules.append(load_transformation_rule(path))
        selection = select_transformation(transformation_set,
            [rule for rule in rules if rule.get("source_pattern", {}).get("op") == "Derivative"])
        self.assertEqual("forward_difference_first_derivative", selection["selected"]["rule_id"])

    def test_frequency_requirement_filters_candidates(self) -> None:
        transformation_set = load_transformation_set(ROOT / "registry/transformations/sets/scientific_default.yaml")
        rules = [load_transformation_rule(ROOT / "registry/transformations/rules" / f"{name}.yaml")
                 for name in transformation_set["approximation_rules"]]
        selection = select_transformation(transformation_set, rules, ["frequency_response"])
        self.assertEqual("central_difference_first_derivative", selection["selected"]["rule_id"])
        forward = next(x for x in selection["candidates"] if x["rule_id"].startswith("forward"))
        self.assertIn("REQUIRED_OBSERVABLE_UNAVAILABLE: frequency_response", forward["rejection_reasons"])

    def test_selection_profiles(self) -> None:
        transformation_set = load_transformation_set(ROOT / "registry/transformations/sets/scientific_default.yaml")
        rules = [load_transformation_rule(ROOT / "registry/transformations/rules" / f"{name}.yaml")
                 for name in transformation_set["approximation_rules"]]
        minimum_error = select_transformation(transformation_set, rules, selection_profile="minimum_error")
        frequency = select_transformation(transformation_set, rules, selection_profile="frequency_fidelity")
        stability = select_transformation(transformation_set, rules, selection_profile="stability")
        self.assertEqual("central_difference_first_derivative", minimum_error["selected"]["rule_id"])
        self.assertEqual("central_difference_first_derivative", frequency["selected"]["rule_id"])
        self.assertEqual("NO_FEASIBLE_TRANSFORMATION", stability["status"])

    def test_outside_set_no_feasible_and_tie(self) -> None:
        transformation_set = load_transformation_set(ROOT / "registry/transformations/sets/scientific_default.yaml")
        unknown = {"id": "fft_derivative", "supported_observables": [], "cost": {"symbolic_arithmetic_operations": 1}}
        self.assertEqual("NO_FEASIBLE_TRANSFORMATION",
                         select_transformation(transformation_set, [unknown])["status"])
        rule = load_transformation_rule(ROOT / "registry/transformations/rules/forward_difference_first_derivative.yaml")
        duplicate = deepcopy(rule); duplicate["id"] = "central_difference_first_derivative"
        self.assertEqual("SELECTION_TIE_REQUIRES_USER",
                         select_transformation(transformation_set, [rule, duplicate])["status"])

    def test_conflicting_set_fails(self) -> None:
        data = yaml.safe_load((ROOT / "registry/transformations/sets/scientific_default.yaml").read_text(encoding="utf-8"))
        data["transformation_set"]["forbidden_rules"] = ["central_difference_first_derivative"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conflict.yaml"
            path.write_text(yaml.safe_dump(data), encoding="utf-8")
            with self.assertRaisesRegex(AuditError, "TRANSFORMATION_SET_CONFLICT"):
                load_transformation_set(path)

    def test_ambiguous_formula_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.yaml"; path.write_text("formula: [", encoding="utf-8")
            with self.assertRaisesRegex(AuditError, "AMBIGUOUS_FORMULA_PARSE"):
                load_formula(path)


if __name__ == "__main__":
    unittest.main()
