from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

import jsonschema
from referencing import Registry, Resource

from formulatracer import FormulaTracer, build_end_to_end_claims
from cpp_audit.error_ir import ErrorSpecification
from cpp_audit.interval import analyze_project_ranges


ROOT = Path(__file__).resolve().parents[1]


def component(identifier: str, source: str, bound: float, *, assumptions=(), verified=True, cause=None):
    return {
        "component_id": identifier,
        "source": source,
        "expression": {"op": "OpaqueErrorTerm", "source": identifier},
        "metric": "ABSOLUTE",
        "bound": {"status": "KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS" if assumptions else "KERNEL_VERIFIED_BOUND",
                  "lower_bound": -bound, "upper_bound": bound,
                  "symmetric_bound": {"op": "Constant", "value": bound}},
        "proof_status": "KERNEL_VERIFIED" if verified else "UNRESOLVED",
        "provenance": {"kind": "TEST_FORMAL_BOUND"},
        "origin_id": identifier,
        "semantic_cause_id": cause or identifier,
        "assumptions": list(assumptions),
        "dependencies": [],
    }


class EndToEndEnclosureTests(unittest.TestCase):
    def project(self, source: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "model.py"; path.write_text(source, encoding="utf-8")
        return temporary, path

    def exact(self):
        return FormulaTracer(ROOT / "examples/end_to_end_audit/exact.py",
                             project_root=ROOT / "examples/end_to_end_audit").analyze(ranges={"x": (1, 2)})

    def test_e2e_a_exact_chain_is_kernel_verified(self):
        result = self.exact(); output = result.get_output("y")
        self.assertEqual(output.end_to_end_status, "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS")
        self.assertEqual(result.end_to_end_status, "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS")
        self.assertEqual(output.total_error_bound["exact_value"], 0)
        self.assertEqual(output.true_value_enclosure["lower"], 5)
        self.assertEqual(output.true_value_enclosure["upper"], 8)
        layers = {item["layer"] for item in output.end_to_end_claim["verification_matrix"]}
        self.assertTrue({"THEORY", "IMPLEMENTATION", "THEORY_IMPLEMENTATION", "TRANSFORMATION",
                         "APPROXIMATION", "NUMERIC_EXECUTION", "PARALLEL", "RANGE", "ERROR",
                         "FFI", "SERIALIZATION", "ARTIFACT", "LEAN"} <= layers)
        chain = output.end_to_end_claim["proof_chain"]
        self.assertEqual(chain["status"], "PROOF_CHAIN_COMPLETE")
        self.assertEqual(len(chain["nodes"]), 7)
        self.assertEqual(len(chain["edges"]), 6)
        self.assertTrue(any(item["kind"] == "THEORY_IMPLEMENTATION_EQUIVALENCE"
                            and item["proof_authority"] for item in chain["evidence"]))

    def test_e2e_b_approximation_bound_and_rounding_close_under_assumptions(self):
        result = self.exact(); output = result.outputs[0]
        output.implementation["numeric_execution"] = {"dtype": "float64"}
        output.error_components = [
            component("central", "APPROXIMATION_ERROR", 0.2, assumptions=["h > 0", "|f'''| <= M"]),
            component("rounding", "ROUNDING_ERROR", 0.01),
        ]
        result = analyze_project_ranges(result, {"x": (1, 2)})
        output = result.outputs[0]
        self.assertEqual(output.end_to_end_status, "END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS")
        self.assertEqual(output.end_to_end_claim["error_completeness_status"], "ERROR_MODEL_COMPLETE_UNDER_ASSUMPTIONS")
        assumptions = {item["assumption"] for item in output.end_to_end_claim["assumptions"]}
        self.assertTrue({"h > 0", "|f'''| <= M", "x in [1, 2]"} <= assumptions)

    def test_e2e_c_unresolved_rounding_prevents_total_verification(self):
        result = self.exact(); output = result.outputs[0]
        output.implementation["numeric_execution"] = {"dtype": "float64"}
        output.error_components = [component("central", "APPROXIMATION_ERROR", 0.2, assumptions=["h > 0"])]
        output = analyze_project_ranges(result, {"x": (1, 2)}).outputs[0]
        self.assertEqual(output.range_status, "TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED")
        self.assertEqual(output.end_to_end_status, "PARTIAL_END_TO_END_VERIFICATION")
        self.assertIn("ROUNDING_ERROR", json.dumps(output.remaining_obligations))

    def test_e2e_d_artifact_materialization_is_not_payload_proof(self):
        temporary, source = self.project(
            "import cpp_audit as audit\nimport xarray as xr\n"
            "@audit.theory(output='score', expression='score = x * 2')\n"
            "def write(x):\n    score=x*2\n    ds=xr.Dataset()\n    ds['score']=score\n    ds.to_netcdf('result.nc')\n")
        result = FormulaTracer(source).analyze(ranges={"x": (1, 2)})
        artifact_path = Path(temporary.name) / "result.nc"; artifact_path.write_bytes(b"materialized-not-validated")
        result.artifacts[0].path_expression = str(artifact_path)
        claim = build_end_to_end_claims(result).get_output("score").end_to_end_claim
        artifact = claim["artifact"][0]
        self.assertEqual(artifact["materialization_status"], "ARTIFACT_MATERIALIZED")
        self.assertEqual(artifact["status"], "ARTIFACT_PAYLOAD_ENCLOSURE_UNRESOLVED")
        self.assertIsNotNone(artifact["artifact_hash"])
        result.artifacts[0].library_contract = {"value_preserving": True, "proof_status": "REFERENCE_CONTRACT_VERIFIED"}
        artifact = build_end_to_end_claims(result).get_output("score").artifact_enclosure[0]
        self.assertEqual(artifact["status"], "ARTIFACT_PAYLOAD_ENCLOSURE_VERIFIED")

    def test_e2e_e_cross_language_unresolved_ffi_is_not_skipped(self):
        output = FormulaTracer(ROOT / "examples/cross_language_cpp_audit/analysis.py").analyze(
            ranges={"signal": {"lower": 0, "upper": 1, "shape": [8]}}).outputs[0]
        matrix = {item["layer"]: item["status"] for item in output.end_to_end_claim["verification_matrix"]}
        self.assertEqual(matrix["FFI"], "UNRESOLVED")
        self.assertNotIn(output.end_to_end_status, {"END_TO_END_KERNEL_VERIFIED", "END_TO_END_ENCLOSURE_VERIFIED"})

    def test_e2e_f_multi_output_keeps_independent_statuses_and_coverage(self):
        _, source = self.project("def compute(x):\n    good=x-x\n    bad=x+1\n    return good,bad\n")
        result = FormulaTracer(source).analyze(ranges={"x": (0, 1)},
            output_ranges={"good": (0, 0), "bad": (10, 20)})
        self.assertNotEqual(result.outputs[0].end_to_end_claim["claim_id"], result.outputs[1].end_to_end_claim["claim_id"])
        self.assertEqual(result.get_output("bad").end_to_end_status, "END_TO_END_FAILED")
        self.assertEqual(result.end_to_end_coverage["number_of_outputs"], 2)
        self.assertEqual(result.end_to_end_coverage["failed"], 1)

    def test_runtime_observation_never_substitutes_for_formal_layers(self):
        _, source = self.project("def compute(x):\n    return x+1\n")
        within = FormulaTracer(source).analyze(ranges={"x": (0, 1)}, observed_results={"compute": 1.5}).outputs[0]
        self.assertEqual(within.end_to_end_claim["observed_result_status"], "OBSERVED_VALUE_COMPARISON_UNRESOLVED")
        self.assertNotIn(within.end_to_end_status, {"END_TO_END_KERNEL_VERIFIED", "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"})
        outside = self.exact()
        outside = build_end_to_end_claims(outside, observed_results={"y": 100}).outputs[0]
        self.assertEqual(outside.end_to_end_status, "END_TO_END_FAILED")

    def test_unknown_and_shared_error_sources_are_fail_closed_and_deduplicated(self):
        result = self.exact(); output = result.outputs[0]
        output.error_components = [component("first", "ROUNDING_ERROR", 0.1, cause="shared"),
                                   component("second", "ROUNDING_ERROR", 0.1, cause="shared"),
                                   component("unknown", "UNKNOWN_ERROR_SOURCE", 0.0, verified=False)]
        output = analyze_project_ranges(result, {"x": (1, 2)}).outputs[0]
        obligations = output.end_to_end_claim["remaining_obligations"]
        self.assertTrue(any(item["kind"] == "ERROR_SOURCE_UNRESOLVED" for item in obligations))
        self.assertLessEqual(sum("shared" in json.dumps(item) for item in obligations), 1)

    def test_output_constraint_overlap_is_not_proven(self):
        result = self.exact(); output = result.outputs[0]
        result = analyze_project_ranges(result, {"x": (1, 2)}, output_ranges={"y": (7, 10)})
        self.assertEqual(result.outputs[0].range_constraint_status, "OUTPUT_RANGE_CONSTRAINT_NOT_PROVEN")
        self.assertNotIn(result.outputs[0].end_to_end_status, {"END_TO_END_KERNEL_VERIFIED", "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"})

    def test_tolerance_and_display_rounding_do_not_narrow_machine_enclosure(self):
        result = self.exact(); output = result.outputs[0]
        output.error_components = [component("rounding", "ROUNDING_ERROR", 0.1)]
        result = analyze_project_ranges(result, {"x": (1, 2)})
        result = build_end_to_end_claims(result, error_specifications={
            "y": ErrorSpecification(absolute_tolerance=0.2),
        })
        machine = result.outputs[0].true_value_enclosure["lower"]
        latex = result.to_latex()
        self.assertEqual(result.outputs[0].end_to_end_claim["tolerance_status"], "TOTAL_TOLERANCE_PROVEN")
        self.assertIn("4.9", latex)
        self.assertLess(machine, 4.9)

    def test_schema_json_and_human_certificate(self):
        result = self.exact(); payload = result.to_dict()
        schema_root = ROOT / "schemas"
        project_schema = json.loads((schema_root / "project-audit-result.schema.json").read_text(encoding="utf-8"))
        names = ["project-dependency-graph.schema.json", "output-sink.schema.json", "end-to-end-verification-claim.schema.json"]
        registry = Registry()
        for name in names:
            schema = json.loads((schema_root / name).read_text(encoding="utf-8"))
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        jsonschema.Draft202012Validator(project_schema, registry=registry).validate(payload)
        latex = result.to_latex()
        self.assertIn("y = 3 \\, x + 2", latex)
        self.assertNotIn("[U+79D1]", latex)
        self.assertIn("Overall End-to-End Status", latex)


if __name__ == "__main__":
    unittest.main()
