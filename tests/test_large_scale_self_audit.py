from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from cpp_audit.self_audit import (DEFAULT_SEED, backend_capabilities,
                                  generate_theory_corpus, run_large_scale_self_audit)


ROOT = Path(__file__).resolve().parents[1]


def test_theory_corpus_is_deterministic_diverse_and_parameterized():
    left = generate_theory_corpus(seed=DEFAULT_SEED)
    right = generate_theory_corpus(seed=DEFAULT_SEED)
    assert len(left) >= 300
    assert [case.to_dict() for case in left] == [case.to_dict() for case in right]
    assert {case.complexity for case in left} == {"SIMPLE", "MODERATE", "COMPLEX"}
    assert len({case.family for case in left}) >= 25


def test_backend_matrix_fails_closed_for_missing_library_lowerings():
    payload = backend_capabilities()
    lookup = {(row["backend"], row["family"]): row["status"] for row in payload["capabilities"]}
    assert lookup[("numpy", "FiniteSum")] == "SUPPORTED"
    assert lookup[("rust-ndarray", "MatrixMultiply")] == "REFERENCE_ONLY"
    assert lookup[("cpp-eigen", "SpatialOperation")] == "REFERENCE_ONLY"


def test_large_scale_self_audit_uses_real_frontends_and_has_no_false_acceptance(tmp_path: Path):
    payloads = run_large_scale_self_audit(ROOT, output_dir=tmp_path)
    summary = payloads["summary.json"]
    assert summary["valid_source_cases"] >= 200
    assert summary["CRITICAL_SELF_AUDIT_FALSE_ACCEPTANCE_OPEN"] == 0
    assert summary["release_criterion"] == "PASS"
    rows = payloads["valid-round-trip-results.json"]["cases"]
    assert rows and all(row["reanalysis"] == "ACTUAL_FORMULATRACER_FRONTEND" for row in rows)
    assert all("source_hash" in row and "source" not in row for row in rows)
    mutations = payloads["mutation-results.json"]
    assert mutations["validated_semantic_changing"] > 0
    assert mutations["false_acceptance"] == 0
    schema = json.loads((ROOT / "schemas/self-audit-summary.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(summary)
    for expected in ("summary.json", "theory-corpus.json", "backend-capabilities.json",
                     "valid-round-trip-results.json", "cross-library-results.json",
                     "cross-language-results.json", "mutation-results.json", "metamorphic-results.json",
                     "debugger-localization.json", "approximation-results.json",
                     "probability-results.json", "performance.json", "defect-summary.json"):
        assert (tmp_path / expected).is_file()
        json.loads((tmp_path / expected).read_text(encoding="utf-8"))
