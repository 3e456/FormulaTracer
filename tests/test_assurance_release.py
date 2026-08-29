from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from formulatracer import (FormulaTracer, localized_certificate, run_assurance_suite,
                           summarize_real_world)


ROOT = Path(__file__).resolve().parents[1]


def exact_result(ranges=None):
    path = ROOT / "examples" / "end_to_end_audit" / "exact.py"
    return FormulaTracer(path, project_root=path.parent).analyze(ranges=ranges or {"x": (1, 2)})


def test_mutation_and_adversarial_gate_has_zero_false_acceptance():
    expression = {"op": "Add", "args": [{"op": "Multiply", "args": [
        {"op": "IndexedValue", "name": "x", "indices": [{"op": "BoundVariable", "name": "i"}]},
        {"op": "Constant", "value": 2}], "reduction_order": "left_to_right"},
        {"op": "Constant", "value": 1}], "axes": 0, "dtype": "float64"}
    report = run_assurance_suite(expression)
    assert report.status == "ASSURANCE_GATE_PASSED_WITH_UNRESOLVED"
    assert report.metrics.false_acceptance == 0
    assert report.metrics.true_rejection >= 6
    assert report.metrics.true_acceptance == 0
    assert report.metrics.unresolved == 12
    assert len(report.adversarial) == 10


def test_branch_flip_mutation_swaps_both_branches():
    expression = {"op": "IfThenElse", "condition": {"op": "FreeVariable", "name": "c"},
                  "then": {"op": "Constant", "value": 1},
                  "else": {"op": "Constant", "value": 2}}
    report = run_assurance_suite(expression)
    branch = next(item for item in report.mutations if item.mutation_kind == "BRANCH_FLIP")
    assert branch.detected and not branch.false_acceptance


def test_real_world_summary_and_semantic_audit_diff():
    before = exact_result({"x": (1, 2)}); after = exact_result({"x": (2, 3)})
    summary = summarize_real_world([before, after])
    assert summary.total_projects == 2 and summary.statuses
    diff = before.diff(after)
    assert diff.status == "AUDIT_SEMANTICS_CHANGED"
    assert "RANGE_CHANGED" in {item["kind"] for item in diff.changes}


def test_versioned_bundle_contains_required_artifacts_and_valid_manifest(tmp_path: Path):
    result = exact_result(); debug = result.debug(); bundle = result.create_bundle(tmp_path / "bundle", debug=debug)
    required = {"manifest.json", "certificate.json", "certificate.tex", "project-dependency-graph.json",
                "implementation-ir.json", "mathematical-ir.json", "theory.json", "transformation-trace.json",
                "library-contracts.json", "assumptions.json", "error-range.json", "lean-proofs.json",
                "debug-findings.json", "end-to-end-claims.json"}
    assert required <= {item.name for item in Path(bundle.path).iterdir()}
    manifest = json.loads((Path(bundle.path) / "manifest.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / "audit-bundle-manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(manifest)
    assert manifest["bundle_hash"] == bundle.bundle_hash


def test_bilingual_certificate_preserves_machine_ids_and_symbols():
    result = exact_result(); debug = result.debug()
    english = localized_certificate(result, locale="en-US", debug=debug)
    japanese = localized_certificate(result, locale="ja-JP", debug=debug)
    assert "FormulaTracer Audit Certificate" in english and "FormulaTracer 監査証明書" in japanese
    assert "END\\_TO\\_END\\_KERNEL\\_VERIFIED\\_UNDER\\_ASSUMPTIONS" in english
    assert "END\\_TO\\_END\\_KERNEL\\_VERIFIED\\_UNDER\\_ASSUMPTIONS" in japanese
    assert "y" in english and "y" in japanese
    assert "exact.compute" not in english and "exact.compute" not in japanese


def test_defect_ledger_release_gate_and_burndown_are_consistent():
    ledger = json.loads((ROOT / "docs" / "defect-ledger" / "defects.json").read_text(encoding="utf-8"))
    burndown = json.loads((ROOT / "output" / "stabilization" / "defect-burndown.json").read_text(encoding="utf-8"))
    required = {"defect_id", "discovered_in_batch", "severity", "category", "affected_language",
                "affected_library", "affected_file", "source_span", "reproduction", "expected", "actual",
                "affected_outputs", "affected_verification_claims", "false_acceptance_risk", "workaround",
                "proposed_fix", "status"}
    assert all(required <= item.keys() for item in ledger["defects"])
    open_critical = [item for item in ledger["defects"]
                     if item["severity"] == "CRITICAL_FALSE_ACCEPTANCE"
                     and item["status"] != "VERIFIED_FIXED"]
    assert not open_critical
    assert ledger["release_gate"]["critical_false_acceptance_open"] == 0
    counts = burndown["counts"]
    assert counts["discovered_defects"] == len(ledger["defects"])
    assert counts["verified_fixed"] == sum(item["status"] == "VERIFIED_FIXED" for item in ledger["defects"])
    assert counts["deferred"] == sum(item["status"] == "DEFERRED" for item in ledger["defects"])
    assert counts["critical_false_acceptance_open"] == 0
