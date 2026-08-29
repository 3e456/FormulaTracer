from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from cpp_audit import (ControlFlowAssuranceStatus, EphemeralCheckout, ExternalCorpusManifest, evaluate_mathematical_ir,
                       inventory_source, run_finite_exhaustive,
                       run_generated_round_trip, run_metamorphic_assurance,
                       run_mutation_assurance)


ROOT = Path(__file__).resolve().parents[1]


def test_assurance_status_ids_are_machine_readable():
    assert ControlFlowAssuranceStatus.FINITE_LOOP_SEMANTICS_VERIFIED.value == "FINITE_LOOP_SEMANTICS_VERIFIED"
    assert ControlFlowAssuranceStatus.CONTROL_FLOW_UNRESOLVED.value == "CONTROL_FLOW_UNRESOLVED"


def test_independent_ir_evaluator_observes_zero_iteration_and_conditional_fold():
    expression = {"op": "FoldLeft", "bound_index": "i", "index_domain": {
        "lower": {"op": "Constant", "value": 0}, "upper_exclusive": {"op": "FreeVariable", "name": "n"},
        "step": {"op": "Constant", "value": 1}}, "initial_value": {"op": "Constant", "value": 7},
        "operation": "Add", "body": {"op": "IfThenElse",
            "condition": {"op": "IndexedValue", "name": "mask", "indices": [{"op": "BoundVariable", "name": "i"}]},
            "then": {"op": "IndexedValue", "name": "x", "indices": [{"op": "BoundVariable", "name": "i"}]},
            "else": {"op": "Constant", "value": 0}}}
    assert evaluate_mathematical_ir(expression, {"n": 0, "x": [], "mask": []}) == 7
    assert evaluate_mathematical_ir(expression, {"n": 3, "x": [2, 3, 5], "mask": [True, False, True]}) == 14


def test_finite_exhaustive_known_good_has_no_mismatch():
    result = run_finite_exhaustive()
    assert result["finite_exhaustive_comparisons"] >= 50
    assert result["semantic_mismatch_count"] == 0
    assert result["unresolved_comparisons"] == 0


def test_mutations_do_not_false_accept_and_localize_semantic_node():
    result, localization = run_mutation_assurance()
    assert result["false_acceptance_count"] == 0
    assert result["counts"]["SEMANTIC_MISMATCH_DETECTED"] + result["counts"]["CONTROL_FLOW_UNRESOLVED_FAIL_CLOSED"] >= 4
    assert localization["counts"]["CORRECT_SEMANTIC_NODE"] >= 3


def test_fixed_symbol_identity_preserves_real_associativity_without_accepting_branch_swap():
    from cpp_audit.python_audit import compare_symbolic
    def payload(expression):
        return {"outputs": [{"target": {"op": "FreeVariable", "name": "y"}, "expression": expression}]}
    variable = lambda name: {"op": "FreeVariable", "name": name}
    left = {"op": "Add", "args": [{"op": "Add", "args": [variable("a"), variable("b")]}, variable("c")]}
    right = {"op": "Add", "args": [variable("a"), {"op": "Add", "args": [variable("b"), variable("c")]}]}
    assert compare_symbolic(payload(left), payload(right))["match"]
    branch = {"op": "IfThenElse", "condition": variable("c"), "then": variable("a"), "else": variable("b")}
    swapped = {"op": "IfThenElse", "condition": variable("c"), "then": variable("b"), "else": variable("a")}
    assert not compare_symbolic(payload(branch), payload(swapped))["match"]


def test_metamorphic_and_cross_language_generation():
    metamorphic = run_metamorphic_assurance()
    assert metamorphic["false_rejection_count"] == 0
    assert metamorphic["correct_equivalence_count"] == metamorphic["metamorphic_case_count"]
    generated = run_generated_round_trip()
    assert generated["self_generated_valid_cases"] == 9
    assert generated["round_trip_success"] >= 3


def test_python_inventory_counts_nested_control_flow(tmp_path: Path):
    path = tmp_path / "nested.py"
    path.write_text("def f(x):\n total=0\n for i in range(x):\n  for j in range(x):\n   if i < j:\n    total += i\n return total\n", encoding="utf-8")
    record = inventory_source(path, root=tmp_path)
    assert record["constructs"]["loops"] == 2
    assert record["constructs"]["nested_loops"] == 1
    assert record["constructs"]["branches"] == 1


def test_control_flow_summary_schema_accepts_required_release_fields():
    payload = {"schema_version": "1.0", "status": "CONTROL_FLOW_ASSURANCE_COMPLETED",
               "critical_control_flow_false_acceptance_open": 0,
               "cleanup": {"temporary_external_checkout_directories_absent": True,
                           "external_source_archives_absent": True, "external_source_copied_into_repo": False},
               "corpora": {}, "metrics": {}, "evidence_levels": ["EXHAUSTIVELY_TESTED_ON_FINITE_DOMAIN"]}
    schema = json.loads((ROOT / "schemas" / "control-flow-assurance-summary.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_ephemeral_cleanup_removes_read_only_git_like_files(tmp_path: Path):
    checkout = EphemeralCheckout(ExternalCorpusManifest("unused", "local", "0", "test", ()))
    checkout.root = tmp_path / "checkout"; pack = checkout.root / ".git" / "objects" / "pack" / "sample.idx"
    pack.parent.mkdir(parents=True); pack.write_text("pack", encoding="utf-8"); pack.chmod(0o444)
    checkout._cleanup()
    assert checkout.cleanup_verified and not checkout.root.exists()
