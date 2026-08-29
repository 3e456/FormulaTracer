"""Lossless, fail-closed artifacts for later reconstruction comparison.

This module serializes evidence produced elsewhere.  It does not decide
mathematical equivalence, provider adoption, or proof status.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from formulatracer.native import execute_native_kernel


REQUIRED_FIELDS = (
    "case_id", "split", "reference_id", "original_theory_tex",
    "original_theory_ir", "normalized_theory_ir", "theory_structural_quotient",
    "generation_plan", "selected_provider", "generation_decision", "algorithm_ir",
    "generated_language", "generated_source_fingerprint", "observed_implementation_ir",
    "reconstructed_math_ir", "reconstructed_structural_quotient",
    "structural_isomorphism_status", "structural_isomorphism_witness",
    "exact_egraph_status", "relation_graph_status", "assumptions",
    "error_range_evidence", "final_reconstruction_status",
)


def _native(operation: str, **values: Any) -> dict[str, Any]:
    request = {"schema_version": "1.0", "kernel": "B", "operation": operation, **values}
    return execute_native_kernel(request)["result"]


def _canonical_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")).hexdigest()


def _contract(candidate: Any) -> dict[str, Any]:
    contract = candidate.contract
    return {
        "provider_id": contract.provider_id,
        "language": contract.language,
        "callable": contract.callable,
        "contract_pattern": contract.pattern,
        "mathematical_relation": contract.implementation_relation,
        "realization_relation": contract.realization_relation,
        "lowering": contract.lowering,
        "normalization_convention": contract.execution_metadata.get("normalization_convention"),
        "assumptions": list(contract.constraints),
        "shape_type_constraints": list(contract.constraints),
        "execution_metadata": dict(contract.execution_metadata),
        "useful_rewrites": list(contract.useful_rewrites),
    }


def build_reconstruction_artifact(case: Any, outcome: Mapping[str, Any], plan: Any,
                                  reference_versions: Mapping[str, str]) -> dict[str, Any]:
    theory = case.expression
    quotient = _native("QUOTIENT_NORMALIZE", expression=theory, facts={})
    rendered = _native("RENDER_TEX", expression=theory)["tex"]
    candidate = next((item for item in plan.candidates
                      if item.contract.provider_id == case.expected_provider), None)
    unavailable: dict[str, str] = {}

    selected_provider = None
    generation_decision = None
    generated_language = None
    generated_source_fingerprint = None
    observed_ir = None
    reconstructed_ir = None
    reconstructed_quotient = None
    isomorphism_status = None
    isomorphism_witness = None
    error_range = None
    for field, reason in {
        "selected_provider": "NO_RIGOROUS_PROVIDER_SELECTION_WAS_PERFORMED",
        "generation_decision": "NO_PROVIDER_SELECTION_DECISION_WAS_PERFORMED",
        "generated_language": "NO_SOURCE_WAS_GENERATED_FOR_THIS_ASSURANCE_CASE",
        "generated_source_fingerprint": "NO_SOURCE_WAS_GENERATED_FOR_THIS_ASSURANCE_CASE",
        "observed_implementation_ir": "NO_GENERATED_SOURCE_WAS_INDEPENDENTLY_REANALYZED",
        "reconstructed_math_ir": "NO_GENERATED_SOURCE_WAS_INDEPENDENTLY_REANALYZED",
        "reconstructed_structural_quotient": "RECONSTRUCTED_MATH_IR_UNAVAILABLE",
        "structural_isomorphism_status": "THEORY_RECONSTRUCTED_IR_PAIR_UNAVAILABLE",
        "structural_isomorphism_witness": "THEORY_RECONSTRUCTED_IR_PAIR_UNAVAILABLE",
        "error_range_evidence": "NO_CERTIFIED_ERROR_OR_RANGE_EVIDENCE_WAS_PRODUCED",
    }.items():
        unavailable[field] = reason

    provider_candidate = _contract(candidate) if candidate else None
    if candidate is None:
        unavailable["provider_candidate"] = "EXPECTED_PROVIDER_NOT_RETRIEVED_OR_NOT_APPLICABLE"
        algorithm_ir = None
        unavailable["algorithm_ir"] = "NO_PROVIDER_ALGORITHM_CONTRACT_AVAILABLE"
        exact_egraph_status = None
        unavailable["exact_egraph_status"] = "NO_PROVIDER_COMPARISON_WAS_PERFORMED"
        assumptions: list[str] = []
    else:
        algorithm_ir = {
            "op": "ProviderAlgorithmContract",
            "provider_id": candidate.contract.provider_id,
            "language": candidate.contract.language,
            "lowering": candidate.contract.lowering,
            "mathematical_target": candidate.contract.pattern,
            "implementation_relation": candidate.contract.implementation_relation,
            "realization_relation": candidate.contract.realization_relation,
            "execution_metadata": dict(candidate.contract.execution_metadata),
        }
        exact_egraph_status = candidate.egraph_match.status if candidate.egraph_match else None
        if exact_egraph_status is None:
            unavailable["exact_egraph_status"] = "EXACT_EGRAPH_STAGE_NOT_REACHED_OR_NO_MATCH_RECORDED"
        assumptions = sorted(set(candidate.contract.constraints) | set(candidate.remaining_obligations))

    artifact = {
        "schema_version": "1.0",
        "case_id": case.case_id,
        "split": case.split,
        "family": case.family,
        "reference_id": list(case.formula_references),
        "reference_version_or_revision": {
            reference_id: reference_versions.get(reference_id, "UNVERIFIED")
            for reference_id in case.formula_references
        },
        "original_theory_tex": rendered,
        "original_theory_ir": theory,
        "normalized_theory_ir": quotient["representative"],
        "theory_structural_quotient": quotient,
        "generation_plan": plan.to_dict(),
        "provider_candidate": provider_candidate,
        "selected_provider": selected_provider,
        "generation_decision": generation_decision,
        "algorithm_ir": algorithm_ir,
        "generated_language": generated_language,
        "generated_source_fingerprint": generated_source_fingerprint,
        "observed_implementation_ir": observed_ir,
        "reconstructed_math_ir": reconstructed_ir,
        "reconstructed_structural_quotient": reconstructed_quotient,
        "structural_isomorphism_status": isomorphism_status,
        "structural_isomorphism_witness": isomorphism_witness,
        "exact_egraph_status": exact_egraph_status,
        "relation_graph_status": {
            "status": outcome["relation_status"],
            "edges": list(candidate.relation_edges) if candidate else [],
        },
        "assumptions": assumptions,
        "error_range_evidence": error_range,
        "final_reconstruction_status": outcome["relation_status"],
        "implementation_provenance": {
            "temporary_assignments": [],
            "inline_expansions": [],
            "status": "NOT_CAPTURED_NO_GENERATED_IMPLEMENTATION",
        },
        "loop_reduction_provenance": {
            "loop_variable": None,
            "initialization": None,
            "update": None,
            "termination": None,
            "reduction_operation": None,
            "body_dependency": None,
            "order": None,
            "status": "NOT_CAPTURED_NO_GENERATED_IMPLEMENTATION",
        },
        "semantic_fingerprint": case.semantic_fingerprint,
        "external_source_retained": False,
        "unavailable_reasons": unavailable,
    }
    artifact["artifact_payload_hash"] = _canonical_hash(artifact)
    return artifact


def write_reconstruction_artifacts(cases: Iterable[Any], outcomes: Iterable[Mapping[str, Any]],
                                   plans: Mapping[str, Any], output_dir: str | Path, *,
                                   reference_versions: Mapping[str, str] | None = None) -> dict[str, Any]:
    destination = Path(output_dir)
    case_dir = destination / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    outcome_by_id = {item["case_id"]: item for item in outcomes}
    artifacts = []
    for case in cases:
        artifact = build_reconstruction_artifact(
            case, outcome_by_id[case.case_id], plans[case.case_id], reference_versions or {})
        (case_dir / f"{case.case_id}.json").write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        artifacts.append(artifact)

    def complete(artifact: Mapping[str, Any], field: str) -> bool:
        return field in artifact and (artifact[field] is not None or field in artifact["unavailable_reasons"])

    per_field = {field: sum(complete(item, field) for item in artifacts) for field in REQUIRED_FIELDS}
    complete_cases = sum(all(complete(item, field) for field in REQUIRED_FIELDS) for item in artifacts)
    summary = {
        "schema_version": "1.0",
        "cases": len(artifacts),
        "artifact_complete_cases": complete_cases,
        "artifact_completeness": f"{complete_cases} / {len(artifacts)}",
        "field_completeness": per_field,
        "theory_ir_preserved": all(item["original_theory_ir"] is not None for item in artifacts),
        "algorithm_ir_preserved_or_explicitly_unavailable": all(complete(item, "algorithm_ir") for item in artifacts),
        "implementation_ir_preserved_or_explicitly_unavailable": all(complete(item, "observed_implementation_ir") for item in artifacts),
        "reconstructed_math_ir_preserved_or_explicitly_unavailable": all(complete(item, "reconstructed_math_ir") for item in artifacts),
        "structural_quotient_preserved": all(item["theory_structural_quotient"] is not None for item in artifacts),
        "isomorphism_witness_preserved_or_explicitly_unavailable": all(complete(item, "structural_isomorphism_witness") for item in artifacts),
        "provider_decision_preserved_or_explicitly_unavailable": all(complete(item, "generation_decision") for item in artifacts),
        "external_source_retained": 0,
        "warning": "Artifact completeness means every field is present or has an explicit unavailable reason; it does not mean reconstruction succeeded.",
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "artifact-completeness.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    post_native = {
        "schema_version": "1.0",
        "status": "POST_NATIVE_ARTIFACT_PRESERVATION_ONLY",
        "resolved": sum(item["final_reconstruction_status"] not in
                        {"RECONSTRUCTION_UNRESOLVED", "UNRESOLVED_OR_OUT_OF_SCOPE"}
                        for item in artifacts),
        "unresolved": sum(item["final_reconstruction_status"] in
                          {"RECONSTRUCTION_UNRESOLVED", "UNRESOLVED_OR_OUT_OF_SCOPE"}
                          for item in artifacts),
        "false_acceptance": sum(item["final_reconstruction_status"] == "FALSE_ACCEPTANCE"
                                for item in artifacts),
        "case_specific_fixes_applied": 0,
        "artifact_completeness": summary["artifact_completeness"],
    }
    (destination / "post-native-summary.json").write_text(
        json.dumps(post_native, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary
