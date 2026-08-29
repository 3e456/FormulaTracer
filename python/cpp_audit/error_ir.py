"""Residual and error IR assembled from independently extracted audit evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from .core import AuditError


class ErrorMetric(str, Enum):
    ABSOLUTE = "ABSOLUTE"
    RELATIVE = "RELATIVE"
    MIXED_ABSOLUTE_RELATIVE = "MIXED_ABSOLUTE_RELATIVE"
    COMPONENTWISE = "COMPONENTWISE"
    L1 = "L1"
    L2 = "L2"
    LINF = "LINF"


class ErrorSource(str, Enum):
    MODEL_ERROR = "MODEL_ERROR"
    APPROXIMATION_ERROR = "APPROXIMATION_ERROR"
    DISCRETIZATION_ERROR = "DISCRETIZATION_ERROR"
    ROUNDING_ERROR = "ROUNDING_ERROR"
    CAST_ERROR = "CAST_ERROR"
    OVERFLOW_ERROR = "OVERFLOW_ERROR"
    UNDERFLOW_ERROR = "UNDERFLOW_ERROR"
    PARALLEL_ORDER_ERROR = "PARALLEL_ORDER_ERROR"
    LIBRARY_CONTRACT_ERROR = "LIBRARY_CONTRACT_ERROR"
    STATISTICAL_ERROR = "STATISTICAL_ERROR"
    INPUT_UNCERTAINTY = "INPUT_UNCERTAINTY"
    UNKNOWN_ERROR_SOURCE = "UNKNOWN_ERROR_SOURCE"


class BoundStatus(str, Enum):
    EXACT_ZERO_BOUND = "EXACT_ZERO_BOUND"
    KERNEL_VERIFIED_BOUND = "KERNEL_VERIFIED_BOUND"
    KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS = "KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS"
    REFERENCE_CONTRACT_BOUND = "REFERENCE_CONTRACT_BOUND"
    SYMBOLIC_BOUND = "SYMBOLIC_BOUND"
    INTERVAL_BOUND = "INTERVAL_BOUND"
    NUMERICALLY_CHECKED_ONLY = "NUMERICALLY_CHECKED_ONLY"
    BOUND_NOT_EVALUATED = "BOUND_NOT_EVALUATED"
    BOUND_UNRESOLVED = "BOUND_UNRESOLVED"
    BOUND_INVALID = "BOUND_INVALID"


class ErrorCompositionKind(str, Enum):
    SUM = "SUM"
    MAX = "MAX"
    NORM = "NORM"
    SCALAR_MULTIPLICATION = "SCALAR_MULTIPLICATION"
    PRODUCT_PROPAGATION = "PRODUCT_PROPAGATION"
    QUOTIENT_PROPAGATION = "QUOTIENT_PROPAGATION"
    POWER_PROPAGATION = "POWER_PROPAGATION"
    FUNCTION_PROPAGATION = "FUNCTION_PROPAGATION"
    LINEAR_MAP_PROPAGATION = "LINEAR_MAP_PROPAGATION"
    REDUCTION_PROPAGATION = "REDUCTION_PROPAGATION"
    CUSTOM = "CUSTOM"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class ErrorBound:
    status: str
    metric: str
    expression: Any | None
    exact_value: int | float | None = None
    theorem_reference: str | None = None
    assumptions: list[str] = field(default_factory=list)
    bound_id: str = ""
    lower_bound: Any | None = None
    upper_bound: Any | None = None
    symmetric_bound: Any | None = None
    symbolic_expression: Any | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    domain: Any | None = None
    proof_evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.bound_id:
            self.bound_id = _id("bound", [self.status, self.metric, self.expression, self.theorem_reference])
        if self.symbolic_expression is None:
            self.symbolic_expression = deepcopy(self.expression)
        if self.symmetric_bound is None and self.expression is not None:
            self.symmetric_bound = deepcopy(self.expression)
        if self.exact_value == 0:
            self.lower_bound = 0 if self.lower_bound is None else self.lower_bound
            self.upper_bound = 0 if self.upper_bound is None else self.upper_bound
        elif self.expression is not None:
            self.lower_bound = ({"op": "Negate", "args": [deepcopy(self.expression)]}
                                if self.lower_bound is None else self.lower_bound)
            self.upper_bound = deepcopy(self.expression) if self.upper_bound is None else self.upper_bound
        if self.theorem_reference and not self.proof_evidence:
            self.proof_evidence = {"kind": "LEAN_THEOREM_REFERENCE", "theorem": self.theorem_reference}


@dataclass
class ProofObligation:
    obligation_id: str
    kind: str
    description: str
    status: str = "UNRESOLVED"
    component_id: str | None = None
    required_evidence: list[str] = field(default_factory=list)
    origin_id: str | None = None
    semantic_cause_id: str | None = None
    source_component: str | None = None

    def __post_init__(self) -> None:
        if self.source_component is None:
            self.source_component = self.component_id


@dataclass
class ErrorComponent:
    component_id: str
    source: str
    expression: Any
    metric: str
    bound: ErrorBound
    proof_status: str
    provenance: dict[str, Any]
    origin_id: str
    semantic_cause_id: str
    assumptions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


@dataclass
class ResidualExpression:
    status: str
    expression: Any | None
    implementation_expression: Any
    theory_expression: Any | None
    output: str
    scalar_or_componentwise: str
    shape: list[int] | None
    dimensions: list[str] | None
    alignment: str
    numeric_samples_used_as_proof: bool = False
    residual_id: str = ""
    theory_expression_id: str | None = None
    implementation_expression_id: str | None = None
    raw_relation: Any | None = None
    normalized_residual: Any | None = None
    domain: Any | None = None
    axes: list[int] | None = None
    numeric_domain: str | None = None
    source_correspondence: dict[str, Any] = field(default_factory=dict)
    transformation_trace: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.raw_relation = deepcopy(self.raw_relation if self.raw_relation is not None else self.expression)
        self.normalized_residual = deepcopy(self.normalized_residual if self.normalized_residual is not None else self.expression)
        self.theory_expression_id = self.theory_expression_id or (_id("theory", self.theory_expression) if self.theory_expression is not None else None)
        self.implementation_expression_id = self.implementation_expression_id or _id("implementation", self.implementation_expression)
        self.residual_id = self.residual_id or _id("residual", [self.theory_expression_id, self.implementation_expression_id, self.normalized_residual])
        if self.axes is None and self.shape:
            self.axes = list(range(len(self.shape)))


@dataclass
class ErrorSpecification:
    metric: str = ErrorMetric.ABSOLUTE.value
    absolute_tolerance: float | None = None
    relative_tolerance: float | None = None
    reference_nonzero: bool | None = None
    axis: int | None = None
    dimension: str | None = None
    output: str | None = None
    mixed_tolerance: dict[str, float] | None = None
    per_output: dict[str, Any] = field(default_factory=dict)
    per_axis: dict[str, Any] | None = None
    per_dimension: dict[str, Any] | None = None

    @classmethod
    def from_value(cls, value: dict[str, Any] | None, *, output: str) -> "ErrorSpecification":
        raw = deepcopy(value or {})
        raw.setdefault("output", output)
        try:
            result = cls(**raw)
            result.metric = ErrorMetric(result.metric).value
        except (TypeError, ValueError) as exc:
            raise AuditError(f"INVALID_ERROR_SPECIFICATION: {exc}") from exc
        if result.absolute_tolerance is not None and result.absolute_tolerance < 0:
            raise AuditError("NEGATIVE_ABSOLUTE_TOLERANCE")
        if result.relative_tolerance is not None and result.relative_tolerance < 0:
            raise AuditError("NEGATIVE_RELATIVE_TOLERANCE")
        if result.metric == ErrorMetric.RELATIVE.value and result.reference_nonzero is False:
            raise AuditError("RELATIVE_ERROR_DENOMINATOR_ZERO")
        if result.metric == ErrorMetric.RELATIVE.value and result.reference_nonzero is None:
            raise AuditError("RELATIVE_ERROR_DOMAIN_UNRESOLVED")
        if result.metric == ErrorMetric.MIXED_ABSOLUTE_RELATIVE.value and (
                result.absolute_tolerance is None or result.relative_tolerance is None):
            raise AuditError("MIXED_ERROR_REQUIRES_BOTH_TOLERANCES")
        return result


@dataclass
class ErrorComposition:
    rule: str
    status: str
    component_ids: list[str]
    cancellation_assumed: bool = False
    kind: str = ErrorCompositionKind.UNRESOLVED.value
    composition_id: str = ""
    operation: str = ErrorCompositionKind.UNRESOLVED.value
    input_components: list[str] = field(default_factory=list)
    input_bounds: list[dict[str, Any]] = field(default_factory=list)
    output_metric: str | None = None
    output_bound: ErrorBound | None = None
    assumptions: list[str] = field(default_factory=list)
    proof_rule: str | None = None
    proof_evidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    dependency_status: str = "DEPENDENCE_UNKNOWN"

    def __post_init__(self) -> None:
        self.operation = self.operation if self.operation != ErrorCompositionKind.UNRESOLVED.value else self.kind
        self.input_components = self.input_components or list(self.component_ids)
        if not self.composition_id:
            self.composition_id = _id("composition", [self.operation, self.input_components, self.rule])


@dataclass
class GraphEnclosure:
    status: str
    output: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, str]]
    output_bound: ErrorBound
    node_bounds: list[dict[str, Any]] = field(default_factory=list)
    edge_dependencies: list[dict[str, str]] = field(default_factory=list)
    input_bounds: list[dict[str, Any]] = field(default_factory=list)
    unresolved_nodes: list[str] = field(default_factory=list)
    proof_dependencies: list[str] = field(default_factory=list)
    propagation_trace: list[dict[str, Any]] = field(default_factory=list)
    known_output_bound: ErrorBound | None = None
    total_output_status: str = "TOTAL_ERROR_BOUND_UNRESOLVED"
    error_budget: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_bounds:
            self.node_bounds = deepcopy(self.nodes)
        if not self.edge_dependencies:
            self.edge_dependencies = deepcopy(self.edges)


@dataclass
class ErrorAnalysis:
    residual_expression: ResidualExpression
    error_specification: ErrorSpecification
    error_components: list[ErrorComponent]
    error_composition: ErrorComposition
    proof_obligations: list[ProofObligation]
    graph_enclosure: GraphEnclosure
    component_status: str
    total_status: str

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(asdict(self))


def _root(ir: dict[str, Any] | None) -> Any:
    if not ir:
        return None
    outputs = ir.get("outputs")
    return deepcopy(outputs[0].get("expression")) if isinstance(outputs, list) and outputs else deepcopy(ir)


def _output_metadata(ir: dict[str, Any] | None) -> tuple[list[int] | None, list[str] | None, str | None]:
    if not ir:
        return None, None, None
    outputs = ir.get("outputs")
    item = outputs[0] if isinstance(outputs, list) and outputs else ir
    return item.get("shape") or ir.get("shape"), item.get("dimensions") or ir.get("dimensions"), item.get("mathematical_domain") or ir.get("mathematical_domain")


def _id(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    return f"{prefix}-{sha256(encoded).hexdigest()[:12]}"


def _add_component(components: list[ErrorComponent], component: ErrorComponent) -> None:
    existing = next((item for item in components if item.semantic_cause_id == component.semantic_cause_id), None)
    if existing is None:
        components.append(component)
    elif asdict(existing) != asdict(component):
        raise AuditError(f"CONFLICTING_ERROR_COMPONENT: {component.semantic_cause_id}")


def _reference_build_error_analysis(*, theory_ir: dict[str, Any] | None, implementation_ir: dict[str, Any],
                         output: str, comparison_relation: str,
                         comparison: dict[str, Any] | None = None,
                         numeric_type_semantics: dict[str, Any] | None = None,
                         ieee754_semantics: dict[str, Any] | None = None,
                         parallel_semantics: dict[str, Any] | None = None,
                         library_contracts: list[dict[str, Any]] | None = None,
                         approximation_proofs: list[dict[str, Any]] | None = None,
                         transformation_trace: dict[str, Any] | None = None,
                         propagation_context: dict[str, Any] | None = None,
                         kernel_checked: bool = False,
                         specification: dict[str, Any] | None = None) -> ErrorAnalysis:
    """Build error evidence without using runtime samples as proof or inventing bounds."""
    spec = ErrorSpecification.from_value(specification, output=output)
    types = numeric_type_semantics or {}
    output_type = (types.get("outputs") or {}).get(output) or next(iter((types.get("outputs") or {}).values()), {})
    shape, dimensions = output_type.get("shape"), output_type.get("dimensions")
    theory_shape, theory_dimensions, theory_domain = _output_metadata(theory_ir)
    execution_domain = output_type.get("mathematical_domain")
    shape_mismatch = theory_shape is not None and shape is not None and theory_shape != shape
    dimension_mismatch = (theory_dimensions is not None and dimensions is not None and
                          theory_dimensions != dimensions)
    domain_mismatch = theory_domain is not None and execution_domain is not None and theory_domain != execution_domain
    componentwise = bool(shape) or bool(dimensions)
    implementation_expression, theory_expression = _root(implementation_ir), _root(theory_ir)
    exact = (comparison_relation in {"EXACT_EQUAL", "EQUIVALENT_UNDER_ASSUMPTIONS"} and
             bool(comparison and comparison.get("match")) and
             not (shape_mismatch or dimension_mismatch or domain_mismatch))
    if theory_expression is None:
        residual_status, residual_ir = "THEORY_EXPRESSION_UNAVAILABLE", None
    elif exact:
        residual_status, residual_ir = "EXACT_ZERO_RESIDUAL", {"op": "Constant", "value": 0}
    else:
        residual_status = "SYMBOLIC_RESIDUAL"
        residual_ir = {"op": "ComponentwiseSubtract" if componentwise else "Subtract",
                       "args": [deepcopy(implementation_expression), deepcopy(theory_expression)]}
    residual = ResidualExpression(residual_status, residual_ir, implementation_expression,
        theory_expression, output, "COMPONENTWISE" if componentwise else "SCALAR", shape, dimensions,
        "DIMENSION_NAMES_PRESERVED" if dimensions else "POSITIONAL_SHAPE_PRESERVED" if shape else "SCALAR",
        False, raw_relation=({"op": "ComponentwiseSubtract" if componentwise else "Subtract",
                              "args": [deepcopy(implementation_expression), deepcopy(theory_expression)]}
                             if theory_expression is not None else None),
        domain=theory_domain or output_type.get("mathematical_domain"),
        numeric_domain=output_type.get("mathematical_domain"),
        theory_expression_id=(theory_ir or {}).get("expression_id"),
        implementation_expression_id=implementation_ir.get("expression_id"),
        source_correspondence=deepcopy((comparison or {}).get("mapping", {})),
        transformation_trace=deepcopy(transformation_trace or {}))
    components: list[ErrorComponent] = []
    obligations: list[ProofObligation] = []
    if shape_mismatch:
        residual.status = "SHAPE_MISMATCH"
        obligations.append(ProofObligation("residual-shape-match", "SHAPE_COMPATIBILITY",
            f"Theory shape {theory_shape} must match implementation shape {shape}",
            required_evidence=["shape equality"], origin_id="residual", semantic_cause_id="residual-shape"))
    if dimension_mismatch:
        residual.status = "DIMENSION_ALIGNMENT_MISMATCH"
        obligations.append(ProofObligation("residual-dimension-match", "DIMENSION_ALIGNMENT",
            f"Theory dimensions {theory_dimensions} must match implementation dimensions {dimensions}",
            required_evidence=["named dimension alignment"], origin_id="residual", semantic_cause_id="residual-dimensions"))
    if domain_mismatch:
        residual.status = "DOMAIN_MISMATCH"
        obligations.append(ProofObligation("residual-domain-match", "MATHEMATICAL_DOMAIN_COMPATIBILITY",
            f"Theory domain {theory_domain} must match implementation domain {execution_domain}",
            required_evidence=["domain embedding or equality"], origin_id="residual", semantic_cause_id="residual-domain"))
    if exact:
        _add_component(components, ErrorComponent("mathematical-residual", ErrorSource.MODEL_ERROR.value,
            {"op": "Constant", "value": 0}, spec.metric,
            ErrorBound("EXACT_ZERO_BOUND", spec.metric, {"op": "Constant", "value": 0}, 0,
                       "CppAudit.Error.exact_equivalence_has_zero_residual"),
            "KERNEL_VERIFIABLE", {"kind": "SYMBOLIC_COMPARISON"}, "comparison", "exact-mathematical-residual"))
    elif not approximation_proofs:
        cause = "unbounded-symbolic-residual"
        source = ErrorSource.MODEL_ERROR.value if theory_expression is not None else ErrorSource.UNKNOWN_ERROR_SOURCE.value
        _add_component(components, ErrorComponent(cause, source,
            deepcopy(residual_ir) if residual_ir is not None else {"op": "OpaqueResidual"}, spec.metric,
            ErrorBound("BOUND_UNRESOLVED", spec.metric, None), "UNRESOLVED",
            {"kind": "INDEPENDENT_SYMBOLIC_RESIDUAL"}, cause, cause))
        obligations.append(ProofObligation("bound-symbolic-residual", "MODEL_ERROR_BOUND_REQUIRED",
            "A bound for the unmatched symbolic residual is required", component_id=cause,
            required_evidence=["model discrepancy bound"], origin_id=cause, semantic_cause_id=cause))
    for proof in approximation_proofs or []:
        theorem_id = str(proof.get("theorem_id") or proof.get("family_id"))
        bound = proof.get("error_bound", {})
        family_id = str(proof.get("family_id", ""))
        discrete_family = any(token in family_id for token in
                              ("difference", "rectangle", "midpoint", "trapezoidal", "simpson"))
        source = (ErrorSource.DISCRETIZATION_ERROR.value if comparison_relation == "DISCRETIZATION_OF" or discrete_family
                  else ErrorSource.APPROXIMATION_ERROR.value)
        proof_status = str(proof.get("proof_status", "UNRESOLVED"))
        verified = proof_status.startswith("KERNEL_VERIFIED")
        component = ErrorComponent(f"approximation-{theorem_id}", source,
            bound.get("error_expression") or {"op": "Residual", "family": proof.get("family_id")}, spec.metric,
            ErrorBound(("KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS" if verified and proof.get("remaining_obligations") else
                        "KERNEL_VERIFIED_BOUND" if verified else "BOUND_UNRESOLVED"), spec.metric, bound.get("bound"),
                       theorem_reference=proof.get("evidence", {}).get("lean_theorem_name"),
                       assumptions=[item.get("statement", "") for item in proof.get("assumptions", [])],
                       parameters=deepcopy(proof.get("parameters", {})), domain=deepcopy(proof.get("domain")),
                       proof_evidence=deepcopy(proof.get("evidence", {}))),
            proof_status, {"kind": "PHASE7_APPROXIMATION_PROOF", "family_id": proof.get("family_id"),
                           "error_role": "LOCAL_ERROR"},
            theorem_id, theorem_id)
        _add_component(components, component)
        for item in proof.get("remaining_obligations", []):
            oid = str(item.get("assumption_id") or _id("approx-obligation", item))
            obligations.append(ProofObligation(oid, str(item.get("kind", "APPROXIMATION_ASSUMPTION")),
                f"Discharge approximation assumption {oid}", component_id=component.component_id,
                origin_id=theorem_id, semantic_cause_id=f"{theorem_id}:{oid}"))
    ieee = ieee754_semantics or {}
    if ieee.get("operations"):
        source_specs = [(ErrorSource.ROUNDING_ERROR.value, "ieee754-rounding", "IEEE-754 rounding bound"),
                        (ErrorSource.OVERFLOW_ERROR.value, "ieee754-overflow", "finite-range overflow exclusion"),
                        (ErrorSource.UNDERFLOW_ERROR.value, "ieee754-underflow", "underflow/subnormal bound")]
        for source, cause, description in source_specs:
            component = ErrorComponent(cause, source, {"op": "OpaqueErrorTerm", "source": source}, spec.metric,
                ErrorBound("BOUND_NOT_EVALUATED", spec.metric, None), "UNRESOLVED",
                {"kind": "IEEE754_SEMANTICS", "operation_count": len(ieee["operations"])}, cause, cause)
            _add_component(components, component)
            obligations.append(ProofObligation(f"bound-{cause}", "NUMERICAL_EXECUTION_BOUND", description,
                component_id=cause, required_evidence=["range analysis", "machine error model"],
                origin_id=cause, semantic_cause_id=cause))
    for cast in types.get("casts", []):
        cause = _id("cast", cast)
        component = ErrorComponent(cause, ErrorSource.CAST_ERROR.value,
            {"op": "OpaqueErrorTerm", "source": ErrorSource.CAST_ERROR.value, "cast": cast}, spec.metric,
            ErrorBound("EXACT_ZERO_BOUND" if cast.get("exact") == "EXACT" else "BOUND_NOT_EVALUATED", spec.metric,
                       {"op": "Constant", "value": 0} if cast.get("exact") == "EXACT" else None,
                       0 if cast.get("exact") == "EXACT" else None),
            "PROVEN_EXACT" if cast.get("exact") == "EXACT" else "UNRESOLVED",
            {"kind": "NUMERIC_CAST"}, cause, cause)
        _add_component(components, component)
        if component.proof_status == "UNRESOLVED":
            obligations.append(ProofObligation(f"bound-{cause}", "CAST_ERROR_BOUND", "Bound inexact cast error",
                component_id=cause, origin_id=cause, semantic_cause_id=cause))
    parallel = parallel_semantics or {}
    if parallel.get("claims", {}).get("PARALLEL_REDUCTION_ORDER_DIFFERS") in {"POSSIBLE", "MIXED"}:
        cause = "parallel-reduction-order"
        exact_parallel = execution_domain in {"Integer", "Rational"} and not ieee.get("operations")
        _add_component(components, ErrorComponent(cause, ErrorSource.PARALLEL_ORDER_ERROR.value,
            ({"op": "Constant", "value": 0} if exact_parallel else
             {"op": "OpaqueErrorTerm", "source": ErrorSource.PARALLEL_ORDER_ERROR.value}), spec.metric,
            ErrorBound("EXACT_ZERO_BOUND" if exact_parallel else "BOUND_NOT_EVALUATED", spec.metric,
                       {"op": "Constant", "value": 0} if exact_parallel else None,
                       0 if exact_parallel else None), "PROVEN_EXACT_DOMAIN" if exact_parallel else "UNRESOLVED",
            {"kind": "PARALLEL_SEMANTICS", "policy": parallel.get("overall_policy")}, cause, cause))
        if not exact_parallel:
            obligations.append(ProofObligation(f"bound-{cause}", "PARALLEL_ORDER_BOUND",
                "Bound floating reduction reordering", component_id=cause, origin_id=cause, semantic_cause_id=cause))
    for contract in library_contracts or []:
        reference_status = contract.get("reference_status") or contract.get("provenance", {}).get("reference_status")
        reference_only = (contract.get("proof_status") == "REFERENCE_CONTRACT_ONLY" or
                          contract.get("reference_status") in {"REFERENCE_ONLY", "REFERENCE_CONTRACT_ONLY"} or
                          contract.get("contract_status") in {"REFERENCE_ONLY", "NEEDS_CONTRACT"} or
                          bool(reference_status and reference_status != "LEAN_VERIFIED_MAPPING"))
        if reference_only:
            name = str(contract.get("qualified_callable") or contract.get("callable") or "unknown")
            cause = f"library-contract:{name}"
            obligations.append(ProofObligation(_id("library", cause), "LIBRARY_SEMANTIC_PROOF_REQUIRED",
                f"Kernel-level semantic mapping required for {name}", required_evidence=["formal semantic contract"],
                origin_id=name, semantic_cause_id=cause))
    from .error_composition import (FunctionSensitivityContract, compose_error_components,
                                    evaluate_error_budget, propagate_expression_graph)
    propagation_context = deepcopy(propagation_context or {})
    coefficient_map = propagation_context.get("component_coefficients", {})
    coefficients = [coefficient_map.get(item.component_id, 1) for item in components]
    sensitivity_value = propagation_context.get("function_sensitivity")
    sensitivity = FunctionSensitivityContract(**sensitivity_value) if sensitivity_value else None
    axis = spec.axis if spec.axis is not None else 0
    vector_length = shape[axis] if shape and 0 <= axis < len(shape) else None
    composition_result = compose_error_components(components,
        operation=propagation_context.get("operation", ErrorCompositionKind.SUM.value),
        coefficients=coefficients, output_metric=propagation_context.get("output_metric"),
        value_bounds=propagation_context.get("value_bounds"),
        denominator_lower_bound=propagation_context.get("denominator_lower_bound"),
        exponent=propagation_context.get("exponent"), dimension=propagation_context.get("dimension"),
        operator_norm=propagation_context.get("operator_norm"), count=propagation_context.get("count"),
        sensitivity=sensitivity, vector_length=vector_length,
        expected_coefficients=propagation_context.get("expected_coefficients"),
        assumptions=propagation_context.get("assumptions"),
        allow_exact_cancellation=bool(propagation_context.get("allow_exact_cancellation", False)),
        dependence=propagation_context.get("dependence", "DEPENDENCE_UNKNOWN"),
        independence_proven=bool(propagation_context.get("independence_proven", False)),
        kernel_checked=kernel_checked)
    graph_propagation = None
    component_paths = propagation_context.get("component_paths", {})
    if component_paths:
        by_id = {item.component_id: item for item in components}
        local_by_path: dict[str, list[ErrorComponent]] = {}
        for component_id, path_value in component_paths.items():
            if component_id not in by_id:
                raise AuditError(f"ERROR_COMPONENT_PATH_UNKNOWN: {component_id}")
            path_key = path_value if isinstance(path_value, str) else "/" + "/".join(str(item) for item in path_value)
            local_by_path.setdefault(path_key, []).append(by_id[component_id])
        graph_propagation = propagate_expression_graph(implementation_expression,
            local_components=local_by_path, output=output,
            contracts=propagation_context.get("node_contracts"), kernel_checked=kernel_checked)
        mapped = set(component_paths)
        final_components = [*graph_propagation.output_components,
                            *[item for item in components if item.component_id not in mapped]]
        composition_result = compose_error_components(final_components,
            operation=ErrorCompositionKind.SUM.value, kernel_checked=kernel_checked)
        composition_result.propagation_trace = [*graph_propagation.propagation_trace,
                                                *composition_result.propagation_trace]
        composition_result.obligations.extend(graph_propagation.obligations)
    obligations.extend(composition_result.obligations)
    unique_obligations = {item.semantic_cause_id or item.obligation_id: item for item in obligations}
    obligations = list(unique_obligations.values())
    unresolved = (not components or any(item.proof_status == "UNRESOLVED" or
                  item.bound.status in {"BOUND_NOT_EVALUATED", "BOUND_UNRESOLVED"}
                  for item in components) or bool(obligations))
    verified_nonzero = any(item.bound.status.startswith("KERNEL_VERIFIED_BOUND") for item in components)
    component_status = "PARTIAL_ERROR_BOUND_VERIFIED" if verified_nonzero and unresolved else (
        "ALL_COMPONENT_BOUNDS_VERIFIED" if not unresolved else "ERROR_COMPONENTS_UNRESOLVED")
    total_status = ("TOTAL_ERROR_BOUND_UNRESOLVED" if composition_result.invalidated or unresolved or
        composition_result.total_status != "TOTAL_ERROR_BOUND_VERIFIED" else (
        "EXACT_ZERO_BOUND_VERIFIED" if exact and all(item.bound.exact_value == 0 for item in components)
        else "TOTAL_ERROR_BOUND_VERIFIED"))
    composition = composition_result.composition
    total_bound = (ErrorBound("EXACT_ZERO_BOUND", spec.metric, {"op": "Constant", "value": 0}, 0,
                              "CppAudit.Error.zero_residual_has_zero_absolute_error")
                   if total_status == "EXACT_ZERO_BOUND_VERIFIED" else
                   ErrorBound("BOUND_INVALID" if composition_result.invalidated else
                              "BOUND_NOT_EVALUATED" if total_status != "TOTAL_ERROR_BOUND_VERIFIED" else
                              composition_result.known_bound.status, spec.metric,
                              None if composition_result.invalidated else composition_result.known_bound.expression))
    nodes = [{"node_id": item.component_id, "kind": "ERROR_COMPONENT", "bound_status": item.bound.status}
             for item in components]
    propagation_node_id = f"propagation:{output}"
    edges = ([{"source": item.component_id, "target": propagation_node_id} for item in components] +
             [{"source": propagation_node_id, "target": output}])
    propagation_node = {"node_id": propagation_node_id, "operation": composition.operation,
        "input_bounds": [item.bound.bound_id for item in components],
        "local_error": [item.component_id for item in components],
        "propagated_error": [item.semantic_cause_id for item in components],
        "output_bound": asdict(composition_result.known_bound), "proof_rule": composition.proof_rule,
        "status": composition.status, "dependency_status": composition.dependency_status}
    nodes.append(propagation_node)
    if graph_propagation:
        nodes.extend(asdict(item) for item in graph_propagation.nodes)
        edges.extend(graph_propagation.edges)
    budget = evaluate_error_budget(composition_result.known_bound, total_status, spec)
    graph_status = ("ENCLOSURE_INVALIDATED" if composition_result.invalidated else
                    "ENCLOSURE_UNRESOLVED" if total_status not in {"TOTAL_ERROR_BOUND_VERIFIED", "EXACT_ZERO_BOUND_VERIFIED"}
                    else "ENCLOSURE_VERIFIED")
    graph = GraphEnclosure(graph_status, output, nodes,
        edges, total_bound, unresolved_nodes=[item.component_id for item in components if item.bound.status in
                                             {"BOUND_NOT_EVALUATED", "BOUND_UNRESOLVED"}] +
                                             [item.obligation_id for item in obligations if item.component_id is None],
        proof_dependencies=[item.bound.theorem_reference for item in components if item.bound.theorem_reference],
        propagation_trace=composition_result.propagation_trace,
        known_output_bound=composition_result.known_bound, total_output_status=total_status, error_budget=budget)
    return ErrorAnalysis(residual, spec, components, composition, obligations, graph, component_status, total_status)


def _bound_from_native(value: dict[str, Any]) -> ErrorBound:
    return ErrorBound(**deepcopy(value))


def _analysis_from_native(value: dict[str, Any]) -> ErrorAnalysis:
    raw = deepcopy(value)
    components = []
    for item in raw["error_components"]:
        item["bound"] = _bound_from_native(item["bound"])
        components.append(ErrorComponent(**item))
    composition = raw["error_composition"]
    composition["input_bounds"] = [_bound_from_native(item) if isinstance(item, dict) else item
                                   for item in composition.get("input_bounds", [])]
    if composition.get("output_bound") is not None:
        composition["output_bound"] = _bound_from_native(composition["output_bound"])
    graph = raw["graph_enclosure"]
    graph["output_bound"] = _bound_from_native(graph["output_bound"])
    if graph.get("known_output_bound") is not None:
        graph["known_output_bound"] = _bound_from_native(graph["known_output_bound"])
    return ErrorAnalysis(ResidualExpression(**raw["residual_expression"]),
        ErrorSpecification(**raw["error_specification"]), components,
        ErrorComposition(**composition), [ProofObligation(**item) for item in raw["proof_obligations"]],
        GraphEnclosure(**graph), raw["component_status"], raw["total_status"])


def build_error_analysis(*, theory_ir: dict[str, Any] | None, implementation_ir: dict[str, Any],
                         output: str, comparison_relation: str,
                         comparison: dict[str, Any] | None = None,
                         numeric_type_semantics: dict[str, Any] | None = None,
                         ieee754_semantics: dict[str, Any] | None = None,
                         parallel_semantics: dict[str, Any] | None = None,
                         library_contracts: list[dict[str, Any]] | None = None,
                         approximation_proofs: list[dict[str, Any]] | None = None,
                         transformation_trace: dict[str, Any] | None = None,
                         propagation_context: dict[str, Any] | None = None,
                         kernel_checked: bool = False,
                         specification: dict[str, Any] | None = None) -> ErrorAnalysis:
    """Build Error IR through the native core; Python only projects typed objects."""
    from formulatracer.native import execute_native_kernel
    request = {"schema_version": "1.0", "kernel": "C", "operation": "BUILD_ERROR_ANALYSIS",
        "theory_ir": deepcopy(theory_ir), "implementation_ir": deepcopy(implementation_ir),
        "output": output, "comparison_relation": comparison_relation,
        "comparison": deepcopy(comparison), "numeric_type_semantics": deepcopy(numeric_type_semantics),
        "ieee754_semantics": deepcopy(ieee754_semantics), "parallel_semantics": deepcopy(parallel_semantics),
        "library_contracts": deepcopy(library_contracts or []),
        "approximation_proofs": deepcopy(approximation_proofs or []),
        "transformation_trace": deepcopy(transformation_trace or {}),
        "propagation_context": deepcopy(propagation_context or {}), "kernel_checked": kernel_checked,
        "specification": deepcopy(specification)}
    try:
        return _analysis_from_native(execute_native_kernel(request)["result"])
    except Exception as exc:
        message = str(exc)
        for prefix in ("native call failed: ", "invalid semantic document: "):
            message = message.replace(prefix, "")
        raise AuditError(message) from exc
