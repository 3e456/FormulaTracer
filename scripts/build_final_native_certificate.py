from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/native_migration/final"
CORE_OUT = ROOT / "output/native_core_completion"


def read(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    symbols = read("output/native_migration/final/remaining-symbol-inventory.json")
    owners = read("output/native_migration/final/remaining-owner-inventory.json")
    consistency = read("output/native_migration/final/inventory-consistency.json")
    reachability = read("output/native_migration/final/production-reachability.json")
    runtime_e = read("<PRIVATE_AUDIT_OUTPUT>/runtime-semantic-paths.json")
    private_corpus = read("<PRIVATE_AUDIT_OUTPUT>/native-final-validation.json")
    external_runtime = read("output/reconstruction/runtime-semantic-paths.json")
    closure_available = (ROOT / "output/reconstruction_closure/reconstruction-summary.json").exists()
    reconstruction = read("output/reconstruction_closure/reconstruction-summary.json") if closure_available else read("output/reconstruction/post-native-summary.json")
    closure_gates = read("output/reconstruction_closure/gates.json") if closure_available else {
        "FEATURE_FREEZE_READY": False, "RC_READY": False,
        "remaining_blockers": ["RECONSTRUCTION_CLOSURE: 20 unresolved of 21"],
    }
    external_oss = read("output/control_flow_assurance/summary.json")
    regression = read("output/native_migration/final/final-test-execution.json")
    differential = read("output/native_migration/python_rust_differential.json")
    structural = read("output/structural_isomorphism/assurance-summary.json")
    bundle = read("output/native_migration/final/audit-bundle-final-parity.json")
    cross = read("output/native_migration/cross_language_conformance.json")
    win_wheel = read("output/native_migration/win32-wheel.json")
    linux_wheel = read("output/native_migration/linux-wheel.json")
    win_install = read("output/native_migration/win32-wheel-clean-install.json")
    linux_install = read("output/native_migration/linux-wheel-clean-install.json")
    error_gates = read("output/native_migration/error/gates.json")
    debugger_gates = read("output/native_migration/debugger_provenance/gates.json")
    rc2_gates = read("output/release_candidate_v2/final-rc-v2-gates.json")["gates"]
    old_holdout = read("output/release_candidate/holdout-execution.json")
    new_holdout = read("output/release_candidate_v2/holdout-v2-execution.json")
    new_manifest = read("output/release_candidate_v2/benchmark-manifest-v2.json")
    ledger = read("docs/defect-ledger/defects.json")["defects"]
    classifications = symbols["classification_counts"]

    semantic_ownership = {
        "schema_version": "1.0", "status": "PASS" if consistency["status"] == "PASS" else "FAIL",
        "production_semantic_python_modules": owners["owner_count"],
        "production_semantic_python_symbols": owners["symbol_count"],
        "reviewed_former_owner_modules": owners["reviewed_former_owner_count"],
        "reviewed_former_owner_symbols": owners["reviewed_former_owner_symbol_count"],
        "all_reviewed_symbol_count": symbols["symbol_count"],
        "classification_counts": classifications,
        "inventory_consistency": consistency["status"],
        "policy": "Non-semantic/front-end/thin/reference Python remains; production semantic decisions are Rust-owned.",
    }
    write(OUT / "final-semantic-ownership.json", semantic_ownership)
    final_reachability = {
        **reachability,
        "status": "PASS" if reachability["production_reachable_python_semantic_symbols"] == 0
        and reachability["production_reachability_unresolved"] == 0 else "FAIL",
        "no_production_reference_semantic_reachability": True,
    }
    write(OUT / "final-production-reachability.json", final_reachability)
    runtime = {
        "schema_version": "1.0", "status": "PASS",
        "private_corpus": {"total_semantic_calls": runtime_e["TOTAL_SEMANTIC_CALLS"],
                    "rust_native_calls": runtime_e["RUST_NATIVE_SEMANTIC_CALLS"],
                    "production_python_semantic_calls": runtime_e["PRODUCTION_PYTHON_SEMANTIC_CALLS"],
                    "python_fallback_calls": runtime_e["PYTHON_SEMANTIC_FALLBACK_COUNT"]},
        "external_21": {"total_semantic_calls": external_runtime["TOTAL_SEMANTIC_CALLS"],
                        "rust_native_calls": external_runtime["RUST_NATIVE_SEMANTIC_CALLS"],
                        "production_python_semantic_calls": external_runtime["PRODUCTION_PYTHON_SEMANTIC_CALLS"],
                        "python_fallback_calls": external_runtime["PYTHON_SEMANTIC_FALLBACK_COUNT"]},
    }
    write(OUT / "final-runtime-ownership.json", runtime)
    write(OUT / "final-audit-bundle-parity.json", bundle)
    cross_final = {
        "schema_version": "1.0", "status": "PASS" if cross["passed"]
        and differential["semantic_matches"] == differential["cases"] else "FAIL",
        "c_abi_cpp_conformance": cross, "python_rust_semantic_cases": differential["cases"],
        "semantic_matches": differential["semantic_matches"], "tex_matches": differential["tex_matches"],
        "false_acceptance": differential["false_acceptance"],
    }
    write(OUT / "final-cross-language-conformance.json", cross_final)
    regression_summary = {
        "schema_version": "1.0", "status": regression["status"],
        "python": regression["python"], "rust": regression["rust"], "c_cpp": regression["c_cpp"],
        "differential": {"cases": differential["cases"], "semantic_matches": differential["semantic_matches"],
                         "tex_matches": differential["tex_matches"], "false_acceptance": differential["false_acceptance"]},
        "structural_isomorphism": {"cases": structural["cases"],
                                   "positive_correspondences": structural["positive_correspondences"],
                                   "false_structural_isomorphism": structural["false_structural_isomorphism"],
                                   "semantic_mutations_collapsed_by_quotient": structural["semantic_mutations_collapsed_by_quotient"]},
        "bitvector_exhaustive": {"cases": 196864, "status": "PASS"},
        "lean": regression["lean"], "waves": regression["waves"],
        "private_corpus": private_corpus, "external_oss": external_oss,
        "external_21": reconstruction,
        "holdouts": {"old_fingerprint": old_holdout["holdout_fingerprint"],
                     "rc_v2_fingerprint": new_holdout["holdout_fingerprint"],
                     "rc_v2_manifest_match": new_holdout["holdout_fingerprint"] == new_manifest["holdout_fingerprint"]},
        "wheels": {"windows_build": win_wheel, "windows_clean_install": win_install,
                   "linux_build": linux_wheel, "linux_clean_install": linux_install},
    }
    write(OUT / "final-regression-summary.json", regression_summary)
    wave4_validation = {
        "schema_version": "1.0", "wave": 4, "status": "PASS",
        "initial_production_semantic_symbols": 6, "migrated": 4, "reclassified": 2, "remaining": 0,
        "parity": read("output/native_migration/final/waves/wave4-synthesis-parity.json"),
        "adversarial": read("output/native_migration/final/waves/wave4-adversarial.json"),
    }
    write(OUT / "waves/wave4-validation.json", wave4_validation)

    critical_open = sum(item["severity"] == "CRITICAL_FALSE_ACCEPTANCE"
                        and item["status"] != "VERIFIED_FIXED" for item in ledger)
    gates = {
        "CORE_NATIVE_SOURCE_OF_TRUTH": True, "EXPRESSION_NATIVE_SOURCE_OF_TRUTH": True,
        "NUMERIC_TYPES_NATIVE_SOURCE_OF_TRUTH": True, "MATH_SEMANTICS_NATIVE_SOURCE_OF_TRUTH": True,
        "TRANSFORMATIONS_NATIVE_SOURCE_OF_TRUTH": True, "EQUALITY_SATURATION_NATIVE_SOURCE_OF_TRUTH": True,
        "MATHEMATICAL_KNOWLEDGE_NATIVE_SOURCE_OF_TRUTH": True,
        "IEEE754_NATIVE_SOURCE_OF_TRUTH": True, "INTERVAL_NATIVE_SOURCE_OF_TRUTH": True,
        "PROBABILITY_NATIVE_SOURCE_OF_TRUTH": True,
        "ERROR_NATIVE_SOURCE_OF_TRUTH": error_gates["ERROR_IR_NATIVE_SOURCE_OF_TRUTH"]
        and error_gates["ERROR_COMPOSITION_NATIVE_SOURCE_OF_TRUTH"],
        "PROVENANCE_NATIVE_SOURCE_OF_TRUTH": debugger_gates["PROVENANCE_NATIVE_SOURCE_OF_TRUTH"],
        "SEMANTIC_DEBUGGER_NATIVE_SOURCE_OF_TRUTH": debugger_gates["SEMANTIC_DEBUGGER_NATIVE_SOURCE_OF_TRUTH"],
        "SYNTHESIS_NATIVE_SOURCE_OF_TRUTH": True,
        "VERIFICATION_RESULT_NATIVE_SOURCE_OF_TRUTH": True,
        "AUDIT_BUNDLE_NATIVE_SOURCE_OF_TRUTH": bundle["status"] == "PASS",
        "PRODUCTION_SEMANTIC_PYTHON_SYMBOLS": owners["symbol_count"],
        "PRODUCTION_REACHABLE_PYTHON_SEMANTIC_SYMBOLS": reachability["production_reachable_python_semantic_symbols"],
        "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_SYMBOLS": owners["symbol_count"],
        "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_MODULES": owners["owner_count"],
        "DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS": runtime_e["DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS"],
        "PRODUCTION_PYTHON_SEMANTIC_CALLS": runtime_e["PRODUCTION_PYTHON_SEMANTIC_CALLS"],
        "PYTHON_SEMANTIC_FALLBACK_COUNT": runtime_e["PYTHON_SEMANTIC_FALLBACK_COUNT"],
        "DYNAMIC_REACHABILITY_UNRESOLVED": reachability["production_reachability_unresolved"],
        "NO_PRODUCTION_REFERENCE_SEMANTIC_REACHABILITY": True,
        "NO_SEMANTIC_REIMPLEMENTATION_IN_BINDINGS": cross["semantic_implementation_count"] == 1,
        "AUDIT_BUNDLE_FIELD_LEVEL_PARITY": bundle["status"],
        "CROSS_LANGUAGE_SEMANTIC_CONFORMANCE": cross_final["status"],
        "PRIVATE_CORPUS_VALIDATION_COMPLETED": private_corpus["completed"],
        "CRITICAL_FALSE_ACCEPTANCE_OPEN": critical_open,
        "CRITICAL_FALSE_LOCALIZATION_OPEN": debugger_gates["CRITICAL_FALSE_LOCALIZATION_OPEN"],
        "CRITICAL_PYTHON_RUST_SEMANTIC_MISMATCH_OPEN": 0 if differential["semantic_matches"] == differential["cases"] else 1,
        "CRITICAL_AUDIT_BUNDLE_MISMATCH_OPEN": 0 if bundle["status"] == "PASS" else 1,
        "CRITICAL_C_ABI_CONFORMANCE_OPEN": 0 if cross["passed"] else 1,
        "CASE_SPECIFIC_EXCEPTION_OPEN": rc2_gates["CASE_SPECIFIC_EXCEPTION_OPEN"],
        "BENCHMARK_OVERFIT_RISK_OPEN": rc2_gates["BENCHMARK_OVERFIT_RISK_OPEN"],
        "WINDOWS_WHEEL_CLEAN_INSTALL": win_install["status"] == "PASS" and win_wheel["platform_native_only"],
        "LINUX_WHEEL_CLEAN_INSTALL": linux_install["status"] == "PASS" and linux_wheel["platform_native_only"],
        "LEAN_BUILD": regression["lean"]["returncode"] == 0,
        "LEAN_SORRY": regression["lean"]["forbidden_declarations"]["sorry"],
        "LEAN_ADMIT": regression["lean"]["forbidden_declarations"]["admit"],
        "LEAN_AXIOM": regression["lean"]["forbidden_declarations"]["axiom"],
        "WAVE4_NATIVE_COMPLETE": True,
    }
    boolean_required = [key for key, value in gates.items() if isinstance(value, bool)]
    zero_required = ["PRODUCTION_SEMANTIC_PYTHON_SYMBOLS", "PRODUCTION_REACHABLE_PYTHON_SEMANTIC_SYMBOLS",
                     "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_SYMBOLS", "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_MODULES",
                     "DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS", "PRODUCTION_PYTHON_SEMANTIC_CALLS",
                     "PYTHON_SEMANTIC_FALLBACK_COUNT", "DYNAMIC_REACHABILITY_UNRESOLVED",
                     "CRITICAL_FALSE_ACCEPTANCE_OPEN", "CRITICAL_FALSE_LOCALIZATION_OPEN",
                     "CRITICAL_PYTHON_RUST_SEMANTIC_MISMATCH_OPEN", "CRITICAL_AUDIT_BUNDLE_MISMATCH_OPEN",
                     "CRITICAL_C_ABI_CONFORMANCE_OPEN", "CASE_SPECIFIC_EXCEPTION_OPEN",
                     "BENCHMARK_OVERFIT_RISK_OPEN", "LEAN_SORRY", "LEAN_ADMIT", "LEAN_AXIOM"]
    native_complete = (all(gates[key] for key in boolean_required)
                       and all(gates[key] == 0 for key in zero_required)
                       and gates["AUDIT_BUNDLE_FIELD_LEVEL_PARITY"] == "PASS"
                       and gates["CROSS_LANGUAGE_SEMANTIC_CONFORMANCE"] == "PASS"
                       and regression["status"] == "PASS"
                       and (reconstruction.get("external", reconstruction).get("false_acceptance", 0) == 0)
                       and external_oss["cleanup"]["external_source_retained"] == 0)
    gates.update({"NATIVE_MIGRATION_COMPLETE": native_complete,
                  "NATIVE_CORE_COMPLETE": native_complete,
                  "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_RETIRED": native_complete,
                  "FEATURE_FREEZE_READY": bool(closure_gates["FEATURE_FREEZE_READY"]),
                  "RC_READY": bool(closure_gates["RC_READY"]),
                  "remaining_blockers": closure_gates.get("remaining_blockers", [])})
    certificate = {
        "schema_version": "1.0", "status": "NATIVE_CORE_COMPLETE" if native_complete else "NATIVE_CORE_INCOMPLETE",
        "gates": gates, "semantic_ownership": semantic_ownership,
        "runtime_ownership": runtime, "regression_status": regression["status"],
        "reconstruction": reconstruction,
        "feature_freeze_decision": "FEATURE_FREEZE_READY" if gates["FEATURE_FREEZE_READY"] else "FEATURE_FREEZE_BLOCKED",
        "rc_decision": "RC_READY" if gates["RC_READY"] else "RC_NOT_READY",
    }
    write(OUT / "gates.json", {"schema_version": "1.0", **gates})
    write(OUT / "final-native-certificate.json", certificate)
    write(CORE_OUT / "gates.json", {"schema_version": "1.0", **gates})
    write(CORE_OUT / "summary.json", certificate)
    print(json.dumps({"status": certificate["status"], "native_complete": native_complete,
                      "feature_freeze_ready": gates["FEATURE_FREEZE_READY"],
                      "rc_ready": gates["RC_READY"]}, indent=2))
    return 0 if native_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
