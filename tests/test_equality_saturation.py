from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from cpp_audit.equality_saturation import (
    ExactEqualitySaturator,
    MathematicalFact,
    MathematicalFactEngine,
    MathematicalRelationGraph,
    RelationKind,
    SaturationBudget,
    TypedEGraph,
    replay_equality_trace,
    saturate_and_match,
    select_rewrite_packs,
)
from cpp_audit.generation_planning import ProviderContract, plan_generation


ROOT = Path(__file__).resolve().parents[1]


def v(name: str) -> dict:
    return {"op": "FreeVariable", "name": name}


def call(name: str, *args: dict) -> dict:
    return {"op": "FunctionCall", "name": name, "args": list(args)}


def test_exact_egraph_retains_all_forms_and_eliminates_phase_ordering() -> None:
    a, b, x = v("a"), v("b"), v("x")
    distributed = {"op": "Add", "args": [
        {"op": "Multiply", "args": [a, x]},
        {"op": "Multiply", "args": [b, x]},
    ]}
    factored = {"op": "Multiply", "args": [x, {"op": "Add", "args": [a, b]}]}
    result = saturate_and_match(distributed, factored,
        authorized_rule_ids=["factor_multiplication", "distribute_multiplication"],
        motifs=["add", "multiply"], useful_rewrites=["factor_multiplication"])

    assert result.status == "EGRAPH_EXACT_MATCH"
    assert result.graph.equivalent(result.requested_eclass_id, result.provider_eclass_id)
    forms = [node.expression for node in result.graph.nodes(result.requested_eclass_id)]
    assert distributed in forms and factored in forms
    assert replay_equality_trace(result.saturation.trace, result.graph)


def test_conditional_identity_never_merges_without_all_facts() -> None:
    expression = call("exp", call("log", v("x")))
    blocked = saturate_and_match(expression, v("x"),
        authorized_rule_ids=["exp_log_cancel_positive"], motifs=["exp", "log"])
    assert blocked.status == "EGRAPH_NO_EXACT_MATCH"
    assert blocked.saturation.status == "CONDITIONALLY_BLOCKED"
    assert {condition for item in blocked.saturation.blocked_rewrites for condition in item.missing_conditions} >= {
        "x_positive_real", "x > 0"
    }

    accepted = saturate_and_match(expression, v("x"),
        authorized_rule_ids=["exp_log_cancel_positive"], facts=["x > 0"], motifs=["exp", "log"])
    assert accepted.status == "EGRAPH_EXACT_MATCH"
    assert replay_equality_trace(accepted.saturation.trace, accepted.graph)


def test_fact_conflict_fails_closed_before_union() -> None:
    graph = TypedEGraph()
    left_facts = MathematicalFactEngine([MathematicalFact("shape", (2, 3), subject="x")])
    right_facts = MathematicalFactEngine([MathematicalFact("shape", (3, 2), subject="x")])
    left = graph.add(v("x"), origin="left", facts=left_facts)
    right = graph.add({"op": "Identity", "args": [v("x")]}, origin="right", facts=right_facts)
    with pytest.raises(ValueError, match="ECLASS_FACT_CONFLICT"):
        graph.union(left, right)
    duplicate = TypedEGraph()
    duplicate.add(v("x"), origin="left", facts=left_facts)
    with pytest.raises(ValueError, match="ECLASS_FACT_CONFLICT"):
        duplicate.add(v("x"), origin="right", facts=right_facts)


def test_non_exact_relations_cannot_be_added_as_equality() -> None:
    relations = MathematicalRelationGraph()
    edge = relations.add("exact-integral", "trapezoid", RelationKind.APPROXIMATION_OF,
                         conditions=["quadrature error bound"])
    assert edge.source_eclass_id != edge.target_eclass_id
    assert edge.relation_kind == "APPROXIMATION_OF"
    with pytest.raises(ValueError):
        relations.add("a", "b", "EXACT_EQUAL")

    derivative = {"op": "Derivative", "variable": "x", "body": call("f", v("x"))}
    finite_difference = {"op": "Divide", "args": [v("numerator"), v("h")]}
    result = saturate_and_match(derivative, finite_difference,
        authorized_rule_ids=["finite_difference_first_derivative"],
        facts=["spacing_nonzero", "smoothness", "local smoothness"],
        motifs=["derivative", "shifted_evaluation"])
    assert result.status == "EGRAPH_NO_EXACT_MATCH"
    assert not result.saturation.trace


def test_rewrite_pack_selection_is_fingerprint_and_hint_driven() -> None:
    selected = {pack.pack_id for pack in select_rewrite_packs(
        ["finite_sum", "complex_exponential"], useful_rewrites=["euler_to_exponential"])}
    assert {"Fourier", "Trigonometric", "IndexedReduction"} <= selected
    assert "Probability" not in selected


def test_saturation_budget_is_a_visible_non_verification_status() -> None:
    expression = {"op": "Add", "args": [
        {"op": "Multiply", "args": [v("a"), v("x")]},
        {"op": "Multiply", "args": [v("b"), v("x")]},
    ]}
    engine = ExactEqualitySaturator(authorized_rule_ids=["factor_multiplication"],
        motifs=["add", "multiply"], budget=SaturationBudget(iterations=2, enodes=1, rule_applications=1))
    _, result = engine.run([expression])
    assert result.status == "SATURATION_BUDGET_EXHAUSTED"
    assert "SATURATION_BUDGET_EXHAUSTED" in result.diagnostics


def test_generation_uses_egraph_but_refuses_non_exact_provider_promotion() -> None:
    a, b, x = v("a"), v("b"), v("x")
    distributed = {"op": "Add", "args": [
        {"op": "Multiply", "args": [a, x]},
        {"op": "Multiply", "args": [b, x]},
    ]}
    factored = {"op": "Multiply", "args": [x, {"op": "Add", "args": [a, b]}]}
    exact_provider = ProviderContract("example.factor", "python", "factor", factored,
        ("add", "multiply"), ("factor_multiplication",))
    plan = plan_generation(distributed, registry=[exact_provider],
                           authorized_rewrites=["factor_multiplication"])
    assert plan.candidate("example.factor").verification_status == "MATCH_WITH_EXACT_EGRAPH"
    assert plan.select().contract.provider_id == "example.factor"

    integral = {"op": "Integral", "variable": "x", "lower": v("a"), "upper": v("b"),
                "integrand": call("f", v("x"))}
    approximate_provider = ProviderContract("example.quad", "python", "quad", {"op": "Integral"},
        ("integral",), ("quadrature_weighted_sum",), ("error bound checked",), lowering="quadrature",
        implementation_relation=RelationKind.APPROXIMATION_OF.value)
    approximate = plan_generation(integral, registry=[approximate_provider],
                                  authorized_rewrites=["quadrature_weighted_sum"])
    candidate = approximate.candidate("example.quad")
    assert candidate.verification_status == "NON_EXACT_RELATION_CANDIDATE"
    assert candidate.relation_edges[0]["relation_kind"] == "APPROXIMATION_OF"
    with pytest.raises(ValueError, match="NO_RIGOROUSLY_VERIFIED_PROVIDER_CANDIDATE"):
        approximate.select()


def test_egraph_and_relation_artifacts_validate_against_versioned_schemas() -> None:
    result = saturate_and_match(call("exp", call("log", v("x"))), v("x"),
        authorized_rule_ids=["exp_log_cancel_positive"], facts=["x > 0"], motifs=["exp", "log"])
    saturation_schema = json.loads((ROOT / "schemas/equality-saturation-result.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(saturation_schema).validate(result.saturation.to_dict())

    relations = MathematicalRelationGraph()
    relations.add("integral", "quadrature", RelationKind.APPROXIMATION_OF,
                  conditions=["certified error bound"], metadata={"order": 2})
    relation_schema = json.loads((ROOT / "schemas/mathematical-relation-graph.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(relation_schema).validate(relations.to_dict())
