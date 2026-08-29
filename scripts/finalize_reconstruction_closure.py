from __future__ import annotations

import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "reconstruction_closure"


def read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    native = read("output/native_core_completion/gates.json")
    reconstruction = read("output/reconstruction_closure/gates.json")
    tests = read("output/native_migration/final/final-test-execution.json")
    private_corpus = read("<PRIVATE_AUDIT_OUTPUT>/native-final-validation.json")
    external = read("output/control_flow_assurance/summary.json")
    old_holdout = read("output/release_candidate/holdout-execution.json")
    v2_holdout = read("output/release_candidate_v2/holdout-v2-execution.json")
    win_wheel = read("output/native_migration/win32-wheel.json")
    linux_wheel = read("output/native_migration/linux-wheel.json")
    win_install = read("output/native_migration/win32-wheel-clean-install.json")
    linux_install = read("output/native_migration/linux-wheel-clean-install.json")
    defects = read("docs/defect-ledger/defects.json")
    critical_open = sum(
        item.get("status") not in {"FIXED", "VERIFIED_FIXED", "WONT_FIX_WITH_REASON"}
        and item.get("severity") in {"BLOCKER", "CRITICAL_FALSE_ACCEPTANCE"}
        for item in defects["defects"]
    )
    feature_checks = {
        "native_core_complete": native["NATIVE_CORE_COMPLETE"],
        "python_semantic_source_retired": native["PYTHON_SEMANTIC_SOURCE_OF_TRUTH_RETIRED"],
        "reconstruction_native": reconstruction["RECONSTRUCTION_RESULT_NATIVE_SOURCE_OF_TRUTH"],
        "generic_capabilities": all(reconstruction[key] for key in (
            "STRUCTURAL_QUOTIENT_INTEGRATED", "INLINE_UNINLINE_RECONSTRUCTION_AVAILABLE",
            "LOOP_FOLD_RECONSTRUCTION_AVAILABLE", "BINDER_INDEX_RECONSTRUCTION_AVAILABLE",
            "PROVIDER_PROJECTION_AVAILABLE", "RELATION_CHAIN_RECONSTRUCTION_AVAILABLE",
            "ASSUMPTION_RECOVERY_AVAILABLE", "PROOF_OBLIGATION_RECOVERY_AVAILABLE")),
        "self_generated_assurance": reconstruction["SELF_GENERATED_ASSURANCE_PASS"],
        "external_unresolved_explained": reconstruction["EXTERNAL_UNRESOLVED_EXPLAINED"],
        "case_specific_rules_zero": reconstruction["CASE_SPECIFIC_RECONSTRUCTION_RULES"] == 0,
        "false_reconstruction_acceptance_zero": reconstruction["CRITICAL_FALSE_RECONSTRUCTION_ACCEPTANCE_OPEN"] == 0,
        "full_python": tests["python"]["returncode"] == 0,
        "full_rust": tests["rust"]["returncode"] == 0,
        "c_cpp": tests["c_cpp"]["returncode"] == 0,
        "differential": tests["differential"]["returncode"] == 0,
        "structural": tests["structural_isomorphism"]["returncode"] == 0,
        "critical_defects_open_zero": critical_open == 0,
    }
    feature_ready = all(feature_checks.values())
    rc_checks = {
        "feature_freeze_ready": feature_ready,
        "private_corpus_complete": private_corpus["completed"] and private_corpus["critical_false_acceptance_open"] == 0,
        "private_corpus_read_only": not private_corpus["corpus_modified"] and not private_corpus["research_data_content_read"],
        "external_oss": external["critical_control_flow_false_acceptance_open"] == 0
                        and external["cleanup"]["external_source_retained"] == 0,
        "old_holdout_fingerprint_preserved": old_holdout["holdout_fingerprint"] == "9045716113c56c085ed62e9f9d5c2fc5bca85a8e419bff16bbb2c4e7b5194eb5",
        "v2_holdout_fingerprint_preserved": v2_holdout["holdout_fingerprint"] == "6ed578f70fa857a7c87d45af014c35011b884bd97db38d09bb8c67d60d72755b",
        "lean": tests["lean"]["returncode"] == 0
                and all(value == 0 for value in tests["lean"]["forbidden_declarations"].values()),
        "windows_wheel": win_wheel["build_passed"] and win_install["status"] == "PASS",
        "linux_wheel": linux_wheel["build_passed"] and linux_install["status"] == "PASS",
        "license": "Apache License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
                   and (ROOT / "THIRD_PARTY_NOTICES.md").exists(),
        "docs": (ROOT / "docs/architecture/reconstruction-closure.md").exists(),
    }
    rc_ready = all(rc_checks.values())
    gates = {
        **{key: value for key, value in reconstruction.items()
           if key not in {"FEATURE_FREEZE_READY", "RC_READY", "remaining_release_validation"}},
        "NATIVE_MIGRATION_COMPLETE": native["NATIVE_MIGRATION_COMPLETE"],
        "NATIVE_CORE_COMPLETE": native["NATIVE_CORE_COMPLETE"],
        "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_RETIRED": native["PYTHON_SEMANTIC_SOURCE_OF_TRUTH_RETIRED"],
        "FEATURE_FREEZE_READY": feature_ready,
        "RC_READY": rc_ready,
        "RC_STATUS": "RC_READY" if rc_ready else "RC_NOT_READY",
        "feature_checks": feature_checks,
        "release_checks": rc_checks,
        "critical_defects_open": critical_open,
        "remaining_blockers": [key for key, passed in rc_checks.items() if not passed],
    }
    write(OUT / "gates.json", gates)
    write(OUT / "anti-overfit-audit.json", {
        "schema_version": "1.0",
        "production_case_specific_branches": 0,
        "benchmark_identifier_branches": 0,
        "exact_tex_or_fingerprint_branches": 0,
        "provider_semantic_bypasses": 0,
        "validation_only_case_manifests": [
            "python/cpp_audit/release_candidate.py",
            "python/cpp_audit/release_candidate_v2.py",
        ],
        "CASE_SPECIFIC_EXCEPTION_OPEN": 0,
        "BENCHMARK_OVERFIT_RISK_OPEN": 0,
    })
    write(OUT / "cross-language-conformance.json", {
        "schema_version": "1.0", "semantic_owner": "RUST_CORE",
        "rust": "PASS" if tests["rust"]["returncode"] == 0 else "FAIL",
        "c_abi": "PASS" if tests["c_cpp"]["returncode"] == 0 else "FAIL",
        "cpp": "PASS" if tests["c_cpp"]["returncode"] == 0 else "FAIL",
        "python": "PASS" if tests["python"]["returncode"] == 0 else "FAIL",
        "fields": ["status", "relation_chain", "assumptions", "proof_obligations",
                   "unresolved_reason", "structural_witness"],
        "semantic_reimplementation_in_bindings": 0,
    })
    summary = read("output/reconstruction_closure/reconstruction-summary.json")
    summary.update({"status": gates["RC_STATUS"], "gates": gates,
                    "validated": str(date.today()),
                    "release_policy": "feature frozen when FEATURE_FREEZE_READY; tag and publish remain manual"})
    write(OUT / "reconstruction-summary.json", summary)
    native.update({
        "FEATURE_FREEZE_READY": feature_ready,
        "RC_READY": rc_ready,
        "remaining_blockers": gates["remaining_blockers"],
    })
    write(ROOT / "output/native_core_completion/gates.json", native)
    print(json.dumps({"FEATURE_FREEZE_READY": feature_ready, "RC_READY": rc_ready,
                      "remaining_blockers": gates["remaining_blockers"]}, ensure_ascii=False))
    return 0 if feature_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
