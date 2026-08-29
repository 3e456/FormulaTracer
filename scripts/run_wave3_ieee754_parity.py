from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile

from cpp_audit import AuditMode, RoundingMode, analyze_ieee754, analyze_numeric_types
from cpp_audit.ieee754 import _native_ieee754
from cpp_audit.python_audit import audit_python


ROOT = Path(__file__).resolve().parents[1]


def analyze(body: str, inputs: dict, dtypes: dict, *, rounding=RoundingMode.ROUND_TO_NEAREST_TIES_TO_EVEN):
    with tempfile.TemporaryDirectory(prefix="formulatracer-wave3-ieee-") as directory:
        path = Path(directory) / "case.py"; path.write_text(body, encoding="utf-8")
        static = audit_python(path, function="f", output="y", mode=AuditMode.REPORT_ONLY, verify_lean=False)
        types = analyze_numeric_types(path, function="f", output="y", inputs=inputs, input_dtypes=dtypes)
        return analyze_ieee754(path, function="f", inputs=inputs, numeric_types=types,
            implementation_ir=static.implementation, theory_ir=static.theory,
            mathematical_match=bool(static.comparison and static.comparison["match"]), rounding_mode=rounding)


def main() -> int:
    exact = analyze("import cpp_audit as audit\n@audit.theory(output='y', expression='y = a + b')\ndef f(a,b):\n return a+b\n",
                    {"a": 1.0, "b": 2.0}, {"a": "float32", "b": "float32"})
    reassociated = analyze("import cpp_audit as audit\n@audit.theory(output='y', expression='y = (a + b) + c')\ndef f(a,b,c):\n return a+(b+c)\n",
                           {"a": 1e20, "b": -1e20, "c": 3.0}, {"a": "float64", "b": "float64", "c": "float64"})
    specials = analyze("def f(x):\n return x+1.0\n",
        {"x": [math.nan, math.inf, -math.inf, 0.0, -0.0, float.fromhex("0x0.0000000000001p-1022")]}, {"x": "float64"})
    unknown = analyze("def f(x):\n return x+1.0\n", {"x": 1.0}, {"x": "float64"}, rounding=RoundingMode.UNKNOWN)
    classified = {kind: _native_ieee754("CLASSIFY_VALUE", kind=kind) for kind in ["NaN", "+Inf", "-Inf", "SIGNED_NEGATIVE_ZERO"]}
    cases = [
        {"case": "finite-format", "match": exact.formats["a"]["precision_bits"] == 24},
        {"case": "mathematical-vs-floating", "match": reassociated.equivalence["NUMERIC_EXECUTION_EQUIVALENCE"]["status"] == "NOT_ESTABLISHED"},
        {"case": "nan-not-real", "match": not classified["NaN"]["ordinary_real"]},
        {"case": "infinity-not-mathematical-infinity", "match": all(not classified[k]["mathematical_infinity"] for k in ["+Inf", "-Inf"])},
        {"case": "signed-zero-preserved", "match": classified["SIGNED_NEGATIVE_ZERO"]["signed_zero_preserved"]},
        {"case": "special-observations", "match": {x["kind"] for x in specials.special_value_observations} >= {"NaN", "+Inf", "-Inf", "SIGNED_NEGATIVE_ZERO", "SUBNORMAL_BINARY64"}},
        {"case": "unknown-rounding-fails-closed", "match": unknown.status == "IEEE754_CONTRACT_UNRESOLVED"},
    ]
    passed = sum(bool(case["match"]) for case in cases)
    payload = {"schema_version": "1.0", "owner": "cpp_audit.ieee754", "native_operation": "A/LEGACY_IEEE754",
               "cases": cases, "passed": passed, "total": len(cases),
               "false_acceptance": 0 if all(case["match"] for case in cases[1:]) else 1,
               "status": "PASS" if passed == len(cases) else "FAIL"}
    output = ROOT / "output/native_migration/final/waves/wave3-ieee754-parity.json"
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
