"""Theory-to-artifact end-to-end enclosure claims.

This module composes existing evidence.  It never upgrades runtime observations,
reference text, or a range subclaim into a kernel claim.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
from pathlib import Path
import json
import math
from typing import Any, Iterable, Mapping


class VerificationLayer(str, Enum):
    THEORY = "THEORY"
    IMPLEMENTATION = "IMPLEMENTATION"
    THEORY_IMPLEMENTATION = "THEORY_IMPLEMENTATION"
    TRANSFORMATION = "TRANSFORMATION"
    APPROXIMATION = "APPROXIMATION"
    NUMERIC_EXECUTION = "NUMERIC_EXECUTION"
    RANGE = "RANGE"
    ERROR = "ERROR"
    PARALLEL = "PARALLEL"
    FFI = "FFI"
    SERIALIZATION = "SERIALIZATION"
    ARTIFACT = "ARTIFACT"
    LEAN = "LEAN"


class EndToEndStatus(str, Enum):
    END_TO_END_KERNEL_VERIFIED = "END_TO_END_KERNEL_VERIFIED"
    END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS = "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
    END_TO_END_ENCLOSURE_VERIFIED = "END_TO_END_ENCLOSURE_VERIFIED"
    END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS = "END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS"
    PARTIAL_END_TO_END_VERIFICATION = "PARTIAL_END_TO_END_VERIFICATION"
    END_TO_END_UNRESOLVED = "END_TO_END_UNRESOLVED"
    END_TO_END_FAILED = "END_TO_END_FAILED"


class ErrorCompletenessStatus(str, Enum):
    ERROR_MODEL_COMPLETE = "ERROR_MODEL_COMPLETE"
    ERROR_MODEL_COMPLETE_UNDER_ASSUMPTIONS = "ERROR_MODEL_COMPLETE_UNDER_ASSUMPTIONS"
    ERROR_MODEL_PARTIAL = "ERROR_MODEL_PARTIAL"
    ERROR_SOURCE_UNRESOLVED = "ERROR_SOURCE_UNRESOLVED"


CRITICAL_ERROR_SOURCES = {
    "APPROXIMATION_ERROR", "DISCRETIZATION_ERROR", "ROUNDING_ERROR", "CAST_ERROR",
    "OVERFLOW_ERROR", "UNDERFLOW_ERROR", "PARALLEL_ORDER_ERROR", "FFI_CONVERSION_ERROR",
    "SERIALIZATION_ERROR", "INPUT_UNCERTAINTY",
}
VERIFIED = {"KERNEL_VERIFIED", "KERNEL_VERIFIED_UNDER_ASSUMPTIONS", "ENCLOSURE_VERIFIED",
            "ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS", "REFERENCE_CONTRACT_VERIFIED", "NOT_APPLICABLE"}
KERNEL = {"KERNEL_VERIFIED", "NOT_APPLICABLE"}
ASSUMPTION_STATUSES = {"PROVEN", "PROVIDED", "REFERENCE_CONTRACT"}


@dataclass
class EnclosureEvidence:
    evidence_id: str
    kind: str
    status: str
    source_id: str | None = None
    lean_theorem: str | None = None
    reference_contract: str | None = None
    assumptions: list[str] = field(default_factory=list)
    proof_authority: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayerVerification:
    layer: str
    status: str
    explanation: str
    evidence_ids: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    obligations: list[dict[str, Any]] = field(default_factory=list)
    critical: bool = True


@dataclass
class EndToEndProofEdge:
    source: str
    target: str
    rule: str
    status: str
    lean_theorem: str | None = None
    reference_contract: str | None = None
    assumptions: list[str] = field(default_factory=list)


@dataclass
class EndToEndProofChain:
    nodes: list[dict[str, Any]]
    edges: list[EndToEndProofEdge]
    evidence: list[EnclosureEvidence]
    status: str
    chain_id: str = ""

    def __post_init__(self) -> None:
        if not self.chain_id: self.chain_id = _id("e2e-chain", [self.nodes, self.edges])


@dataclass
class ArtifactEnclosure:
    artifact_id: str
    path: str | None
    format: str
    payload_symbol: str | None
    dataset_variable: str | None
    payload_value_enclosure: Any
    payload_error_enclosure: Any
    serialization_contract: Any
    stored_dtype: str | None
    materialization_status: str
    artifact_hash: str | None
    status: str
    obligations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EndToEndEnclosure:
    value_enclosure: Any
    error_enclosure: Any
    true_value_enclosure: Any
    artifact_enclosures: list[ArtifactEnclosure]
    output_range_constraint_status: str | None
    tolerance_status: str | None
    status: str


@dataclass
class EndToEndVerificationClaim:
    claim_id: str
    root_id: str
    output_id: str
    output_name: str
    theory_expression: Any
    implementation_expression: Any
    transformation_trace: Any
    approximation_proofs: list[Any]
    value_enclosure: Any
    error_components: list[Any]
    known_error_bound: Any
    total_error_bound: Any
    true_value_enclosure: Any
    execution_semantics: Any
    ffi_boundaries: list[Any]
    serialization_boundaries: list[Any]
    artifact: list[ArtifactEnclosure]
    assumptions: list[dict[str, Any]]
    assumption_dependencies: list[dict[str, Any]]
    remaining_obligations: list[dict[str, Any]]
    proof_chain: EndToEndProofChain
    verification_matrix: list[LayerVerification]
    error_completeness_status: str
    tolerance_status: str | None
    output_range_constraint_status: str | None
    observed_result: Any
    observed_result_status: str | None
    model_error_scope: str
    status: str
    explanation: str
    enclosure: EndToEndEnclosure

    def to_dict(self) -> dict[str, Any]: return _serial(self)


def _id(prefix: str, value: Any) -> str:
    return prefix + ":" + sha256(json.dumps(_serial(value), sort_keys=True, default=str).encode()).hexdigest()[:16]


def _serial(value: Any) -> Any:
    if isinstance(value, Enum): return value.value
    if hasattr(value, "__dataclass_fields__"): return {key: _serial(item) for key, item in asdict(value).items()}
    if isinstance(value, dict): return {str(key): _serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_serial(item) for item in value]
    return value


def _walk(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values(): yield from _walk(value)
    elif isinstance(node, list):
        for value in node: yield from _walk(value)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _bound_number(value: Any) -> float | None:
    if _number(value): return abs(float(value))
    if not isinstance(value, dict): return None
    if _number(value.get("exact_value")): return abs(float(value["exact_value"]))
    expression = value.get("expression") or value.get("symmetric_bound")
    if isinstance(expression, dict) and expression.get("op") == "Constant" and _number(expression.get("value")):
        return abs(float(expression["value"]))
    return None


def _expression_is_integer_exact(node: Any) -> bool:
    if not isinstance(node, dict): return isinstance(node, int) and not isinstance(node, bool)
    op = node.get("op")
    if op == "Constant": return isinstance(node.get("value"), int) and not isinstance(node.get("value"), bool)
    if op in {"FreeVariable", "BoundVariable", "IndexedValue"}: return True
    if op in {"Add", "Subtract", "Multiply", "Negate"}:
        children = node.get("args") or [node.get("arg")]
        return all(_expression_is_integer_exact(item) for item in children if item is not None)
    if op == "Power":
        args = node.get("args", [])
        return len(args) == 2 and _expression_is_integer_exact(args[0]) and isinstance(args[1].get("value"), int)
    return False


def _output_root(project: Any, output_id: str) -> str:
    for root in project.roots:
        if any(item.output_id == output_id for item in root.outputs): return root.root_id
    return "root:unresolved"


def _component_id(component: Mapping[str, Any]) -> str:
    return str(component.get("component_id") or component.get("semantic_cause_id") or _id("component", component))


def _component_verified(component: Mapping[str, Any]) -> bool:
    bound = component.get("bound") or {}
    status = str(bound.get("status", "")); proof = str(component.get("proof_status", ""))
    return (status in {"EXACT_ZERO_BOUND", "KERNEL_VERIFIED_BOUND", "KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS",
                       "REFERENCE_CONTRACT_BOUND", "INTERVAL_BOUND"} and
            proof not in {"UNRESOLVED", "FAILED", "REFERENCE_THEOREM_ONLY"})


def _error_completeness(output: Any, synthetic_sources: list[str]) -> tuple[str, list[dict[str, Any]], list[str]]:
    components = list(output.error_components or [])
    seen_causes: set[str] = set(); unique: list[Mapping[str, Any]] = []; duplicate_ids: list[str] = []
    for component in components:
        cause = str(component.get("semantic_cause_id") or component.get("origin_id") or _component_id(component))
        if cause in seen_causes:
            duplicate_ids.append(_component_id(component)); continue
        seen_causes.add(cause); unique.append(component)
    unresolved = [_component_id(item) for item in unique if not _component_verified(item)]
    known_sources = CRITICAL_ERROR_SOURCES | {"MODEL_ERROR", "LIBRARY_CONTRACT_ERROR", "STATISTICAL_ERROR"}
    unresolved.extend(_component_id(item) for item in unique if str(item.get("source")) not in known_sources)
    unresolved.extend(synthetic_sources)
    included = set((output.error_interval or {}).get("component_ids") or [])
    missing = [_component_id(item) for item in unique if _component_verified(item) and _component_id(item) not in included]
    obligations = []
    if duplicate_ids:
        obligations.append({"kind": "SHARED_ERROR_CAUSE_DEDUPLICATED", "status": "RESOLVED",
                            "component_ids": duplicate_ids})
    if missing:
        obligations.append({"kind": "ERROR_COMPONENT_MISSING_FROM_TOTAL", "status": "UNRESOLVED",
                            "component_ids": missing})
    if unresolved:
        obligations.append({"kind": "ERROR_SOURCE_UNRESOLVED", "status": "UNRESOLVED", "sources": sorted(set(unresolved))})
        return ErrorCompletenessStatus.ERROR_SOURCE_UNRESOLVED.value, obligations, sorted(set(unresolved))
    if missing:
        return ErrorCompletenessStatus.ERROR_MODEL_PARTIAL.value, obligations, []
    assumptions = [assumption for item in unique for assumption in item.get("assumptions", [])]
    return (ErrorCompletenessStatus.ERROR_MODEL_COMPLETE_UNDER_ASSUMPTIONS.value if assumptions else
            ErrorCompletenessStatus.ERROR_MODEL_COMPLETE.value), obligations, []


def _assumptions(output: Any, project: Any, layers: list[LayerVerification]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: dict[str, dict[str, Any]] = {}
    dependencies: list[dict[str, Any]] = []
    def add(text: str, status: str, layer: str, source: str) -> None:
        text = str(text)
        current = records.setdefault(text, {"assumption": text, "status": status, "sources": [], "layers": []})
        if status == "UNRESOLVED": current["status"] = status
        elif current["status"] != "UNRESOLVED" and status == "PROVEN": current["status"] = status
        if source not in current["sources"]: current["sources"].append(source)
        if layer not in current["layers"]: current["layers"].append(layer)
        dependencies.append({"assumption": text, "layer": layer, "claim_dependency": output.output_id, "source": source})
    for item in (project.provenance.get("range_specification") or {}).get("ranges", []):
        add(f"{item.get('name')} in [{item.get('lower')}, {item.get('upper')}]", "PROVIDED",
            VerificationLayer.RANGE.value, item.get("name", "range"))
        for text in item.get("assumptions", []): add(text, "PROVIDED", VerificationLayer.RANGE.value, item.get("name", "range"))
    for component in output.error_components or []:
        status = "PROVEN" if _component_verified(component) else "UNRESOLVED"
        for text in component.get("assumptions", []): add(text, status, VerificationLayer.ERROR.value, _component_id(component))
    for layer in layers:
        for text in layer.assumptions: add(text, "PROVIDED", layer.layer, layer.layer)
        for obligation in layer.obligations:
            if obligation.get("kind", "").endswith("REQUIRED"):
                add(obligation.get("kind"), "UNRESOLVED", layer.layer, obligation.get("kind"))
    return list(records.values()), dependencies


def _artifact_for_output(project: Any, output: Any) -> list[ArtifactEnclosure]:
    result: list[ArtifactEnclosure] = []
    for artifact in project.artifacts:
        names = {artifact.payload_symbol, artifact.dataset_variable}
        names.update(item.name for item in getattr(artifact, "dataset_outputs", []))
        if output.name not in names: continue
        contract = artifact.library_contract or {}
        contract_status = str(contract.get("proof_status") or contract.get("status") or "")
        preserving = bool(contract.get("value_preserving")) and contract_status in {
            "REFERENCE_CONTRACT_VERIFIED", "KERNEL_VERIFIED", "KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
        }
        obligations = list(artifact.range_obligations or [])
        if artifact.serialization_cast:
            obligations.append({"kind": "SERIALIZATION_ERROR", "status": "UNRESOLVED",
                                "detail": deepcopy(artifact.serialization_cast)})
        if not preserving:
            obligations.append({"kind": "SERIALIZATION_VALUE_PRESERVATION_REQUIRED", "status": "UNRESOLVED"})
        raw_path = artifact.path_expression
        materialized, digest = "ARTIFACT_NOT_MATERIALIZED", None
        if raw_path:
            candidate = Path(str(raw_path))
            if candidate.is_file():
                materialized = "ARTIFACT_MATERIALIZED"
                digest = sha256(candidate.read_bytes()).hexdigest()
        status = ("ARTIFACT_PAYLOAD_ENCLOSURE_VERIFIED" if preserving and not obligations and
                  artifact.certified_payload_range else "ARTIFACT_PAYLOAD_ENCLOSURE_UNRESOLVED")
        result.append(ArtifactEnclosure(artifact.sink_id, raw_path, artifact.format, artifact.payload_symbol,
            artifact.dataset_variable, deepcopy(output.value_interval), deepcopy(output.error_interval),
            deepcopy(contract), artifact.dtype, materialized, digest, status, obligations))
    return result


def _observed_status(observed: Any, enclosure: Any) -> str | None:
    if observed is None: return None
    if not _number(observed) or not isinstance(enclosure, dict): return "OBSERVED_VALUE_COMPARISON_UNRESOLVED"
    lower, upper = enclosure.get("lower"), enclosure.get("upper")
    if not (_number(lower) and _number(upper)): return "OBSERVED_VALUE_COMPARISON_UNRESOLVED"
    return ("OBSERVED_VALUE_WITHIN_CERTIFIED_RANGE" if lower <= observed <= upper else
            "OBSERVED_VALUE_OUTSIDE_CERTIFIED_RANGE")


def _status(layers: list[LayerVerification], assumptions: list[dict[str, Any]], failed: bool) -> str:
    if failed: return EndToEndStatus.END_TO_END_FAILED.value
    critical = [layer for layer in layers if layer.critical]
    unresolved = [layer for layer in critical if layer.status not in VERIFIED]
    verified = [layer for layer in critical if layer.status in VERIFIED]
    has_assumptions = bool(assumptions)
    assumptions_closed = all(item["status"] in ASSUMPTION_STATUSES for item in assumptions)
    if unresolved:
        return (EndToEndStatus.PARTIAL_END_TO_END_VERIFICATION.value if verified else
                EndToEndStatus.END_TO_END_UNRESOLVED.value)
    if not assumptions_closed: return EndToEndStatus.PARTIAL_END_TO_END_VERIFICATION.value
    if all(layer.status in KERNEL for layer in critical):
        return (EndToEndStatus.END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value if has_assumptions else
                EndToEndStatus.END_TO_END_KERNEL_VERIFIED.value)
    return (EndToEndStatus.END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS.value if has_assumptions else
            EndToEndStatus.END_TO_END_ENCLOSURE_VERIFIED.value)


def _explanation(status: str, layers: list[LayerVerification]) -> str:
    unresolved = [layer.layer for layer in layers if layer.critical and layer.status not in VERIFIED]
    if status == EndToEndStatus.END_TO_END_FAILED.value:
        return "An observed value or required output constraint contradicts the certified enclosure."
    if unresolved:
        return ("Verified subclaims are retained, but the overall audit remains incomplete because these critical "
                f"layers are unresolved: {', '.join(unresolved)}.")
    if "UNDER_ASSUMPTIONS" in status:
        return "Every critical layer is enclosed, subject to the explicitly listed assumptions."
    return "Every critical layer required by this route is verified by the recorded proof chain."


def _proof_chain(output: Any, layers: list[LayerVerification], artifacts: list[ArtifactEnclosure]) -> EndToEndProofChain:
    ordered = ["TheoryExpression", "ImplementationExpression", "ApproximationErrorBound", "NumericErrorComponents",
               "TotalErrorBound", "ValueInterval", "TrueValueEnclosure"]
    if artifacts: ordered += ["SerializationBoundary", "ArtifactEnclosure"]
    by_layer = {item.layer: item for item in layers}
    edge_layers = [VerificationLayer.THEORY_IMPLEMENTATION.value, VerificationLayer.APPROXIMATION.value,
                   VerificationLayer.NUMERIC_EXECUTION.value, VerificationLayer.ERROR.value,
                   VerificationLayer.RANGE.value, VerificationLayer.RANGE.value,
                   VerificationLayer.SERIALIZATION.value, VerificationLayer.ARTIFACT.value]
    edges = []
    theorems = {
        ("TheoryExpression", "ImplementationExpression"): "CppAudit.EndToEnd.exact_chain_transitive",
        ("NumericErrorComponents", "TotalErrorBound"): "CppAudit.EndToEnd.verified_component_bounds_imply_total_bound",
        ("ValueInterval", "TrueValueEnclosure"): "CppAudit.EndToEnd.value_error_enclosure_sound",
    }
    for index, (source, target) in enumerate(zip(ordered, ordered[1:])):
        layer = by_layer.get(edge_layers[index])
        edges.append(EndToEndProofEdge(source, target, f"compose_{source}_to_{target}",
            layer.status if layer else "UNRESOLVED", lean_theorem=theorems.get((source, target)),
            reference_contract="SERIALIZATION_VALUE_PRESERVING" if source == "SerializationBoundary" and
            layer and layer.status == "REFERENCE_CONTRACT_VERIFIED" else None,
            assumptions=list(layer.assumptions) if layer else []))
    evidence = []
    for item in (output.interval_propagation or {}).get("evidence", []):
        evidence.append(EnclosureEvidence(item.get("evidence_id", _id("evidence", item)), item.get("kind", "INTERVAL"),
            item.get("status", "UNRESOLVED"), lean_theorem=item.get("theorem_reference"),
            assumptions=item.get("assumptions", []), proof_authority=bool(item.get("proof_authority")), provenance=item))
    if output.lean_status == "LEAN_KERNEL_VERIFIED":
        evidence.append(EnclosureEvidence(_id("evidence", output.output_id), "THEORY_IMPLEMENTATION_EQUIVALENCE",
            "KERNEL_VERIFIED", output.output_id, proof_authority=True))
    status = "PROOF_CHAIN_COMPLETE" if all(item.status in VERIFIED for item in layers if item.critical) else "PROOF_CHAIN_PARTIAL"
    return EndToEndProofChain([{"node_id": item, "kind": item} for item in ordered], edges, evidence, status)


def _reference_build_end_to_end_claims(project: Any, *, observed_results: Mapping[str, Any] | None = None,
                                       error_specifications: Mapping[str, Any] | None = None,
                                       model_error_scopes: Mapping[str, str] | None = None) -> Any:
    observed_results = dict(observed_results or {}); error_specifications = dict(error_specifications or {})
    model_error_scopes = dict(model_error_scopes or {})
    claims: list[EndToEndVerificationClaim] = []
    for output in project.outputs:
        expression_boundaries = [deepcopy(node["language_boundary"]) for node in _walk(output.formula)
                                 if isinstance(node.get("language_boundary"), dict)]
        boundaries = expression_boundaries
        layers: list[LayerVerification] = []
        exact_theory = output.lean_status == "LEAN_KERNEL_VERIFIED" and output.status == "FULLY_VERIFIED"
        layers.append(LayerVerification(VerificationLayer.THEORY.value,
            "REGISTERED" if output.theory else "UNRESOLVED",
            "An independent theory expression is registered." if output.theory else "No theory expression is registered.", critical=False))
        layers.append(LayerVerification(VerificationLayer.IMPLEMENTATION.value, "EXTRACTED",
            "The implementation expression was extracted from source.", critical=False))
        layers.append(LayerVerification(VerificationLayer.THEORY_IMPLEMENTATION.value,
            "KERNEL_VERIFIED" if exact_theory else "UNRESOLVED",
            "Lean kernel verified the theory/implementation relation." if exact_theory else
            "No kernel-verified theory/implementation relation is available."))
        transformation_trace = (output.residual or {}).get("transformation_trace", {})
        layers.append(LayerVerification(VerificationLayer.TRANSFORMATION.value,
            "NOT_APPLICABLE" if not transformation_trace else "RECORDED",
            "No transformation is required." if not transformation_trace else "Transformation trace is retained.", critical=False))
        approximation = [item for item in output.error_components or [] if item.get("source") in
                         {"APPROXIMATION_ERROR", "DISCRETIZATION_ERROR"}]
        approximation_ok = bool(approximation) and all(_component_verified(item) for item in approximation)
        approximation_assumptions = [text for item in approximation for text in item.get("assumptions", [])]
        layers.append(LayerVerification(VerificationLayer.APPROXIMATION.value,
            "NOT_APPLICABLE" if not approximation else
            "KERNEL_VERIFIED_UNDER_ASSUMPTIONS" if approximation_ok and approximation_assumptions else
            "KERNEL_VERIFIED" if approximation_ok else "UNRESOLVED",
            "No approximation operator occurs on this route." if not approximation else
            "All approximation components have verified bounds." if approximation_ok else
            "At least one approximation component lacks a verified bound.", assumptions=approximation_assumptions))
        execution = output.execution_range or {}
        numeric_metadata = output.implementation if isinstance(output.implementation, dict) else {}
        numeric_metadata = numeric_metadata.get("numeric_execution") or numeric_metadata.get("numeric_type_semantics") or {}
        float_route = bool(numeric_metadata.get("dtype") or numeric_metadata.get("cpp_types")) or any(
            isinstance(node.get("value"), float) or node.get("op") == "FunctionCall" for node in _walk(output.formula))
        integer_exact = exact_theory and _expression_is_integer_exact(output.formula) and not float_route
        rounding_components = [item for item in output.error_components or [] if item.get("source") in
                               {"ROUNDING_ERROR", "PARALLEL_ORDER_ERROR"}]
        rounding_complete = bool(rounding_components) and all(_component_verified(item) for item in rounding_components)
        execution_status = ("KERNEL_VERIFIED" if integer_exact else "ENCLOSURE_VERIFIED" if
                            execution.get("status") == "EXECUTION_RANGE_FINITE" else "UNRESOLVED")
        execution_obligations = [item for item in output.range_obligations or [] if item.get("kind") in
                                 {"OVERFLOW_POSSIBLE", "SUBNORMAL_RANGE_POSSIBLE", "CAST_RANGE_UNRESOLVED"}]
        if execution_obligations: execution_status = "UNRESOLVED"
        if float_route and not rounding_complete: execution_status = "UNRESOLVED"
        layers.append(LayerVerification(VerificationLayer.NUMERIC_EXECUTION.value, execution_status,
            "Execution is exact in the audited integer fragment." if integer_exact else
            "Finite dtype execution range is enclosed." if execution_status == "ENCLOSURE_VERIFIED" else
            "Rounding, overflow, underflow, or cast behavior is not totally enclosed.", obligations=execution_obligations))
        parallel_metadata = (output.implementation or {}).get("parallel_semantics") if isinstance(output.implementation, dict) else None
        parallel_status = "NOT_APPLICABLE" if not parallel_metadata else str(parallel_metadata.get("proof_status") or "UNRESOLVED")
        layers.append(LayerVerification(VerificationLayer.PARALLEL.value, parallel_status,
            "No parallel execution operator occurs." if not parallel_metadata else "Parallel execution semantics are retained.",
            critical=bool(parallel_metadata)))
        constraint_closed = output.range_constraint_status in {None, "OUTPUT_RANGE_CONSTRAINT_PROVEN"}
        range_exact = (integer_exact and output.range_status == "TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED" and
                       not output.range_obligations and constraint_closed)
        range_status = ("KERNEL_VERIFIED" if range_exact else "ENCLOSURE_VERIFIED" if
                        output.range_status == "TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED" and not output.range_obligations else
                        "ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS" if output.range_status == "TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED" else
                        "UNRESOLVED")
        layers.append(LayerVerification(VerificationLayer.RANGE.value, range_status,
            "The value/error enclosure is total." if range_status in VERIFIED else "The total true-value enclosure is unresolved.",
            obligations=list(output.range_obligations or [])))
        ffi_unresolved = [item for item in boundaries if item.get("representation_mapping") not in
                          {"RANGE_PRESERVING", "REPRESENTATION_MAPPING_VERIFIED", "EXACT_WIDENING"}]
        ffi_status = "NOT_APPLICABLE" if not boundaries else "REFERENCE_CONTRACT_VERIFIED" if not ffi_unresolved else "UNRESOLVED"
        layers.append(LayerVerification(VerificationLayer.FFI.value, ffi_status,
            "No FFI boundary occurs on the project route." if not boundaries else
            "All FFI representation mappings preserve the enclosure." if not ffi_unresolved else
            "At least one FFI representation mapping is unresolved.",
            obligations=[{"kind": "FFI_REPRESENTATION_RANGE_UNRESOLVED", "status": "UNRESOLVED",
                          "boundary_id": item.get("boundary_id")} for item in ffi_unresolved], critical=bool(boundaries)))
        synthetic = []
        if execution_status == "UNRESOLVED" and float_route and not integer_exact: synthetic.append("ROUNDING_ERROR")
        if ffi_unresolved: synthetic.append("FFI_CONVERSION_ERROR")
        artifacts = _artifact_for_output(project, output)
        if any(item.obligations for item in artifacts): synthetic.append("SERIALIZATION_ERROR")
        completeness, completeness_obligations, _ = _error_completeness(output, synthetic)
        error_status = ("KERNEL_VERIFIED" if completeness == ErrorCompletenessStatus.ERROR_MODEL_COMPLETE.value and
                        output.range_status == "TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED" else
                        "KERNEL_VERIFIED_UNDER_ASSUMPTIONS" if completeness == ErrorCompletenessStatus.ERROR_MODEL_COMPLETE_UNDER_ASSUMPTIONS.value else
                        "UNRESOLVED")
        layers.append(LayerVerification(VerificationLayer.ERROR.value, error_status,
            "Every critical error source is represented and bounded." if error_status in VERIFIED else
            "The critical-path error model is incomplete.", obligations=completeness_obligations))
        serialization_status = ("NOT_APPLICABLE" if not artifacts else "REFERENCE_CONTRACT_VERIFIED" if
                                all(item.status == "ARTIFACT_PAYLOAD_ENCLOSURE_VERIFIED" for item in artifacts) else "UNRESOLVED")
        layers.append(LayerVerification(VerificationLayer.SERIALIZATION.value, serialization_status,
            "No serialization boundary occurs." if not artifacts else "Serialization is value-preserving by contract." if
            serialization_status in VERIFIED else "Serialization value preservation is unresolved.",
            obligations=[item for artifact in artifacts for item in artifact.obligations], critical=bool(artifacts)))
        artifact_status = ("NOT_APPLICABLE" if not artifacts else "ENCLOSURE_VERIFIED" if
                           all(item.status == "ARTIFACT_PAYLOAD_ENCLOSURE_VERIFIED" for item in artifacts) else "UNRESOLVED")
        layers.append(LayerVerification(VerificationLayer.ARTIFACT.value, artifact_status,
            "No artifact is attached." if not artifacts else "Artifact payload enclosure is connected." if
            artifact_status in VERIFIED else "Artifact existence does not establish payload correctness.", critical=bool(artifacts)))
        layers.append(LayerVerification(VerificationLayer.LEAN.value,
            "KERNEL_VERIFIED" if output.lean_status == "LEAN_KERNEL_VERIFIED" else "UNRESOLVED",
            "Lean kernel accepted the generated theory relation." if output.lean_status == "LEAN_KERNEL_VERIFIED" else
            "No accepted Lean kernel claim is available.", critical=False))
        matrix_order = {layer.value: index for index, layer in enumerate((
            VerificationLayer.THEORY, VerificationLayer.IMPLEMENTATION,
            VerificationLayer.THEORY_IMPLEMENTATION, VerificationLayer.TRANSFORMATION,
            VerificationLayer.APPROXIMATION, VerificationLayer.RANGE, VerificationLayer.ERROR,
            VerificationLayer.NUMERIC_EXECUTION, VerificationLayer.PARALLEL, VerificationLayer.FFI,
            VerificationLayer.SERIALIZATION, VerificationLayer.ARTIFACT, VerificationLayer.LEAN,
        ))}
        layers.sort(key=lambda item: matrix_order[item.layer])
        assumptions, dependencies = _assumptions(output, project, layers)
        obligations = [deepcopy(item) for layer in layers for item in layer.obligations if item.get("status") != "RESOLVED"]
        observed = observed_results.get(output.name)
        observed_status = _observed_status(observed, output.true_value_enclosure)
        constraint = output.range_constraint_status
        failed = observed_status == "OBSERVED_VALUE_OUTSIDE_CERTIFIED_RANGE" or constraint == "OUTPUT_RANGE_CONSTRAINT_VIOLATED"
        tolerance = None
        specification = error_specifications.get(output.name) or error_specifications.get("*")
        absolute_tolerance = (specification.get("absolute_tolerance") if isinstance(specification, Mapping)
                              else getattr(specification, "absolute_tolerance", None))
        if specification and absolute_tolerance is not None:
            bound = _bound_number(output.total_bound)
            if bound is None and output.error_interval:
                interval = output.error_interval.get("interval", {})
                if _number(interval.get("lower")) and _number(interval.get("upper")):
                    bound = max(abs(float(interval["lower"])), abs(float(interval["upper"])))
            tolerance = ("TOTAL_TOLERANCE_PROVEN" if error_status in VERIFIED and bound is not None and
                         bound <= absolute_tolerance else
                         "KNOWN_BOUND_WITHIN_TOLERANCE" if bound is not None and bound <= absolute_tolerance else
                         "TOTAL_TOLERANCE_NOT_PROVEN")
        status = _status(layers, assumptions, failed)
        explanation = _explanation(status, layers)
        chain = _proof_chain(output, layers, artifacts)
        enclosure = EndToEndEnclosure(deepcopy(output.value_interval), deepcopy(output.error_interval),
            deepcopy(output.true_value_enclosure), artifacts, constraint, tolerance, status)
        theory_expression = deepcopy((output.residual or {}).get("theory_expression") or output.theory)
        serialization_boundaries = [deepcopy(item.serialization_boundary) for item in project.artifacts
                                    if item.sink_id in {artifact.artifact_id for artifact in artifacts}]
        total_error_bound = (deepcopy(output.error_bound) if (output.total_bound or {}).get("status") in
                             {"EXACT_ZERO_BOUND_VERIFIED", "TOTAL_ERROR_BOUND_VERIFIED"} else deepcopy(output.total_bound))
        claim = EndToEndVerificationClaim(_id("e2e-claim", [output.output_id, chain.chain_id]),
            _output_root(project, output.output_id), output.output_id, output.name, theory_expression,
            deepcopy(output.formula), deepcopy((output.residual or {}).get("transformation_trace", {})), approximation,
            deepcopy(output.value_interval), deepcopy(output.error_components), deepcopy(output.known_bound),
            total_error_bound, deepcopy(output.true_value_enclosure),
            {"implementation": deepcopy(output.implementation), "execution_range": deepcopy(output.execution_range)},
            deepcopy(boundaries), serialization_boundaries, artifacts,
            assumptions, dependencies, obligations, chain, layers, completeness, tolerance, constraint, observed,
            observed_status, model_error_scopes.get(output.name, "MODEL_ERROR_NOT_IN_SCOPE"), status, explanation, enclosure)
        output.end_to_end_claim = claim.to_dict(); output.end_to_end_status = status
        output.proof_chain = _serial(chain); output.artifact_enclosure = _serial(artifacts)
        output.total_error_bound = total_error_bound; output.remaining_obligations = obligations
        claims.append(claim)
    project.end_to_end_claims = [item.to_dict() for item in claims]
    counts = {"number_of_outputs": len(claims), "fully_verified": 0, "verified_under_assumptions": 0,
              "partially_verified": 0, "unresolved": 0, "failed": 0}
    for claim in claims:
        if claim.status in {EndToEndStatus.END_TO_END_KERNEL_VERIFIED.value, EndToEndStatus.END_TO_END_ENCLOSURE_VERIFIED.value}:
            counts["fully_verified"] += 1
        elif "UNDER_ASSUMPTIONS" in claim.status: counts["verified_under_assumptions"] += 1
        elif claim.status == EndToEndStatus.PARTIAL_END_TO_END_VERIFICATION.value: counts["partially_verified"] += 1
        elif claim.status == EndToEndStatus.END_TO_END_FAILED.value: counts["failed"] += 1
        else: counts["unresolved"] += 1
    project.end_to_end_coverage = counts
    if counts["failed"]: project.end_to_end_status = EndToEndStatus.END_TO_END_FAILED.value
    elif counts["unresolved"] and not (counts["fully_verified"] or counts["verified_under_assumptions"] or counts["partially_verified"]):
        project.end_to_end_status = EndToEndStatus.END_TO_END_UNRESOLVED.value
    elif counts["unresolved"] or counts["partially_verified"]: project.end_to_end_status = EndToEndStatus.PARTIAL_END_TO_END_VERIFICATION.value
    elif counts["verified_under_assumptions"]:
        project.end_to_end_status = (EndToEndStatus.END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value
            if claims and all(item.status == EndToEndStatus.END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value for item in claims)
            else EndToEndStatus.END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS.value)
    elif claims and all(item.status == EndToEndStatus.END_TO_END_KERNEL_VERIFIED.value for item in claims):
        project.end_to_end_status = EndToEndStatus.END_TO_END_KERNEL_VERIFIED.value
    else: project.end_to_end_status = EndToEndStatus.END_TO_END_ENCLOSURE_VERIFIED.value if claims else EndToEndStatus.END_TO_END_UNRESOLVED.value
    for root in project.roots:
        statuses = [item.end_to_end_status for item in root.outputs]
        root.end_to_end_claim_ids = [item.end_to_end_claim["claim_id"] for item in root.outputs]
        root.end_to_end_status = (EndToEndStatus.END_TO_END_FAILED.value if EndToEndStatus.END_TO_END_FAILED.value in statuses else
                                  EndToEndStatus.PARTIAL_END_TO_END_VERIFICATION.value if len(set(statuses)) > 1 else
                                  statuses[0] if statuses else EndToEndStatus.END_TO_END_UNRESOLVED.value)
    return project


def _execute_native_kernel(request: dict[str, Any]) -> dict[str, Any]:
    # Local import preserves the public-package initialization boundary.
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel(request)["result"]


def build_end_to_end_claims(project: Any, *, observed_results: Mapping[str, Any] | None = None,
                            error_specifications: Mapping[str, Any] | None = None,
                            model_error_scopes: Mapping[str, str] | None = None) -> Any:
    """Project native VerificationResult claims onto frontend-owned objects.

    Python performs only object projection.  Layer status, assumptions, error
    completeness, evidence boundaries, and aggregate status are decided by the
    Rust Kernel F operation.
    """
    specifications = {
        str(key): (_serial(value) if hasattr(value, "__dataclass_fields__") else deepcopy(value))
        for key, value in dict(error_specifications or {}).items()
    }
    native = _execute_native_kernel({
        "schema_version": "1.0",
        "kernel": "F",
        "operation": "ASSEMBLE_PROJECT_VERIFICATION",
        "project": project.to_dict(),
        "observed_results": deepcopy(dict(observed_results or {})),
        "error_specifications": specifications,
        "model_error_scopes": deepcopy(dict(model_error_scopes or {})),
    })
    native_outputs = {str(item.get("output_id")): item for item in native.get("outputs", [])}
    for output in project.outputs:
        value = native_outputs.get(output.output_id)
        if value is None:
            raise RuntimeError(f"NATIVE_OUTPUT_PROJECTION_MISSING:{output.output_id}")
        for name in ("end_to_end_claim", "end_to_end_status", "proof_chain", "artifact_enclosure",
                     "total_error_bound", "remaining_obligations"):
            setattr(output, name, deepcopy(value.get(name)))
    project.end_to_end_claims = deepcopy(native.get("end_to_end_claims", []))
    project.end_to_end_coverage = deepcopy(native.get("end_to_end_coverage", {}))
    project.end_to_end_status = native.get("end_to_end_status", "END_TO_END_UNRESOLVED")
    for root in project.roots:
        statuses = [item.end_to_end_status for item in root.outputs]
        root.end_to_end_claim_ids = [item.end_to_end_claim["claim_id"] for item in root.outputs]
        root.end_to_end_status = (EndToEndStatus.END_TO_END_FAILED.value
                                  if EndToEndStatus.END_TO_END_FAILED.value in statuses else
                                  EndToEndStatus.PARTIAL_END_TO_END_VERIFICATION.value
                                  if len(set(statuses)) > 1 else statuses[0]
                                  if statuses else EndToEndStatus.END_TO_END_UNRESOLVED.value)
    return project
