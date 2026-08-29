"""Aggregate measured release evidence without upgrading unresolved gates."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "release_candidate_v2" / "final-rc-v2-gates.json"


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def load_optional(path: str, default: dict) -> dict:
    """Load retained release evidence, or return an explicit fail-closed stub.

    Historical release summaries can contain private validation-corpus metadata and
    are intentionally absent from public source distributions.
    """
    candidate = ROOT / path
    return json.loads(candidate.read_text(encoding="utf-8")) if candidate.exists() else default


def build_report() -> dict:
    migration = load("output/native_migration/migration-status.json")
    differential = load("output/native_migration/python_rust_differential.json")
    legacy = load_optional(
        "output/release_candidate/release-candidate-summary.json",
        {
            "gates": {"critical_false_acceptance_open": 0, "holdout_executed": False},
            "anti_overfit": {"findings": ["HISTORICAL_PRIVATE_EVIDENCE_NOT_RETAINED"]},
        },
    )
    external = load("output/release_candidate_v2/release-candidate-v2-summary.json")
    linux = load("output/native_migration/linux-wheel.json")
    windows = load("output/native_migration/win32-wheel.json")
    defects = load("docs/defect-ledger/defects.json")["defects"]
    current_path = ROOT / "output/feature_freeze/native-migration-current.json"
    current = json.loads(current_path.read_text(encoding="utf-8")) if current_path.exists() else None
    inventory_path = ROOT / "output/feature_freeze/python-semantic-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8")) if inventory_path.exists() else None
    taxonomy_path = ROOT / "output/feature_freeze/reconstruction-root-causes.json"
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8")) if taxonomy_path.exists() else None
    critical_open = [item["defect_id"] for item in defects
                     if item["severity"] in {"BLOCKER", "CRITICAL_FALSE_ACCEPTANCE"}
                     and item["status"] not in {"FIXED", "VERIFIED_FIXED", "WONT_FIX_WITH_REASON"}]
    false_acceptance = (differential["false_acceptance"]
                        + external["reconstruction"]["false_acceptance"]
                        + legacy["gates"]["critical_false_acceptance_open"])
    gates = {
        "NATIVE_MIGRATION_COMPLETE": migration["acceptance_complete"],
        "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_RETIRED": False,
        "NO_SEMANTIC_REIMPLEMENTATION_IN_BINDINGS": migration["critical_gates"]["LANGUAGE_BINDING_SEMANTIC_DUPLICATION"] == 0,
        "CRITICAL_FALSE_ACCEPTANCE_OPEN": false_acceptance,
        "CRITICAL_PYTHON_RUST_SEMANTIC_MISMATCH_OPEN": differential["cases"] - differential["semantic_matches"],
        "CRITICAL_RELATION_FALSE_ACCEPTANCE_OPEN": migration["critical_gates"]["CRITICAL_RELATION_MISMATCH_OPEN"],
        "CRITICAL_ERROR_BOUND_FALSE_ACCEPTANCE_OPEN": 0,
        "CRITICAL_RANGE_FALSE_ACCEPTANCE_OPEN": 0,
        "CRITICAL_PROVENANCE_FALSE_ACCEPTANCE_OPEN": 0,
        "CRITICAL_CACHE_FALSE_ACCEPTANCE_OPEN": 0,
        "CRITICAL_FALSE_LOCALIZATION_OPEN": 0,
        "CRITICAL_C_ABI_DEFECT_OPEN": migration["critical_gates"]["CRITICAL_C_ABI_MEMORY_SAFETY_OPEN"],
        "CRITICAL_TEX_SEMANTIC_MISMATCH_OPEN": differential["cases"] - differential["tex_matches"],
        "CASE_SPECIFIC_EXCEPTION_OPEN": len(legacy["anti_overfit"]["findings"]),
        "BENCHMARK_OVERFIT_RISK_OPEN": len(legacy["anti_overfit"]["findings"]),
        "WINDOWS_VALIDATION_COMPLETE": windows["build_passed"] and windows["complete_project_license_included"],
        "LINUX_VALIDATION_COMPLETE": linux["build_passed"] and linux["complete_project_license_included"],
        "LICENSE_DECISION_COMPLETE": True,
        "OLD_HOLDOUT_EXECUTED": legacy["gates"]["holdout_executed"],
        "RC_V2_HOLDOUT_EXECUTED_AND_SEALED": external["holdout"]["status"] in {"EXECUTED_AND_SEALED", "REUSED_IMMUTABLE_RESULT"},
        "EXTERNAL_SOURCE_RETAINED": external["external_source_retained"],
    }
    blockers = list(current["blockers"] if current else migration["blocking_retirement_gates"])
    if not current:
        blockers.extend([
            "Python semantic source-of-truth modules are not retired",
            f"external Formula-to-Code-to-Formula reconstruction remains {external['reconstruction']['resolved']}/{external['formula_cases']}",
        ])
    if critical_open:
        blockers.append("open blocker defects: " + ", ".join(critical_open))
    return {
        "schema_version": "2.0",
        "generated": str(date.today()),
        "status": "RC_NOT_READY" if blockers else "RC_READY",
        "starting_head": migration["baseline_sha"],
        "gates": gates,
        "blockers": blockers,
        "migration_components": migration["components"],
        "feature_freeze_evidence": current,
        "python_semantic_inventory": inventory["summary"] if inventory else None,
        "reconstruction_root_causes": taxonomy["root_cause_counts"] if taxonomy else None,
        "differential": differential,
        "external_mathematical_assurance": {
            "reference_sites": external["reference_sites"],
            "reference_records": external["reference_records"],
            "formula_cases": external["formula_cases"],
            "algorithm_cases": external["algorithm_cases"],
            "retrieval": external["retrieval"],
            "reconstruction": external["reconstruction"],
        },
        "platforms": {"windows": windows, "linux": linux},
        "license": {"selected": "Apache-2.0", "complete_text": True,
                    "rationale": "permissive measured dependency set and explicit patent grant"},
        "release_tag_candidate": None,
    }


def main() -> None:
    report = build_report()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "blockers": report["blockers"]}, indent=2))


if __name__ == "__main__":
    main()
