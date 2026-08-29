"""Focused soundness/parity gate for Wave 3 native interval semantics."""
from __future__ import annotations
import json
import math
from pathlib import Path
from cpp_audit.interval import Interval, interval_add, interval_div, interval_mul, interval_power
from formulatracer.native import NativeContext

OUT = Path("output/native_migration/final/waves/wave3-interval-parity.json")

def native(action: str, **payload):
    with NativeContext() as context:
        return context.execute_kernel({"schema_version":"1.0","kernel":"C","operation":"LEGACY_INTERVAL","action":action,**payload})["result"]

def main() -> int:
    cases = []
    def check(name: str, passed: bool, invariant: str): cases.append({"case":name,"passed":bool(passed),"invariant":invariant})
    exact = interval_add(Interval(1, 2), Interval(3, 4)); check("exact_integer_add", (exact.lower, exact.upper) == (4, 6), "integer arithmetic remains exact")
    product = interval_mul(Interval(-2, 3), Interval(-4, 5)); check("four_corner_product", (product.lower, product.upper) == (-12, 15), "all endpoint products considered")
    divided = interval_div(Interval(1, 2), Interval(-1, 1)); check("division_zero_crossing", not divided.resolved and divided.provenance.get("diagnostic") == "DIVISION_INTERVAL_CROSSES_ZERO", "zero-crossing never certified")
    square = interval_power(Interval(-2, 3), 2); check("even_power_crossing_zero", (square.lower, square.upper) == (0, 9), "even power contains zero")
    sine = native("ELEMENTARY", function="Sin", value={"lower":0,"upper":math.pi,"status":"INTERVAL_ARITHMETIC_VERIFIED"}, node={"op":"Sin"}); check("periodic_critical_point", sine["upper"] == 1.0, "critical points included")
    bad = native("ELEMENTARY", function="Sqrt", value={"lower":-1,"upper":4,"status":"INTERVAL_ARITHMETIC_VERIFIED"}, node={"op":"Sqrt"}); check("sqrt_domain_fail_closed", bad["status"] == "INTERVAL_UNRESOLVED", "invalid domain unresolved")
    condition = native("CONDITION", operator=">", left={"lower":2,"upper":4,"status":"INTERVAL_ARITHMETIC_VERIFIED"}, right={"lower":0,"upper":0,"status":"EXACT_SINGLETON"}, left_node={"op":"FreeVariable","name":"x"}, right_node={"op":"Constant","value":0}); check("branch_feasibility", condition["status"] == "BRANCH_PROVEN_TRUE", "branch status native")
    payload = {"schema_version":"1.0","wave":3,"component":"interval","cases":cases,"passed":sum(x["passed"] for x in cases),"total":len(cases),"false_acceptance":0 if all(x["passed"] for x in cases) else 1,"status":"PASS" if all(x["passed"] for x in cases) else "FAIL"}
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8"); print(f"{payload['passed']}/{payload['total']} {payload['status']}")
    return 0 if payload["status"] == "PASS" else 1
if __name__ == "__main__": raise SystemExit(main())
