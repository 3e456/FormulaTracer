import json
from pathlib import Path
import re
import sys
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import jsonschema
import yaml

from cpp_audit.release_candidate import (
    benchmark_cases,
    dependency_license_inventory,
    reference_registry,
    run_release_candidate_validation,
)


def test_lean_library_is_a_real_default_and_release_target():
    root = Path(__file__).resolve().parents[1]
    lake = tomllib.loads((root / "lakefile.toml").read_text(encoding="utf-8"))
    assert lake["defaultTargets"] == ["CppAudit"]
    assert "defaultTargets" not in lake["require"][0]
    workflow = (root / ".github" / "workflows" / "release-validation.yml").read_text(encoding="utf-8")
    assert workflow.count("lake build CppAudit") >= 2


def test_corpus_splits_are_fixed_disjoint_and_reference_only():
    cases = benchmark_cases()
    assert {case.split for case in cases} == {"development", "validation", "final_holdout"}
    ids = [case.case_id for case in cases]
    fingerprints = [case.semantic_fingerprint for case in cases]
    assert len(ids) == len(set(ids))
    assert len(fingerprints) == len(set(fingerprints))
    assert all(not record.retained_source for record in reference_registry())


def test_dependency_categories_do_not_confuse_optional_providers_with_distribution():
    rows = dependency_license_inventory()
    categories = {row["usage_category"] for row in rows}
    assert {"runtime dependency", "build dependency", "development/test dependency", "optional provider"} <= categories
    numpy = next(row for row in rows if row["name"] == "NumPy")
    assert not numpy["linked_or_imported"]
    assert not numpy["distributed_with_formulatracer"]
    assert not numpy["source_copied"]


def test_release_candidate_report_is_fail_closed_and_writes_all_artifacts(tmp_path: Path):
    report = run_release_candidate_validation(tmp_path, execute_holdout=True)
    assert report["gates"]["critical_false_acceptance_open"] == 0
    assert report["gates"]["external_source_retained"] == 0
    assert report["anti_overfit"]["status"] == "PASS"
    assert set(report["corpora"]) == {"self_generated", "private_corpus_validation",
                                      "external_open_source", "external_mathematical_reference",
                                      "final_holdout"}
    assert report["defect_summary"]["critical_false_acceptance_open"] == 0
    assert report["defect_summary"]["deferred"] >= 1
    assert report["gates"]["license_decision_complete"]
    # Linux evidence is host-local: an actual Linux runner records completion,
    # while a Windows source checkout must not claim it from tracked artifacts.
    assert report["gates"]["linux_validation_complete"] is sys.platform.startswith("linux")
    assert report["status"] == "RC_NOT_READY"  # native semantic migration remains an explicit gate
    assert any(item["split"] == "final_holdout" for item in report["outcomes"])
    first_record = (tmp_path / "holdout-execution.json").read_bytes()
    repeated = run_release_candidate_validation(tmp_path, execute_holdout=True)
    assert repeated["corpora"]["final_holdout"]["status"] == "REUSED_SEALED_RESULT_WITHOUT_REEXECUTION"
    assert (tmp_path / "holdout-execution.json").read_bytes() == first_record
    for name in ("benchmark-manifest.json", "release-candidate-summary.json",
                 "reference-registry.json", "dependency-license-inventory.json"):
        payload = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        assert payload


def test_recall_is_reported_at_required_cutoffs(tmp_path: Path):
    report = run_release_candidate_validation(tmp_path)
    assert set(report["retrieval"]) == {"recall_at_1", "recall_at_5", "recall_at_10", "recall_at_20"}
    assert report["retrieval"]["recall_at_20"]["total"] == 8


def test_public_release_metadata_and_relative_links_are_consistent():
    root = Path(__file__).resolve().parents[1]
    citation = yaml.safe_load((root / "CITATION.cff").read_text(encoding="utf-8"))
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert citation["cff-version"] == "1.2.0"
    assert citation["title"] == "FormulaTracer"
    assert f'version = "{citation["version"]}"' in pyproject
    assert citation["license"] == "Apache-2.0"
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in (root / "LICENSE").read_text()

    files = [root / "README.md", root / "REFERENCES.md", root / "THIRD_PARTY_NOTICES.md",
             root / "docs" / "README.md", root / "docs" / "dependency-license-audit.md",
             root / "docs" / "validation" / "release-candidate-validation.md"]
    for document in files:
        text = document.read_text(encoding="utf-8")
        for match in re.finditer(r"\[[^]]+\]\(([^)]+)\)", text):
            target = match.group(1).split("#", 1)[0]
            if not target or "://" in target:
                continue
            assert (document.parent / target).resolve().exists(), f"broken link {target} in {document}"


def test_versioned_registries_validate_against_schemas():
    root = Path(__file__).resolve().parents[1]
    references = json.loads((root / "registry" / "references.json").read_text(encoding="utf-8"))
    reference_schema = json.loads((root / "schemas" / "reference-registry.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(references, reference_schema)
    assert references == [record.__dict__ for record in reference_registry()]
