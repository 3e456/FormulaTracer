from __future__ import annotations

import math
from pathlib import Path

from cpp_audit import AuditMode, RoundingMode, analyze_ieee754, analyze_numeric_types, execute_audit
from cpp_audit.python_audit import audit_python


def source(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "floating.py"; path.write_text(body, encoding="utf-8"); return path


def analyze(path: Path, inputs: dict, dtypes: dict):
    static = audit_python(path, function="f", output="y", mode=AuditMode.REPORT_ONLY, verify_lean=False)
    types = analyze_numeric_types(path, function="f", output="y", inputs=inputs, input_dtypes=dtypes)
    return analyze_ieee754(path, function="f", inputs=inputs, numeric_types=types,
                           implementation_ir=static.implementation, theory_ir=static.theory,
                           mathematical_match=bool(static.comparison and static.comparison["match"]))


def test_float_format_and_operation_contract(tmp_path: Path):
    path = source(tmp_path, "import cpp_audit as audit\n@audit.theory(output='y', expression='y = a + b')\ndef f(a,b):\n    y=a+b\n    return y\n")
    result = analyze(path, {"a": 1.0, "b": 2.0}, {"a": "float32", "b": "float32"})
    assert result.formats["a"]["precision_bits"] == 24
    assert result.operations[0].rounding == "ROUND_TO_NEAREST_TIES_TO_EVEN"
    assert result.equivalence["MATHEMATICAL_EQUIVALENCE"]["status"] == "ESTABLISHED"
    assert result.equivalence["BITWISE_EQUIVALENCE"]["status"] == "NOT_APPLICABLE"


def test_real_reassociation_is_not_float_equivalence(tmp_path: Path):
    path = source(tmp_path, "import cpp_audit as audit\n@audit.theory(output='y', expression='y = (a + b) + c')\ndef f(a,b,c):\n    y=a+(b+c)\n    return y\n")
    result = analyze(path, {"a": 1e20, "b": -1e20, "c": 3.0}, {"a": "float64", "b": "float64", "c": "float64"})
    assert result.equivalence["MATHEMATICAL_EQUIVALENCE"]["status"] == "ESTABLISHED"
    assert result.equivalence["NUMERIC_EXECUTION_EQUIVALENCE"]["status"] == "NOT_ESTABLISHED"
    assert any(item["code"] == "REAL_EQUIVALENT_FLOAT_REASSOCIATION" for item in result.non_associativity_risks)


def test_reduction_order_is_an_explicit_risk(tmp_path: Path):
    path = source(tmp_path, "import numpy as np\nimport cpp_audit as audit\n@audit.theory(output='y', expression='y = sum(i=0..I-1, x[i])')\ndef f(x):\n    y=np.sum(x)\n    return y\n")
    result = analyze(path, {"x": [1.0, 2.0]}, {"x": "float32"})
    assert result.operations[0].evaluation_order == "LIBRARY_REDUCTION_OR_CONTRACTION_ORDER"
    assert result.non_associativity_risks[0]["code"] == "FLOAT_REDUCTION_REORDERING"


def test_nan_inf_signed_zero_and_subnormal_are_observed(tmp_path: Path):
    path = source(tmp_path, "def f(x):\n    y=x+1.0\n    return y\n")
    inputs = {"x": [math.nan, math.inf, -math.inf, -0.0, float.fromhex('0x0.0000000000001p-1022')]}
    types = analyze_numeric_types(path, function="f", output="y", inputs=inputs, input_dtypes={"x": "float64"})
    result = analyze_ieee754(path, function="f", inputs=inputs, numeric_types=types)
    assert {item["kind"] for item in result.special_value_observations} == {"NaN", "+Inf", "-Inf", "SIGNED_NEGATIVE_ZERO", "SUBNORMAL_BINARY64"}


def test_unknown_rounding_fails_closed_but_report_only_completes(tmp_path: Path):
    path = source(tmp_path, "import cpp_audit as audit\n@audit.theory(output='y', expression='y = x + 1')\ndef f(x):\n    y=x+1\n    return y\n")
    certificate = execute_audit(path, inputs={"x": 1.0}, input_dtypes={"x": "float64"}, function="f", output="y",
                                rounding_mode=RoundingMode.UNKNOWN, mode=AuditMode.REPORT_ONLY, verify_lean=False)
    assert certificate.status == "VERIFICATION_FAILED"
    assert certificate.ieee754_semantics["status"] == "IEEE754_CONTRACT_UNRESOLVED"
    assert any(item["code"] == "ROUNDING_MODE_UNRESOLVED" for item in certificate.diagnostics)


def test_certificate_has_three_independent_equivalence_levels(tmp_path: Path):
    path = source(tmp_path, "import cpp_audit as audit\n@audit.theory(output='y', expression='y = x * 2')\ndef f(x):\n    y=x*2\n    return y\n")
    certificate = execute_audit(path, inputs={"x": 1.5}, input_dtypes={"x": "float32"}, function="f", output="y", verify_lean=False)
    assert set(certificate.ieee754_semantics["equivalence"]) == {"MATHEMATICAL_EQUIVALENCE", "NUMERIC_EXECUTION_EQUIVALENCE", "BITWISE_EQUIVALENCE"}
    assert "ieee754_semantics_hash" in certificate.verification_certificate
