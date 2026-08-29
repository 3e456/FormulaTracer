from __future__ import annotations

import json
from pathlib import Path

import pytest

from cpp_audit import AuditMode, analyze_numeric_types, execute_audit, execution_type, infer_value_type


ROOT = Path(__file__).resolve().parents[1]


def source(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "numeric_types.py"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.parametrize("dtype,kind,bits,domain", [
    ("int8", "integer", 8, "Integer"), ("int64", "integer", 64, "Integer"),
    ("uint32", "integer", 32, "Natural"), ("float32", "float", 32, "Real"),
    ("float64", "float", 64, "Real"), ("complex128", "complex", 128, "Complex"),
    ("bool", "bool", 1, "Boolean"),
])
def test_execution_type_catalog(dtype: str, kind: str, bits: int, domain: str):
    value = execution_type(dtype)
    assert (value.kind, value.bits, value.mathematical_domain) == (kind, bits, domain)


def test_python_int_is_unbounded_but_numpy_int_wraps():
    assert execution_type("python.int").overflow == "UNBOUNDED_INTEGER"
    assert execution_type("int32").overflow == "MODULAR_WRAP"


def test_float_domain_is_separate_from_execution_dtype():
    value = execution_type("float32")
    assert value.mathematical_domain == "Real"
    assert value.dtype == "float32"
    assert value.underflow == "GRADUAL_SUBNORMAL"


def test_input_override_is_a_contract_not_a_value_guess():
    value = infer_value_type([1.0, 2.0], {"dtype": "float32", "container": "xarray.DataArray",
                                                   "dimensions": ["time"]})
    assert value.dtype == "float32" and value.provenance == "caller dtype contract"
    assert value.dimensions == ["time"] and value.shape == [2]


def test_explicit_cast_and_mixed_dtype_promotion(tmp_path: Path):
    path = source(tmp_path, "import numpy as np\ndef f(x, y):\n    a = x.astype(np.float32)\n    z = a + y\n    return z\n")
    result = analyze_numeric_types(path, function="f", output="z", inputs={"x": [1], "y": [2]},
                                   input_dtypes={"x": "int16", "y": "float64"})
    assert result.status == "TYPE_RESOLVED"
    assert result.outputs["z"].dtype == "float64"
    assert result.casts[0].source == "int16" and result.casts[0].target == "float32"
    assert result.promotions[-1].rule == "FLOAT_WIDENING"


def test_signed_unsigned_promotion_is_explicit(tmp_path: Path):
    path = source(tmp_path, "def f(x, y):\n    z=x+y\n    return z\n")
    result = analyze_numeric_types(path, function="f", output="z", inputs={"x": [1], "y": [2]},
                                   input_dtypes={"x": "int32", "y": "uint32"})
    assert result.outputs["z"].dtype == "int64"
    assert result.promotions[0].rule == "SIGNED_UNSIGNED_SAFE_WIDENING"


def test_numpy_mean_integer_promotes_to_float64(tmp_path: Path):
    path = source(tmp_path, "import numpy as np\ndef f(x):\n    y=np.mean(x)\n    return y\n")
    result = analyze_numeric_types(path, function="f", output="y", inputs={"x": [1, 2]},
                                   input_dtypes={"x": "int16"})
    assert result.outputs["y"].dtype == "float64"


def test_array_creation_dtype_and_shape(tmp_path: Path):
    path = source(tmp_path, "import numpy as np\ndef f():\n    y=np.zeros((2, 3), dtype=np.float32)\n    return y\n")
    result = analyze_numeric_types(path, function="f", output="y")
    assert result.outputs["y"].dtype == "float32"
    assert result.outputs["y"].shape == [2, 3]
    assert result.outputs["y"].container == "numpy.ndarray"


def test_xarray_dimensions_survive_cast_and_arithmetic(tmp_path: Path):
    path = source(tmp_path, "import xarray as xr\ndef f(x):\n    a=x.astype('float32')\n    y=a * 2\n    return y\n")
    result = analyze_numeric_types(path, function="f", output="y", inputs={"x": [[1, 2]]},
        input_dtypes={"x": {"dtype": "int16", "container": "xarray.DataArray", "dimensions": ["row", "col"]}})
    assert result.outputs["y"].dimensions == ["row", "col"]
    assert result.outputs["y"].container == "xarray.DataArray"


def test_receiver_mean_and_default_global_constants(tmp_path: Path):
    path = source(tmp_path, "OFFSET=2.0\ndef f(x, scale=3):\n    shifted=x+OFFSET\n    y=shifted.mean() * scale\n    return y\n")
    result = analyze_numeric_types(path, function="f", output="y", inputs={"x": [1, 2]},
                                   input_dtypes={"x": {"dtype": "int16", "container": "xarray.DataArray", "dimensions": ["time"]}})
    assert result.status == "TYPE_RESOLVED"
    assert result.values["shifted"].dtype == "float64"
    assert result.values["scale"].provenance == "default argument"
    assert result.outputs["y"].dtype == "float64"


def test_unknown_call_fails_type_resolution_without_stopping_report(tmp_path: Path):
    path = source(tmp_path, "import cpp_audit as audit\n@audit.theory(output='y', expression='y = x')\ndef f(x):\n    y=external(x)\n    return y\n")
    analysis = analyze_numeric_types(path, function="f", output="y", inputs={"x": 1})
    assert analysis.status == "TYPE_UNRESOLVED"
    assert analysis.diagnostics[0]["code"] == "CALL_DTYPE_UNRESOLVED"
    certificate = execute_audit(path, inputs={"x": 1}, function="f", output="y",
                                mode=AuditMode.REPORT_ONLY, verify_lean=False)
    assert certificate.status == "VERIFICATION_FAILED"
    assert certificate.numeric_type_semantics["status"] == "TYPE_UNRESOLVED"


def test_certificate_records_float32_beside_real_ir():
    fixture = ROOT / "tests" / "fixtures" / "synthetic_weighted_reduction.py"
    inputs = {"samples": [[2, 3], [4, 5]], "weights": [1000, 2000]}
    certificate = execute_audit(fixture, inputs=inputs, function="calculate_weighted_score",
        output="weighted_score", input_dtypes={"samples": "float32", "weights": "float32"}, verify_lean=False)
    types = certificate.numeric_type_semantics
    assert types["inputs"]["samples"]["dtype"] == "float32"
    assert types["outputs"]["weighted_score"]["dtype"] == "float32"
    assert "Real" in types["mathematical_domain"]["domains"]


def test_numeric_type_schema_is_valid_json_schema():
    schema = json.loads((ROOT / "schemas" / "numeric-type-semantics.schema.json").read_text(encoding="utf-8"))
    assert schema["$defs"]["executionType"]["required"][-1] == "provenance"
