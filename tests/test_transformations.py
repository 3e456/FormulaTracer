from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import jsonschema
from referencing import Registry, Resource

from cpp_audit import AuditMode, apply_transformation_set, execute_audit, render_latex_certificate


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "registry" / "transformations" / "rules"
SCIENTIFIC = ROOT / "registry" / "transformations" / "sets" / "scientific_default.yaml"


def variable(name: str): return {"op": "FreeVariable", "name": name}
def constant(value): return {"op": "Constant", "value": value}
def ir(expression, target="y"):
    return {"schema_version": "0.1", "status": "EXPRESSION_EXTRACTED", "outputs": [{"target": variable(target), "expression": expression}], "expression_id": f"id-{target}"}


def set_(exact=(), approximation=(), hard=None):
    return {"id": "test", "version": "1", "exact_rules": list(exact), "approximation_rules": list(approximation),
            "forbidden_rules": [], "hard_constraints": hard or {}, "objectives": [],
            "selection_policy": {"type": "lexicographic"}, "provenance": {"source": "test"}}


def test_exact_transformation_application():
    theory = ir({"op": "Add", "args": [variable("x"), constant(0)]})
    implementation = ir(variable("value"))
    result = apply_transformation_set(theory, implementation, set_(exact=["alpha_rename", "neutral_element_elimination"]), rules_root=RULES)
    assert result.status == "TRANSFORMATION_APPLIED"
    assert result.comparison_relation == "EXACT_EQUAL"
    assert all(item["rule_kind"] == "EXACT" for item in result.applied_rules)
    assert all(item["authorization_status"] == "RULE_ALLOWED" for item in result.applied_rules)
    neutral = next(item for item in result.applied_rules if item["rule_id"] == "neutral_element_elimination")
    assert neutral["reference"]["theorem_reference"].endswith("add_neutral_sound")


def test_multi_step_exact_trace():
    fold = {"op": "TransformReduce", "bound_index": "j", "index_domain": {"lower": constant(0), "upper_exclusive": variable("n")},
            "initial_value": constant(0), "transform": variable("x"), "reduction": "Add", "reduction_order": "left_to_right"}
    finite = {"op": "FiniteSum", "bound_index": "_i0", "index_domain": {"lower": constant(0), "upper_exclusive": variable("m")},
              "body": variable("value"), "reduction_order": "left_to_right"}
    result = apply_transformation_set(ir(fold), ir(finite), set_(exact=["alpha_rename", "finite_sum_normalization"]), rules_root=RULES)
    assert [item["rule_id"] for item in result.applied_rules] == ["alpha_rename", "finite_sum_normalization"]
    assert result.transformation_trace.source_expression_id != result.transformation_trace.target_expression_id
    assert result.applied_rules[0]["target_expression_id"] == result.applied_rules[1]["source_expression_id"]


def test_forbidden_rule_rejected():
    result = apply_transformation_set(ir({"op": "Derivative", "order": 1, "variable": "x"}), ir(variable("z")),
        set_(approximation=["forward_difference_first_derivative"]), rules_root=RULES,
        requested_rule_ids=["central_difference_first_derivative"], context={"finite_domain": True})
    assert result.status == "TRANSFORMATION_NOT_ALLOWED"
    assert result.rejected_rules[0]["status"] == "RULE_NOT_ALLOWED"


def test_hard_constraint_precedes_selection():
    result = apply_transformation_set(ir({"op": "Derivative", "order": 1, "variable": "x"}), ir(variable("z")),
        set_(approximation=["central_difference_first_derivative"], hard={"finite_domain_required": True}),
        rules_root=RULES, requested_rule_ids=["central_difference_first_derivative"])
    assert result.status == "TRANSFORMATION_CONSTRAINT_FAILED"
    assert "finite_domain_required" in result.rejected_rules[0]["failures"]


def test_error_hard_constraint_cannot_be_overridden_by_objective():
    result = apply_transformation_set(ir({"op": "Derivative", "order": 1, "variable": "x"}), ir(variable("z")),
        set_(approximation=["central_difference_first_derivative"], hard={"maximum_error": 1e-9}),
        rules_root=RULES, context={"finite_domain": True}, selection_profile="minimum_cost")
    assert result.status == "TRANSFORMATION_CONSTRAINT_FAILED"
    assert "maximum_error" in result.rejected_rules[0]["failures"]
    assert result.selection["selected"] is None


def test_exact_under_assumptions_exposes_remaining_and_discharged():
    theory = ir({"op": "Divide", "args": [variable("x"), variable("d")]})
    implementation = ir({"op": "Multiply", "args": [variable("x"), {"op": "Divide", "args": [constant(1), variable("d")]}]})
    transformation_set = set_(exact=["division_rewrite_nonzero"])
    unresolved = apply_transformation_set(theory, implementation, transformation_set, rules_root=RULES)
    assert unresolved.comparison_relation == "EQUIVALENT_UNDER_ASSUMPTIONS"
    assert unresolved.status == "TRANSFORMATION_OBLIGATION_REMAINING"
    assert unresolved.remaining_obligations[0]["statement"] == "denominator != 0"
    resolved = apply_transformation_set(theory, implementation, transformation_set, rules_root=RULES,
                                        assumptions=["denominator != 0"])
    assert resolved.status == "EXACT_TRANSFORMATION_VERIFIED_UNDER_ASSUMPTIONS"
    assert not resolved.remaining_obligations


def central_target():
    return {"op": "Divide", "args": [
        {"op": "Subtract", "args": [
            {"op": "FunctionCall", "name": "f", "args": [{"op": "Add", "args": [variable("x"), variable("h")]}]},
            {"op": "FunctionCall", "name": "f", "args": [{"op": "Subtract", "args": [variable("x"), variable("h")]}]}]},
        {"op": "Multiply", "args": [constant(2), variable("h")]}]}


def test_approximation_recognized_unproven_and_residual_created():
    theory = ir({"op": "Derivative", "order": 1, "variable": "x", "expression": {"op": "FunctionCall", "name": "f", "args": [variable("x")]}})
    result = apply_transformation_set(theory, ir(central_target()),
        set_(approximation=["central_difference_first_derivative"]), rules_root=RULES,
        context={"finite_domain": True, "spacing": "h", "spacing_resolved": True, "stencil_region": "interior",
                 "required_observables": ["frequency_response"]}, selection_profile="minimum_error")
    assert result.comparison_relation == "DISCRETIZATION_OF"
    assert result.status == "APPROXIMATION_ERROR_NOT_YET_PROVEN"
    assert any(item["kind"] == "APPROXIMATION_ERROR_BOUND" for item in result.remaining_obligations)
    assert result.residual_candidate["status"] == "BOUND_NOT_YET_EVALUATED"
    assert result.residual_candidate["numeric_samples_used_as_proof"] is False
    assert result.applied_rules[0]["reference"]["library_contract"]["qualified_callable"] == "numpy.gradient"


def test_application_candidate_selection_profiles():
    theory = ir({"op": "Derivative", "order": 1, "variable": "x"})
    transformation_set = set_(approximation=["forward_difference_first_derivative", "central_difference_first_derivative"])
    minimum_cost = apply_transformation_set(theory, ir(variable("z")), transformation_set, rules_root=RULES,
                                             context={"finite_domain": True, "spacing": "h", "stencil_region": "interior"}, selection_profile="minimum_cost")
    minimum_error = apply_transformation_set(theory, ir(variable("z")), transformation_set, rules_root=RULES,
                                              context={"finite_domain": True, "spacing": "h", "stencil_region": "interior"}, selection_profile="minimum_error")
    assert minimum_cost.selection["selected"]["rule_id"] == "forward_difference_first_derivative"
    assert minimum_error.selection["selected"]["rule_id"] == "central_difference_first_derivative"


def test_different_stencil_is_not_accepted_as_central_difference():
    theory = ir({"op": "Derivative", "order": 1, "variable": "x"})
    forward = {"op": "Divide", "args": [{"op": "Subtract", "args": [
        {"op": "FunctionCall", "name": "f", "args": [variable("x")]},
        {"op": "FunctionCall", "name": "f", "args": [{"op": "Subtract", "args": [variable("x"), variable("h")]}]}]}, variable("h")]}
    result = apply_transformation_set(theory, ir(forward), set_(approximation=["central_difference_first_derivative"]),
                                      rules_root=RULES, context={"finite_domain": True, "spacing": "h", "stencil_region": "interior"})
    assert result.comparison_relation == "INCONSISTENT_WITH"
    assert not result.comparison["match"]


def test_certificate_exact_transformation_e2e(tmp_path: Path):
    path = ROOT / "tests" / "fixtures" / "synthetic_identity_transformation.py"
    certificate = execute_audit(path, inputs={"value": 4.25}, function="preserve_value", output="normalized_value", mode=AuditMode.STRICT,
        transformation_set=SCIENTIFIC, requested_transformations=["neutral_element_elimination"], verify_lean=False)
    assert certificate.status == "PARTIALLY_KERNEL_VERIFIED"
    assert certificate.comparison_relation == "EXACT_EQUAL"
    assert certificate.transformation_trace["applications"][0]["rule_id"] == "neutral_element_elimination"
    assert certificate.applied_rules and not certificate.remaining_obligations
    latex = render_latex_certificate(certificate)
    assert "Transformation Trace" in latex and "neutral\\_element\\_elimination" in latex
    schema_root = ROOT / "schemas"
    registry = Registry()
    for name in ("constant-dependency-graph.schema.json", "numeric-type-semantics.schema.json",
                 "ieee754-semantics.schema.json", "parallel-semantics.schema.json",
                 "transformation-application.schema.json"):
        child = json.loads((schema_root / name).read_text(encoding="utf-8"))
        registry = registry.with_resource(child["$id"], Resource.from_contents(child))
    schema = json.loads((schema_root / "audit-certificate.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, registry=registry).validate(certificate.to_dict())
    application = certificate.transformation_trace["applications"][0]
    assert certificate.transformation_trace["source_expression_id"] == application["source_expression_id"]
    assert certificate.transformation_trace["target_expression_id"] == application["target_expression_id"]


def test_exact_application_lean_kernel_verification(tmp_path: Path):
    path = ROOT / "tests" / "fixtures" / "synthetic_identity_transformation.py"
    certificate = execute_audit(path, inputs={"value": 4.25}, function="preserve_value", output="normalized_value",
        transformation_set=SCIENTIFIC, requested_transformations=["neutral_element_elimination"],
        verify_lean=True, lean_file=tmp_path / "transformation.lean")
    assert certificate.lean["kernel_verified"]
    assert certificate.status == "LEAN_KERNEL_VERIFIED"
    assert "transformed_expression_matches_implementation" in certificate.lean["theorem_names"]
    assert "CppAudit.Semantics.Transformation.add_neutral_sound" in certificate.lean["theorem_names"]
