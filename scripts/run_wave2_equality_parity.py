from __future__ import annotations

import json
from pathlib import Path

from cpp_audit.equality_saturation import (MathematicalFact, MathematicalFactEngine,
    MathematicalRelationGraph, SaturationBudget, ExactEqualitySaturator, TypedEGraph,
    saturate_and_match)


ROOT = Path(__file__).resolve().parents[1]


def v(name: str) -> dict:
    return {"op": "FreeVariable", "name": name}


def main() -> int:
    cases: list[dict] = []
    expression = {"op": "FunctionCall", "name": "exp", "args": [
        {"op": "FunctionCall", "name": "log", "args": [v("x")]}]}
    blocked = saturate_and_match(expression, v("x"), authorized_rule_ids=["exp_log_cancel_positive"],
                                 motifs=["exp", "log"])
    cases.append({"case": "unknown-fact-blocks-exact-merge", "match": blocked.status == "EGRAPH_NO_EXACT_MATCH"
                  and blocked.saturation.status == "CONDITIONALLY_BLOCKED"})
    accepted = saturate_and_match(expression, v("x"), authorized_rule_ids=["exp_log_cancel_positive"],
                                  facts=["x > 0"], motifs=["exp", "log"])
    cases.append({"case": "discharged-fact-authorizes-exact-merge", "match": accepted.status == "EGRAPH_EXACT_MATCH"})

    derivative = {"op": "Derivative", "variable": "x", "body": v("f")}
    nonexact = saturate_and_match(derivative, {"op": "Divide", "args": [v("n"), v("h")]},
        authorized_rule_ids=["finite_difference_first_derivative"],
        facts=["spacing_nonzero", "smoothness", "local smoothness"], motifs=["derivative"])
    cases.append({"case": "nonexact-relation-never-merges", "match": nonexact.status == "EGRAPH_NO_EXACT_MATCH"
                  and not nonexact.saturation.trace})

    facts = MathematicalFactEngine([MathematicalFact("shape", (2, 3), subject="x")])
    conflict = MathematicalFactEngine([MathematicalFact("shape", (3, 2), subject="x")])
    cases.append({"case": "fact-conflict-fails-closed", "match": not facts.merge(conflict) and bool(facts.conflicts)})

    relation_rejected = False
    try:
        MathematicalRelationGraph().add("a", "b", "EXACT_EQUAL")
    except ValueError:
        relation_rejected = True
    cases.append({"case": "exact-equality-rejected-from-relation-graph", "match": relation_rejected})

    graph = TypedEGraph()
    root = graph.add({"op": "Add", "args": [v("x"), {"op": "Constant", "value": 0}]}, cost=3)
    graph.add_equivalent(root, v("x"), origin="neutral", cost=1)
    cases.append({"case": "native-cost-extraction", "match": graph.extract(root) == v("x")})

    _, budget = ExactEqualitySaturator(authorized_rule_ids=["factor_multiplication"],
        motifs=["add", "multiply"], budget=SaturationBudget(iterations=2, enodes=1, rule_applications=1)).run([
            {"op": "Add", "args": [{"op": "Multiply", "args": [v("a"), v("x")]},
                                      {"op": "Multiply", "args": [v("b"), v("x")]}]}])
    cases.append({"case": "budget-exhaustion-visible", "match": budget.status == "SATURATION_BUDGET_EXHAUSTED"})

    passed = sum(bool(case["match"]) for case in cases)
    payload = {"schema_version": "1.0", "owner": "cpp_audit.equality_saturation",
               "native_operations": ["B/LEGACY_EQUALITY", "B/EGRAPH"], "cases": cases,
               "passed": passed, "total": len(cases),
               "false_acceptance": 0 if all(cases[index]["match"] for index in (0, 2, 3, 4)) else 1,
               "status": "PASS" if passed == len(cases) else "FAIL"}
    output = ROOT / "output/native_migration/final/waves/wave2-equality-parity.json"
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
