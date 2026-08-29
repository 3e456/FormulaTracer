"""Focused native-ownership gate for approximation-family decisions."""

from __future__ import annotations

import json
from pathlib import Path

from cpp_audit.approximation_families import approximation_metadata, classify_library_call
from formulatracer.runtime_paths import reset_semantic_runtime_metrics, semantic_runtime_snapshot

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry/approximation_families.yaml"
MAPPINGS = REGISTRY


def main() -> int:
    reset_semantic_runtime_metrics()
    metadata = approximation_metadata({"approximation_family_id":"central_difference_first_derivative"}, REGISTRY)
    missing = classify_library_call("unknown.call", MAPPINGS)
    unresolved = classify_library_call("xarray.DataArray.interp", MAPPINGS)
    extrapolated = classify_library_call("xarray.DataArray.interp", MAPPINGS, domain_status="EXTRAPOLATION")
    runtime = semantic_runtime_snapshot()
    checks = {
        "metadata_selected": metadata is not None and metadata["family_id"] == "central_difference_first_derivative",
        "unknown_mapping_fail_closed": missing["status"] == "NO_APPROXIMATION_FAMILY_MAPPING",
        "interpolation_domain_unresolved": unresolved["status"] == "INTERPOLATION_DOMAIN_UNRESOLVED",
        "extrapolation_separated": extrapolated["exact_semantic_operator"] == "Extrapolation"
            and extrapolated["approximation_family_ids"] == [],
        "native_path_only": runtime["RUST_NATIVE_SEMANTIC_CALLS"] == 4
            and runtime["PYTHON_REFERENCE_CALLS"] == 0
            and runtime["PYTHON_SEMANTIC_FALLBACK_COUNT"] == 0,
    }
    payload = {"schema_version":"1.0","component":"cpp_audit.approximation_families",
               "native_operation":"C/APPROXIMATION_FAMILY","status":"PASS" if all(checks.values()) else "FAIL",
               "checks":checks,"runtime":runtime}
    destination = ROOT / "output/native_migration/final/approximation-family-parity.json"
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
