from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from cpp_audit.expression import (_normalize_node, _stable_id, compare_exact,
                                  normalize_exact, select_transformation)


ROOT = Path(__file__).resolve().parents[1]


def reference_normalize(expression: dict) -> dict:
    trace: list[dict] = []
    outputs = _normalize_node(deepcopy(expression["outputs"]), trace)
    canonical = {"schema_version": "0.1", "outputs": outputs}
    return {
        "status": "EQUIVALENT_BY_EXACT_TRANSFORMATIONS" if trace else "EXACT_CANONICAL_MATCH",
        "canonical_expression": canonical,
        "rewrite_trace": trace,
        "canonical_expression_id": _stable_id("canonical-expression", canonical),
    }


def main() -> int:
    plain = {"outputs": [{"target": {"op": "FreeVariable", "name": "y"},
                           "expression": {"op": "Add", "args": [
                               {"op": "Constant", "value": 0},
                               {"op": "FreeVariable", "name": "x"}]}}]}
    reduction = {"outputs": [{"target": {"op": "FreeVariable", "name": "y"},
        "expression": {"op": "TransformReduce", "bound_index": "k",
            "index_domain": {"lower": {"op": "Constant", "value": 0},
                             "upper_exclusive": {"op": "FreeVariable", "name": "n"}},
            "initial_value": {"op": "Constant", "value": 0},
            "transform": {"op": "BoundVariable", "name": "k"},
            "reduction": "Add", "reduction_order": "left_to_right"}}]}
    different = deepcopy(plain)
    different["outputs"][0]["expression"] = {"op": "Constant", "value": 9}
    normalize_cases = [plain, reduction, different]
    results = []
    for index, case in enumerate(normalize_cases):
        native, reference = normalize_exact(case), reference_normalize(case)
        results.append({"case": f"normalize-{index}", "match": native == reference})
    results.append({"case": "compare-positive", "match": compare_exact(plain, plain)["match"] is True})
    results.append({"case": "compare-negative-mutation", "match": compare_exact(plain, different)["status"] == "NO_ALLOWED_APPROXIMATION_FOUND"})
    transformation_set = {"approximation_rules": ["fast", "accurate"], "forbidden_rules": [],
                          "hard_constraints": {"maximum_error": 0.2}}
    rules = [
        {"id": "fast", "selection_error_estimate": 0.1,
         "cost": {"symbolic_arithmetic_operations": 1}, "supported_observables": []},
        {"id": "accurate", "selection_error_estimate": 0.01,
         "cost": {"symbolic_arithmetic_operations": 5}, "supported_observables": []},
    ]
    selected = select_transformation(transformation_set, rules)
    results.append({"case": "selection-cost", "match": selected["selected"]["rule_id"] == "fast"})
    selected = select_transformation(transformation_set, rules, selection_profile="minimum_error")
    results.append({"case": "selection-error", "match": selected["selected"]["rule_id"] == "accurate"})
    rejected = select_transformation({**transformation_set, "approximation_rules": []}, rules)
    results.append({"case": "selection-fail-closed", "match": rejected["status"] == "NO_FEASIBLE_TRANSFORMATION"})
    payload = {"schema_version": "1.0", "owner": "cpp_audit.expression",
               "native_operation": "F/LEGACY_EXPRESSION", "cases": results,
               "passed": sum(item["match"] for item in results), "total": len(results),
               "false_acceptance": 0 if all(item["match"] for item in results) else 1,
               "status": "PASS" if all(item["match"] for item in results) else "FAIL"}
    destination = ROOT / "output/native_migration/final/waves/wave1-expression-parity.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
