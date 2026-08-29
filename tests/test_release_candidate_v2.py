import json
from pathlib import Path

from jsonschema import Draft202012Validator

from cpp_audit.release_candidate_v2 import (
    benchmark_cases_v2,
    reference_registry_v2,
    run_release_candidate_v2,
)


def test_v2_multisite_fixed_splits_and_no_retained_source():
    cases = benchmark_cases_v2()
    assert {case.split for case in cases} == {"development", "validation", "final_holdout_v2"}
    assert len({case.semantic_fingerprint for case in cases}) == len(cases)
    assert len({item.organization for item in reference_registry_v2()}) >= 6
    assert all(not item.retained_source for item in reference_registry_v2())


def test_v2_holdout_is_immutable_and_fail_closed(tmp_path: Path):
    first = run_release_candidate_v2(tmp_path)
    result = (tmp_path / "holdout-v2-execution.json").read_bytes()
    second = run_release_candidate_v2(tmp_path)
    assert first["reconstruction"]["false_acceptance"] == 0
    assert first["external_source_retained"] == 0
    assert second["holdout"]["status"] == "REUSED_IMMUTABLE_RESULT"
    assert (tmp_path / "holdout-v2-execution.json").read_bytes() == result
    assert json.loads((tmp_path / "benchmark-manifest-v2.json").read_text())["holdout_fingerprint"]
    reconstruction = tmp_path.parent / "reconstruction"
    completeness = json.loads((reconstruction / "artifact-completeness.json").read_text())
    assert completeness["artifact_completeness"] == "21 / 21"
    assert completeness["external_source_retained"] == 0
    artifacts = sorted((reconstruction / "cases").glob("*.json"))
    assert len(artifacts) == 21
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" /
                         "reconstruction-artifact.schema.json").read_text())
    for path in artifacts:
        artifact = json.loads(path.read_text())
        Draft202012Validator(schema).validate(artifact)
        assert artifact["original_theory_ir"]
        assert artifact["theory_structural_quotient"]["witness"]["proof_authority"] is False
        assert artifact["external_source_retained"] is False
        for field, value in artifact.items():
            if value is None and field != "provider_candidate":
                assert field in artifact["unavailable_reasons"]


def test_v2_reports_required_retrieval_cutoffs(tmp_path: Path):
    report = run_release_candidate_v2(tmp_path)
    assert set(report["retrieval"]) == {"recall_at_1", "recall_at_5", "recall_at_10", "recall_at_20"}
