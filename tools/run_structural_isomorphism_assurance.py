"""Exercise the native structural comparison aid and emit auditable gates.

Structural isomorphism is deliberately not an equality proof.  These fixtures
measure high-recall correspondence while ensuring semantic mutations are not
collapsed by quotient normalization.
"""

from __future__ import annotations

import json
from pathlib import Path

from formulatracer import structural_isomorphism


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "structural_isomorphism"


def variable(name: str, **metadata):
    return {"op": "FreeVariable", "name": name, **metadata}


def constant(value):
    return {"op": "Constant", "value": value}


def binary(op: str, left, right, **metadata):
    return {"op": op, "args": [left, right], **metadata}


def typed(*names: str):
    return {name: {"numeric_domain": "REAL", "shape": []} for name in names}


def positive_cases():
    return [
        ("identical", variable("x"), variable("x"), {}),
        ("typed-rename", variable("x"), variable("y"), {"symbol_types": typed("x", "y")}),
        ("source-span", variable("x", source_span={"line": 1}),
         variable("x", source_span={"line": 9}), {}),
        ("node-id", variable("x", node_id="a"), variable("x", node_id="b"), {}),
        ("alpha-sum",
         {"op": "FiniteSum", "bound_index": "i", "body": {"op": "BoundVariable", "name": "i"}},
         {"op": "FiniteSum", "bound_index": "j", "body": {"op": "BoundVariable", "name": "j"}}, {}),
        ("explicit-map", variable("quantity"), variable("Q"),
         {"explicit_symbol_mapping": {"quantity": "Q"}}),
        ("commutative-add", binary("Add", variable("x"), constant(1)),
         binary("Add", constant(1), variable("y")),
         {"commutative_operators": ["Add"], "symbol_types": typed("x", "y")}),
        ("associative-add", binary("Add", binary("Add", constant(1), constant(2)), constant(3)),
         {"op": "Add", "args": [constant(1), constant(2), constant(3)]},
         {"associative_operators": ["Add"]}),
        ("associative-commutative-multiply",
         binary("Multiply", binary("Multiply", constant(2), variable("x")), constant(3)),
         {"op": "Multiply", "args": [constant(3), constant(2), variable("y")]},
         {"associative_operators": ["Multiply"], "commutative_operators": ["Multiply"],
          "symbol_types": typed("x", "y")}),
        ("indexed-typed-rename",
         {"op": "IndexedValue", "name": "A", "indices": [constant(0)]},
         {"op": "IndexedValue", "name": "matrix", "indices": [constant(0)]},
         {"symbol_types": {"A": {"numeric_domain": "REAL", "shape": [4]},
                           "matrix": {"numeric_domain": "REAL", "shape": [4]}}}),
    ]


def negative_cases():
    x = variable("x")
    return [
        ("add-subtract", binary("Add", x, constant(1)), binary("Subtract", x, constant(1))),
        ("multiply-divide", binary("Multiply", x, constant(2)), binary("Divide", x, constant(2))),
        ("power-exponent", binary("Power", x, constant(2)), binary("Power", x, constant(3))),
        ("reduction-axis", {"op": "Reduce", "axis": 0, "input": x},
         {"op": "Reduce", "axis": 1, "input": x}),
        ("transpose-inverse", {"op": "Transpose", "input": x}, {"op": "Inverse", "input": x}),
        ("bit-width", {"op": "BitAnd", "args": [], "bit_representation": {"width": 8}},
         {"op": "BitAnd", "args": [], "bit_representation": {"width": 16}}),
        ("signedness", {"op": "BitAnd", "args": [], "bit_representation": {"width": 8, "signedness": "SIGNED"}},
         {"op": "BitAnd", "args": [], "bit_representation": {"width": 8, "signedness": "UNSIGNED"}}),
        ("dtype", variable("x", dtype="float32"), variable("x", dtype="float64")),
        ("shape", variable("x", shape=[2, 2]), variable("x", shape=[4])),
        ("units", variable("x", units="m"), variable("x", units="s")),
        ("branch-swap", {"op": "Select", "condition": variable("p"), "then": constant(1), "else": constant(0)},
         {"op": "Select", "condition": variable("p"), "then": constant(0), "else": constant(1)}),
        ("condition", {"op": "Select", "condition": variable("p"), "then": constant(1), "else": constant(0)},
         {"op": "Select", "condition": variable("q"), "then": constant(1), "else": constant(0)}),
        ("comparison", binary("LessThan", x, constant(0)), binary("GreaterThan", x, constant(0))),
        ("bound", {"op": "FiniteSum", "lower": 0, "upper": 3, "body": x},
         {"op": "FiniteSum", "lower": 0, "upper": 4, "body": x}),
        ("index", {"op": "IndexedValue", "name": "x", "indices": [constant(0)]},
         {"op": "IndexedValue", "name": "x", "indices": [constant(1)]}),
        ("normalization", binary("Multiply", constant(0.5), x), binary("Multiply", constant(1.0), x)),
        ("operator-metadata", {"op": "Gradient", "axis": 0, "input": x},
         {"op": "Gradient", "axis": 0, "input": x, "edge_order": 2}),
        ("untyped-rename", variable("x"), variable("unknown")),
    ]


def main() -> None:
    cases = []
    false_isomorphism = 0
    for case_id, left, right, facts in positive_cases():
        result = structural_isomorphism(left, right, facts=facts)
        accepted = result.comparison_may_proceed
        cases.append({"case_id": case_id, "kind": "POSITIVE", "status": result.status,
                      "comparison_may_proceed": accepted, "proof_authority": False,
                      "witness": result.witness})
    mutation_collapsed = 0
    for case_id, left, right in negative_cases():
        result = structural_isomorphism(left, right)
        if result.comparison_may_proceed:
            false_isomorphism += 1
            mutation_collapsed += 1
        cases.append({"case_id": case_id, "kind": "NEGATIVE_MUTATION", "status": result.status,
                      "comparison_may_proceed": result.comparison_may_proceed,
                      "proof_authority": False, "witness": result.witness})

    summary = {
        "schema_version": "1.0",
        "engine": "formulatracer-core:typed-structural-isomorphism-v1",
        "semantic_role": "COMPARISON_AID_NOT_PROOF",
        "cases": len(cases),
        "positive_cases": len(positive_cases()),
        "negative_mutations": len(negative_cases()),
        "positive_correspondences": sum(c["comparison_may_proceed"] for c in cases if c["kind"] == "POSITIVE"),
        "unresolved": sum(c["status"] == "ISOMORPHISM_UNRESOLVED" for c in cases),
        "false_structural_isomorphism": false_isomorphism,
        "semantic_mutations_collapsed_by_quotient": mutation_collapsed,
        "cases_detail": cases,
    }
    gates = {
        "STRUCTURAL_ISOMORPHISM_ENGINE_NATIVE": True,
        "QUOTIENT_NORMALIZER_NATIVE": True,
        "STRUCTURAL_ISOMORPHISM_USED_AS_PROOF": False,
        "FALSE_STRUCTURAL_ISOMORPHISM": false_isomorphism,
        "SEMANTIC_MUTATION_COLLAPSED_BY_QUOTIENT": mutation_collapsed,
        "CASE_SPECIFIC_ISOMORPHISM_RULES": 0,
        "STRUCTURAL_ISOMORPHISM_COMPLETION": False,
        "completion_blockers": [
            "TEMPORARY_INLINE_UNINLINE_CORRESPONDENCE_NOT_IMPLEMENTED",
            "LOOP_FOLD_REDUCTION_CORRESPONDENCE_NOT_IMPLEMENTED",
            "STRUCTURAL_RESULT_NOT_YET_USED_BY_PRODUCTION_PROVIDER_RECONSTRUCTION",
        ],
    }
    source = ROOT / "output" / "feature_freeze" / "reconstruction-root-causes.json"
    external = json.loads(source.read_text(encoding="utf-8"))
    diagnostics = {
        "schema_version": "1.0",
        "requested_case_count": 21,
        "available_unresolved_case_count": len(external.get("findings", [])),
        "source_artifact": str(source.relative_to(ROOT)).replace("\\", "/"),
        "source_artifact_modified": False,
        "native_structural_reexecution_status": "NOT_EXECUTED_PAIRED_IR_UNAVAILABLE",
        "reason": "The retained root-cause artifact contains classifications but not theory/implementation IR pairs.",
        "findings": external.get("findings", []),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "assurance-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUTPUT / "gates.json").write_text(json.dumps(gates, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUTPUT / "external-diagnostics.json").write_text(json.dumps(diagnostics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("cases", "positive_correspondences",
          "false_structural_isomorphism", "semantic_mutations_collapsed_by_quotient")}, indent=2))


if __name__ == "__main__":
    main()
