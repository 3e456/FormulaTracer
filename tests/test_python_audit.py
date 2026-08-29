from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import jsonschema

from cpp_audit.python_audit import AuditMode, audit_python


ROOT = Path(__file__).resolve().parents[1]


class PythonAuditTests(unittest.TestCase):
    def write(self, directory: str, text: str) -> Path:
        path = Path(directory) / "research.py"
        path.write_text(text, encoding="utf-8")
        return path

    @staticmethod
    def semantic_only(value):
        if isinstance(value, dict):
            ignored = {"source_span", "operator_span", "argument_spans", "condition_span", "branch_spans"}
            return {key: PythonAuditTests.semantic_only(item) for key, item in value.items() if key not in ignored}
        if isinstance(value, list):
            return [PythonAuditTests.semantic_only(item) for item in value]
        return value

    def test_semantic_noise_does_not_change_numeric_ir(self) -> None:
        plain = '''import cpp_audit as audit
@audit.theory(output="y", expression="y = x + 1")
def calculate(x):
    return x + 1
'''
        noisy = '''import cpp_audit as audit
@audit.theory(output="y", expression="y = x + 1")
def calculate(x):
    """URL https://example.invalid/a+b and Markdown: `x * y`."""
    note = f"display only: {x} / 2"
    print("title: a+b*c", note)
    # The symbols + - * / below are comments, never mathematical dependencies.
    return x + 1
'''
        with tempfile.TemporaryDirectory() as directory:
            first = audit_python(self.write(directory, plain), mode="REPORT_ONLY", verify_lean=False)
            second_path = Path(directory) / "noisy.py"
            second_path.write_text(noisy, encoding="utf-8")
            second = audit_python(second_path, mode="REPORT_ONLY", verify_lean=False)
        left = first.implementation["outputs"][0]["expression"]
        right = second.implementation["outputs"][0]["expression"]
        self.assertEqual(self.semantic_only(left), self.semantic_only(right))
        self.assertFalse(second.diagnostics)

    def test_semantic_string_consumers_are_never_executed(self) -> None:
        source = '''import cpp_audit as audit
@audit.theory(output="y", expression="y = x + 1")
def calculate(x):
    return eval("x + 1")
'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        expression = result.implementation["outputs"][0]["expression"]
        self.assertEqual("OpaqueNumericCall", expression["op"])
        self.assertFalse(expression["semantic_string"]["executed_by_analyzer"])
        self.assertIn("SEMANTIC_STRING_UNRESOLVED", {item["code"] for item in result.diagnostics})

    def test_explicit_custom_operator_owner_is_fail_closed(self) -> None:
        source = '''import cpp_audit as audit
class Quantity: pass
@audit.theory(output="y", expression="y = x + x")
def calculate(x: Quantity):
    return x + x
'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        self.assertEqual("OpaqueNumericCall", result.implementation["outputs"][0]["expression"]["op"])
        self.assertIn("OVERLOADED_OPERATOR_SEMANTICS_UNRESOLVED",
                      {item["code"] for item in result.diagnostics})

    def test_numpy_weighted_sum_end_to_end_without_executing_source(self) -> None:
        result = audit_python(ROOT / "examples/python_audit/weighted_sum.py",
                              mode=AuditMode.REPORT_ONLY, verify_lean=False)
        self.assertTrue(result.comparison["match"])
        self.assertEqual("Map", result.implementation["outputs"][0]["expression"]["op"])
        self.assertIn("Σ", result.renderings["unicode"])
        self.assertIn("\\sum", result.renderings["latex"])
        self.assertEqual({"weighted_score": "weighted_score", "samples": "samples", "weights": "weights", "dim(samples,1)": "I"},
                         result.comparison["mapping"]["symbols"])
        json.loads(result.renderings["json"])

    def test_custom_function_is_inlined_and_temporaries_disappear(self) -> None:
        source = '''import numpy as np\nimport cpp_audit as audit\n\ndef scale(x, f):\n    tmp = x * f\n    return tmp\n\n@audit.theory(output="y", expression="y[r] = sum(i=0..N-1, x[r,i] * f[i])")\ndef calculate(x, f):\n    z = scale(x, f)\n    y = np.sum(z, axis=1)\n    return y\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        self.assertTrue(result.comparison["match"])
        self.assertIn("inlined_user_function", {item["classification"] for item in result.output_slice["calls"]})
        self.assertNotIn('"name": "tmp"', result.renderings["json"])

    def test_unknown_call_is_opaque_and_report_only_completes(self) -> None:
        source = '''import cpp_audit as audit\n@audit.theory(output="y", expression="y = x")\ndef calculate(x):\n    y = vendor.magic(x)\n    return y\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        self.assertEqual("PASS_WITH_FINDINGS", result.status)
        self.assertEqual("OpaqueNumericCall", result.implementation["outputs"][0]["expression"]["op"])
        self.assertIn("opaque_result_shape", {item["kind"] for item in result.implementation["shape_constraints"]})

    def test_backward_slice_excludes_unrelated_unknown_call(self) -> None:
        source = '''import cpp_audit as audit\n@audit.theory(output="y", expression="y = x + 1")\ndef calculate(x):\n    unrelated = vendor.magic(x)\n    tmp = x + 1\n    y = tmp\n    return y\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        self.assertTrue(result.comparison["match"])
        self.assertNotIn("OpaqueNumericCall", result.renderings["json"])
        self.assertFalse(result.diagnostics)

    def test_strict_mismatch_fails(self) -> None:
        source = '''import cpp_audit as audit\n@audit.theory(output="y", expression="y = x + 1")\ndef calculate(x):\n    return x - 1\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), output="y", mode="STRICT", verify_lean=False)
        self.assertEqual("FAIL", result.status)
        self.assertFalse(result.comparison["match"])

    def test_for_range_accumulator_normalizes_to_finite_sum(self) -> None:
        source = '''import cpp_audit as audit\n@audit.theory(output="y", expression="y = sum(i=0..N-1, x[i])")\ndef calculate(x, N):\n    acc = 0\n    for k in range(N):\n        acc += x[k]\n    y = acc\n    return y\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        self.assertTrue(result.comparison["match"])
        self.assertIn("For", {item["kind"] for item in result.output_slice["nodes"]})

    def test_if_else_comparison_and_slice_are_extracted(self) -> None:
        source = '''import cpp_audit as audit\n@audit.theory(output="y", expression="y = x")\ndef calculate(x, limit):\n    if x > limit:\n        y = x\n    else:\n        y = limit\n    return y\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        value = result.implementation["outputs"][0]["expression"]
        self.assertEqual("IfThenElse", value["op"])
        self.assertEqual("Compare", value["condition"]["op"])

    def test_simple_commutative_algebraic_equivalence(self) -> None:
        source = '''import cpp_audit as audit\n@audit.theory(output="y", expression="y = 1 + x")\ndef calculate(x):\n    return x + 1\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), output="y", mode="REPORT_ONLY", verify_lean=False)
        self.assertTrue(result.comparison["match"])

    def test_alpha_rename_builds_requested_symbol_mapping(self) -> None:
        source = '''import numpy as np\nimport cpp_audit as audit\n@audit.theory(output="score", expression="T[j] = sum(k=0..I-1, Q[j,k] * F[k])")\ndef calculate(quantity, factor):\n    return np.sum(quantity * factor, axis=1)\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), output="score", mode="REPORT_ONLY", verify_lean=False)
        self.assertTrue(result.comparison["match"])
        self.assertEqual("T", result.comparison["mapping"]["symbols"]["score"])
        self.assertEqual("Q", result.comparison["mapping"]["symbols"]["quantity"])
        self.assertEqual("j", result.comparison["mapping"]["bound_indices"]["r"])
        self.assertEqual("k", result.comparison["mapping"]["bound_indices"]["i"])
        self.assertIn("def implementationExpression", result.lean["source"])

    def test_all_required_numpy_calls_are_classified(self) -> None:
        source = '''import numpy as np\nimport cpp_audit as audit\n@audit.theory(output="y", expression="y = x")\ndef calculate(a, b, c):\n    y = (np.sum(a), np.prod(a), np.mean(a), np.dot(a,b), np.matmul(a,b), np.einsum("ij,j->i",a,b), np.where(c,a,b), np.clip(a,0,1), np.abs(a), np.sqrt(a), np.log(a), np.exp(a), np.power(a,2), np.reshape(a,(1,-1)), np.transpose(a), np.diff(a), np.gradient(a))\n    return y\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        self.assertNotIn("OpaqueNumericCall", result.renderings["json"])
        self.assertIn('"op": "DiscreteDifference"', result.renderings["json"])
        self.assertIn('"derivative_claim": false', result.renderings["json"])
        self.assertIn('"op": "FiniteDifference"', result.renderings["json"])
        self.assertIn('"boundary_stencil": "one_sided"', result.renderings["json"])

    def test_xarray_top_level_broadcast_is_alignment_aware(self) -> None:
        source = '''import xarray as xr\nimport cpp_audit as audit\n@audit.theory(output="y", expression="y = x")\ndef calculate(a,b):\n    y = xr.broadcast(a,b)\n    return y\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        self.assertTrue(any(item.get("operation") == "broadcast" for item in result.implementation["shape_constraints"]))

    def test_xarray_dimensions_and_labels_are_preserved(self) -> None:
        source = '''import xarray as xr\nimport cpp_audit as audit\n@audit.theory(output="y", expression="y = x")\ndef calculate(data):\n    x = xr.DataArray(data, dims=("region", "time"), coords={"time": [1, 2]})\n    y = x.sel(time=1).mean(dim="time")\n    return y\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        constraints = result.implementation["shape_constraints"]
        self.assertTrue(any(item.get("dimension_names_preserved") for item in constraints))
        self.assertIn("time", json.dumps(result.implementation, ensure_ascii=False))

    def test_xarray_diff_and_interp_keep_named_dimension_semantics(self) -> None:
        source = '''import xarray as xr\nimport cpp_audit as audit\n@audit.theory(output="y", expression="y = x")\ndef calculate(data):\n    x = xr.DataArray(data, dims=("time",))\n    delta = x.diff("time")\n    y = delta.interp(time=1.5, method="linear")\n    return y\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        rendered = result.renderings["json"]
        self.assertIn('"op": "DiscreteDifference"', rendered)
        self.assertIn('"dimension": "time"', rendered)
        self.assertIn('"label_alignment": "PRESERVED"', rendered)
        self.assertIn('"op": "Interpolation"', rendered)
        self.assertIn('"domain_status": "UNRESOLVED"', rendered)

    def test_expression_schema_accepts_python_extension_nodes(self) -> None:
        source = '''import cpp_audit as audit\n@audit.theory(output="y", expression="y = x")\ndef calculate(x):\n    return external(x)\n'''
        with tempfile.TemporaryDirectory() as directory:
            result = audit_python(self.write(directory, source), mode="REPORT_ONLY", verify_lean=False)
        schema = json.loads((ROOT / "schemas/expression-ir.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(result.implementation, schema)


if __name__ == "__main__":
    unittest.main()
