from __future__ import annotations

import pytest

from formulatracer.native import NativeCallError, compare_ir, execute_native_kernel, native_available
from cpp_audit.algebraic_domains import (AlgebraicStructure,
                                         _reference_structure_closure,
                                         structure_closure)
from cpp_audit.math_surface import (MathBuilder, SymbolDeclaration, _reference_instantiate,
                                    _reference_anti_unify, _reference_generalize,
                                    _reference_typed_unify, anti_unify, generalize,
                                    instantiate, typed_unify)


pytestmark = pytest.mark.skipif(not native_available(), reason="native core not built")


def request(kernel: str, operation: str, **values):
    return execute_native_kernel({"schema_version": "1.0", "kernel": kernel,
                                  "operation": operation, **values})["result"]


def test_kernel_a_facts_and_domains_fail_closed():
    assert request("A", "SUPPORTS_STRUCTURE", domain="NATURAL", structure="RING")["status"] == "PROVEN_FALSE"
    assert request("A", "SUPPORTS_STRUCTURE", domain="UNKNOWN", structure="FIELD")["status"] == "UNRESOLVED"
    facts = [{"subject": "x", "predicate": "positive", "value": True, "evidence": "fixture"}]
    assert request("A", "QUERY_FACTS", facts=facts, subject="x", predicate="positive",
                   expected=True)["status"] == "PROVEN_TRUE"


def test_kernel_a_structure_closure_matches_validation_oracle():
    for structure in AlgebraicStructure:
        expected = _reference_structure_closure([structure])
        assert structure_closure([structure]) == expected
    field = request("A", "STRUCTURE_CLOSURE", structures=["FIELD"])["structures"]
    assert {"FIELD", "INTEGRAL_DOMAIN", "COMMUTATIVE_RING", "RING"} <= set(field)


def test_kernel_b_canonical_unification_and_egraph_relation_boundary():
    left = {"op": "Add", "args": [{"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 1}]}
    right = {"op": "Add", "args": [{"op": "Constant", "value": 1}, {"op": "FreeVariable", "name": "y"}]}
    assert request("B", "EQUAL", left=left, right=right)["equal"]
    pattern = {"op": "Add", "args": [{"op": "PatternVariable", "name": "a"}, {"op": "Constant", "value": 1}]}
    assert request("B", "TYPED_UNIFY", pattern=pattern, candidate=left)["status"] == "MATCH"
    with pytest.raises(NativeCallError, match="non-exact relation"):
        request("B", "EGRAPH", values=[left, right], merges=[{
            "left": 0, "right": 1, "relation": "APPROXIMATION_OF", "rule_id": "invalid"}], queries=[[0, 1]])


def test_kernel_b_public_unification_and_substitution_match_reference_oracle():
    bound = lambda name: {"op": "BoundVariable", "name": name}
    pattern_expression = {"op": "IndexedValue", "name": "A", "indices": [bound("i"), bound("j")]}
    pattern = generalize(pattern_expression, {"A": SymbolDeclaration("A", role="tensor", shape=(None, None))})
    matching = {"op": "IndexedValue", "name": "matrix", "indices": [bound("r"), bound("c")]}
    mismatch = {"op": "IndexedValue", "name": "vector", "indices": [bound("r")]}
    assert typed_unify(pattern, matching).status == _reference_typed_unify(pattern, matching).status
    assert typed_unify(pattern, mismatch).status == _reference_typed_unify(pattern, mismatch).status

    generalized = generalize(MathBuilder.indexed("quantity", "i")).pattern
    mapping = {"$v0": {"op": "FreeVariable", "name": "samples"}}
    assert instantiate(generalized, mapping) == _reference_instantiate(generalized, mapping)


def test_kernel_b_generalization_and_anti_unification_match_reference_oracle():
    expressions = [
        MathBuilder.var("x"),
        MathBuilder.indexed("matrix", "i", "j"),
        MathBuilder.sum("i", MathBuilder.constant(0), MathBuilder.var("N"),
                        MathBuilder.indexed("samples", "i")),
    ]
    for expression in expressions:
        assert generalize(expression) == _reference_generalize(expression)
    pairs = [(MathBuilder.var("x"), MathBuilder.var("y")),
             (MathBuilder.constant(1), MathBuilder.constant(2))]
    for left, right in pairs:
        assert anti_unify(left, right) == _reference_anti_unify(left, right)


def test_kernel_c_relation_error_and_range_keep_certification_boundaries():
    division = request("C", "INTERVAL", operator="DIVIDE",
                       left={"lower": 1.0, "upper": 2.0}, right={"lower": -1.0, "upper": 1.0})
    assert division["status"] == "UNRESOLVED"
    error = request("C", "COMPOSE_ABSOLUTE_ERRORS", parts=[
        {"status": "CERTIFIED_WITHIN_ERROR_BOUND", "absolute_bound": 0.1,
         "assumptions": [], "provenance": ["a"]},
        {"status": "CERTIFIED_WITHIN_ERROR_BOUND", "absolute_bound": 0.2,
         "assumptions": [], "provenance": ["b"]},
    ])
    assert error["status"] == "CERTIFIED_WITHIN_ERROR_BOUND"
    assert error["absolute_bound"] == pytest.approx(0.3)


def test_kernel_d_provider_adoption_preserves_obligations():
    expression = {"op": "Reduce", "reduction": "Add", "input": {"op": "FreeVariable", "name": "x"}}
    pack = {"schema_version": "1.0", "pack_id": "fixture", "providers": [{
        "provider_id": "numpy.sum", "pattern": {"op": "Reduce", "reduction": "Add",
            "input": {"op": "PatternVariable", "name": "input"}},
        "relation": "EXACT_UNDER_ASSUMPTIONS", "motifs": ["finite_sum"],
        "assumptions": ["finite axis"], "execution_metadata": {"device": "cpu"}}]}
    match = request("D", "PROVIDER_MATCH", pack=pack, expression=expression)[0]
    assert match["status"] == "MATCH_WITH_OBLIGATIONS"
    assert match["obligations"] == ["finite axis"]


def test_kernel_e_provenance_localization_and_semantic_diff():
    localized = request("E", "LOCALIZE", origins=[{"producer": "python-ast", "span": {
        "path": "research.py", "start_line": 3, "start_column": 4,
        "end_line": 3, "end_column": 9}, "semantic_path": ["args", "0"]}],
        semantic_path=["args", "0"])
    assert localized["level"] == "EXACT_SOURCE_SPAN"
    diff = request("E", "SEMANTIC_DIFF", left={"op": "Constant", "value": 1},
                   right={"op": "Constant", "value": 2})
    assert diff["status"] == "SEMANTIC_DIVERGENCE"


def test_kernel_f_audit_bundle_uses_native_verification_result():
    expression = {"op": "FreeVariable", "name": "x"}
    result = compare_ir(expression, expression).raw
    structural = request("B", "STRUCTURAL_ISOMORPHISM", left=expression,
                         right=expression, facts={})
    bundle = request("F", "AUDIT_BUNDLE", result=result,
                     source_context={"source_hash": "abc"}, environment={"engine": "native"},
                     artifact_lineage={"artifact": "certificate.tex"},
                     structural_normalization={"status": "STRUCTURALLY_IDENTICAL"},
                     structural_isomorphism=structural,
                     ignored_representation_differences=["source_span"])
    assert bundle["result"]["status"] == "EXACT_EQUALITY"
    assert bundle["structural_isomorphism"]["establishes_mathematical_equality"] is False
    assert bundle["ignored_representation_differences"] == ["source_span"]
    assert len(bundle["payload_hash"]) == 64
