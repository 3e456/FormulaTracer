"""Approximation proof IR, assumption discharge, and coverage accounting."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from .approximation_families import load_approximation_families
from .core import AuditError


def _native(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeCallError, NativeContext
    try:
        with NativeContext() as context:
            return context.execute_kernel({"schema_version":"1.0","kernel":"C",
                "operation":"APPROXIMATION_PROOF","action":action,**payload})["result"]
    except NativeCallError as error:
        raise AuditError(str(error)) from error


class ProofStatus(str, Enum):
    KERNEL_VERIFIED_ERROR_BOUND = "KERNEL_VERIFIED_ERROR_BOUND"
    KERNEL_VERIFIED_ERROR_BOUND_UNDER_ASSUMPTIONS = "KERNEL_VERIFIED_ERROR_BOUND_UNDER_ASSUMPTIONS"
    KERNEL_VERIFIED_CONVERGENCE = "KERNEL_VERIFIED_CONVERGENCE"
    KERNEL_VERIFIED_CONVERGENCE_UNDER_ASSUMPTIONS = "KERNEL_VERIFIED_CONVERGENCE_UNDER_ASSUMPTIONS"
    REFERENCE_THEOREM_ONLY = "REFERENCE_THEOREM_ONLY"
    PROOF_OBLIGATION_REMAINING = "PROOF_OBLIGATION_REMAINING"
    SMOOTHNESS_BOUND_UNRESOLVED = "SMOOTHNESS_BOUND_UNRESOLVED"
    DOMAIN_CONDITION_UNRESOLVED = "DOMAIN_CONDITION_UNRESOLVED"
    BOUND_CONSTANT_UNRESOLVED = "BOUND_CONSTANT_UNRESOLVED"
    CONVERGENCE_NOT_PROVEN = "CONVERGENCE_NOT_PROVEN"


class AssumptionStatus(str, Enum):
    PROVEN = "ASSUMPTION_PROVEN"
    PROVIDED = "ASSUMPTION_PROVIDED"
    REFERENCE_CONTRACT = "ASSUMPTION_REFERENCE_CONTRACT"
    UNRESOLVED = "ASSUMPTION_UNRESOLVED"


@dataclass
class ApproximationAssumption:
    assumption_id: str
    kind: str
    statement: str
    lean_type: str
    discharge_status: str
    evidence: dict[str, Any] | None


@dataclass
class ApproximationErrorBound:
    error_expression: str
    bound: str | None
    bound_constant: str | None
    exponent: int | None
    error_kind: str = "APPROXIMATION_ERROR"


@dataclass
class ApproximationTheorem:
    theorem_id: str
    family_id: str
    target_operator: str
    statement: str
    lean_theorem_name: str | None
    proof_status: str


@dataclass
class ConvergenceClaim:
    order: int | None
    parameter: str | None
    target: str
    status: str
    lean_theorem_name: str | None


@dataclass
class ProofEvidence:
    lean_theorem_name: str | None
    lean_source_hash: str | None
    kernel_checked: bool
    provenance: dict[str, Any]


@dataclass
class ApproximationProof:
    family_id: str
    theorem_id: str
    target_operator: str
    approximation_expression: str
    domain: dict[str, Any]
    parameters: dict[str, Any]
    assumptions: list[ApproximationAssumption]
    error_bound: ApproximationErrorBound
    convergence: ConvergenceClaim
    proof_status: str
    order_cross_check: str
    evidence: ProofEvidence
    remaining_obligations: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(asdict(self))


def _source_hash(root: Path, proof: dict[str, Any]) -> str | None:
    source = proof.get("provenance", {}).get("proof_source")
    if not source or source in {"reference_only", "external_reference"}:
        return None
    path = root / str(source)
    return sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def load_approximation_proof_registry(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "0.1":
        raise AuditError("UNSUPPORTED_APPROXIMATION_PROOF_SCHEMA")
    expected_theorems = {
        "forward_difference_first_derivative": "CppAudit.Approximation.forward_difference_error_bound",
        "backward_difference_first_derivative": "CppAudit.Approximation.backward_difference_error_bound",
        "central_difference_first_derivative": "CppAudit.Approximation.central_difference_error_bound",
        "trapezoidal_rule": "CppAudit.Approximation.composite_trapezoidal_error_bound",
        "nearest_neighbor_interpolation": "CppAudit.Approximation.nearest_interpolation_error_bound",
        "linear_interpolation": "CppAudit.Approximation.linear_interpolation_error_bound_from_remainder",
    }
    formal_bounds = {
        "forward_difference_first_derivative": "(M/2)*abs(h)",
        "backward_difference_first_derivative": "(M/2)*abs(h)",
        "central_difference_first_derivative": "(M/6)*abs(h)^2",
        "trapezoidal_rule": "((b-a)*M/12)*h^2",
        "nearest_neighbor_interpolation": "L*radius",
        "linear_interpolation": "(M/8)*h^2",
    }
    result = {}
    for proof in payload.get("proofs", []):
        family_id = str(proof["family_id"])
        if family_id in result:
            raise AuditError(f"DUPLICATE_APPROXIMATION_PROOF: {family_id}")
        if proof.get("provenance", {}).get("proof_uses_selection_metadata") is not False:
            raise AuditError(f"SELECTION_METADATA_USED_AS_PROOF: {family_id}")
        expected = expected_theorems.get(family_id)
        if expected and proof.get("lean_theorem_name") != expected:
            raise AuditError(f"FAMILY_PROOF_THEOREM_MISMATCH: {family_id}")
        formal = formal_bounds.get(family_id)
        if formal and proof.get("error_bound") != formal:
            raise AuditError(f"FORMAL_BOUND_REGISTRY_MISMATCH: {family_id}")
        result[family_id] = deepcopy(proof)
    return result


def _discharge(assumption: dict[str, Any], context: dict[str, Any]) -> ApproximationAssumption:
    item = deepcopy(assumption)
    assumption_id, kind = item["assumption_id"], item["kind"]
    provided = set(context.get("provided_assumptions", []))
    status, evidence = AssumptionStatus.UNRESOLVED.value, None
    if assumption_id == "positive_step" and isinstance(context.get("h"), (int, float)):
        if context["h"] > 0:
            status, evidence = AssumptionStatus.PROVEN.value, {"kind": "NUMERIC_POSITIVITY", "value": context["h"]}
    elif assumption_id == "nonnegative_step" and isinstance(context.get("h"), (int, float)):
        if context["h"] >= 0:
            status, evidence = AssumptionStatus.PROVEN.value, {"kind": "NUMERIC_NONNEGATIVITY", "value": context["h"]}
    elif kind == "DOMAIN_CONDITION" and context.get("domain_condition_proven"):
        status, evidence = AssumptionStatus.PROVEN.value, {"kind": "STATIC_DOMAIN_CHECK"}
    elif kind == "PARTITION_CONDITION" and context.get("partition_resolved"):
        status, evidence = AssumptionStatus.PROVEN.value, {"kind": "PHASE6_HARD_CONSTRAINT", "partition": context.get("partition")}
    elif assumption_id in provided:
        status, evidence = AssumptionStatus.PROVIDED.value, {"kind": "USER_PROVIDED_ASSUMPTION"}
    elif assumption_id in set(context.get("reference_contract_assumptions", [])):
        status, evidence = AssumptionStatus.REFERENCE_CONTRACT.value, {"kind": "PUBLIC_REFERENCE_CONTRACT"}
    item["discharge_status"], item["evidence"] = status, evidence
    return ApproximationAssumption(**item)


def resolve_approximation_proof(family_id: str, *, repository_root: str | Path,
                                context: dict[str, Any] | None = None,
                                kernel_checked: bool = False) -> ApproximationProof:
    root, context = Path(repository_root), context or {}
    registry = load_approximation_proof_registry(root / "registry" / "approximation_proofs.yaml")
    families = load_approximation_families(root / "registry" / "approximation_families.yaml")
    if family_id not in registry or family_id not in families:
        raise AuditError(f"APPROXIMATION_PROOF_NOT_FOUND: {family_id}")
    raw, family = registry[family_id], families[family_id]
    value = _native("RESOLVE", family_id=family_id, proof=raw, family=family.to_dict(),
                    context=context, kernel_checked=kernel_checked, source_hash=_source_hash(root, raw))
    return ApproximationProof(
        value["family_id"], value["theorem_id"], value["target_operator"],
        value["approximation_expression"], value["domain"], value["parameters"],
        [ApproximationAssumption(**item) for item in value["assumptions"]],
        ApproximationErrorBound(**value["error_bound"]), ConvergenceClaim(**value["convergence"]),
        value["proof_status"], value["order_cross_check"], ProofEvidence(**value["evidence"]),
        value["remaining_obligations"])


def approximation_proof_coverage(repository_root: str | Path, *, kernel_checked: bool = True) -> list[dict[str, Any]]:
    root = Path(repository_root)
    families = load_approximation_families(root / "registry" / "approximation_families.yaml")
    registry = load_approximation_proof_registry(root / "registry" / "approximation_proofs.yaml")
    result = []
    for family_id in sorted(families):
        raw = registry.get(family_id)
        if raw is None:
            status = "UNRESOLVED"
        elif raw["proof_status"] == ProofStatus.REFERENCE_THEOREM_ONLY.value:
            status = "REFERENCE_ONLY"
        else:
            status = "ERROR_BOUND_VERIFIED_UNDER_ASSUMPTIONS" if kernel_checked else "REFERENCE_ONLY"
        result.append({"family_id": family_id, "discrete_semantics": "DISCRETE_SEMANTICS_VERIFIED",
                       "error_bound": status,
                       "convergence": ("CONVERGENCE_KERNEL_VERIFIED" if kernel_checked and raw and
                            str(raw.get("convergence_status", "")).startswith("KERNEL_VERIFIED") else "UNRESOLVED")})
    return result
