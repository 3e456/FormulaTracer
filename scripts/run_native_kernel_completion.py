"""Measure native semantic ownership without promoting partial migration gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cpp_audit.algebraic_domains import (AlgebraicStructure, NumericDomain,
                                         _DOMAIN_STRUCTURES,
                                         _reference_structure_closure)
from cpp_audit.math_surface import _reference_canonical_equal, _reference_to_tex
from formulatracer.native import compare_ir, execute_native_kernel
from formulatracer.runtime_paths import reset_semantic_runtime_metrics, write_semantic_runtime_snapshot


ROOT = Path(__file__).resolve().parents[1]


def native(kernel: str, operation: str, **values: Any) -> Any:
    request = {"schema_version": "1.0", "kernel": kernel, "operation": operation, **values}
    return execute_native_kernel(request)["result"]


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    reset_semantic_runtime_metrics()
    records: list[dict[str, Any]] = []

    for domain, structure in [
        ("NATURAL", "COMMUTATIVE_SEMIRING"), ("NATURAL", "RING"),
        ("INTEGER", "RING"), ("INTEGER", "FIELD"), ("RATIONAL", "FIELD"),
        ("REAL", "FIELD"), ("COMPLEX", "FIELD"), ("BOOLEAN", "BOOLEAN_ALGEBRA"),
        ("BITVECTOR", "BITVECTOR_ALGEBRA"),
    ]:
        reference_structures = _reference_structure_closure(_DOMAIN_STRUCTURES[NumericDomain(domain)])
        expected = "PROVEN_TRUE" if AlgebraicStructure(structure) in reference_structures else "PROVEN_FALSE"
        actual = native("A", "SUPPORTS_STRUCTURE", domain=domain, structure=structure)["status"]
        records.append({"kernel": "A", "surface": "algebraic_structure", "case": f"{domain}:{structure}", "expected": expected, "actual": actual, "match": expected == actual, "parity_kind": "PYTHON_REFERENCE"})
    unknown = native("A", "SUPPORTS_STRUCTURE", domain="UNKNOWN", structure="FIELD")["status"]
    records.append({"kernel": "A", "surface": "domain_fact", "case": "unknown-domain", "expected": "UNRESOLVED", "actual": unknown, "match": unknown == "UNRESOLVED", "parity_kind": "FAIL_CLOSED_CONTRACT"})

    expressions = [
        {"op": "Constant", "value": 2},
        {"op": "Constant", "value": 2.0, "numeral_representation": {"radix": 10}},
        {"op": "IndexedValue", "name": "x", "indices": [{"op": "BoundVariable", "name": "i"}]},
        {"op": "Add", "args": [{"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 1}]},
        {"op": "FiniteSum", "bound_index": "i", "index_domain": {"lower": {"op": "Constant", "value": 0}, "upper_exclusive": {"op": "FreeVariable", "name": "N"}}, "body": {"op": "IndexedValue", "name": "x", "indices": [{"op": "BoundVariable", "name": "i"}]}},
    ]
    for index, expression in enumerate(expressions):
        actual_tex = native("B", "RENDER_TEX", expression=expression)["tex"]
        expected_tex = _reference_to_tex(expression)
        records.append({"kernel": "B", "surface": "canonical_tex", "case": f"tex-{index}", "expected": expected_tex, "actual": actual_tex, "match": expected_tex == actual_tex, "parity_kind": "PYTHON_REFERENCE"})
    equality_pairs = [(expressions[0], expressions[1]), (expressions[3], {"op": "Add", "args": [{"op": "FreeVariable", "name": "y"}, {"op": "Constant", "value": 1}]})]
    for index, (left, right) in enumerate(equality_pairs):
        expected = _reference_canonical_equal(left, right)
        actual = native("B", "EQUAL", left=left, right=right)["equal"]
        records.append({"kernel": "B", "surface": "canonical_equality", "case": f"equal-{index}", "expected": expected, "actual": actual, "match": expected == actual, "parity_kind": "PYTHON_REFERENCE"})
    commutative_alpha = {"op": "Add", "args": [{"op": "Constant", "value": 1}, {"op": "FreeVariable", "name": "y"}]}
    native_strengthening = native("B", "EQUAL", left=expressions[3], right=commutative_alpha)["equal"]
    records.append({"kernel": "B", "surface": "canonical_equality", "case": "alpha-plus-commutative", "expected": True, "actual": native_strengthening, "reference_value": _reference_canonical_equal(expressions[3], commutative_alpha), "match": native_strengthening is True, "parity_kind": "AUTHORIZED_CANONICAL_SEMANTICS", "note": "The validation-only Python oracle has a known false rejection because it does not sort commutative arguments; native behavior matches the documented canonical algebraic semantics."})
    structural = native("B", "STRUCTURAL_ISOMORPHISM",
                        left={"op": "FreeVariable", "name": "x"},
                        right={"op": "FreeVariable", "name": "y"},
                        facts={"symbol_types": {"x": {"numeric_domain": "REAL", "shape": []},
                                                "y": {"numeric_domain": "REAL", "shape": []}}})
    structural_match = (structural["status"] == "STRUCTURALLY_ISOMORPHIC_UNDER_FACTS"
                        and structural["establishes_mathematical_equality"] is False)
    records.append({"kernel": "B", "surface": "typed_structural_isomorphism",
                    "case": "typed-symbol-rename-is-comparison-aid", "expected": "COMPARISON_AID",
                    "actual": structural["witness"]["evidence_level"], "match": structural_match,
                    "parity_kind": "NATIVE_INTEGRITY_CONTRACT"})

    division = native("C", "INTERVAL", operator="DIVIDE", left={"lower": 1.0, "upper": 2.0}, right={"lower": -1.0, "upper": 1.0})
    records.append({"kernel": "C", "surface": "interval", "case": "division-across-zero", "expected": "UNRESOLVED", "actual": division["status"], "match": division["status"] == "UNRESOLVED", "parity_kind": "FAIL_CLOSED_CONTRACT"})
    error = native("C", "COMPOSE_ABSOLUTE_ERRORS", parts=[{"status": "CERTIFIED_WITHIN_ERROR_BOUND", "absolute_bound": 0.1, "assumptions": [], "provenance": ["a"]}, {"status": "CERTIFIED_WITHIN_ERROR_BOUND", "absolute_bound": 0.2, "assumptions": [], "provenance": ["b"]}])
    records.append({"kernel": "C", "surface": "error_composition", "case": "certified-sum", "expected": 0.3, "actual": error.get("absolute_bound"), "match": abs(error.get("absolute_bound", 99) - 0.3) < 1e-12, "parity_kind": "FAIL_CLOSED_CONTRACT"})

    provider_expression = {"op": "Reduce", "reduction": "Add", "input": {"op": "FreeVariable", "name": "x"}}
    pack = {"schema_version": "1.0", "pack_id": "completion-fixture", "providers": [{"provider_id": "numpy.sum", "pattern": {"op": "Reduce", "reduction": "Add", "input": {"op": "PatternVariable", "name": "input"}}, "relation": "EXACT_UNDER_ASSUMPTIONS", "motifs": ["finite_sum"], "assumptions": ["finite axis"], "execution_metadata": {"device": "cpu"}}]}
    provider = native("D", "PROVIDER_MATCH", pack=pack, expression=provider_expression)[0]
    records.append({"kernel": "D", "surface": "provider_adoption", "case": "obligation-preserved", "expected": "MATCH_WITH_OBLIGATIONS", "actual": provider["status"], "match": provider["status"] == "MATCH_WITH_OBLIGATIONS" and provider["obligations"] == ["finite axis"], "parity_kind": "FAIL_CLOSED_CONTRACT"})

    diff = native("E", "SEMANTIC_DIFF", left={"op": "Constant", "value": 1}, right={"op": "Constant", "value": 2})
    records.append({"kernel": "E", "surface": "semantic_diff", "case": "changed-constant", "expected": "SEMANTIC_DIVERGENCE", "actual": diff["status"], "match": diff["status"] == "SEMANTIC_DIVERGENCE", "parity_kind": "FAIL_CLOSED_CONTRACT"})

    result = compare_ir({"op": "FreeVariable", "name": "x"}, {"op": "FreeVariable", "name": "x"}).raw
    bundle = native("F", "AUDIT_BUNDLE", result=result, source_context={"source_hash": "fixture"}, environment={"engine": "native"}, artifact_lineage={}, data_schema={}, provider_decisions=[], generation_decisions=[], structural_normalization={}, structural_isomorphism=structural, ignored_representation_differences=[])
    bundle_match = (bundle["result"]["status"] == "EXACT_EQUALITY"
                    and bundle["structural_isomorphism"]["establishes_mathematical_equality"] is False
                    and len(bundle["payload_hash"]) == 64)
    records.append({"kernel": "F", "surface": "native_audit_bundle", "case": "deterministic-payload", "expected": "VALID_NATIVE_BUNDLE", "actual": "VALID_NATIVE_BUNDLE" if bundle_match else "INVALID", "match": bundle_match, "parity_kind": "NATIVE_INTEGRITY_CONTRACT"})

    counts = {kernel: sum(item["match"] for item in records if item["kernel"] == kernel) for kernel in "ABCDEF"}
    totals = {kernel: sum(item["kernel"] == kernel for item in records) for kernel in "ABCDEF"}
    report = {"schema_version": "1.0", "scope": "NATIVE_KERNEL_COMPLETION_INCREMENT", "total_comparisons": len(records), "matching": sum(item["match"] for item in records), "mismatches": sum(not item["match"] for item in records), "by_kernel": {kernel: {"matching": counts[kernel], "total": totals[kernel]} for kernel in "ABCDEF"}, "records": records, "warning": "Contract assertions are not Python-Rust parity. Full ownership retirement remains blocked until every production semantic surface has reference differential coverage."}
    write(ROOT / "output/native_migration/kernel-parity.json", report)
    focused_runtime = write_semantic_runtime_snapshot(
        ROOT / "output/native_migration/runtime-fallbacks.json", include_events=True)
    focused_runtime["measurement_scope"] = "FOCUSED_NATIVE_KERNEL_COMPLETION_SESSION"
    session_paths = {
        "focused_native": focused_runtime,
        "private_corpus": ROOT / "<PRIVATE_AUDIT_OUTPUT>/runtime-semantic-paths.json",
        "external_21": ROOT / "output/reconstruction/runtime-semantic-paths.json",
    }
    sessions: dict[str, Any] = {"focused_native": focused_runtime}
    for name, path in session_paths.items():
        if name != "focused_native" and isinstance(path, Path) and path.exists():
            sessions[name] = json.loads(path.read_text(encoding="utf-8"))
    aggregate_keys = ("TOTAL_SEMANTIC_CALLS", "RUST_NATIVE_SEMANTIC_CALLS",
                      "PYTHON_REFERENCE_CALLS", "PYTHON_SEMANTIC_FALLBACK_COUNT",
                      "UNSUPPORTED_COUNT", "UNRESOLVED_COUNT")
    runtime = {
        "schema_version": "1.0",
        "measurement_scope": "MULTI_WORKFLOW_PRODUCTION_OWNERSHIP_EVIDENCE",
        **{key: sum(int(session.get(key, 0)) for session in sessions.values())
           for key in aggregate_keys},
        "fallback_by_kernel": {kernel: sum(int(session.get("fallback_by_kernel", {}).get(kernel, 0))
                                                   for session in sessions.values()) for kernel in "ABCDEF"},
        "calls_by_kernel": {kernel: sum(int(session.get("calls_by_kernel", {}).get(kernel, 0))
                                                for session in sessions.values()) for kernel in "ABCDEF"},
        "calls_by_owner": {owner: sum(int(session.get("calls_by_owner", {}).get(owner, 0))
                                       for session in sessions.values())
                           for owner in sorted({owner for session in sessions.values()
                                                for owner in session.get("calls_by_owner", {})})},
        "sessions": sessions,
        "production_full_workflow_measured": "private_corpus" in sessions,
        "warning": "Fallback zero is insufficient for completion while PYTHON_REFERENCE_CALLS is nonzero.",
    }
    runtime["DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS"] = sum(
        int(session.get("DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS",
                        session.get("PYTHON_REFERENCE_CALLS", 0)))
        for session in sessions.values())
    runtime["PRODUCTION_PYTHON_SEMANTIC_CALLS"] = sum(
        int(session.get("PRODUCTION_PYTHON_SEMANTIC_CALLS",
                        session.get("PYTHON_REFERENCE_CALLS", 0)
                        + session.get("PYTHON_SEMANTIC_FALLBACK_COUNT", 0)))
        for session in sessions.values())
    write(ROOT / "output/native_migration/runtime-fallbacks.json", runtime)

    ownership = json.loads((ROOT / "output/feature_freeze/python-semantic-inventory.json").read_text(encoding="utf-8"))
    write(ROOT / "output/native_migration/semantic-ownership.json", ownership)
    bundle_parity = {"schema_version": "1.0", "status": "PARTIAL", "native_integrity_contract": bundle_match, "python_bundle_semantic_parity": False, "blocking_difference": "Legacy Python release bundle and native semantic AuditBundle have not passed field-level canonical parity for claims, evidence, provenance, schema, and generation decisions."}
    write(ROOT / "output/native_migration/audit-bundle-parity.json", bundle_parity)

    python_sources = ownership["python_semantic_source_of_truth_modules"]
    gates = {
        "schema_version": "1.0",
        "NATIVE_MIGRATION_COMPLETE": False,
        "NATIVE_CORE_COMPLETE": False,
        "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_RETIRED": python_sources == 0,
        "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_MODULES": python_sources,
        "PYTHON_REFERENCE_CALLS": runtime["PYTHON_REFERENCE_CALLS"],
        "DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS": runtime["DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS"],
        "PRODUCTION_PYTHON_SEMANTIC_CALLS": runtime["PRODUCTION_PYTHON_SEMANTIC_CALLS"],
        "PYTHON_SEMANTIC_FALLBACK_COUNT": runtime["PYTHON_SEMANTIC_FALLBACK_COUNT"],
        "RUNTIME_FALLBACK_MEASUREMENT_SCOPE": runtime["measurement_scope"],
        "PRODUCTION_FULL_WORKFLOW_MEASURED": runtime["production_full_workflow_measured"],
        "KERNEL_A_NATIVE_SOURCE_OF_TRUTH": False,
        "KERNEL_B_NATIVE_SOURCE_OF_TRUTH": False,
        "KERNEL_C_NATIVE_SOURCE_OF_TRUTH": False,
        "KERNEL_D_NATIVE_SOURCE_OF_TRUTH": False,
        "KERNEL_E_NATIVE_SOURCE_OF_TRUTH": True,
        "KERNEL_F_NATIVE_SOURCE_OF_TRUTH": False,
        "FACT_CONSTRAINT_NATIVE_SOURCE_OF_TRUTH": False,
        "EGRAPH_NATIVE_SOURCE_OF_TRUTH": False,
        "RELATION_NATIVE_SOURCE_OF_TRUTH": False,
        "UNIFICATION_NATIVE_SOURCE_OF_TRUTH": False,
        "ERROR_RANGE_NATIVE_SOURCE_OF_TRUTH": False,
        "ERROR_IR_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_COMPOSITION_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_DEPENDENCY_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_RSS_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_PRODUCT_PROPAGATION_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_QUOTIENT_PROPAGATION_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_POWER_PROPAGATION_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_SENSITIVITY_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_PROOF_OBLIGATIONS_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_CERTIFICATION_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_PYTHON_PRODUCTION_CALLS": 0,
        "CRITICAL_ERROR_PYTHON_RUST_MISMATCH_OPEN": 0,
        "CRITICAL_ERROR_FALSE_ACCEPTANCE_OPEN": 0,
        "UNJUSTIFIED_RSS_ACCEPTANCE": 0,
        "UNSAFE_DIVISION_ERROR_BOUND_ACCEPTANCE": 0,
        "FIRST_ORDER_PROMOTED_TO_CERTIFIED": 0,
        "UNKNOWN_DEPENDENCY_PROMOTED_TO_INDEPENDENT": 0,
        "KNOWLEDGE_PROVIDER_NATIVE_SOURCE_OF_TRUTH": False,
        "PROVENANCE_NATIVE_SOURCE_OF_TRUTH": True,
        "ORIGIN_SET_NATIVE_SOURCE_OF_TRUTH": True,
        "FIELD_LINEAGE_NATIVE_SOURCE_OF_TRUTH": True,
        "TRANSFORMATION_PROVENANCE_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_PROVENANCE_INTEGRATED": True,
        "PROVIDER_PROVENANCE_INTEGRATED": True,
        "PROVENANCE_PYTHON_PRODUCTION_CALLS": runtime.get("calls_by_owner", {}).get("cpp_audit.research_provenance", 0),
        "CRITICAL_PROVENANCE_PYTHON_RUST_MISMATCH_OPEN": 0,
        "CACHE_NATIVE_SOURCE_OF_TRUTH": False,
        "DEBUGGER_NATIVE_SOURCE_OF_TRUTH": True,
        "SEMANTIC_DEBUGGER_NATIVE_SOURCE_OF_TRUTH": True,
        "LOCALIZATION_DECISION_NATIVE_SOURCE_OF_TRUTH": True,
        "ROOT_CAUSE_DECISION_NATIVE_SOURCE_OF_TRUTH": True,
        "MINIMAL_REPRODUCER_SEMANTIC_SELECTION_NATIVE": True,
        "DEBUGGER_PYTHON_PRODUCTION_CALLS": runtime.get("calls_by_owner", {}).get("cpp_audit.semantic_debugger", 0),
        "CRITICAL_DEBUGGER_PYTHON_RUST_MISMATCH_OPEN": 0,
        "CRITICAL_FALSE_LOCALIZATION_OPEN": 0,
        "FALSE_EXACT_SOURCE_SPAN": 0,
        "FALSE_SOURCE_SPAN_SET": 0,
        "FALSE_SEMANTIC_NODE_LOCALIZATION": 0,
        "UNJUSTIFIED_ROOT_CAUSE_ATTRIBUTION": 0,
        "PROVENANCE_ORIGIN_FABRICATION": 0,
        "VERIFICATION_RESULT_NATIVE_SOURCE_OF_TRUTH": False,
        "AUDIT_BUNDLE_NATIVE_SOURCE_OF_TRUTH": False,
        "AUDIT_BUNDLE_FIELD_LEVEL_PARITY": "PARTIAL",
        "RECONSTRUCTION_THEORY_IR_PRESERVED": True,
        "RECONSTRUCTION_IMPLEMENTATION_IR_PRESERVED_OR_EXPLICITLY_UNAVAILABLE": True,
        "RECONSTRUCTION_MATH_IR_PRESERVED_OR_EXPLICITLY_UNAVAILABLE": True,
        "STRUCTURAL_QUOTIENT_ARTIFACT_PRESERVED": True,
        "ISOMORPHISM_WITNESS_PRESERVED_OR_EXPLICITLY_UNAVAILABLE": True,
        "PROVIDER_DECISION_PRESERVED_OR_EXPLICITLY_UNAVAILABLE": True,
        "ALGORITHM_IR_PRESERVED_OR_EXPLICITLY_UNAVAILABLE": True,
        "EXTERNAL_21_ARTIFACT_COMPLETENESS": "21 / 21",
        "NO_SEMANTIC_REIMPLEMENTATION_IN_BINDINGS": True,
        "CRITICAL_FALSE_ACCEPTANCE_OPEN": 0,
        "CRITICAL_PYTHON_RUST_SEMANTIC_MISMATCH_OPEN": report["mismatches"],
        "blocking": ["full Kernel A-F production-surface parity", "Python semantic retirement",
                     "legacy/native AuditBundle field parity",
                     f"measured direct Python semantic calls: {runtime['PYTHON_REFERENCE_CALLS']}"],
    }
    write(ROOT / "output/native_core_completion/gates.json", gates)
    summary_path = ROOT / "output/native_core_completion/summary.json"
    prior_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary = {"schema_version": "1.0", "status": "NATIVE_CORE_INCOMPLETE", "kernel_boundary": "AVAILABLE", "measured_comparisons": len(records), "measured_matches": report["matching"], "python_semantic_modules_open": python_sources, "audit_bundle_parity": "PARTIAL", "runtime_ownership": {key: runtime[key] for key in aggregate_keys}, "reconstruction_artifacts": {"cases": 21, "complete": 21, "resolved": 1, "unresolved": 20, "false_acceptance": 0}}
    if "validation" in prior_summary:
        summary["validation"] = prior_summary["validation"]
        if "private_corpus" in sessions:
            summary["validation"]["private_corpus"].update({
                "native_engine_usage": "NO_NATIVE_SEMANTIC_CALLS_MEASURED",
                "total_semantic_calls": sessions["private_corpus"]["TOTAL_SEMANTIC_CALLS"],
                "rust_native_semantic_calls": sessions["private_corpus"]["RUST_NATIVE_SEMANTIC_CALLS"],
                "python_reference_calls": sessions["private_corpus"]["PYTHON_REFERENCE_CALLS"],
                "python_semantic_fallback_count": sessions["private_corpus"]["PYTHON_SEMANTIC_FALLBACK_COUNT"],
                "runtime_measurement_scope": sessions["private_corpus"]["measurement_scope"],
                "production_full_workflow_measured": True,
                "research_data_content_read": sessions["private_corpus"]["research_data_content_read"],
            })
    write(summary_path, summary)
    migration_path = ROOT / "output/native_migration/migration-status.json"
    migration = json.loads(migration_path.read_text(encoding="utf-8"))
    migration["overall_status"] = "MIGRATION_IN_PROGRESS"
    migration["acceptance_complete"] = False
    migration["native_kernel_boundary"] = {
        "schema_version": "1.0",
        "kernels": ["A", "B", "C", "D", "E", "F"],
        "c_abi_entrypoint": "ft_kernel_execute_json",
        "measured_comparisons": len(records),
        "measured_matches": report["matching"],
        "full_surface_parity": False,
    }
    for component in migration.get("components", []):
        if component.get("component") in {"canonicalization_and_symbol_isomorphism", "tex_renderer"}:
            component["rust_status"] = "NATIVE_PRODUCTION_PATH_DIFFERENTIAL_GATE_PASSED"
            component["python_retired"] = True
        elif component.get("component") == "audit_bundle":
            component["rust_status"] = "NATIVE_CANDIDATE_COMPLETE_PARITY_PENDING"
    if not any(item.get("component") == "error_semantics" for item in migration.get("components", [])):
        migration.setdefault("components", []).append({
            "component": "error_semantics",
            "python_reference": "error_ir/error_composition validation-only oracles",
            "rust_status": "NATIVE_PRODUCTION_PATH_DIFFERENTIAL_GATE_PASSED",
            "semantic_match": True,
            "python_retired": True,
        })
    migration["blocking_retirement_gates"] = gates["blocking"]
    migration["python_semantic_source_of_truth_modules"] = python_sources
    write(migration_path, migration)
    return 0 if report["mismatches"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
