"""Semantic numerical-approximation families and public API mappings.

The discrete operator is exact data.  Its relationship to a continuous
operator is an approximation and deliberately carries no proved error bound.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from .core import AuditError


def _native(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeCallError, NativeContext
    try:
        with NativeContext() as context:
            return context.execute_kernel({"schema_version":"1.0","kernel":"C",
                "operation":"APPROXIMATION_FAMILY","action":action,**payload})["result"]
    except NativeCallError as error:
        if "APPROXIMATION_FAMILY_NOT_FOUND" in str(error): raise AuditError(str(error)) from error
        raise


class ExactSemanticOperator(str, Enum):
    DISCRETE_DIFFERENCE = "DiscreteDifference"
    FINITE_DIFFERENCE = "FiniteDifference"
    QUADRATURE = "Quadrature"
    INTERPOLATION = "Interpolation"
    EXTRAPOLATION = "Extrapolation"


class ApproximationStatus(str, Enum):
    FINITE_DIFFERENCE_RECOGNIZED = "FINITE_DIFFERENCE_RECOGNIZED"
    QUADRATURE_RECOGNIZED = "QUADRATURE_RECOGNIZED"
    INTERPOLATION_RECOGNIZED = "INTERPOLATION_RECOGNIZED"
    EXTRAPOLATION_RECOGNIZED = "EXTRAPOLATION_RECOGNIZED"
    BOUNDARY_STENCIL_UNRESOLVED = "BOUNDARY_STENCIL_UNRESOLVED"
    SPACING_UNRESOLVED = "SPACING_UNRESOLVED"
    INTEGRATION_PARTITION_UNRESOLVED = "INTEGRATION_PARTITION_UNRESOLVED"
    INTERPOLATION_DOMAIN_UNRESOLVED = "INTERPOLATION_DOMAIN_UNRESOLVED"
    CONVERGENCE_ORDER_RECORDED = "CONVERGENCE_ORDER_RECORDED"
    CONVERGENCE_PROOF_NOT_YET_ESTABLISHED = "CONVERGENCE_PROOF_NOT_YET_ESTABLISHED"
    APPROXIMATION_ERROR_NOT_YET_PROVEN = "APPROXIMATION_ERROR_NOT_YET_PROVEN"


@dataclass(frozen=True)
class ApproximationFamily:
    family_id: str
    mathematical_operator: str
    approximation_kind: str
    order: int | None
    stencil: dict[str, Any] | None
    quadrature: dict[str, Any] | None
    step_parameter: str | None
    domain_requirements: list[str]
    smoothness_requirements: list[str]
    boundary_requirements: list[str]
    convergence_order: int | None
    convergence_parameter: str | None
    convergence_target: str
    library_contract_mappings: list[str]
    provenance: dict[str, Any]
    proof_status: str
    selection_error_estimate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(asdict(self))


@dataclass(frozen=True)
class LibraryFamilyMapping:
    qualified_callable: str
    exact_semantic_operator: str
    approximation_family_ids: tuple[str, ...]
    public_reference_semantics: dict[str, Any]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        item = asdict(self)
        item["approximation_family_ids"] = list(self.approximation_family_ids)
        return item


def load_approximation_families(path: str | Path) -> dict[str, ApproximationFamily]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "0.2":
        raise AuditError("UNSUPPORTED_APPROXIMATION_FAMILY_SCHEMA")
    result: dict[str, ApproximationFamily] = {}
    for raw in payload.get("families", []):
        family = ApproximationFamily(**raw)
        if family.family_id in result:
            raise AuditError(f"DUPLICATE_APPROXIMATION_FAMILY: {family.family_id}")
        if family.proof_status != "CONVERGENCE_PROOF_NOT_YET_ESTABLISHED":
            raise AuditError(f"PHASE6_PROOF_STATUS_INVALID: {family.family_id}")
        result[family.family_id] = family
    return result


def load_library_family_mappings(path: str | Path) -> dict[str, LibraryFamilyMapping]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {raw["qualified_callable"]: LibraryFamilyMapping(
        raw["qualified_callable"], raw["exact_semantic_operator"],
        tuple(raw.get("approximation_family_ids", [])),
        deepcopy(raw.get("public_reference_semantics", {})),
        deepcopy(raw.get("provenance", {}))) for raw in payload.get("library_mappings", [])}


def approximation_metadata(rule: dict[str, Any], registry_path: str | Path) -> dict[str, Any] | None:
    families = load_approximation_families(registry_path)
    return _native("METADATA", rule=rule,
                   families={name: family.to_dict() for name, family in families.items()})["value"]


def classify_library_call(qualified_callable: str, registry_path: str | Path, *,
                          domain_status: str | None = None) -> dict[str, Any]:
    """Return exact public-call semantics separately from approximation options."""
    mapping = load_library_family_mappings(registry_path).get(qualified_callable)
    return _native("CLASSIFY_LIBRARY_CALL", qualified_callable=qualified_callable,
                   mapping=mapping.to_dict() if mapping else None, domain_status=domain_status)
