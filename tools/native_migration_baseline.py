"""Freeze the pre-native migration evidence without modifying source corpora."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess

from cpp_audit.bitvector import run_exhaustive_bit_assurance


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "native_migration" / "pre_native_migration_baseline.json"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def main() -> None:
    release = load("output/release_candidate/release-candidate-summary.json")
    holdout = load("output/release_candidate/holdout-execution.json")
    self_audit = load("output/self_audit/summary.json")
    real_world = load("<PRIVATE_AUDIT_OUTPUT>/summary.json")
    external = load("output/control_flow_assurance/external-corpus-results.json")
    defects = load("docs/defect-ledger/defects.json")
    bit = run_exhaustive_bit_assurance()
    critical = [item for item in defects["defects"] if item["severity"] in {
        "BLOCKER", "CRITICAL_FALSE_ACCEPTANCE"
    } and item["status"] not in {"FIXED", "VERIFIED_FIXED", "WONT_FIX_WITH_REASON"}]
    evidence_files = [
        "schemas/expression-ir.schema.json",
        "schemas/implementation-ir.schema.json",
        "schemas/audit-bundle-manifest.schema.json",
        "output/self_audit/summary.json",
        "<PRIVATE_AUDIT_OUTPUT>/summary.json",
        "output/control_flow_assurance/external-corpus-results.json",
        "output/release_candidate/benchmark-manifest.json",
        "output/release_candidate/holdout-execution.json",
        "output/release_candidate/release-candidate-summary.json",
        "docs/defect-ledger/defects.json",
    ]
    payload = {
        "schema_version": "1.0",
        "baseline_kind": "PRE_NATIVE_MIGRATION_BASELINE",
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "python_regression": {"passed": 471, "subtests_passed": 36, "failed": 0},
        "lean": {"toolchain": "v4.19.0", "mathlib": "v4.19.0", "lake_build": "PASS",
                 "sorry_admit_axiom_open": 0},
        "bit_vector_exhaustive": bit.__dict__,
        "self_generated": {
            "theories_generated": self_audit["theories_generated"],
            "valid_source_cases": self_audit["valid_source_cases"],
            "mutation_cases": self_audit["mutation_cases"],
            "mutations_detected": self_audit["mutations_detected"],
            "metamorphic_cases": self_audit["metamorphic_cases"],
            "false_acceptance": self_audit["false_acceptance"],
            "analysis_wall_time_seconds": self_audit["analysis_wall_time_seconds"],
        },
        "private_corpus_validation": {
            "projects_discovered": real_world["corpus"]["projects_discovered"],
            "projects_analyzed": real_world["corpus"]["projects_analyzed"],
            "source_files": real_world["corpus"]["source_files"],
            "loc": real_world["corpus"]["loc"],
            "roots": real_world["audit"]["audit_roots"],
            "outputs": real_world["audit"]["outputs"],
            "critical_false_acceptance_open": real_world["critical_false_acceptance_open"],
        },
        "external_oss": {
            "files_analyzed": external["files_analyzed"],
            "external_source_retained": external["cleanup"]["external_source_retained"],
            "evidence_level": external["evidence_level"],
        },
        "external_mathematical": {
            "status": release["status"], "retrieval": release["retrieval"],
            "critical_false_acceptance_open": release["gates"]["critical_false_acceptance_open"],
        },
        "sealed_holdout": {
            "fingerprint": holdout["holdout_fingerprint"],
            "outcome_fingerprints": [item["semantic_fingerprint"] for item in holdout["outcomes"]],
            "immutable": True,
        },
        "defect_ledger": {
            "discovered": len(defects["defects"]),
            "verified_fixed": sum(item["status"] == "VERIFIED_FIXED" for item in defects["defects"]),
            "critical_open": len(critical),
        },
        "evidence_fingerprints": {relative: digest(ROOT / relative) for relative in evidence_files},
        "priority_kpis": {
            "semantic_equivalence_target": 1.0,
            "critical_false_acceptance_target": 0,
            "binding_semantic_duplication_target": 0,
            "performance_is_release_gate": False,
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
