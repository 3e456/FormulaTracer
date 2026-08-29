"""Focused native-ownership gate for approximation proof resolution."""

from __future__ import annotations
import json
from pathlib import Path

from cpp_audit.approximation_proofs import resolve_approximation_proof
from formulatracer.runtime_paths import reset_semantic_runtime_metrics, semantic_runtime_snapshot

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    reset_semantic_runtime_metrics()
    reference = resolve_approximation_proof("forward_difference_first_derivative",
        repository_root=ROOT, context={"h":0.1}, kernel_checked=False)
    checked = resolve_approximation_proof("forward_difference_first_derivative",
        repository_root=ROOT, context={"h":0.1,"provided_assumptions":["bounded_second_derivative"]}, kernel_checked=True)
    runtime = semantic_runtime_snapshot()
    checks = {
        "unverified_not_promoted": reference.proof_status == "REFERENCE_THEOREM_ONLY",
        "positive_step_discharged": reference.assumptions[0].discharge_status == "ASSUMPTION_PROVEN",
        "kernel_evidence_preserved": checked.evidence.kernel_checked is True,
        "native_path_only": runtime["RUST_NATIVE_SEMANTIC_CALLS"] == 2
            and runtime["PYTHON_REFERENCE_CALLS"] == 0
            and runtime["PYTHON_SEMANTIC_FALLBACK_COUNT"] == 0,
    }
    payload={"schema_version":"1.0","component":"cpp_audit.approximation_proofs",
             "native_operation":"C/APPROXIMATION_PROOF","status":"PASS" if all(checks.values()) else "FAIL",
             "checks":checks,"runtime":runtime}
    destination=ROOT/"output/native_migration/final/approximation-proof-parity.json"
    destination.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return 0 if payload["status"]=="PASS" else 1

if __name__=="__main__": raise SystemExit(main())
