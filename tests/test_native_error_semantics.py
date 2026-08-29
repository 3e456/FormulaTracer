from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pytest

from cpp_audit import AuditError
from cpp_audit.error_composition import (
    FunctionSensitivityContract,
    _reference_compose_error_components,
    compose_error_components,
)
from cpp_audit.error_ir import (
    ErrorBound,
    ErrorComponent,
    _reference_build_error_analysis,
    build_error_analysis,
)


VOLATILE_IDS = {
    "bound_id", "composition_id", "obligation_id", "residual_id",
    "theory_expression_id", "implementation_expression_id",
}


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        result = {key: canonical(item) for key, item in sorted(value.items()) if key not in VOLATILE_IDS}
        if isinstance(result.get("proof_obligations"), list):
            result["proof_obligations"] = sorted(result["proof_obligations"],
                key=lambda item: (item.get("semantic_cause_id") or "", item.get("kind") or ""))
        return result
    if isinstance(value, list):
        return [canonical(item) for item in value]
    if isinstance(value, str) and any(value.startswith(prefix) for prefix in
        ("bound-", "composition-", "obligation-", "residual-", "theory-", "implementation-",
         "cast-", "graph-node-", "composed-cause-", "library-", "approx-obligation-")):
        return value.split("-", 1)[0] + "-<semantic-id>"
    return value


def component(name: str, value: Any = 1, *, status: str = "KERNEL_VERIFIED_BOUND",
              source: str = "INPUT_UNCERTAINTY", metric: str = "ABSOLUTE",
              cause: str | None = None) -> ErrorComponent:
    expression = {"op": "Constant", "value": value} if isinstance(value, (int, float)) else value
    return ErrorComponent(name, source, {"op": "ErrorSymbol", "name": name}, metric,
        ErrorBound(status, metric, expression, value if isinstance(value, (int, float)) else None,
                   "CppAudit.Test.bound" if status.startswith("KERNEL") else None),
        "KERNEL_VERIFIED_ERROR_BOUND" if status.startswith("KERNEL") else "UNRESOLVED",
        {"fixture": "native-error"}, name, cause or name)


CASES = [
    ("sum", [component("x", 1), component("y", 2)], {"operation": "SUM"}),
    ("subtract", [component("x", 1), component("y", 2)], {"operation": "SUM", "coefficients": [1, -1]}),
    ("scalar", [component("x", "B")], {"operation": "SCALAR_MULTIPLICATION", "coefficients": [3]}),
    ("product-unresolved", [component("x", .1), component("y", .2)], {"operation": "PRODUCT_PROPAGATION"}),
    ("product", [component("x", .1), component("y", .2)], {"operation": "PRODUCT_PROPAGATION", "value_bounds": {"x_abs": 4, "y_abs": 5}}),
    ("quotient-missing", [component("x", .1), component("y", .2)], {"operation": "QUOTIENT_PROPAGATION"}),
    ("quotient", [component("x", .1), component("y", .2)], {"operation": "QUOTIENT_PROPAGATION", "value_bounds": {"x_abs": 4, "y_abs": 5}, "denominator_lower_bound": 2}),
    ("power", [component("x", .1)], {"operation": "POWER_PROPAGATION", "value_bounds": {"x_abs": 4}, "exponent": 3}),
    ("linear", [component("x", .1, metric="L1")], {"operation": "LINEAR_MAP_PROPAGATION", "operator_norm": 4}),
    ("reduce", [component("x", 1), component("y", 2)], {"operation": "REDUCTION_PROPAGATION"}),
    ("mean", [component("x", 1), component("y", 2)], {"operation": "REDUCTION_PROPAGATION", "count": 2}),
    ("norm", [component("x", 1, metric="LINF")], {"operation": "NORM", "output_metric": "L1", "dimension": 3}),
    ("partial", [component("x", 1), component("y", None, status="BOUND_NOT_EVALUATED")], {"operation": "SUM"}),
    ("shared", [component("x", 1, cause="same"), component("y", 1, cause="same")], {"operation": "SUM", "coefficients": [1, -1]}),
]


@pytest.mark.parametrize(("case_id", "components", "kwargs"), CASES, ids=[item[0] for item in CASES])
def test_python_rust_error_composition_semantic_parity(case_id, components, kwargs):
    reference = _reference_compose_error_components(components, **kwargs)
    native = compose_error_components(components, **kwargs)
    assert canonical(asdict(native)) == canonical(asdict(reference)), case_id


def test_function_sensitivity_semantic_parity():
    sensitivity = FunctionSensitivityContract("sin", "ABSOLUTE", 1, [-3.14, 3.14],
        ["x in domain"], "KERNEL_VERIFIED", "CppAudit.Test.sin_lipschitz")
    kwargs = {"operation": "FUNCTION_PROPAGATION", "sensitivity": sensitivity}
    assert canonical(asdict(compose_error_components([component("x", .1)], **kwargs))) == canonical(
        asdict(_reference_compose_error_components([component("x", .1)], **kwargs)))


@pytest.mark.parametrize("kwargs,error", [
    ({"operation": "RSS"}, "RSS_REQUIRES_PROVEN_INDEPENDENCE"),
    ({"operation": "SUM", "coefficients": [float("inf")]}, "INVALID_PROPAGATION_COEFFICIENT"),
    ({"operation": "SUM", "coefficients": [1], "expected_coefficients": [2]}, "WRONG_PROPAGATION_COEFFICIENT"),
    ({"operation": "SCALAR_MULTIPLICATION", "coefficients": [1, 1]}, "SCALAR_PROPAGATION_REQUIRES_ONE_INPUT"),
    ({"operation": "NORM", "output_metric": "L1", "dimension": -1}, "INVALID_NORM_DIMENSION"),
])
def test_native_negative_cases_fail_closed(kwargs, error):
    values = [component("x", 1), component("y", 2)] if error == "SCALAR_PROPAGATION_REQUIRES_ONE_INPUT" else [
        component("x", 1, metric="LINF" if error == "INVALID_NORM_DIMENSION" else "ABSOLUTE")]
    with pytest.raises(AuditError, match=error):
        compose_error_components(values, **kwargs)


def test_unknown_dependency_cannot_enable_rss_but_proven_independence_is_explicit():
    values = [component("x", 1), component("y", 2)]
    with pytest.raises(AuditError, match="RSS_REQUIRES_PROVEN_INDEPENDENCE"):
        compose_error_components(values, operation="RSS", dependence="DEPENDENCE_UNKNOWN")
    result = compose_error_components(values, operation="RSS", dependence="INDEPENDENCE_PROVEN",
                                      independence_proven=True)
    assert result.composition.proof_rule == "RSS_UNDER_PROVEN_INDEPENDENCE"
    assert result.composition.assumptions == ["INPUTS_INDEPENDENT"]
    assert result.composition.status != "COMPOSITION_KERNEL_VERIFIED"


def test_quotient_zero_crossing_and_missing_sensitivity_never_certify():
    crossing = compose_error_components([component("x", .1), component("y", .2)],
        operation="QUOTIENT_PROPAGATION", value_bounds={"x_abs": 2, "y_abs": 2},
        denominator_lower_bound=.2)
    assert crossing.total_status == "TOTAL_ERROR_BOUND_UNRESOLVED"
    assert {item.kind for item in crossing.obligations} == {"DENOMINATOR_MAY_CROSS_ZERO"}
    sensitivity = compose_error_components([component("x", .1)], operation="FUNCTION_PROPAGATION")
    assert sensitivity.total_status == "TOTAL_ERROR_BOUND_UNRESOLVED"
    assert {item.kind for item in sensitivity.obligations} == {"FUNCTION_SENSITIVITY_UNRESOLVED"}


def test_error_analysis_semantic_parity_for_exact_and_unresolved_evidence():
    ir = {"outputs": [{"target": {"op": "FreeVariable", "name": "y"},
                       "expression": {"op": "FreeVariable", "name": "x"}}]}
    cases = [
        {"theory_ir": ir, "implementation_ir": ir, "output": "y",
         "comparison_relation": "EXACT_EQUAL", "comparison": {"match": True}},
        {"theory_ir": None, "implementation_ir": ir, "output": "y",
         "comparison_relation": "UNRESOLVED", "ieee754_semantics": {"operations": ["ADD"]}},
        {"theory_ir": ir, "implementation_ir": ir, "output": "y",
         "comparison_relation": "EXACT_EQUAL", "comparison": {"match": True},
         "numeric_type_semantics": {"outputs": {"y": {"mathematical_domain": "Integer"}},
                                    "casts": [{"source": "u8", "target": "u16", "exact": "EXACT"}]},
         "parallel_semantics": {"overall_policy": "PARALLEL_REORDERABLE",
                                "claims": {"PARALLEL_REDUCTION_ORDER_DIFFERS": "POSSIBLE"}}},
    ]
    for kwargs in cases:
        reference = canonical(_reference_build_error_analysis(**kwargs).to_dict())
        native = canonical(build_error_analysis(**kwargs).to_dict())
        assert native == reference


def test_proof_obligation_removal_cannot_promote_unresolved_analysis():
    ir = {"outputs": [{"expression": {"op": "FreeVariable", "name": "x"}}]}
    result = build_error_analysis(theory_ir=None, implementation_ir=ir, output="y",
                                  comparison_relation="UNRESOLVED")
    assert result.total_status == "TOTAL_ERROR_BOUND_UNRESOLVED"
    assert result.proof_obligations
    assert result.graph_enclosure.status == "ENCLOSURE_UNRESOLVED"


def numeric_bound(result) -> float:
    expression = result.known_bound.expression
    assert expression["op"] == "Constant"
    return float(expression["value"])


def test_metamorphic_larger_input_error_and_range_do_not_reduce_product_bound():
    small = compose_error_components([component("x", .1), component("y", .2)],
        operation="PRODUCT_PROPAGATION", value_bounds={"x_abs": 2, "y_abs": 3})
    larger_error = compose_error_components([component("x", .2), component("y", .3)],
        operation="PRODUCT_PROPAGATION", value_bounds={"x_abs": 2, "y_abs": 3})
    wider_range = compose_error_components([component("x", .1), component("y", .2)],
        operation="PRODUCT_PROPAGATION", value_bounds={"x_abs": 4, "y_abs": 6})
    assert numeric_bound(larger_error) >= numeric_bound(small)
    assert numeric_bound(wider_range) >= numeric_bound(small)


def test_metamorphic_weaker_dependency_or_removed_sensitivity_never_strengthens():
    values = [component("x", 1), component("y", 2)]
    proven = compose_error_components(values, operation="RSS", dependence="INDEPENDENCE_PROVEN",
                                      independence_proven=True)
    assert proven.total_status == "TOTAL_ERROR_BOUND_VERIFIED"
    with pytest.raises(AuditError, match="RSS_REQUIRES_PROVEN_INDEPENDENCE"):
        compose_error_components(values, operation="RSS", dependence="DEPENDENCE_UNKNOWN")
    contract = FunctionSensitivityContract("f", "ABSOLUTE", 2, [-1, 1], [], "REFERENCE_CONTRACT")
    with_contract = compose_error_components([component("x", .1)], operation="FUNCTION_PROPAGATION",
                                             sensitivity=contract)
    without_contract = compose_error_components([component("x", .1)], operation="FUNCTION_PROPAGATION")
    assert with_contract.total_status == "TOTAL_ERROR_BOUND_VERIFIED"
    assert without_contract.total_status == "TOTAL_ERROR_BOUND_UNRESOLVED"


def test_unsupported_covariance_variance_and_unit_semantics_fail_closed():
    # The migrated Python reference had no covariance matrix/variance/unit conversion rule.
    # Such requests therefore remain unsupported rather than being approximated as RSS.
    for operation in ("COVARIANCE_PROPAGATION", "VARIANCE_PROPAGATION", "UNIT_CONVERSION"):
        with pytest.raises(AuditError, match="UNKNOWN_ERROR_COMPOSITION"):
            compose_error_components([component("x", 1)], operation=operation)
    with pytest.raises(AuditError, match="INCOMPATIBLE_ERROR_METRICS"):
        compose_error_components([component("x", 1, metric="ABSOLUTE"),
                                  component("y", 1, metric="L1")], operation="SUM")


def test_wrong_dependency_graph_and_approximate_status_mutation_fail_closed():
    ir = {"outputs": [{"expression": {"op": "FreeVariable", "name": "x"}}]}
    with pytest.raises(AuditError, match="ERROR_COMPONENT_PATH_UNKNOWN"):
        build_error_analysis(theory_ir=None, implementation_ir=ir, output="y",
            comparison_relation="UNRESOLVED", propagation_context={"component_paths": {"missing": "/"}})
    unresolved = component("x", None, status="BOUND_NOT_EVALUATED")
    result = compose_error_components([unresolved], operation="SUM", kernel_checked=True)
    assert result.composition.status == "COMPOSITION_UNRESOLVED"
    assert result.total_status == "TOTAL_ERROR_BOUND_UNRESOLVED"
