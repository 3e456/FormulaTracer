from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path


FAMILY_CAUSES = {
    "fourier": "FRONTEND_RECONSTRUCTION_GAP",
    "series": "TRUNCATION_RELATION_GAP",
    "quadrature": "ERROR_EVIDENCE_GAP",
    "finite_difference": "ASSUMPTION_GAP",
    "integral": "APPROXIMATION_RELATION_GAP",
    "convolution": "FRONTEND_RECONSTRUCTION_GAP",
    "gamma": "PROVIDER_CONTRACT_GAP",
    "beta": "PROVIDER_CONTRACT_GAP",
    "asymptotic": "THEORY_IR_GAP",
    "matrix_multiply": "PROVIDER_CONTRACT_GAP",
    "svd": "PROVIDER_CONTRACT_GAP",
    "root_finding": "ALGORITHM_SEMANTICS_GAP",
    "probability": "THEORY_IR_GAP",
    "piecewise": "THEORY_IR_GAP",
    "integer_modulo": "THEORY_IR_GAP",
    "bitvector": "FRONTEND_RECONSTRUCTION_GAP",
    "units": "CONSTRAINT_PROPAGATION_GAP",
    "laplace": "TRANSFORM_RELATION_GAP",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    report = json.loads((root / "output/release_candidate_v2/release-candidate-v2-summary.json").read_text(encoding="utf-8"))
    unresolved = [item for item in report["outcomes"] if item["relation_status"] in {"RECONSTRUCTION_UNRESOLVED", "UNRESOLVED_OR_OUT_OF_SCOPE"}]
    findings = []
    for item in unresolved:
        cause = FAMILY_CAUSES.get(item["family"], "UNSUPPORTED_MATHEMATICS")
        findings.append({
            "case_id": item["case_id"],
            "split": item["split"],
            "family": item["family"],
            "primary_root_cause": cause,
            "retrieval_status": item["retrieval_status"],
            "verification_status": item["verification_status"],
            "relation_status": item["relation_status"],
            "false_acceptance": False,
            "repair_policy": "GENERIC_FAMILY_FIX_ONLY",
            "holdout_mutation_allowed": False,
        })
    counts = Counter(item["primary_root_cause"] for item in findings)
    payload = {
        "schema_version": "1.0",
        "generated": str(date.today()),
        "source_report": "output/release_candidate_v2/release-candidate-v2-summary.json",
        "source_report_modified": False,
        "unresolved_count": len(findings),
        "false_acceptance": 0,
        "root_cause_counts": dict(sorted(counts.items())),
        "findings": findings,
    }
    destination = root / "output/feature_freeze/reconstruction-root-causes.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if len(findings) != 20:
        raise SystemExit(f"expected sealed 20 unresolved outcomes, got {len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
