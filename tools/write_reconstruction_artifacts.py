"""Regenerate the sealed RC-v2 outcomes and derivative reconstruction artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from cpp_audit.release_candidate_v2 import run_release_candidate_v2
from formulatracer import (observe_python_semantic_runtime, reset_semantic_runtime_metrics,
                           write_semantic_runtime_snapshot)


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    reset_semantic_runtime_metrics()
    with observe_python_semantic_runtime(capture_event_details=False):
        report = run_release_candidate_v2(ROOT / "output" / "release_candidate_v2")
    runtime = write_semantic_runtime_snapshot(
        ROOT / "output" / "reconstruction" / "runtime-semantic-paths.json",
        include_events=False,
    )
    runtime["measurement_scope"] = "EXTERNAL_21_RECONSTRUCTION_ARTIFACT_RUN"
    production_paths = runtime["paths_by_scope"]["PRODUCTION"]
    runtime["TOTAL_PRODUCTION_SEMANTIC_CALLS"] = runtime["calls_by_scope"].get("PRODUCTION", 0)
    runtime["DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS"] = production_paths["PYTHON_REFERENCE"]
    runtime["PRODUCTION_PYTHON_SEMANTIC_CALLS"] = (
        production_paths["PYTHON_REFERENCE"] + production_paths["PYTHON_FALLBACK"])
    (ROOT / "output" / "reconstruction" / "runtime-semantic-paths.json").write_text(
        json.dumps(runtime, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    completeness = json.loads((ROOT / "output" / "reconstruction" /
                               "artifact-completeness.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "formula_cases": report["formula_cases"],
        "resolved": report["reconstruction"]["resolved"],
        "unresolved": report["reconstruction"]["unresolved"],
        "false_acceptance": report["reconstruction"]["false_acceptance"],
        "artifact_completeness": completeness["artifact_completeness"],
        "runtime_semantic_calls": runtime["TOTAL_SEMANTIC_CALLS"],
        "python_reference_calls": runtime["DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS"],
        "python_fallback_calls": runtime["PYTHON_SEMANTIC_FALLBACK_COUNT"],
    }, indent=2))


if __name__ == "__main__":
    main()
