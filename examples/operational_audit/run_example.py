"""Run the public, independent synthetic operational example."""

from __future__ import annotations

import json
from pathlib import Path

from cpp_audit import AuditMode, audit_python
from cpp_audit.expression import load_transformation_set
from cpp_audit.transformations import apply_transformation_set


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).with_name("implementation.py")
RULES = ROOT / "registry" / "transformations" / "rules"
SCIENTIFIC = ROOT / "registry" / "transformations" / "sets" / "scientific_default.yaml"


def variable(name: str) -> dict[str, str]:
    return {"op": "FreeVariable", "name": name}


def expression_ir(expression: dict[str, object], target: str) -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "status": "EXPRESSION_EXTRACTED",
        "outputs": [{"target": variable(target), "expression": expression}],
        "expression_id": f"synthetic-{target}",
    }


def exact_case() -> dict[str, object]:
    result = audit_python(
        SOURCE,
        output="weighted_score",
        function="weighted_score",
        mode=AuditMode.REPORT_ONLY,
        verify_lean=False,
    )
    expression = result.implementation["outputs"][0]["expression"]
    return {
        "status": result.status,
        "comparison_match": bool(result.comparison and result.comparison["match"]),
        "implementation_root": expression["op"],
    }


def relational_case() -> dict[str, object]:
    theory = expression_ir(
        {
            "op": "Derivative",
            "order": 1,
            "variable": "x",
            "expression": {"op": "FunctionCall", "name": "f", "args": [variable("x")]},
        },
        "derivative",
    )
    implementation = expression_ir(
        {
            "op": "Divide",
            "args": [
                {
                    "op": "Subtract",
                    "args": [
                        {"op": "FunctionCall", "name": "f", "args": [{"op": "Add", "args": [variable("x"), variable("h")]}]},
                        {"op": "FunctionCall", "name": "f", "args": [{"op": "Subtract", "args": [variable("x"), variable("h")]}]},
                    ],
                },
                {"op": "Multiply", "args": [{"op": "Constant", "value": 2}, variable("h")]},
            ],
        },
        "estimate",
    )
    transformation_set = load_transformation_set(SCIENTIFIC)
    result = apply_transformation_set(
        theory,
        implementation,
        transformation_set,
        rules_root=RULES,
        context={
            "finite_domain": True,
            "spacing": "h",
            "spacing_resolved": True,
            "stencil_region": "interior",
            "required_observables": ["frequency_response"],
        },
        selection_profile="minimum_error",
    )
    return {
        "status": result.status,
        "relation": result.comparison_relation,
        "remaining_obligations": len(result.remaining_obligations),
    }


def unresolved_case() -> dict[str, object]:
    result = audit_python(
        SOURCE,
        output="adjusted",
        function="opaque_adjustment",
        mode=AuditMode.REPORT_ONLY,
        verify_lean=False,
    )
    expression = result.implementation["outputs"][0]["expression"]
    return {"status": result.status, "operation": expression["op"]}


def main() -> int:
    report = {
        "schema_version": "1.0",
        "example_origin": "INDEPENDENT_SYNTHETIC",
        "exact": exact_case(),
        "relational": relational_case(),
        "unresolved": unresolved_case(),
    }
    report["false_acceptance"] = int(
        not report["exact"]["comparison_match"]
        or report["relational"]["relation"] != "DISCRETIZATION_OF"
        or report["unresolved"]["operation"] != "OpaqueNumericCall"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report["false_acceptance"]


if __name__ == "__main__":
    raise SystemExit(main())
