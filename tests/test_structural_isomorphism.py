from __future__ import annotations

import pytest

from formulatracer import structural_isomorphism
from formulatracer.native import native_available


pytestmark = pytest.mark.skipif(not native_available(), reason="native core not built")


def v(name, **metadata): return {"op": "FreeVariable", "name": name, **metadata}
def c(value): return {"op": "Constant", "value": value}
def binary(op, left, right, **metadata): return {"op": op, "args": [left, right], **metadata}


def test_positive_typed_rename_alpha_and_representation_witnesses():
    typed = {name: {"numeric_domain": "REAL", "shape": []} for name in ("x", "y")}
    renamed = structural_isomorphism(v("x", source_span={"line": 1}), v("y", source_span={"line": 99}),
                                     facts={"symbol_types": typed})
    assert renamed.status == "STRUCTURALLY_ISOMORPHIC_UNDER_FACTS"
    assert renamed.mapping == {"x": "y"}
    assert "source_span" in renamed.witness["ignored_representation_metadata"]
    assert renamed.witness["evidence_level"] == "COMPARISON_AID"
    assert not renamed.establishes_mathematical_equality

    left = {"op": "FiniteSum", "bound_index": "i", "body": {"op": "BoundVariable", "name": "i"}}
    right = {"op": "FiniteSum", "bound_index": "j", "body": {"op": "BoundVariable", "name": "j"}}
    alpha = structural_isomorphism(left, right)
    assert alpha.status == "STRUCTURALLY_ISOMORPHIC"
    assert alpha.binder_mapping == {"i": "#b0", "j": "#b0"}


def test_commutativity_and_association_are_fact_gated():
    left = binary("Add", binary("Add", c(1), c(2)), c(3))
    right = {"op": "Add", "args": [c(3), c(2), c(1)]}
    without_facts = structural_isomorphism(left, right)
    assert without_facts.status == "NOT_STRUCTURALLY_ISOMORPHIC"
    with_facts = structural_isomorphism(left, right, facts={
        "associative_operators": ["Add"], "commutative_operators": ["Add"]})
    assert with_facts.status == "STRUCTURALLY_ISOMORPHIC_UNDER_FACTS"
    assert with_facts.witness["association_changes"]
    assert with_facts.witness["operand_permutations"]


@pytest.mark.parametrize("left,right", [
    (binary("Add", v("x"), c(1)), binary("Subtract", v("x"), c(1))),
    (binary("Multiply", v("x"), c(2)), binary("Divide", v("x"), c(2))),
    ({"op": "Reduce", "axis": 0, "input": v("x")}, {"op": "Reduce", "axis": 1, "input": v("x")}),
    ({"op": "Power", "args": [v("A"), v("T")]}, {"op": "Power", "args": [v("A"), c(-1)]}),
    ({"op": "BitAnd", "args": [], "bit_representation": {"width": 8, "signedness": "UNSIGNED"}},
     {"op": "BitAnd", "args": [], "bit_representation": {"width": 16, "signedness": "UNSIGNED"}}),
    ({"op": "Select", "condition": v("p"), "then": c(1), "else": c(0)},
     {"op": "Select", "condition": v("p"), "then": c(0), "else": c(1)}),
])
def test_near_isomorphic_semantic_mutations_are_not_collapsed(left, right):
    result = structural_isomorphism(left, right)
    assert result.status in {"NOT_STRUCTURALLY_ISOMORPHIC", "ISOMORPHISM_UNRESOLVED"}
    assert not result.comparison_may_proceed
