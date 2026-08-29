from __future__ import annotations

from pathlib import Path
import json
import math
import tempfile
import unittest

import jsonschema
from referencing import Registry, Resource

from formulatracer import FormulaTracer, InputRange, IntervalEngine, RangeSpecification, RangeStatus
from cpp_audit.interval import (ErrorInterval, Interval, RangeEnclosure, ValueInterval,
                                analyze_project_ranges, interval_power, singleton)


class IntervalRangeTests(unittest.TestCase):
    def evaluate(self, expression, ranges):
        engine = IntervalEngine(RangeSpecification.from_value(ranges))
        return engine, engine.evaluate(expression)

    def project(self, source: str):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "model.py").write_text(source, encoding="utf-8")
        self.addCleanup(temporary.cleanup)
        return root / "model.py"

    def test_e2e_a_scalar_arithmetic(self):
        expression = {"op": "Add", "args": [
            {"op": "Multiply", "args": [{"op": "Constant", "value": 3}, {"op": "FreeVariable", "name": "x"}]},
            {"op": "Constant", "value": 2},
        ]}
        _, result = self.evaluate(expression, {"x": (1, 2)})
        self.assertEqual((result.lower, result.upper), (5, 8))

    def test_e2e_b_symbol_identity_before_interval_arithmetic(self):
        x = {"op": "FreeVariable", "name": "x"}
        _, same = self.evaluate({"op": "Subtract", "args": [x, x]}, {"x": (0, 1)})
        self.assertEqual((same.lower, same.upper), (0, 0))
        _, distinct = self.evaluate({"op": "Subtract", "args": [x, {"op": "FreeVariable", "name": "y"}]},
                                    {"x": (0, 1), "y": (0, 1)})
        self.assertEqual((distinct.lower, distinct.upper), (-1, 1))

    def test_e2e_c_branch_pruning_and_split(self):
        branch = {"op": "IfThenElse",
                  "condition": {"op": "Compare", "operator": "Gt", "args": [
                      {"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 0}]},
                  "then": {"op": "Sqrt", "arg": {"op": "FreeVariable", "name": "x"}},
                  "else": {"op": "Constant", "value": 0}}
        _, positive = self.evaluate(branch, {"x": (2, 4)})
        self.assertEqual(positive.provenance["branch_status"], "BRANCH_PROVEN_TRUE")
        self.assertGreaterEqual(positive.lower, 0)
        split_engine, split = self.evaluate(branch, {"x": (-2, 4)})
        self.assertEqual(split.provenance["branch_status"], "BRANCH_INTERVAL_SPLIT")
        self.assertLessEqual(split.lower, 0)
        self.assertGreaterEqual(split.upper, 2)
        self.assertFalse(any(item.kind == "SQRT_DOMAIN_VIOLATION" for item in split_engine.obligations))

    def test_python_cfg_simple_assignment_merge_reaches_range_engine(self):
        source = self.project("import math\ndef compute(x):\n    if x > 0:\n        y=math.sqrt(x)\n    else:\n        y=0\n    return y\n")
        positive = FormulaTracer(source).analyze(ranges={"x": (2, 4)}).outputs[0]
        self.assertEqual(positive.formula["op"], "IfThenElse")
        self.assertEqual(positive.value_interval["interval"]["provenance"]["branch_status"], "BRANCH_PROVEN_TRUE")
        split = FormulaTracer(source).analyze(ranges={"x": (-2, 4)}).outputs[0]
        self.assertEqual(split.value_interval["interval"]["provenance"]["branch_status"], "BRANCH_INTERVAL_SPLIT")

    def test_elementary_critical_points_and_domains(self):
        _, sine = self.evaluate({"op": "Sin", "arg": {"op": "FreeVariable", "name": "x"}},
                                {"x": (0, math.pi)})
        self.assertGreaterEqual(sine.upper, 1)
        sqrt_engine, sqrt = self.evaluate({"op": "Sqrt", "arg": {"op": "FreeVariable", "name": "x"}}, {"x": (-1, 4)})
        self.assertFalse(sqrt.resolved)
        self.assertIn("SQRT_DOMAIN_VIOLATION", {item.kind for item in sqrt_engine.obligations})
        log_engine, log = self.evaluate({"op": "Log", "arg": {"op": "FreeVariable", "name": "x"}}, {"x": (0, 1)})
        self.assertFalse(log.resolved)
        self.assertIn("LOG_DOMAIN_VIOLATION", {item.kind for item in log_engine.obligations})

    def test_division_even_power_reduction_and_symbolic_bounds(self):
        div_engine, division = self.evaluate({"op": "Divide", "args": [
            {"op": "Constant", "value": 1}, {"op": "FreeVariable", "name": "x"}]}, {"x": (-1, 1)})
        self.assertFalse(division.resolved)
        self.assertIn("DIVISION_INTERVAL_CROSSES_ZERO", {item.kind for item in div_engine.obligations})
        square = interval_power(Interval(-2, 3), 2)
        self.assertEqual((square.lower, square.upper), (0, 9))
        _, symbolic = self.evaluate({"op": "Add", "args": [
            {"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 1}]},
            {"x": {"lower": 0, "upper": "M", "assumptions": ["M >= 0"]}})
        self.assertEqual(symbolic.status, RangeStatus.SYMBOLIC_INTERVAL.value)

    def test_named_tensor_dimensions_survive_elementwise_propagation(self):
        _, value = self.evaluate({"op": "Multiply", "args": [
            {"op": "FreeVariable", "name": "temperature"}, {"op": "Constant", "value": 2}]},
            {"temperature": {"lower": 250, "upper": 330, "dimensions": ["time", "lat", "lon"]}})
        self.assertEqual(value.dimensions, ["time", "lat", "lon"])

    def test_reduction_mean_and_componentwise_dot(self):
        tensor = {"lower": -1, "upper": 2, "shape": [3], "item_count": 3}
        _, summed = self.evaluate({"op": "FiniteSum", "input": {"op": "FreeVariable", "name": "x"}}, {"x": tensor})
        self.assertEqual((summed.lower, summed.upper), (-3, 6))
        _, mean = self.evaluate({"op": "Mean", "input": {"op": "FreeVariable", "name": "x"}}, {"x": tensor})
        self.assertEqual((mean.lower, mean.upper), (-1, 2))
        _, dot = self.evaluate({"op": "Dot", "args": [
            {"op": "FreeVariable", "name": "x"}, {"op": "FreeVariable", "name": "y"}]},
            {"x": tensor, "y": {"lower": 2, "upper": 4, "item_count": 3}})
        self.assertEqual((dot.lower, dot.upper), (-12, 24))

    def test_numpy_reduction_uses_axis_extent_and_preserves_remaining_dimension(self):
        source = self.project("import numpy as np\ndef compute(quantity, factor):\n    return np.sum(quantity*factor, axis=1)\n")
        output = FormulaTracer(source).analyze(ranges={
            "quantity": {"lower": 1, "upper": 2, "shape": [2, 3], "dimensions": ["region", "input"]},
            "factor": {"lower": 3, "upper": 4, "shape": [3], "dimensions": ["input"]},
        }).outputs[0]
        interval = output.value_interval["interval"]
        self.assertEqual((interval["lower"], interval["upper"]), (9, 24))
        self.assertEqual(interval["dimensions"], ["region"])

    def test_object_api_constraints_multi_output_and_latex(self):
        source = self.project("def compute(x):\n    a = 3*x + 2\n    b = x - x\n    return a, b\n")
        result = FormulaTracer(source).analyze(
            ranges={"x": (1, 2)}, output_ranges={"a": (0, 10), "b": (1, 2)})
        a, b = result.get_output("a"), result.get_output("b")
        self.assertEqual((a.value_interval["interval"]["lower"], a.value_interval["interval"]["upper"]), (5, 8))
        self.assertEqual((b.value_interval["interval"]["lower"], b.value_interval["interval"]["upper"]), (0, 0))
        self.assertEqual(a.range_constraint_status, "OUTPUT_RANGE_CONSTRAINT_PROVEN")
        self.assertEqual(b.range_constraint_status, "OUTPUT_RANGE_CONSTRAINT_VIOLATED")
        self.assertIn("Certified ranges", result.to_latex())

    def test_unresolved_error_never_becomes_total_true_enclosure(self):
        source = self.project("import numpy as np\ndef compute(x):\n    return np.gradient(x)\n")
        result = FormulaTracer(source).analyze(ranges={"x": {"lower": 0, "upper": 1, "shape": [4]}})
        output = result.outputs[0]
        self.assertNotEqual(output.range_status, "TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED")
        self.assertIn("UNRESOLVED_ERROR_COMPONENT", {item["kind"] for item in output.range_obligations})

    def test_e2e_d_known_approximation_plus_unknown_rounding_is_partial(self):
        source = self.project("def compute(x):\n    return x\n")
        project = FormulaTracer(source).analyze()
        project.outputs[0].error_components = [
            {"component_id": "central-difference", "proof_status": "KERNEL_VERIFIED",
             "bound": {"status": "KERNEL_VERIFIED_BOUND", "symmetric_bound": {
                 "op": "Divide", "args": [{"op": "Multiply", "args": ["M", {"op": "Power", "args": ["h", 2]}]}, 6]}}},
            {"component_id": "rounding", "proof_status": "UNRESOLVED", "bound": {"status": "BOUND_NOT_EVALUATED"}},
        ]
        output = analyze_project_ranges(project, {"x": (10, 12)}).outputs[0]
        self.assertEqual(output.range_status, "PARTIAL_TRUE_VALUE_ENCLOSURE")
        self.assertFalse(output.error_interval["total"])
        self.assertIn("UNRESOLVED_ERROR_COMPONENT", {item["kind"] for item in output.range_obligations})

    def test_e2e_e_cross_language_boundary_is_not_guessed(self):
        expression = {"op": "Multiply", "args": [
            {"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 2}],
            "language_boundary": {"source_language": "python", "target_language": "cpp",
                                  "representation_mapping": "REPRESENTATION_MAPPING_UNRESOLVED"}}
        engine, value = self.evaluate(expression, {"x": (1, 2)})
        self.assertEqual((value.lower, value.upper), (2, 4))
        self.assertIn("FFI_REPRESENTATION_RANGE_UNRESOLVED", {item.kind for item in engine.obligations})

    def test_e2e_f_io_payload_range_and_serialization_boundary(self):
        source = self.project("import xarray as xr\ndef write(x):\n    score=x*2\n    ds=xr.Dataset()\n    ds['score']=score\n    ds.to_netcdf('result.nc')\n")
        result = FormulaTracer(source).analyze()
        result.outputs[0].implementation["numeric_execution"] = {"dtype": "float64"}
        result.artifacts[0].dtype = "float32"
        result = analyze_project_ranges(result, {"x": (1, 2)})
        artifact = result.artifacts[0]
        self.assertIsNotNone(artifact.certified_payload_range)
        self.assertEqual(artifact.serialization_cast["kind"], "SERIALIZATION_CAST")
        self.assertEqual(artifact.range_status, "SERIALIZATION_RANGE_UNRESOLVED")
        self.assertIn("payload range", result.to_latex())

    def test_execution_overflow_and_cast_fail_closed(self):
        source = self.project("def compute(x):\n    return x*2\n")
        project = FormulaTracer(source).analyze()
        project.outputs[0].implementation["numeric_execution"] = {"dtype": "float32"}
        output = analyze_project_ranges(project, {"x": (2.0e38, 2.0e38)}).outputs[0]
        self.assertEqual(output.execution_range["diagnostic"], "OVERFLOW_POSSIBLE")
        engine, cast = self.evaluate({"op": "Cast", "arg": {"op": "FreeVariable", "name": "x"},
                                      "target_type": "int32"}, {"x": (0, 1)})
        self.assertFalse(cast.resolved)
        self.assertIn("CAST_RANGE_UNRESOLVED", {item.kind for item in engine.obligations})

    def test_observed_ranges_are_not_proof_and_verified_error_can_enclose(self):
        observed = InputRange("x", 0, 0, status=RangeStatus.NUMERICALLY_OBSERVED_ONLY.value)
        _, value = self.evaluate({"op": "FreeVariable", "name": "x"}, RangeSpecification([observed]))
        self.assertFalse(value.resolved)
        source = self.project("def compute(x):\n    return x + 1\n")
        specification = RangeSpecification(
            [InputRange("x", 1, 2)],
            error_ranges={"compute": InputRange("compute", -0.1, 0.1, status=RangeStatus.KERNEL_VERIFIED_INTERVAL.value)},
        )
        output = FormulaTracer(source).analyze(ranges=specification).outputs[0]
        self.assertEqual(output.range_status, "TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED")

    def test_interval_range_schemas(self):
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
        interval_schema = json.loads((schema_root / "interval.schema.json").read_text(encoding="utf-8"))
        specification_schema = json.loads((schema_root / "range-specification.schema.json").read_text(encoding="utf-8"))
        enclosure_schema = json.loads((schema_root / "range-enclosure.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(interval_schema).validate(singleton(1).to_dict())
        jsonschema.Draft202012Validator(specification_schema).validate(
            RangeSpecification.from_value({"x": (0, 1)}).__dict__ | {
                "ranges": [item.__dict__ for item in RangeSpecification.from_value({"x": (0, 1)}).ranges]
            })
        registry = Registry().with_resource(interval_schema["$id"], Resource.from_contents(interval_schema))
        interval = singleton(1)
        enclosure = RangeEnclosure("y", ValueInterval(interval, "y"), ErrorInterval(singleton(0), "y", total=True),
                                   interval, "TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED", "INTERVAL_PROPAGATION_KERNEL_VERIFIED")
        jsonschema.Draft202012Validator(enclosure_schema, registry=registry).validate(enclosure.to_dict())


if __name__ == "__main__":
    unittest.main()
