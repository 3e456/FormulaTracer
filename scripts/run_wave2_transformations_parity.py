from __future__ import annotations

import json
from pathlib import Path

from cpp_audit.transformations import apply_transformation_set, bounded_rewrite_search


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "registry/transformations/rules"


def variable(name: str) -> dict:
    return {"op": "FreeVariable", "name": name}


def constant(value: int | float) -> dict:
    return {"op": "Constant", "value": value}


def ir(expression: dict) -> dict:
    return {"schema_version": "1.0", "outputs": [{"name": "out", "expression": expression}]}


def transformation_set(*, exact: list[str] | None = None,
                       approximation: list[str] | None = None,
                       hard: dict | None = None) -> dict:
    return {"id": "wave2-parity", "version": "1", "exact_rules": exact or [],
            "approximation_rules": approximation or [], "hard_constraints": hard or {}}


def main() -> int:
    cases: list[dict] = []

    exact = apply_transformation_set(
        ir({"op": "Add", "args": [variable("x"), constant(0)]}), ir(variable("value")),
        transformation_set(exact=["alpha_rename", "neutral_element_elimination"]), rules_root=RULES)
    cases.append({"case": "exact-neutral", "expected": "TRANSFORMATION_APPLIED",
                  "actual": exact.status, "match": exact.status == "TRANSFORMATION_APPLIED"})

    conditional = apply_transformation_set(
        ir({"op": "Divide", "args": [variable("x"), variable("d")]}),
        ir({"op": "Multiply", "args": [variable("x"), {"op": "Divide", "args": [constant(1), variable("d")]}]}),
        transformation_set(exact=["division_rewrite_nonzero"]), rules_root=RULES)
    cases.append({"case": "unknown-condition-fails-closed", "expected": "TRANSFORMATION_OBLIGATION_REMAINING",
                  "actual": conditional.status, "match": conditional.status == "TRANSFORMATION_OBLIGATION_REMAINING"})

    derivative = {"op": "Derivative", "order": 1, "variable": "x",
                  "expression": {"op": "FunctionCall", "name": "f", "args": [variable("x")]}}
    failed = apply_transformation_set(
        ir(derivative), ir(variable("z")),
        transformation_set(approximation=["central_difference_first_derivative"], hard={"finite_domain_required": True}),
        rules_root=RULES, context={})
    cases.append({"case": "hard-constraint-before-selection", "expected": "TRANSFORMATION_CONSTRAINT_FAILED",
                  "actual": failed.status, "match": failed.status == "TRANSFORMATION_CONSTRAINT_FAILED"})

    rewrite = bounded_rewrite_search(
        {"op": "Add", "args": [{"op": "Divide", "args": [variable("a"), variable("d")]},
                                  {"op": "Divide", "args": [variable("b"), variable("d")]}]},
        {"op": "Divide", "args": [{"op": "Add", "args": [variable("a"), variable("b")]}, variable("d")]},
        authorized_rule_ids=["factor_common_denominator"], relevant_motifs=["add", "divide"])
    cases.append({"case": "authorized-exact-rewrite", "expected": "REWRITE_PATH_FOUND",
                  "actual": rewrite.status, "match": rewrite.status == "REWRITE_PATH_FOUND"})

    nonexact = bounded_rewrite_search(
        derivative, variable("z"), authorized_rule_ids=["finite_difference_first_derivative"],
        relevant_motifs=["derivative"])
    cases.append({"case": "nonexact-never-enters-exact-search", "expected": "NO_AUTHORIZED_REWRITE_PATH",
                  "actual": nonexact.status, "match": nonexact.status != "REWRITE_PATH_FOUND"})

    passed = sum(bool(case["match"]) for case in cases)
    payload = {"schema_version": "1.0", "owner": "cpp_audit.transformations",
               "native_operation": "B/LEGACY_TRANSFORMATIONS", "cases": cases,
               "passed": passed, "total": len(cases),
               "false_acceptance": 0 if cases[-1]["match"] else 1,
               "status": "PASS" if passed == len(cases) else "FAIL"}
    output = ROOT / "output/native_migration/final/waves/wave2-transformations-parity.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
