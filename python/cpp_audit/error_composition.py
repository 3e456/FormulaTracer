"""Conservative Phase 9 error-bound composition and graph propagation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Any

from .core import AuditError
from .error_ir import (BoundStatus, ErrorBound, ErrorComponent, ErrorComposition,
                       ErrorCompositionKind, ErrorMetric, ErrorSource, ProofObligation)


class CompositionProofStatus(str, Enum):
    KERNEL_VERIFIED = "COMPOSITION_KERNEL_VERIFIED"
    KERNEL_VERIFIED_UNDER_ASSUMPTIONS = "COMPOSITION_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
    SYMBOLICALLY_DERIVED = "COMPOSITION_SYMBOLICALLY_DERIVED"
    PARTIALLY_RESOLVED = "COMPOSITION_PARTIALLY_RESOLVED"
    UNRESOLVED = "COMPOSITION_UNRESOLVED"
    INVALID = "COMPOSITION_INVALID"


class DependencyStatus(str, Enum):
    SHARED_ERROR_CAUSE = "SHARED_ERROR_CAUSE"
    INDEPENDENT_COMPONENTS = "INDEPENDENT_COMPONENTS"
    DEPENDENCE_UNKNOWN = "DEPENDENCE_UNKNOWN"
    INDEPENDENCE_PROVEN = "INDEPENDENCE_PROVEN"


@dataclass(frozen=True)
class FunctionSensitivityContract:
    function: str
    metric: str
    lipschitz_bound: Any
    domain: Any
    assumptions: list[str]
    proof_status: str
    theorem_reference: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class PropagationNode:
    node_id: str
    operation: str
    input_bounds: list[str]
    local_error: list[str]
    propagated_error: list[str]
    output_bound: dict[str, Any] | None
    proof_rule: str | None
    status: str
    semantic_causes: list[str]
    dependency_status: str


@dataclass
class CompositionResult:
    composition: ErrorComposition
    known_bound: ErrorBound
    total_status: str
    obligations: list[ProofObligation]
    propagation_trace: list[dict[str, Any]]
    invalidated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "composition": asdict(self.composition), "known_bound": asdict(self.known_bound),
            "total_status": self.total_status, "obligations": [asdict(item) for item in self.obligations],
            "propagation_trace": deepcopy(self.propagation_trace), "invalidated": self.invalidated,
        }


@dataclass
class GraphPropagationResult:
    nodes: list[PropagationNode]
    edges: list[dict[str, str]]
    output_components: list[ErrorComponent]
    output_composition: CompositionResult
    obligations: list[ProofObligation]
    propagation_trace: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": [asdict(item) for item in self.nodes], "edges": deepcopy(self.edges),
                "output_components": [asdict(item) for item in self.output_components],
                "output_composition": self.output_composition.to_dict(),
                "obligations": [asdict(item) for item in self.obligations],
                "propagation_trace": deepcopy(self.propagation_trace)}


def _stable_id(prefix: str, value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return f"{prefix}-{sha256(raw).hexdigest()[:12]}"


def _constant(value: int | float) -> dict[str, Any]:
    return {"op": "Constant", "value": value}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _expr(value: Any) -> Any:
    return _constant(value) if _is_number(value) else deepcopy(value)


def _add(values: list[Any]) -> Any:
    flattened: list[Any] = []
    numeric: int | float = 0
    for value in values:
        if value is None:
            continue
        if _is_number(value):
            numeric += value
        elif isinstance(value, dict) and value.get("op") == "Constant" and _is_number(value.get("value")):
            numeric += value["value"]
        elif isinstance(value, dict) and value.get("op") == "AddBounds":
            flattened.extend(value.get("args", []))
        else:
            flattened.append(deepcopy(value))
    if numeric != 0 or not flattened:
        flattened.append(_constant(numeric))
    if len(flattened) == 1:
        return flattened[0]
    return {"op": "AddBounds", "args": flattened}


def _mul(left: Any, right: Any) -> Any:
    if _is_number(left): left = _constant(left)
    if _is_number(right): right = _constant(right)
    if isinstance(left, dict) and left.get("op") == "Constant":
        if left.get("value") == 0: return _constant(0)
        if left.get("value") == 1: return deepcopy(right)
    if isinstance(right, dict) and right.get("op") == "Constant":
        if right.get("value") == 0: return _constant(0)
        if right.get("value") == 1: return deepcopy(left)
    if all(isinstance(item, dict) and item.get("op") == "Constant" and _is_number(item.get("value"))
           for item in (left, right)):
        return _constant(left["value"] * right["value"])
    return {"op": "MultiplyBounds", "args": [deepcopy(left), deepcopy(right)]}


def _div(left: Any, right: Any) -> Any:
    if _is_number(right) and right == 0:
        raise AuditError("DENOMINATOR_MAY_CROSS_ZERO")
    return {"op": "DivideBounds", "args": [_expr(left), _expr(right)]}


def _pow(base: Any, exponent: int) -> Any:
    if exponent == 0: return _constant(1)
    if exponent == 1: return _expr(base)
    return {"op": "PowerBound", "args": [_expr(base), _constant(exponent)]}


def _known(component: ErrorComponent) -> bool:
    return component.bound.status not in {BoundStatus.BOUND_NOT_EVALUATED.value,
                                          BoundStatus.BOUND_UNRESOLVED.value,
                                          BoundStatus.BOUND_INVALID.value}


def _metric(components: list[ErrorComponent], output_metric: str | None) -> str:
    metrics = {item.metric for item in components if _known(item)}
    if output_metric is not None:
        ErrorMetric(output_metric)
        metrics.add(output_metric)
    if len(metrics) > 1:
        raise AuditError("INCOMPATIBLE_ERROR_METRICS")
    return next(iter(metrics), output_metric or ErrorMetric.ABSOLUTE.value)


def _bound_expression(component: ErrorComponent) -> Any:
    return deepcopy(component.bound.symbolic_expression if component.bound.symbolic_expression is not None
                    else component.bound.expression)


def _obligation(kind: str, description: str, operation: str) -> ProofObligation:
    cause = f"composition:{operation}:{kind}"
    return ProofObligation(_stable_id("obligation", cause), kind, description,
                           required_evidence=[kind], origin_id=operation, semantic_cause_id=cause)


def _status(known: list[ErrorComponent], unresolved: list[ErrorComponent], assumptions: list[str],
            *, theorem: str | None, kernel_checked: bool, invalid: bool = False) -> str:
    if invalid: return CompositionProofStatus.INVALID.value
    if unresolved and known: return CompositionProofStatus.PARTIALLY_RESOLVED.value
    if unresolved or not known: return CompositionProofStatus.UNRESOLVED.value
    formal = all(item.bound.status in {BoundStatus.EXACT_ZERO_BOUND.value,
                                       BoundStatus.KERNEL_VERIFIED_BOUND.value,
                                       BoundStatus.KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS.value} for item in known)
    conditional = bool(assumptions) or any(item.bound.status == BoundStatus.KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS.value
                                          for item in known)
    if formal and theorem and kernel_checked:
        return (CompositionProofStatus.KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value if conditional
                else CompositionProofStatus.KERNEL_VERIFIED.value)
    return CompositionProofStatus.SYMBOLICALLY_DERIVED.value


def _reference_compose_error_components(components: list[ErrorComponent], *, operation: str = "SUM",
                             coefficients: list[int | float] | None = None,
                             output_metric: str | None = None,
                             value_bounds: dict[str, Any] | None = None,
                             denominator_lower_bound: int | float | None = None,
                             exponent: int | None = None, dimension: int | None = None,
                             operator_norm: Any | None = None,
                             sensitivity: FunctionSensitivityContract | None = None,
                             count: int | None = None, assumptions: list[str] | None = None,
                             vector_length: int | None = None,
                             expected_coefficients: list[int | float] | None = None,
                             allow_exact_cancellation: bool = False,
                             dependence: str = DependencyStatus.DEPENDENCE_UNKNOWN.value,
                             independence_proven: bool = False,
                             kernel_checked: bool = False) -> CompositionResult:
    """Compose local bounds conservatively; unresolved inputs never disappear."""
    assumptions = list(assumptions or [])
    value_bounds = deepcopy(value_bounds or {})
    if operation == "RSS" and not independence_proven:
        raise AuditError("RSS_REQUIRES_PROVEN_INDEPENDENCE")
    try:
        kind = ErrorCompositionKind(operation).value
    except ValueError as exc:
        raise AuditError(f"UNKNOWN_ERROR_COMPOSITION: {operation}") from exc
    metric = (ErrorMetric(output_metric).value if kind == ErrorCompositionKind.NORM.value and output_metric
              else _metric(components, output_metric))
    if any(item.source == ErrorSource.OVERFLOW_ERROR.value and not _known(item) for item in components):
        obligation = _obligation("OVERFLOW_EXCLUSION_REQUIRED", "Potential overflow invalidates a finite enclosure", operation)
        finite_known = [item for item in components if _known(item)]
        finite_expression = _add([_bound_expression(item) for item in finite_known]) if finite_known else None
        bound = ErrorBound(BoundStatus.SYMBOLIC_BOUND.value if finite_expression is not None else
                           BoundStatus.BOUND_UNRESOLVED.value, metric, finite_expression,
                           proof_evidence={"scope": "KNOWN_COMPONENTS_ONLY", "overflow_excluded": False})
        composition = ErrorComposition("FINITE_ERROR_ENCLOSURE_INVALIDATED", CompositionProofStatus.INVALID.value,
            [item.component_id for item in components], False, kind, operation=operation,
            input_components=[item.component_id for item in components], input_bounds=[asdict(item.bound) for item in components],
            output_metric=metric, output_bound=bound, assumptions=assumptions, provenance={"phase": 9})
        trace = [{"source_component": item.component_id, "semantic_cause_id": item.semantic_cause_id,
                  "source_bound": asdict(item.bound), "operation": operation,
                  "propagation_rule": "FINITE_ERROR_ENCLOSURE_INVALIDATED",
                  "coefficient": 1, "result_bound": asdict(bound), "lean_theorem": None,
                  "assumptions": [], "source_kind": "LOCAL_ERROR", "kind": "PROPAGATED_ERROR"}
                 for item in components]
        return CompositionResult(composition, bound, "FINITE_ERROR_ENCLOSURE_INVALIDATED", [obligation], trace, True)
    known = [item for item in components if _known(item)]
    unresolved = [item for item in components if not _known(item)]
    obligations: list[ProofObligation] = []
    theorem: str | None = None
    proof_rule = operation
    dependency_status = dependence
    result_expr: Any | None = None
    coefficients = coefficients or [1] * len(components)
    if len(coefficients) != len(components) or any(not _is_number(value) for value in coefficients):
        raise AuditError("INVALID_PROPAGATION_COEFFICIENT")
    if expected_coefficients is not None and coefficients != expected_coefficients:
        raise AuditError("WRONG_PROPAGATION_COEFFICIENT")
    if len({item.semantic_cause_id for item in components}) < len(components):
        dependency_status = DependencyStatus.SHARED_ERROR_CAUSE.value

    if kind == ErrorCompositionKind.SUM.value:
        theorem = "CppAudit.ErrorComposition.add_error_bound"
        if len(coefficients) == 2 and coefficients == [1, -1]:
            theorem = "CppAudit.ErrorComposition.sub_error_bound"
            proof_rule = "SUB"
        grouped: dict[str, list[tuple[ErrorComponent, float]]] = {}
        for item, coefficient in zip(components, coefficients):
            grouped.setdefault(item.semantic_cause_id, []).append((item, float(coefficient)))
        terms = []
        safe_cancelled = []
        for cause, occurrences in grouped.items():
            known_occurrences = [(item, coefficient) for item, coefficient in occurrences if _known(item)]
            if not known_occurrences: continue
            signed_sum = sum(coefficient for _, coefficient in known_occurrences)
            if allow_exact_cancellation and signed_sum == 0 and len(known_occurrences) > 1:
                safe_cancelled.append(cause)
                continue
            magnitude = abs(signed_sum) if len(known_occurrences) > 1 else abs(known_occurrences[0][1])
            if len(known_occurrences) > 1 and not allow_exact_cancellation:
                magnitude = sum(abs(coefficient) for _, coefficient in known_occurrences)
            terms.append(_mul(magnitude, _bound_expression(known_occurrences[0][0])))
        result_expr = _add(terms)
        if safe_cancelled:
            proof_rule = "SAFE_EXACT_CANCELLATION"
            theorem = "CppAudit.ErrorComposition.safe_exact_cancellation"
    elif kind == ErrorCompositionKind.MAX.value:
        result_expr = ({"op": "MaxBounds", "args": [_bound_expression(item) for item in known]}
                       if known else None)
        proof_rule = "CONSERVATIVE_MAXIMUM"
    elif kind == ErrorCompositionKind.SCALAR_MULTIPLICATION.value:
        if len(components) != 1:
            raise AuditError("SCALAR_PROPAGATION_REQUIRES_ONE_INPUT")
        scalar = coefficients[0]
        result_expr = _mul(abs(scalar), _bound_expression(components[0])) if known else None
        theorem = "CppAudit.ErrorComposition.scale_error_bound"
        proof_rule = "EXACT_SCALAR_MULTIPLICATION"
    elif kind == ErrorCompositionKind.PRODUCT_PROPAGATION.value:
        theorem = "CppAudit.ErrorComposition.mul_error_bound"
        if len(components) != 2:
            raise AuditError("PRODUCT_PROPAGATION_REQUIRES_TWO_INPUTS")
        if "x_abs" not in value_bounds or "y_abs" not in value_bounds:
            obligations.append(_obligation("INPUT_RANGE_REQUIRED", "Product propagation requires |x| and |y| bounds", operation))
            proof_rule, result_expr = "PRODUCT_BOUND_UNRESOLVED", None
        elif len(known) == 2:
            bx, by = (_bound_expression(item) for item in components)
            result_expr = _add([_mul(value_bounds["y_abs"], bx), _mul(value_bounds["x_abs"], by), _mul(bx, by)])
            assumptions.append("NOMINAL_INPUT_RANGES_BOUND")
    elif kind == ErrorCompositionKind.QUOTIENT_PROPAGATION.value:
        if len(components) != 2:
            raise AuditError("QUOTIENT_PROPAGATION_REQUIRES_TWO_INPUTS")
        by_expr = _bound_expression(components[1]) if _known(components[1]) else None
        by_numeric = components[1].bound.exact_value
        if denominator_lower_bound is None:
            obligations.append(_obligation("DENOMINATOR_LOWER_BOUND_REQUIRED", "A positive lower bound on |y| is required", operation))
            proof_rule = "QUOTIENT_BOUND_UNRESOLVED"
        elif denominator_lower_bound <= 0 or (by_numeric is not None and denominator_lower_bound <= by_numeric):
            obligations.append(_obligation("DENOMINATOR_MAY_CROSS_ZERO", "The perturbed denominator may cross zero", operation))
            proof_rule = "QUOTIENT_BOUND_UNRESOLVED"
        elif len(known) == 2 and {"x_abs", "y_abs"} <= value_bounds.keys():
            bx = _bound_expression(components[0])
            numerator = _add([_mul(value_bounds["y_abs"], bx), _mul(value_bounds["x_abs"], by_expr)])
            result_expr = _div(numerator, _mul(denominator_lower_bound,
                                               _add([denominator_lower_bound, _mul(-1, by_expr)])))
            assumptions.append("DENOMINATOR_SEPARATED_FROM_ZERO")
        else:
            obligations.append(_obligation("INPUT_RANGE_REQUIRED", "Quotient propagation requires numerator and denominator ranges", operation))
            proof_rule = "QUOTIENT_BOUND_UNRESOLVED"
    elif kind == ErrorCompositionKind.POWER_PROPAGATION.value:
        if exponent is None or not isinstance(exponent, int):
            obligations.append(_obligation("INTEGER_EXPONENT_REQUIRED", "Only integer powers are supported", operation))
        elif len(components) != 1 or "x_abs" not in value_bounds:
            obligations.append(_obligation("INPUT_RANGE_REQUIRED", "Power propagation requires an input range", operation))
        elif known:
            bx = _bound_expression(known[0])
            result_expr = _mul(abs(exponent), _mul(_pow(_add([value_bounds["x_abs"], bx]), max(abs(exponent) - 1, 0)), bx))
            assumptions.append("INTEGER_POWER_DOMAIN_RESOLVED")
    elif kind == ErrorCompositionKind.FUNCTION_PROPAGATION.value:
        if sensitivity is None:
            obligations.append(_obligation("FUNCTION_SENSITIVITY_UNRESOLVED", "A derivative or Lipschitz bound is required", operation))
        elif sensitivity.metric != metric:
            raise AuditError("INCOMPATIBLE_ERROR_METRICS")
        elif len(known) == 1:
            result_expr = _mul(sensitivity.lipschitz_bound, _bound_expression(known[0]))
            assumptions.extend(sensitivity.assumptions)
            theorem = sensitivity.theorem_reference
            proof_rule = "LIPSCHITZ_FUNCTION_PROPAGATION"
    elif kind == ErrorCompositionKind.LINEAR_MAP_PROPAGATION.value:
        if operator_norm is None:
            obligations.append(_obligation("OPERATOR_NORM_REQUIRED", "Linear-map propagation requires a compatible operator norm", operation))
        elif metric not in {ErrorMetric.COMPONENTWISE.value, ErrorMetric.L1.value, ErrorMetric.LINF.value}:
            raise AuditError("LINEAR_MAP_METRIC_UNSUPPORTED")
        elif len(known) == 1:
            result_expr = _mul(operator_norm, _bound_expression(known[0]))
            theorem = "CppAudit.ErrorComposition.linear_map_error_bound"
            assumptions.append("COMPATIBLE_OPERATOR_NORM_BOUND")
    elif kind == ErrorCompositionKind.REDUCTION_PROPAGATION.value:
        theorem = "CppAudit.ErrorComposition.sum_error_bound"
        terms = [_bound_expression(item) for item in known]
        result_expr = _add(terms)
        if count is not None:
            if count <= 0:
                obligations.append(_obligation("POSITIVE_REDUCTION_COUNT_REQUIRED", "Mean requires n > 0", operation))
                result_expr = None
            else:
                result_expr = _div(result_expr, count)
                theorem = "CppAudit.ErrorComposition.mean_error_bound"
                assumptions.append("0 < n")
    elif kind == ErrorCompositionKind.NORM.value:
        input_metrics = {item.metric for item in components}
        if output_metric == ErrorMetric.L1.value and input_metrics == {ErrorMetric.LINF.value}:
            if dimension is None:
                obligations.append(_obligation("NORM_DIMENSION_REQUIRED", "Linf to L1 conversion requires vector length", operation))
            elif dimension < 0:
                raise AuditError("INVALID_NORM_DIMENSION")
            elif vector_length is not None and dimension != vector_length:
                raise AuditError("WRONG_NORM_FACTOR")
            else:
                result_expr = _mul(dimension, _bound_expression(components[0]))
                theorem = "CppAudit.ErrorComposition.linf_to_l1_bound"
                assumptions.append("VECTOR_DIMENSION_RESOLVED")
        elif metric == ErrorMetric.L1.value and input_metrics == {ErrorMetric.L1.value}:
            result_expr = _add([_bound_expression(item) for item in known])
        else:
            obligations.append(_obligation("NORM_CONVERSION_UNRESOLVED", "No verified conversion exists for these metrics", operation))
    else:
        obligations.append(_obligation("CUSTOM_COMPOSITION_CONTRACT_REQUIRED", "Custom propagation needs a formal contract", operation))

    unresolved_by_rule = bool(obligations) or result_expr is None
    effective_unresolved = unresolved if not unresolved_by_rule else list({item.component_id: item for item in [*unresolved, *components]}.values())
    status = _status(known, effective_unresolved, assumptions, theorem=theorem, kernel_checked=kernel_checked)
    bound_status = (BoundStatus.KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS.value
                    if status == CompositionProofStatus.KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value else
                    BoundStatus.KERNEL_VERIFIED_BOUND.value
                    if status == CompositionProofStatus.KERNEL_VERIFIED.value else
                    BoundStatus.SYMBOLIC_BOUND.value if result_expr is not None else BoundStatus.BOUND_UNRESOLVED.value)
    known_bound = ErrorBound(bound_status, metric, result_expr, theorem_reference=theorem,
                             assumptions=assumptions, proof_evidence={"composition_status": status})
    total_status = "TOTAL_ERROR_BOUND_UNRESOLVED" if effective_unresolved or obligations else "TOTAL_ERROR_BOUND_VERIFIED"
    composition = ErrorComposition(proof_rule, status, [item.component_id for item in components], False, kind,
        operation=operation, input_components=[item.component_id for item in components],
        input_bounds=[asdict(item.bound) for item in components], output_metric=metric, output_bound=known_bound,
        assumptions=assumptions, proof_rule=proof_rule,
        proof_evidence={"lean_theorem": theorem, "kernel_applicable": status.startswith("COMPOSITION_KERNEL_VERIFIED")},
        provenance={"phase": 9, "numeric_samples_used_as_proof": False}, dependency_status=dependency_status)
    trace = [{"source_component": item.component_id, "semantic_cause_id": item.semantic_cause_id,
              "source_bound": asdict(item.bound), "operation": operation, "propagation_rule": proof_rule,
              "coefficient": coefficient, "result_bound": asdict(known_bound), "lean_theorem": theorem,
              "assumptions": assumptions, "source_kind": "LOCAL_ERROR", "kind": "PROPAGATED_ERROR"}
             for item, coefficient in zip(components, coefficients)]
    return CompositionResult(composition, known_bound, total_status, obligations, trace)


def _reference_evaluate_error_budget(known_bound: ErrorBound, total_status: str, specification: Any) -> dict[str, Any]:
    tolerance = getattr(specification, "absolute_tolerance", None)
    numeric = known_bound.exact_value
    if numeric is None and isinstance(known_bound.expression, dict) and known_bound.expression.get("op") == "Constant":
        numeric = known_bound.expression.get("value")
    known_status = "TOLERANCE_NOT_SPECIFIED"
    if tolerance is not None and _is_number(numeric):
        known_status = "KNOWN_BOUND_WITHIN_TOLERANCE" if numeric <= tolerance else "KNOWN_BOUND_EXCEEDS_TOLERANCE"
    total_tolerance = ("TOTAL_TOLERANCE_PROVEN" if total_status == "TOTAL_ERROR_BOUND_VERIFIED" and
                       known_status == "KNOWN_BOUND_WITHIN_TOLERANCE" else "TOTAL_TOLERANCE_NOT_PROVEN")
    return {"known_bound": deepcopy(known_bound.expression), "absolute_tolerance": tolerance,
            "known_bound_status": known_status, "total_tolerance_status": total_tolerance}


def _path_key(path: tuple[Any, ...]) -> str:
    return "/" + "/".join(str(item) for item in path) if path else "/"


def _constant_value(node: Any) -> int | float | None:
    if isinstance(node, dict) and node.get("op") == "Constant" and _is_number(node.get("value")):
        return node["value"]
    return None


def _derived_component(result: CompositionResult, inputs: list[ErrorComponent], node_id: str) -> ErrorComponent:
    causes = list(dict.fromkeys(item.semantic_cause_id for item in inputs))
    source = inputs[0].source if inputs and len({item.source for item in inputs}) == 1 else ErrorSource.UNKNOWN_ERROR_SOURCE.value
    cause = causes[0] if len(causes) == 1 else _stable_id("composed-cause", causes)
    return ErrorComponent(f"propagated-{node_id}", source,
        {"op": "PropagatedError", "composition_id": result.composition.composition_id},
        result.known_bound.metric, result.known_bound, result.composition.status,
        {"phase": 9, "error_role": "PROPAGATED_ERROR", "composition_id": result.composition.composition_id},
        inputs[0].origin_id if len(inputs) == 1 else result.composition.composition_id,
        cause, assumptions=list(result.composition.assumptions), dependencies=causes)


def _reference_propagate_expression_graph(expression: dict[str, Any], *,
                               local_components: dict[str, list[ErrorComponent]],
                               output: str = "output",
                               contracts: dict[str, dict[str, Any]] | None = None,
                               kernel_checked: bool = False) -> GraphPropagationResult:
    """Propagate path-attached local errors through the Mathematical Expression IR."""
    contracts = deepcopy(contracts or {})
    nodes: list[PropagationNode] = []
    edges: list[dict[str, str]] = []
    obligations: list[ProofObligation] = []
    trace: list[dict[str, Any]] = []

    def walk(node: Any, path: tuple[Any, ...]) -> list[ErrorComponent]:
        key = _path_key(path)
        direct = deepcopy(local_components.get(key, []))
        if direct:
            nodes.append(PropagationNode(key, "LOCAL_ERROR", [], [item.component_id for item in direct], [],
                asdict(direct[0].bound) if len(direct) == 1 else None, None, "LOCAL_BOUND_ATTACHED",
                [item.semantic_cause_id for item in direct], DependencyStatus.DEPENDENCE_UNKNOWN.value))
            return direct
        if not isinstance(node, dict): return []
        op = str(node.get("op", "UNRESOLVED"))
        args = node.get("args") if isinstance(node.get("args"), list) else []
        child_components = [walk(child, (*path, "args", index)) for index, child in enumerate(args)]
        if op == "Reduce" and isinstance(node.get("input"), dict):
            child_components.append(walk(node["input"], (*path, "input")))
        flat = [item for group in child_components for item in group]
        if not flat: return []
        contract = contracts.get(key, {})
        operation, coefficients = ErrorCompositionKind.SUM.value, [1] * len(flat)
        kwargs: dict[str, Any] = {}
        if op == "Subtract" and len(child_components) >= 2:
            coefficients = [*([1] * len(child_components[0])), *([-1] * len(child_components[1]))]
        elif op == "Multiply" and len(args) == 2:
            left_constant, right_constant = _constant_value(args[0]), _constant_value(args[1])
            if left_constant is not None and child_components[1] and not child_components[0]:
                operation, coefficients = ErrorCompositionKind.SCALAR_MULTIPLICATION.value, [left_constant] * len(flat)
            elif right_constant is not None and child_components[0] and not child_components[1]:
                operation, coefficients = ErrorCompositionKind.SCALAR_MULTIPLICATION.value, [right_constant] * len(flat)
            else:
                operation = ErrorCompositionKind.PRODUCT_PROPAGATION.value
                kwargs["value_bounds"] = contract.get("value_bounds")
        elif op == "Divide" and len(args) == 2:
            denominator = _constant_value(args[1])
            if denominator not in {None, 0} and child_components[0] and not child_components[1]:
                operation, coefficients = ErrorCompositionKind.SCALAR_MULTIPLICATION.value, [1 / denominator] * len(flat)
            else:
                operation = ErrorCompositionKind.QUOTIENT_PROPAGATION.value
                kwargs.update(value_bounds=contract.get("value_bounds"),
                              denominator_lower_bound=contract.get("denominator_lower_bound"))
        elif op == "Power" and len(args) == 2:
            operation, kwargs["exponent"] = ErrorCompositionKind.POWER_PROPAGATION.value, _constant_value(args[1])
            kwargs["value_bounds"] = contract.get("value_bounds")
        elif op in {"FiniteSum", "TransformReduce", "Reduce"}:
            operation = ErrorCompositionKind.REDUCTION_PROPAGATION.value
            if node.get("reduction") == "Mean" or node.get("normalization") == "arithmetic_mean":
                kwargs["count"] = contract.get("count")
        elif op in {"FunctionCall", "OpaqueNumericCall"}:
            operation = ErrorCompositionKind.FUNCTION_PROPAGATION.value
            sensitivity = contract.get("function_sensitivity")
            kwargs["sensitivity"] = FunctionSensitivityContract(**sensitivity) if sensitivity else None
        kwargs.update(kernel_checked=kernel_checked,
                      allow_exact_cancellation=bool(contract.get("allow_exact_cancellation", False)),
                      expected_coefficients=contract.get("expected_coefficients"))
        try:
            result = _reference_compose_error_components(flat, operation=operation, coefficients=coefficients, **kwargs)
        except AuditError as exc:
            obligation = _obligation("GRAPH_PROPAGATION_UNRESOLVED", str(exc), op)
            obligations.append(obligation)
            result = _reference_compose_error_components(flat, operation=ErrorCompositionKind.UNRESOLVED.value,
                                              kernel_checked=kernel_checked)
        obligations.extend(result.obligations)
        trace.extend(result.propagation_trace)
        node_id = _stable_id("graph-node", [key, op])
        derived = _derived_component(result, flat, node_id)
        for group in child_components:
            for item in group: edges.append({"source": item.component_id, "target": node_id})
        nodes.append(PropagationNode(node_id, op, [item.bound.bound_id for item in flat], [],
            [derived.component_id], asdict(result.known_bound), result.composition.proof_rule,
            result.composition.status, [item.semantic_cause_id for item in flat],
            result.composition.dependency_status))
        return [derived]

    outputs = walk(expression, ())
    final = _reference_compose_error_components(outputs, operation=ErrorCompositionKind.SUM.value,
                                     kernel_checked=kernel_checked)
    trace.extend(final.propagation_trace); obligations.extend(final.obligations)
    edges.extend({"source": item.component_id, "target": output} for item in outputs)
    return GraphPropagationResult(nodes, edges, outputs, final, obligations, trace)


def _audit_error(exc: Exception) -> AuditError:
    message = str(exc)
    for prefix in ("native call failed: ", "invalid semantic document: "):
        message = message.replace(prefix, "")
    return AuditError(message)


def _bound(value: dict[str, Any]) -> ErrorBound:
    return ErrorBound(**deepcopy(value))


def _obligations(values: list[dict[str, Any]]) -> list[ProofObligation]:
    return [ProofObligation(**deepcopy(value)) for value in values]


def _component(value: dict[str, Any]) -> ErrorComponent:
    raw = deepcopy(value); raw["bound"] = _bound(raw["bound"])
    return ErrorComponent(**raw)


def _composition_result(value: dict[str, Any]) -> CompositionResult:
    raw = deepcopy(value)
    composition = raw["composition"]
    composition["input_bounds"] = [_bound(item) for item in composition.get("input_bounds", [])]
    if composition.get("output_bound") is not None:
        composition["output_bound"] = _bound(composition["output_bound"])
    return CompositionResult(ErrorComposition(**composition), _bound(raw["known_bound"]),
        raw["total_status"], _obligations(raw.get("obligations", [])),
        raw.get("propagation_trace", []), bool(raw.get("invalidated", False)))


def compose_error_components(components: list[ErrorComponent], *, operation: str = "SUM",
                             coefficients: list[int | float] | None = None,
                             output_metric: str | None = None,
                             value_bounds: dict[str, Any] | None = None,
                             denominator_lower_bound: int | float | None = None,
                             exponent: int | None = None, dimension: int | None = None,
                             operator_norm: Any | None = None,
                             sensitivity: FunctionSensitivityContract | None = None,
                             count: int | None = None, assumptions: list[str] | None = None,
                             vector_length: int | None = None,
                             expected_coefficients: list[int | float] | None = None,
                             allow_exact_cancellation: bool = False,
                             dependence: str = DependencyStatus.DEPENDENCE_UNKNOWN.value,
                             independence_proven: bool = False,
                             kernel_checked: bool = False) -> CompositionResult:
    """Thin projection of the native Error composition result."""
    from formulatracer.native import execute_native_kernel
    native_coefficients = [value if not isinstance(value, float) or math.isfinite(value)
                           else "NON_FINITE" for value in coefficients] if coefficients is not None else None
    request = {"schema_version": "1.0", "kernel": "C", "operation": "COMPOSE_ERROR_COMPONENTS",
        "components": [asdict(item) for item in components], "error_operation": operation,
        "coefficients": native_coefficients,
        "output_metric": output_metric, "value_bounds": deepcopy(value_bounds or {}),
        "denominator_lower_bound": denominator_lower_bound, "exponent": exponent,
        "dimension": dimension, "operator_norm": deepcopy(operator_norm),
        "sensitivity": asdict(sensitivity) if sensitivity else None, "count": count,
        "assumptions": list(assumptions or []), "vector_length": vector_length,
        "expected_coefficients": expected_coefficients,
        "allow_exact_cancellation": allow_exact_cancellation, "dependence": dependence,
        "independence_proven": independence_proven, "kernel_checked": kernel_checked}
    try:
        return _composition_result(execute_native_kernel(request)["result"])
    except Exception as exc:
        raise _audit_error(exc) from exc


def evaluate_error_budget(known_bound: ErrorBound, total_status: str, specification: Any) -> dict[str, Any]:
    """Evaluate a tolerance budget in the native semantic core."""
    from formulatracer.native import execute_native_kernel
    request = {"schema_version": "1.0", "kernel": "C", "operation": "EVALUATE_ERROR_BUDGET",
        "known_bound": asdict(known_bound), "total_status": total_status,
        "absolute_tolerance": getattr(specification, "absolute_tolerance", None)}
    try:
        return execute_native_kernel(request)["result"]
    except Exception as exc:
        raise _audit_error(exc) from exc


def propagate_expression_graph(expression: dict[str, Any], *,
                               local_components: dict[str, list[ErrorComponent]],
                               output: str = "output",
                               contracts: dict[str, dict[str, Any]] | None = None,
                               kernel_checked: bool = False) -> GraphPropagationResult:
    """Propagate graph-attached errors through the native semantic core."""
    from formulatracer.native import execute_native_kernel
    request = {"schema_version": "1.0", "kernel": "C", "operation": "PROPAGATE_ERROR_GRAPH",
        "expression": deepcopy(expression),
        "local_components": {key: [asdict(item) for item in values] for key, values in local_components.items()},
        "output": output, "contracts": deepcopy(contracts or {}), "kernel_checked": kernel_checked}
    try:
        raw = execute_native_kernel(request)["result"]
    except Exception as exc:
        raise _audit_error(exc) from exc
    nodes = []
    for value in raw.get("nodes", []):
        item = deepcopy(value)
        if item.get("output_bound") is not None: item["output_bound"] = _bound(item["output_bound"])
        nodes.append(PropagationNode(**item))
    return GraphPropagationResult(nodes, raw.get("edges", []),
        [_component(item) for item in raw.get("output_components", [])],
        _composition_result(raw["output_composition"]), _obligations(raw.get("obligations", [])),
        raw.get("propagation_trace", []))
