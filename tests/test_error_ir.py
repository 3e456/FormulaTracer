from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from cpp_audit import AuditError, build_error_analysis, resolve_approximation_proof


ROOT = Path(__file__).resolve().parents[1]


def variable(name): return {"op": "FreeVariable", "name": name}
def ir(expr): return {"outputs": [{"target": variable("y"), "expression": expr}]}


def analysis(**kwargs):
    defaults = dict(theory_ir=ir(variable("x")), implementation_ir=ir(variable("x")), output="y",
                    comparison_relation="EXACT_EQUAL", comparison={"match": True},
                    numeric_type_semantics={"outputs": {"y": {"shape": None, "dimensions": None}}, "casts": []},
                    ieee754_semantics={"operations": []}, parallel_semantics={"claims": {}},
                    library_contracts=[], approximation_proofs=[])
    defaults.update(kwargs)
    return build_error_analysis(**defaults)


def test_exact_equivalence_has_zero_residual_and_bound():
    result = analysis()
    assert result.residual_expression.expression == {"op": "Constant", "value": 0}
    assert result.residual_expression.numeric_samples_used_as_proof is False
    assert result.graph_enclosure.output_bound.exact_value == 0
    assert result.graph_enclosure.output_bound.status == "EXACT_ZERO_BOUND"
    assert result.total_status == "EXACT_ZERO_BOUND_VERIFIED"


def test_tensor_residual_preserves_shape_and_xarray_dimensions():
    result = analysis(comparison_relation="INCONSISTENT_WITH", comparison={"match": False},
        implementation_ir=ir(variable("computed")), theory_ir=ir(variable("expected")),
        numeric_type_semantics={"outputs": {"y": {"shape": [3, 4], "dimensions": ["sample", "feature"]}}, "casts": []})
    assert result.residual_expression.expression["op"] == "ComponentwiseSubtract"
    assert result.residual_expression.shape == [3, 4]
    assert result.residual_expression.dimensions == ["sample", "feature"]
    assert result.residual_expression.alignment == "DIMENSION_NAMES_PRESERVED"


@pytest.mark.parametrize("metadata,expected", [
    ({"shape": [2, 4]}, "SHAPE_MISMATCH"),
    ({"dimensions": ["feature", "sample"]}, "DIMENSION_ALIGNMENT_MISMATCH"),
    ({"mathematical_domain": "Complex"}, "DOMAIN_MISMATCH"),
])
def test_residual_rejects_incompatible_output_semantics(metadata, expected):
    theory = ir(variable("expected")); theory.update(metadata)
    result = analysis(theory_ir=theory, comparison_relation="INCONSISTENT_WITH", comparison={"match": False},
        numeric_type_semantics={"outputs": {"y": {"shape": [3, 4], "dimensions": ["sample", "feature"],
                                                       "mathematical_domain": "Real"}}, "casts": []})
    assert result.residual_expression.status == expected
    assert result.total_status == "TOTAL_ERROR_BOUND_UNRESOLVED"


@pytest.mark.parametrize("metric", ["ABSOLUTE", "COMPONENTWISE", "L1", "L2", "LINF"])
def test_supported_error_metrics(metric):
    assert analysis(specification={"metric": metric}).error_specification.metric == metric


def test_relative_error_rejects_missing_nonzero_reference():
    with pytest.raises(AuditError, match="RELATIVE_ERROR_DOMAIN_UNRESOLVED"):
        analysis(specification={"metric": "RELATIVE"})
    with pytest.raises(AuditError, match="RELATIVE_ERROR_DENOMINATOR_ZERO"):
        analysis(specification={"metric": "RELATIVE", "reference_nonzero": False})


def test_mixed_metric_requires_both_nonnegative_tolerances():
    with pytest.raises(AuditError, match="MIXED_ERROR_REQUIRES_BOTH_TOLERANCES"):
        analysis(specification={"metric": "MIXED_ABSOLUTE_RELATIVE", "absolute_tolerance": 1e-8})
    with pytest.raises(AuditError, match="NEGATIVE_ABSOLUTE_TOLERANCE"):
        analysis(specification={"absolute_tolerance": -1})


@pytest.mark.parametrize("family,relation,source", [
    ("central_difference_first_derivative", "DISCRETIZATION_OF", "DISCRETIZATION_ERROR"),
    ("trapezoidal_rule", "APPROXIMATION_OF", "DISCRETIZATION_ERROR"),
])
def test_phase7_proof_projects_to_one_error_component(family, relation, source):
    proof = resolve_approximation_proof(family, repository_root=ROOT,
        context={"h": 0.1, "partition_resolved": True,
                 "provided_assumptions": ["third_derivative_bound", "symmetric_third_order_remainders",
                                          "second_derivative_bound", "local_panel_error"],
                 "domain_condition_proven": True}, kernel_checked=True).to_dict()
    result = analysis(comparison_relation=relation, comparison={"match": True}, approximation_proofs=[proof])
    projected = [item for item in result.error_components if item.source == source]
    assert len(projected) == 1
    assert projected[0].bound.theorem_reference == proof["evidence"]["lean_theorem_name"]
    assert projected[0].semantic_cause_id == proof["theorem_id"]


def test_verified_approximation_plus_rounding_is_partial_not_total():
    proof = resolve_approximation_proof("central_difference_first_derivative", repository_root=ROOT,
        context={"h": 0.1}, kernel_checked=True).to_dict()
    result = analysis(comparison_relation="DISCRETIZATION_OF", approximation_proofs=[proof],
        ieee754_semantics={"operations": [{"operation": "SUBTRACT"}]})
    assert result.component_status == "PARTIAL_ERROR_BOUND_VERIFIED"
    assert result.total_status == "TOTAL_ERROR_BOUND_UNRESOLVED"
    assert {item.source for item in result.error_components} >= {
        "DISCRETIZATION_ERROR", "ROUNDING_ERROR", "OVERFLOW_ERROR", "UNDERFLOW_ERROR"}


def test_parallel_and_library_uncertainty_do_not_invent_epsilon_or_double_count():
    result = analysis(parallel_semantics={"overall_policy": "PARALLEL_REORDERABLE",
        "claims": {"PARALLEL_REDUCTION_ORDER_DIFFERS": "POSSIBLE"}},
        library_contracts=[{"qualified_callable": "vendor.native", "proof_status": "REFERENCE_CONTRACT_ONLY"}] * 2)
    assert len([item for item in result.error_components if item.source == "PARALLEL_ORDER_ERROR"]) == 1
    assert len([item for item in result.proof_obligations if item.kind == "LIBRARY_SEMANTIC_PROOF_REQUIRED"]) == 1
    assert "epsilon" not in json.dumps(result.to_dict()).lower()
    assert result.error_composition.cancellation_assumed is False


def test_runtime_samples_cannot_become_proof_evidence():
    payload = analysis().to_dict()
    assert payload["residual_expression"]["numeric_samples_used_as_proof"] is False
    assert all("numeric_samples" not in item["provenance"] for item in payload["error_components"])


def test_unmatched_symbolic_residual_cannot_verify_total_bound():
    result = analysis(comparison_relation="INCONSISTENT_WITH", comparison={"match": False},
                      implementation_ir=ir(variable("implemented")))
    assert result.error_components[0].source == "MODEL_ERROR"
    assert result.error_components[0].bound.status == "BOUND_UNRESOLVED"
    assert result.total_status == "TOTAL_ERROR_BOUND_UNRESOLVED"


def test_phase8_schemas_validate_all_ir_objects():
    result = analysis().to_dict()
    bound_schema = json.loads((ROOT / "schemas/error-bound.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(bound_schema["$id"], Resource.from_contents(bound_schema))
    cases = {
        "residual-expression.schema.json": result["residual_expression"],
        "error-specification.schema.json": result["error_specification"],
        "error-component.schema.json": result["error_components"][0],
        "error-bound.schema.json": result["error_components"][0]["bound"],
        "graph-enclosure.schema.json": result["graph_enclosure"],
    }
    for filename, payload in cases.items():
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema, registry=registry).validate(payload)
    obligation_schema = json.loads((ROOT / "schemas/proof-obligation.schema.json").read_text(encoding="utf-8"))
    mismatch = analysis(theory_ir={**ir(variable("x")), "shape": [2]}, comparison_relation="INCONSISTENT_WITH",
        comparison={"match": False}, numeric_type_semantics={"outputs": {"y": {"shape": [3]}}, "casts": []})
    jsonschema.Draft202012Validator(obligation_schema).validate(mismatch.to_dict()["proof_obligations"][0])
