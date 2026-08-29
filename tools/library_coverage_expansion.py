#!/usr/bin/env python3
"""Generate the versioned major-library coverage evidence bundle."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from cpp_audit.library_coverage import (  # noqa: E402
    PROOF_EVIDENCE, classify_apis, classify_prior_divergences, coverage_summary,
    ecosystem_payloads, library_backends, real_world_gap_analysis,
    run_self_generation_smoke, targeted_mutations,
)
from cpp_audit.major_ecosystem import harvest_major_ecosystem_contracts  # noqa: E402


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def rate(summary: dict, key: str) -> float:
    return float(summary.get("coverage", {}).get(key, 0.0))


def main() -> int:
    output = ROOT / "output" / "library_coverage"; output.mkdir(parents=True, exist_ok=True)
    baseline_root = ROOT / "output" / "real_world_validation"
    inventory = read(baseline_root / "inventory.json")
    projects = read(baseline_root / "project-results.json")
    before = read(baseline_root / "summary.json")
    after_root = ROOT / "output" / "library_coverage" / "private_corpus_after"
    after = read(after_root / "summary.json") if (after_root / "summary.json").is_file() else before

    gap = real_world_gap_analysis(inventory, projects)
    rows = classify_apis(inventory)
    smoke = run_self_generation_smoke()
    divergences = classify_prior_divergences(ROOT / "output" / "control_flow_assurance" / "generated-valid-results.json")
    mutations = targeted_mutations()
    ecosystems = ecosystem_payloads(rows)
    summary = coverage_summary(rows, gap, smoke, mutations)
    major = harvest_major_ecosystem_contracts().to_dict()
    family_counts = Counter(row["meaningful_category"] for row in rows)
    shape_rows = [row for row in rows if row["shape_constraints"]]
    shape = {"schema_version": "1.0", "shape_aware_api_count": len(shape_rows),
             "constraint_count": sum(len(row["shape_constraints"]) for row in shape_rows),
             "named_dimension_api_count": sum(any(c.get("named_dimensions_preserved") for c in row["shape_constraints"])
                                               for row in shape_rows),
             "constraints": [{"qualified_name": row["qualified_name"], "constraints": row["shape_constraints"]}
                             for row in shape_rows],
             "fail_closed": "Missing shape evidence remains SHAPE_UNRESOLVED."}
    provenance = {"schema_version": "1.0", "generated_date": "2026-08-27",
        "proof_evidence_levels": list(PROOF_EVIDENCE),
        "contracts": [{"qualified_name": row["qualified_name"], "package": row["package"],
                       "version": "UNVERIFIED", "reference_source": row["official_reference"],
                       "reference_revision_or_date": "2026-08-27 harvest date",
                       "semantic_family": row["semantic_family"], "proof_evidence": row["proof_evidence"]}
                      for row in rows if row["official_reference"]],
        "warning": "Harvest date is not a library version. UNVERIFIED is retained when no installed/version-pinned evidence exists."}
    before_after = {"schema_version": "1.0", "measurement": "PRIVATE_CORPUS_READ_ONLY",
        "before": {"library_contract_resolution_rate": rate(before, "library_contract_resolution_rate"),
                   "mathematical_ir_extraction_rate": rate(before, "mathematical_ir_extraction_rate"),
                   "UNKNOWN_LIBRARY": before["audit"]["unresolved_causes"].get("UNKNOWN_LIBRARY", 0),
                   "SHAPE_UNRESOLVED": before["audit"]["unresolved_causes"].get("SHAPE_UNRESOLVED", 0),
                   "PARTIAL_OR_UNRESOLVED": sum(before["audit"]["verification_status"].get(k, 0) for k in
                                                ("PARTIAL_END_TO_END_VERIFICATION", "END_TO_END_UNRESOLVED")),
                   "semantic_family_Other": before["algorithm_families"].get("Other", 0)},
        "after": {"library_contract_resolution_rate": rate(after, "library_contract_resolution_rate"),
                  "mathematical_ir_extraction_rate": rate(after, "mathematical_ir_extraction_rate"),
                  "UNKNOWN_LIBRARY": after["audit"]["unresolved_causes"].get("UNKNOWN_LIBRARY", 0),
                  "SHAPE_UNRESOLVED": after["audit"]["unresolved_causes"].get("SHAPE_UNRESOLVED", 0),
                  "PARTIAL_OR_UNRESOLVED": sum(after["audit"]["verification_status"].get(k, 0) for k in
                                               ("PARTIAL_END_TO_END_VERIFICATION", "END_TO_END_UNRESOLVED")),
                  "semantic_family_Other": after["algorithm_families"].get("Other", 0)},
        "after_artifact": "output/library_coverage/private_corpus_after/summary.json" if after is not before else None,
        "data_file_content_read": False, "corpus_modified": False}
    readiness = {"backends": [{"backend": backend.name, "language": backend.language,
        "capabilities": sorted(backend.capabilities), "generation_capability": sorted(backend.rules),
        "round_trip_capability": any(case.get("backend") == backend.name and
                                     case["round_trip_status"] == "ROUND_TRIP_VERIFIED" for case in smoke["cases"]),
        "known_unsupported_families": sorted({"Elementwise", "FiniteSum", "FilteredSum", "Dot",
            "MatrixMultiply", "Piecewise", "Reduction"} - set(backend.capabilities))}
        for backend in library_backends().values()]}
    summary.update({"private_corpus_before_after": before_after, "self_audit_readiness": readiness,
                    "prior_divergences": divergences["classification_counts"],
                    "major_ecosystem_seed": major["coverage"]})

    write(output / "real-world-gap-analysis.json", gap)
    write(output / "api-classification.json", {"schema_version": "1.0", "apis": rows})
    write(output / "semantic-family-coverage.json", {"schema_version": "1.0",
          "meaningful_category_counts": dict(family_counts), "real_world_other_reclassification": gap["semantic_other"]})
    write(output / "shape-coverage.json", shape)
    for language in ("python", "rust", "cpp"): write(output / f"{language}-ecosystem.json", ecosystems[language])
    write(output / "version-provenance.json", provenance)
    write(output / "e-drive-before-after.json", before_after)
    write(output / "self-generation-smoke.json", {**smoke, "readiness": readiness, "mutations": mutations})
    write(output / "round-trip-divergences.json", divergences)
    write(output / "summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["CRITICAL_LIBRARY_FALSE_ACCEPTANCE_OPEN"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
