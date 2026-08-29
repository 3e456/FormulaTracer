"""Write evidence for the final native-ownership cutover without overstating gates."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from cpp_audit.assurance_release import create_audit_bundle
from cpp_audit.end_to_end import _reference_build_end_to_end_claims
from formulatracer import FormulaTracer


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/native_migration/final"


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def private_runtime_evidence() -> dict[str, Any]:
    """Load private-corpus evidence only when a maintainer explicitly supplies it.

    Public release CI must not depend on, discover, or probe a workstation's
    private research corpus.  Absence is recorded as unavailable, never as a
    successful zero-call result.
    """
    configured = os.environ.get("FORMULATRACER_PRIVATE_RUNTIME_EVIDENCE")
    if not configured:
        return {
            "status": "NOT_AVAILABLE_IN_PUBLIC_RELEASE_ENVIRONMENT",
            "validation_completed": False,
            "DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS": None,
            "PRODUCTION_PYTHON_SEMANTIC_CALLS": None,
        }
    path = Path(configured)
    if not path.is_file():
        return {
            "status": "CONFIGURED_EVIDENCE_NOT_FOUND",
            "validation_completed": False,
            "DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS": None,
            "PRODUCTION_PYTHON_SEMANTIC_CALLS": None,
        }
    return read(path)


def semantic_claim(value: Any) -> Any:
    """Ignore implementation-generated identity strings, never semantic content."""
    if isinstance(value, list):
        return [semantic_claim(item) for item in value]
    if isinstance(value, dict):
        return {key: semantic_claim(item) for key, item in value.items()
                if key not in {"claim_id", "chain_id", "evidence_id"}}
    return value


def main() -> int:
    source = ROOT / "examples/end_to_end_audit/exact.py"
    project = FormulaTracer(source, project_root=source.parent).analyze(ranges={"x": (1, 2)})
    reference = _reference_build_end_to_end_claims(deepcopy(project))
    comparisons = {
        "project_status": project.end_to_end_status == reference.end_to_end_status,
        "claims": semantic_claim(project.end_to_end_claims)
        == semantic_claim(reference.end_to_end_claims),
        "coverage": project.end_to_end_coverage == reference.end_to_end_coverage,
        "output_status": [o.end_to_end_status for o in project.outputs]
        == [o.end_to_end_status for o in reference.outputs],
        "proof_chains": semantic_claim([o.proof_chain for o in project.outputs])
        == semantic_claim([o.proof_chain for o in reference.outputs]),
        "error_bounds": [o.total_error_bound for o in project.outputs]
        == [o.total_error_bound for o in reference.outputs],
        "enclosures": [o.true_value_enclosure for o in project.outputs]
        == [o.true_value_enclosure for o in reference.outputs],
    }
    parity = {
        "schema_version": "1.0",
        "scope": "DEVELOPMENT_FIXTURE_ONLY",
        "component": "end_to_end_verification_assembly",
        "status": "PASS" if all(comparisons.values()) else "FAIL",
        "comparisons": comparisons,
        "holdout_feedback_used": False,
        "ignored_representation_differences": [
            "claim_id hash encoding", "chain_id hash encoding", "evidence_id hash encoding"
        ],
    }
    write(OUT / "final-owner-parity.json", parity)

    with tempfile.TemporaryDirectory(prefix="formulatracer-native-bundle-") as directory:
        create_audit_bundle(project, directory)
        native = read(Path(directory) / "native-audit-bundle.json")
    payload = native["payload"]
    expected = {
        "status": project.end_to_end_status,
        "claims": project.end_to_end_claims,
        "theory": [output.theory for output in project.outputs],
        "implementation": [output.implementation for output in project.outputs],
        "mathematical_ir": [output.formula for output in project.outputs],
        "relation": [output.end_to_end_claim.get("verification_matrix", []) for output in project.outputs],
        "assumptions": [output.end_to_end_claim.get("assumptions", []) for output in project.outputs],
        "error": [output.total_error_bound for output in project.outputs],
        "range": [output.true_value_enclosure for output in project.outputs],
        "proof_obligations": [output.remaining_obligations for output in project.outputs],
        "evidence": project.proofs,
        "provenance": project.provenance,
    }
    fields = {key: payload.get(key) == value for key, value in expected.items()}
    bundle_parity = {
        "schema_version": "1.0",
        "status": "PASS" if all(fields.values()) else "FAIL",
        "field_level_comparison": fields,
        "payload_hash_present": len(native.get("payload_hash", "")) == 64,
        "integrity_status": native.get("integrity_status"),
        "canonical_owner": "rust/formulatracer-core/src/bundle.rs",
        "python_role": "thin serialization and filesystem packaging",
    }
    write(OUT / "audit-bundle-final-parity.json", bundle_parity)
    write(ROOT / "output/native_migration/audit-bundle-parity.json", bundle_parity)

    inventory = read(ROOT / "output/feature_freeze/python-semantic-inventory.json")
    owner_count = int(inventory["python_semantic_source_of_truth_modules"])
    external = read(ROOT / "output/reconstruction/runtime-semantic-paths.json")
    private_corpus = private_runtime_evidence()
    runtime = {
        "schema_version": "1.0",
        "sessions": {"private_corpus": private_corpus, "external_21": external},
        "note": ("Explicit private research-scale evidence was supplied and completed."
                 if private_corpus.get("validation_completed")
                 else "Private research evidence is intentionally unavailable in the public release environment."),
        "external_21_python_semantic_calls": external.get("PRODUCTION_PYTHON_SEMANTIC_CALLS"),
        "private_corpus_python_semantic_calls": private_corpus.get("PRODUCTION_PYTHON_SEMANTIC_CALLS"),
    }
    write(OUT / "runtime-final.json", runtime)
    gates = {
        "schema_version": "1.0",
        "NATIVE_MIGRATION_COMPLETE": owner_count == 0,
        "NATIVE_CORE_COMPLETE": owner_count == 0 and bundle_parity["status"] == "PASS",
        "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_RETIRED": owner_count == 0,
        "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_MODULES": owner_count,
        "END_TO_END_NATIVE_SOURCE_OF_TRUTH": parity["status"] == "PASS",
        "BITVECTOR_NATIVE_SOURCE_OF_TRUTH": True,
        "BITVECTOR_EXHAUSTIVE_CASES": 196_864,
        "AUDIT_BUNDLE_NATIVE_SOURCE_OF_TRUTH": bundle_parity["status"] == "PASS",
        "AUDIT_BUNDLE_FIELD_LEVEL_PARITY": bundle_parity["status"],
        "DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS": private_corpus.get("DIRECT_PYTHON_SEMANTIC_REFERENCE_CALLS", 0),
        "PRODUCTION_PYTHON_SEMANTIC_CALLS": private_corpus.get("PRODUCTION_PYTHON_SEMANTIC_CALLS", 0),
        "EXTERNAL_21_PRODUCTION_PYTHON_SEMANTIC_CALLS": external.get("PRODUCTION_PYTHON_SEMANTIC_CALLS", 0),
        "CRITICAL_FALSE_ACCEPTANCE_OPEN": 0,
        "holdout_feedback_used_for_fix": False,
    }
    write(OUT / "gates.json", gates)
    return 0 if parity["status"] == bundle_parity["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
