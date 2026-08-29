from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import jsonschema
import yaml

from cpp_audit import (AuditMode, apply_transformation_set, classify_library_call,
                       execute_audit, load_approximation_families,
                       load_library_family_mappings, render_latex_certificate)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry" / "approximation_families.yaml"
RULES = ROOT / "registry" / "transformations" / "rules"


def variable(name: str): return {"op": "FreeVariable", "name": name}
def constant(value): return {"op": "Constant", "value": value}
def ir(expression, target="y"):
    return {"schema_version": "0.1", "status": "EXPRESSION_EXTRACTED", "outputs": [{"target": variable(target), "expression": expression}], "expression_id": f"id-{target}"}
def set_(*rules):
    return {"id": "phase6", "version": "1", "exact_rules": [], "approximation_rules": list(rules),
            "forbidden_rules": [], "hard_constraints": {}, "objectives": [],
            "selection_policy": {"type": "lexicographic"}, "provenance": {"source": "test"}}


def derivative(order=1):
    return {"op": "Derivative", "order": order, "variable": "x",
            "expression": {"op": "FunctionCall", "name": "f", "args": [variable("x")]}}


def central():
    return {"op": "Divide", "args": [{"op": "Subtract", "args": [
        {"op": "FunctionCall", "name": "f", "args": [{"op": "Add", "args": [variable("x"), variable("h")]}]},
        {"op": "FunctionCall", "name": "f", "args": [{"op": "Subtract", "args": [variable("x"), variable("h")]}]}]},
        {"op": "Multiply", "args": [constant(2), variable("h")]}]}


def fd_context(): return {"spacing": "h", "spacing_resolved": True, "stencil_region": "interior", "axis": 1}


def test_family_registry_schema_and_minimum_families():
    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / "approximation-family.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    families = load_approximation_families(REGISTRY)
    expected = {"forward_difference_first_derivative", "backward_difference_first_derivative",
                "central_difference_first_derivative", "central_difference_second_derivative",
                "left_rectangle_rule", "right_rectangle_rule", "midpoint_rule", "trapezoidal_rule",
                "simpson_rule", "nearest_neighbor_interpolation", "linear_interpolation",
                "multilinear_interpolation"}
    assert expected <= families.keys()
    assert all(item.proof_status == "CONVERGENCE_PROOF_NOT_YET_ESTABLISHED" for item in families.values())
    assert families["central_difference_first_derivative"].convergence_order == 2
    assert families["simpson_rule"].convergence_order == 4


def test_public_library_mappings_preserve_exact_semantics_and_dimensions():
    mappings = load_library_family_mappings(REGISTRY)
    assert mappings["numpy.diff"].exact_semantic_operator == "DiscreteDifference"
    diff = classify_library_call("numpy.diff", REGISTRY)
    assert not diff["derivative_is_exact_semantics"]
    assert diff["public_reference_semantics"]["scaling"] == "absent"
    assert mappings["numpy.gradient"].public_reference_semantics["boundary"] == "one_sided"
    assert mappings["xarray.DataArray.diff"].public_reference_semantics["dimension"] == "named"
    assert mappings["numpy.gradient"].public_reference_semantics["axis"] == "positional"
    public = json.loads((ROOT / "registry" / "generated" / "public_api" /
                         "public_api_contract_bindings.json").read_text(encoding="utf-8"))
    published = {item["qualified_name"] for item in public["bindings"]}
    assert set(mappings) <= published


def test_extrapolation_is_not_interpolation():
    result = classify_library_call("xarray.DataArray.interp", REGISTRY, domain_status="EXTRAPOLATION")
    assert result["status"] == "EXTRAPOLATION_RECOGNIZED"
    assert result["exact_semantic_operator"] == "Extrapolation"
    assert result["approximation_family_ids"] == []


def test_derivative_central_difference_e2e_records_unproven_convergence():
    result = apply_transformation_set(ir(derivative()), ir(central()), set_("central_difference_first_derivative"),
                                      rules_root=RULES, context=fd_context())
    assert result.comparison_relation == "DISCRETIZATION_OF"
    assert result.status == "APPROXIMATION_ERROR_NOT_YET_PROVEN"
    family = result.applied_rules[0]["reference"]["approximation_family"]
    assert family["convergence_order"] == 2
    assert result.applied_rules[0]["parameters"]["axis"] == 1
    assert {item["code"] for item in result.diagnostics} >= {"FINITE_DIFFERENCE_RECOGNIZED", "CONVERGENCE_ORDER_RECORDED"}
    assert result.residual_candidate["numeric_samples_used_as_proof"] is False


def test_trapezoidal_integral_e2e():
    domain = {"lower": constant(0), "upper": constant(1)}
    theory = ir({"op": "Integral", "variable": "x", "domain": domain,
                 "expression": {"op": "FunctionCall", "name": "f", "args": [variable("x")]}})
    quadrature = {"op": "Quadrature", "method": "trapezoidal", "integration_domain": domain,
                  "partition": variable("partition"), "step_size": variable("h"),
                  "sample_nodes": ["left", "right"], "weights": [constant(0.5), constant(0.5)], "composite": True}
    result = apply_transformation_set(theory, ir(quadrature), set_("trapezoidal_rule"), rules_root=RULES,
                                      context={"partition_resolved": True, "h": "h", "partition": "partition", "axis": 0})
    assert result.comparison_relation == "APPROXIMATION_OF"
    assert result.status == "APPROXIMATION_ERROR_NOT_YET_PROVEN"
    assert result.applied_rules[0]["reference"]["approximation_family"]["family_id"] == "trapezoidal_rule"
    assert "QUADRATURE_RECOGNIZED" in {item["code"] for item in result.diagnostics}


def test_named_dimension_linear_interpolation_e2e():
    theory = ir({"op": "Interpolation", "expression": variable("temperature"),
                 "query_point": variable("x"), "dimension": "time"})
    implementation = {"op": "Interpolation", "method": "linear",
        "support_points": [variable("x0"), variable("x1")], "query_point": variable("x"),
        "weights": [{"op": "Subtract", "args": [constant(1), variable("t")]}, variable("t")],
        "axis": variable("axis"), "domain_status": "INTERPOLATION"}
    result = apply_transformation_set(theory, ir(implementation), set_("linear_interpolation"), rules_root=RULES,
        context={"interpolation_domain_status": "INTERPOLATION", "dimension": "time", "axis": None})
    assert result.comparison_relation == "APPROXIMATION_OF"
    assert result.status == "APPROXIMATION_ERROR_NOT_YET_PROVEN"
    assert result.applied_rules[0]["parameters"]["dimension"] == "time"
    assert result.applied_rules[0]["parameters"]["axis"] is None
    assert "INTERPOLATION_RECOGNIZED" in {item["code"] for item in result.diagnostics}


def test_partial_expression_unique_and_explicit_path():
    theory = ir({"op": "Add", "args": [variable("a"), derivative()]})
    implementation = ir({"op": "Add", "args": [variable("a"), central()]})
    result = apply_transformation_set(theory, implementation, set_("central_difference_first_derivative"),
                                      rules_root=RULES, context={**fd_context(), "target_path": ["args", 1]})
    assert result.comparison_relation == "DISCRETIZATION_OF"
    assert result.applied_rules[0]["reference"]["target_path"] == ["args", 1]


def test_ambiguous_partial_expression_requires_target_path():
    theory = ir({"op": "Add", "args": [derivative(), derivative()]})
    result = apply_transformation_set(theory, ir(variable("z")), set_("central_difference_first_derivative"),
                                      rules_root=RULES, context=fd_context())
    assert result.status == "TRANSFORMATION_CONSTRAINT_FAILED"
    assert "AMBIGUOUS_TRANSFORMATION_MATCH" in result.rejected_rules[0]["failures"]


def test_spacing_and_boundary_are_hard_constraints():
    missing_spacing = apply_transformation_set(ir(derivative()), ir(central()), set_("central_difference_first_derivative"),
                                               rules_root=RULES, context={"stencil_region": "interior"})
    assert "spacing_resolved" in missing_spacing.rejected_rules[0]["failures"]
    assert "SPACING_UNRESOLVED" in {item["code"] for item in missing_spacing.diagnostics}
    missing_boundary = apply_transformation_set(ir(derivative()), ir(central()), set_("central_difference_first_derivative"),
                                                rules_root=RULES, context={"spacing": "h"})
    assert "boundary_stencil" in missing_boundary.rejected_rules[0]["failures"]
    assert "BOUNDARY_STENCIL_UNRESOLVED" in {item["code"] for item in missing_boundary.diagnostics}


def test_derivative_order_and_simpson_partition_false_acceptance():
    wrong_order = apply_transformation_set(ir(derivative(2)), ir(central()), set_("central_difference_first_derivative"),
                                           rules_root=RULES, context=fd_context())
    assert "SOURCE_PATTERN_MISMATCH" in wrong_order.rejected_rules[0]["failures"]
    domain = {"lower": constant(0), "upper": constant(1)}
    theory = ir({"op": "Integral", "domain": domain})
    odd = apply_transformation_set(theory, ir(variable("z")), set_("simpson_rule"), rules_root=RULES,
                                   context={"partition_resolved": True, "even_interval_count": False})
    assert "simpson_even_intervals" in odd.rejected_rules[0]["failures"]


def test_fixed_selection_metadata_is_not_a_proof_bound():
    family = load_approximation_families(REGISTRY)["central_difference_first_derivative"]
    assert family.selection_error_estimate == 0.000001
    assert family.proof_status == "CONVERGENCE_PROOF_NOT_YET_ESTABLISHED"


def test_phase6_latex_certificate_identifies_family_and_proof_boundary(tmp_path: Path):
    base = execute_audit(ROOT / "tests" / "fixtures" / "synthetic_identity_transformation.py",
                         inputs={"value": 4.25}, function="preserve_value",
                         output="normalized_value", mode=AuditMode.STRICT, verify_lean=False)
    transformation = apply_transformation_set(ir(derivative()), ir(central()),
        set_("central_difference_first_derivative"), rules_root=RULES, context=fd_context())
    payload = transformation.to_dict()
    base.theory = {"output": "y", "expression": "f'(x)", "ir": ir(derivative())}
    base.implementation = ir(central())
    base.transformed_theory = payload["transformed_theory"]
    base.transformation_trace = payload["transformation_trace"]
    base.applied_rules = payload["applied_rules"]
    base.remaining_obligations = payload["remaining_obligations"]
    base.comparison_relation = payload["comparison_relation"]
    base.comparison = payload["comparison"]
    latex = render_latex_certificate(base)
    assert "Numerical Approximation" in latex
    assert "central\\_difference\\_first\\_derivative" in latex
    assert "Convergence metadata: order 2" in latex
    assert "Error verification: \\textbf{NOT YET PROVEN}" in latex
    if shutil.which("pdflatex"):
        tex = tmp_path / "phase6-certificate.tex"
        tex.write_text(latex, encoding="utf-8")
        proc = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
                              cwd=tmp_path, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stdout
        assert tex.with_suffix(".pdf").is_file()
