from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from cpp_audit import (AuditError, ErrorBound, ErrorComponent, ErrorMetric,
                       FunctionSensitivityContract, compose_error_components,
                       evaluate_error_budget, resolve_approximation_proof,
                       build_error_analysis, propagate_expression_graph)
from cpp_audit.error_ir import ErrorSpecification
from cpp_audit.cli import main as cli_main


ROOT = Path(__file__).resolve().parents[1]


def component(name: str, bound=1, *, source="DISCRETIZATION_ERROR", metric="ABSOLUTE",
              status="KERNEL_VERIFIED_BOUND", cause=None, proof="KERNEL_VERIFIED_ERROR_BOUND"):
    expression = {"op": "Constant", "value": bound} if isinstance(bound, (int, float)) else bound
    return ErrorComponent(name, source, {"op": "ErrorSymbol", "name": name}, metric,
        ErrorBound(status, metric, expression, bound if isinstance(bound, (int, float)) else None,
                   "CppAudit.Test.bound" if status.startswith("KERNEL") else None),
        proof, {"test": True}, name, cause or name)


def test_add_and_sub_bounds_use_triangle_inequality():
    x, y = component("x", 2), component("y", 3)
    added = compose_error_components([x, y], operation="SUM")
    assert added.known_bound.expression == {"op": "Constant", "value": 5}
    assert added.composition.proof_evidence["lean_theorem"] == "CppAudit.ErrorComposition.add_error_bound"
    assert added.total_status == "TOTAL_ERROR_BOUND_VERIFIED"
    subtracted = compose_error_components([x, y], operation="SUM", coefficients=[1, -1])
    assert subtracted.known_bound.expression == {"op": "Constant", "value": 5}
    assert subtracted.composition.proof_rule == "SUB"
    assert subtracted.composition.cancellation_assumed is False


def test_scalar_propagation_central_difference_e2e_a():
    proof = resolve_approximation_proof("central_difference_first_derivative", repository_root=ROOT,
                                       context={"h": 0.1}, kernel_checked=True).to_dict()
    local = component("central", proof["error_bound"]["bound"], cause=proof["theorem_id"])
    result = compose_error_components([local], operation="SCALAR_MULTIPLICATION", coefficients=[3])
    assert result.composition.proof_rule == "EXACT_SCALAR_MULTIPLICATION"
    assert result.composition.proof_evidence["lean_theorem"] == "CppAudit.ErrorComposition.scale_error_bound"
    assert result.known_bound.expression["op"] == "MultiplyBounds"
    assert result.known_bound.expression["args"][0] == {"op": "Constant", "value": 3}
    assert result.propagation_trace[0]["semantic_cause_id"] == proof["theorem_id"]


def test_expression_graph_propagates_local_error_through_scale_and_exact_addition():
    local = component("central", "(M/6)*abs(h)^2", cause="central-theorem")
    expression = {"op": "Add", "args": [
        {"op": "Multiply", "args": [{"op": "Constant", "value": 3},
                                      {"op": "FreeVariable", "name": "D_h_f"}]},
        {"op": "Constant", "value": 7}]}
    graph = propagate_expression_graph(expression,
        local_components={"/args/0/args/1": [local]}, output="y", kernel_checked=True)
    assert graph.output_composition.known_bound.expression["op"] == "MultiplyBounds"
    assert graph.output_composition.known_bound.expression["args"][0] == {"op": "Constant", "value": 3}
    assert any(node.operation == "Multiply" and node.proof_rule == "EXACT_SCALAR_MULTIPLICATION"
               for node in graph.nodes)
    assert all(item.semantic_cause_id == "central-theorem" for item in graph.output_components)


def test_multiple_approximation_sources_e2e_b():
    fd = component("fd", "(M/6)*abs(h)^2", cause="central-theorem")
    quad = component("quad", "((b-a)*M/12)*h^2", cause="trapezoid-theorem")
    result = compose_error_components([fd, quad], operation="SUM", kernel_checked=True)
    assert result.known_bound.expression["op"] == "AddBounds"
    assert result.composition.status == "COMPOSITION_KERNEL_VERIFIED"
    assert {item["semantic_cause_id"] for item in result.propagation_trace} == {"central-theorem", "trapezoid-theorem"}


def test_expression_graph_sums_two_distinct_local_sources():
    expression = {"op": "Add", "args": [{"op": "FreeVariable", "name": "D_h_f"},
                                            {"op": "FreeVariable", "name": "Q_h_g"}]}
    graph = propagate_expression_graph(expression, local_components={
        "/args/0": [component("fd", "B_fd", cause="fd-cause")],
        "/args/1": [component("quad", "B_quad", cause="quad-cause")]}, kernel_checked=True)
    expression = graph.output_composition.known_bound.expression
    assert expression["op"] == "AddBounds"
    assert len(graph.output_components) == 1
    assert graph.output_components[0].semantic_cause_id.startswith("composed-cause-")
    assert set(graph.output_components[0].dependencies) == {"fd-cause", "quad-cause"}


def test_known_approximation_plus_unresolved_rounding_e2e_c():
    approximation = component("approx", 1e-4)
    rounding = component("rounding", None, source="ROUNDING_ERROR", status="BOUND_NOT_EVALUATED", proof="UNRESOLVED")
    result = compose_error_components([approximation, rounding], operation="SUM")
    assert result.known_bound.expression == {"op": "Constant", "value": 1e-4}
    assert result.composition.status == "COMPOSITION_PARTIALLY_RESOLVED"
    assert result.total_status == "TOTAL_ERROR_BOUND_UNRESOLVED"


def test_product_requires_ranges_and_uses_cross_term():
    x, y = component("x", 0.1), component("y", 0.2)
    unresolved = compose_error_components([x, y], operation="PRODUCT_PROPAGATION")
    assert unresolved.composition.proof_rule == "PRODUCT_BOUND_UNRESOLVED"
    assert {item.kind for item in unresolved.obligations} == {"INPUT_RANGE_REQUIRED"}
    resolved = compose_error_components([x, y], operation="PRODUCT_PROPAGATION",
                                        value_bounds={"x_abs": 4, "y_abs": 5})
    assert resolved.known_bound.expression == {"op": "Constant", "value": pytest.approx(1.32)}
    assert resolved.composition.proof_evidence["lean_theorem"] == "CppAudit.ErrorComposition.mul_error_bound"


def test_quotient_requires_denominator_separation():
    x, y = component("x", 0.1), component("y", 0.2)
    missing = compose_error_components([x, y], operation="QUOTIENT_PROPAGATION",
                                       value_bounds={"x_abs": 2, "y_abs": 3})
    assert "DENOMINATOR_LOWER_BOUND_REQUIRED" in {item.kind for item in missing.obligations}
    crossing = compose_error_components([x, y], operation="QUOTIENT_PROPAGATION",
        value_bounds={"x_abs": 2, "y_abs": 3}, denominator_lower_bound=0.1)
    assert "DENOMINATOR_MAY_CROSS_ZERO" in {item.kind for item in crossing.obligations}
    resolved = compose_error_components([x, y], operation="QUOTIENT_PROPAGATION",
        value_bounds={"x_abs": 2, "y_abs": 3}, denominator_lower_bound=1)
    assert resolved.known_bound.expression is not None
    assert "DENOMINATOR_SEPARATED_FROM_ZERO" in resolved.composition.assumptions


def test_integer_power_and_function_sensitivity_contract():
    x = component("x", 0.1)
    missing = compose_error_components([x], operation="POWER_PROPAGATION", exponent=2)
    assert "INPUT_RANGE_REQUIRED" in {item.kind for item in missing.obligations}
    power = compose_error_components([x], operation="POWER_PROPAGATION", exponent=2,
                                     value_bounds={"x_abs": 3})
    assert power.known_bound.expression is not None
    unresolved = compose_error_components([x], operation="FUNCTION_PROPAGATION")
    assert "FUNCTION_SENSITIVITY_UNRESOLVED" in {item.kind for item in unresolved.obligations}
    contract = FunctionSensitivityContract("exp", "ABSOLUTE", "L_exp", {"lower": 0, "upper": 1},
        ["x in [0,1]"], "REFERENCE_CONTRACT_BOUND", provenance={"source": "library-contract"})
    propagated = compose_error_components([x], operation="FUNCTION_PROPAGATION", sensitivity=contract)
    assert propagated.known_bound.expression["op"] == "MultiplyBounds"


def test_linear_map_and_reductions():
    x = component("x", 2, metric="LINF")
    linear = compose_error_components([x], operation="LINEAR_MAP_PROPAGATION", operator_norm=4)
    assert linear.known_bound.expression == {"op": "Constant", "value": 8}
    inputs = [component("a", 1), component("b", 2)]
    summed = compose_error_components(inputs, operation="REDUCTION_PROPAGATION")
    assert summed.known_bound.expression == {"op": "Constant", "value": 3}
    mean = compose_error_components(inputs, operation="REDUCTION_PROPAGATION", count=2)
    assert mean.known_bound.expression["op"] == "DivideBounds"
    empty_mean = compose_error_components(inputs, operation="REDUCTION_PROPAGATION", count=0)
    assert "POSITIVE_REDUCTION_COUNT_REQUIRED" in {item.kind for item in empty_mean.obligations}


def test_norm_conversion_requires_and_uses_exact_dimension():
    x = component("x", 2, metric="LINF")
    with pytest.raises(AuditError, match="INVALID_NORM_DIMENSION"):
        compose_error_components([x], operation="NORM", output_metric="L1", dimension=-1)
    with pytest.raises(AuditError, match="WRONG_NORM_FACTOR"):
        compose_error_components([x], operation="NORM", output_metric="L1", dimension=3, vector_length=4)
    missing = compose_error_components([x], operation="NORM", output_metric="L1")
    assert "NORM_DIMENSION_REQUIRED" in {item.kind for item in missing.obligations}
    result = compose_error_components([x], operation="NORM", output_metric="L1", dimension=3)
    assert result.known_bound.expression == {"op": "Constant", "value": 6}


def test_shared_cause_and_safe_exact_cancellation_are_distinguished():
    left = component("left", 2, cause="shared")
    right = component("right", 2, cause="shared")
    conservative = compose_error_components([left, right], operation="SUM", coefficients=[1, -1])
    assert conservative.known_bound.expression == {"op": "Constant", "value": 4}
    assert conservative.composition.dependency_status == "SHARED_ERROR_CAUSE"
    cancelled = compose_error_components([left, right], operation="SUM", coefficients=[1, -1],
                                         allow_exact_cancellation=True)
    assert cancelled.known_bound.expression == {"op": "Constant", "value": 0}
    assert cancelled.composition.proof_rule == "SAFE_EXACT_CANCELLATION"
    unrelated = compose_error_components([component("e1", 2), component("e2", 2)], operation="SUM",
                                         coefficients=[1, -1], allow_exact_cancellation=True)
    assert unrelated.known_bound.expression == {"op": "Constant", "value": 4}


def test_independence_rss_and_metric_fail_closed():
    with pytest.raises(AuditError, match="RSS_REQUIRES_PROVEN_INDEPENDENCE"):
        compose_error_components([component("a")], operation="RSS")
    with pytest.raises(AuditError, match="INCOMPATIBLE_ERROR_METRICS"):
        compose_error_components([component("a"), component("b", metric="L1")], operation="SUM")
    with pytest.raises(AuditError, match="INVALID_PROPAGATION_COEFFICIENT"):
        compose_error_components([component("a")], operation="SUM", coefficients=["observed"])
    with pytest.raises(AuditError, match="WRONG_PROPAGATION_COEFFICIENT"):
        compose_error_components([component("a")], operation="SUM", coefficients=[3], expected_coefficients=[2])


def test_overflow_invalidates_finite_enclosure_and_parallel_never_disappears():
    overflow = component("overflow", None, source="OVERFLOW_ERROR", status="BOUND_NOT_EVALUATED", proof="UNRESOLVED")
    result = compose_error_components([component("known"), overflow], operation="SUM")
    assert result.invalidated
    assert result.total_status == "FINITE_ERROR_ENCLOSURE_INVALIDATED"
    assert result.known_bound.expression == {"op": "Constant", "value": 1}
    assert result.known_bound.proof_evidence["scope"] == "KNOWN_COMPONENTS_ONLY"
    parallel = component("parallel", None, source="PARALLEL_ORDER_ERROR", status="BOUND_NOT_EVALUATED", proof="UNRESOLVED")
    partial = compose_error_components([component("known"), parallel], operation="SUM")
    assert partial.total_status == "TOTAL_ERROR_BOUND_UNRESOLVED"
    assert any(item["source_component"] == "parallel" for item in partial.propagation_trace)


def test_parallel_reduction_is_zero_only_in_exact_domain():
    ir = {"outputs": [{"target": {"op": "FreeVariable", "name": "y"},
                       "expression": {"op": "FreeVariable", "name": "x"}}]}
    result = build_error_analysis(theory_ir=ir, implementation_ir=ir, output="y",
        comparison_relation="EXACT_EQUAL", comparison={"match": True},
        numeric_type_semantics={"outputs": {"y": {"mathematical_domain": "Integer"}}, "casts": []},
        ieee754_semantics={"operations": []},
        parallel_semantics={"overall_policy": "PARALLEL_REORDERABLE",
                            "claims": {"PARALLEL_REDUCTION_ORDER_DIFFERS": "POSSIBLE"}})
    parallel = next(item for item in result.error_components if item.source == "PARALLEL_ORDER_ERROR")
    assert parallel.bound.status == "EXACT_ZERO_BOUND"
    assert parallel.proof_status == "PROVEN_EXACT_DOMAIN"


def test_error_budget_never_promotes_partial_total_to_pass():
    known = ErrorBound("KERNEL_VERIFIED_BOUND", "ABSOLUTE", {"op": "Constant", "value": 1e-4})
    spec = ErrorSpecification(metric="ABSOLUTE", absolute_tolerance=1e-3)
    budget = evaluate_error_budget(known, "TOTAL_ERROR_BOUND_UNRESOLVED", spec)
    assert budget["known_bound_status"] == "KNOWN_BOUND_WITHIN_TOLERANCE"
    assert budget["total_tolerance_status"] == "TOTAL_TOLERANCE_NOT_PROVEN"


def test_phase9_schemas_validate_composition_trace_and_sensitivity():
    result = compose_error_components([component("a")], operation="SCALAR_MULTIPLICATION", coefficients=[3])
    bound_schema = json.loads((ROOT / "schemas/error-bound.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(bound_schema["$id"], Resource.from_contents(bound_schema))
    cases = [
        ("error-composition.schema.json", asdict(result.composition)),
        ("error-propagation-trace.schema.json", result.propagation_trace),
        ("function-sensitivity-contract.schema.json", asdict(FunctionSensitivityContract(
            "exp", "ABSOLUTE", 3, {"lower": 0, "upper": 1}, [], "REFERENCE_CONTRACT_BOUND"))),
    ]
    for filename, payload in cases:
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema, registry=registry).validate(payload)


def test_python_certificate_cli_accepts_error_propagation_and_budget(tmp_path, monkeypatch):
    propagation = tmp_path / "propagation.json"
    propagation.write_text(json.dumps({"operation": "SCALAR_MULTIPLICATION",
        "component_coefficients": {"mathematical-residual": 3}, "expected_coefficients": [3]}), encoding="utf-8")
    specification = tmp_path / "error.json"
    specification.write_text(json.dumps({"metric": "ABSOLUTE", "absolute_tolerance": 1e-6}), encoding="utf-8")
    output, latex = tmp_path / "certificate.json", tmp_path / "certificate.tex"
    monkeypatch.setattr("sys.argv", ["cpp-audit", "python-certificate",
        str(ROOT / "tests/fixtures/synthetic_identity_transformation.py"),
        "--inputs", str(ROOT / "tests/fixtures/synthetic_identity_transformation_inputs.json"),
        "--function", "preserve_value", "--output", "normalized_value", "--mode", "REPORT_ONLY",
        "--transformation-set", "scientific_default", "--transformation-rule", "neutral_element_elimination",
        "--error-specification", str(specification), "--error-propagation", str(propagation),
        "--json-output", str(output), "--latex-output", str(latex), "--no-lean"])
    assert cli_main() == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["error_composition"]["operation"] == "SCALAR_MULTIPLICATION"
    assert payload["graph_enclosure"]["error_budget"]["known_bound_status"] == "KNOWN_BOUND_WITHIN_TOLERANCE"
    assert "Error Source Composition" in latex.read_text(encoding="utf-8")
