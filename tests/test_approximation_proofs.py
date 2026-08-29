from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import jsonschema
import pytest
import yaml

from cpp_audit import (AuditError, AuditMode, apply_transformation_set,
                       approximation_proof_coverage,
                       execute_audit,
                       load_approximation_proof_registry,
                       render_latex_certificate, resolve_approximation_proof)


ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "registry" / "approximation_proofs.yaml"
RULES = ROOT / "registry" / "transformations" / "rules"


def variable(name): return {"op": "FreeVariable", "name": name}
def constant(value): return {"op": "Constant", "value": value}
def ir(expression): return {"schema_version": "0.1", "outputs": [{"target": variable("y"), "expression": expression}], "expression_id": "id"}
def set_(rule): return {"id": "proof-e2e", "version": "1", "exact_rules": [], "approximation_rules": [rule], "forbidden_rules": [], "hard_constraints": {}, "objectives": [], "selection_policy": {"type": "lexicographic"}, "provenance": {}}


def derivative():
    return {"op": "Derivative", "order": 1, "variable": "x",
            "expression": {"op": "FunctionCall", "name": "f", "args": [variable("x")]}}


def central():
    return {"op": "Divide", "args": [{"op": "Subtract", "args": [
        {"op": "FunctionCall", "name": "f", "args": [{"op": "Add", "args": [variable("x"), variable("h")]}]},
        {"op": "FunctionCall", "name": "f", "args": [{"op": "Subtract", "args": [variable("x"), variable("h")]}]}]},
        {"op": "Multiply", "args": [constant(2), variable("h")]}]}


def test_proof_registry_schema_and_all_twelve_family_coverage():
    payload = yaml.safe_load(PROOFS.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / "approximation-proof.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    registry = load_approximation_proof_registry(PROOFS)
    coverage = approximation_proof_coverage(ROOT)
    assert len(registry) == len(coverage) == 12
    assert all(item["discrete_semantics"] == "DISCRETE_SEMANTICS_VERIFIED" for item in coverage)
    assert next(item for item in coverage if item["family_id"] == "central_difference_first_derivative")["error_bound"] == "ERROR_BOUND_VERIFIED_UNDER_ASSUMPTIONS"
    assert next(item for item in coverage if item["family_id"] == "multilinear_interpolation")["error_bound"] == "REFERENCE_ONLY"
    persisted = json.loads((ROOT / "registry" / "approximation_proof_coverage.json").read_text(encoding="utf-8"))
    assert persisted["families"] == coverage


def test_central_difference_transformation_to_kernel_error_proof_e2e():
    transformation = apply_transformation_set(ir(derivative()), ir(central()),
        set_("central_difference_first_derivative"), rules_root=RULES,
        context={"spacing": "h", "h": 0.01, "stencil_region": "interior"})
    assert transformation.comparison_relation == "DISCRETIZATION_OF"
    proof = resolve_approximation_proof("central_difference_first_derivative", repository_root=ROOT,
        context={"h": 0.01, "domain_condition_proven": True,
                 "provided_assumptions": ["third_derivative_bound", "symmetric_third_order_remainders"]},
        kernel_checked=True)
    assert proof.error_bound.bound == "(M/6)*abs(h)^2"
    assert proof.error_bound.exponent == 2
    assert proof.proof_status == "KERNEL_VERIFIED_ERROR_BOUND_UNDER_ASSUMPTIONS"
    assert proof.convergence.status == "KERNEL_VERIFIED_CONVERGENCE_UNDER_ASSUMPTIONS"
    assert proof.order_cross_check == "REFERENCE_ORDER_CONFIRMED_BY_FORMAL_PROOF"
    assert not proof.remaining_obligations


def test_trapezoidal_transformation_to_kernel_error_proof_e2e():
    domain = {"lower": constant(0), "upper": constant(1)}
    theory = ir({"op": "Integral", "variable": "x", "domain": domain})
    implementation = ir({"op": "Quadrature", "method": "trapezoidal", "integration_domain": domain,
        "partition": variable("partition"), "step_size": variable("h"), "sample_nodes": ["left", "right"],
        "weights": [constant(0.5), constant(0.5)], "composite": True})
    transformation = apply_transformation_set(theory, implementation, set_("trapezoidal_rule"), rules_root=RULES,
        context={"partition_resolved": True})
    assert transformation.comparison_relation == "APPROXIMATION_OF"
    proof = resolve_approximation_proof("trapezoidal_rule", repository_root=ROOT,
        context={"h": 0.1, "partition_resolved": True,
                 "provided_assumptions": ["second_derivative_bound", "local_panel_error"]}, kernel_checked=True)
    assert proof.error_bound.bound == "((b-a)*M/12)*h^2"
    assert proof.proof_status == "KERNEL_VERIFIED_ERROR_BOUND_UNDER_ASSUMPTIONS"
    assert proof.convergence.status == "KERNEL_VERIFIED_CONVERGENCE_UNDER_ASSUMPTIONS"


def test_unresolved_smoothness_and_zero_step_never_become_unconditional():
    proof = resolve_approximation_proof("forward_difference_first_derivative", repository_root=ROOT,
        context={"h": 0, "numeric_samples": [{"h": 0, "error": 0}]}, kernel_checked=True)
    assert proof.proof_status == "KERNEL_VERIFIED_ERROR_BOUND_UNDER_ASSUMPTIONS"
    assert any(item["assumption_id"] == "positive_step" for item in proof.remaining_obligations)
    assert any(item["status"] == "SMOOTHNESS_BOUND_UNRESOLVED" for item in proof.remaining_obligations)
    assert proof.error_bound.error_kind == "APPROXIMATION_ERROR"


def test_reference_or_skipped_kernel_is_not_reported_verified():
    not_run = resolve_approximation_proof("central_difference_first_derivative", repository_root=ROOT, kernel_checked=False)
    assert not_run.proof_status == "REFERENCE_THEOREM_ONLY"
    assert not_run.convergence.status == "CONVERGENCE_NOT_PROVEN"
    simpson = resolve_approximation_proof("simpson_rule", repository_root=ROOT,
        context={"even_interval_count": False}, kernel_checked=True)
    assert simpson.proof_status == "REFERENCE_THEOREM_ONLY"
    assert simpson.error_bound.bound is None


def test_linear_proof_cannot_be_used_for_nearest_or_extrapolation(tmp_path: Path):
    payload = yaml.safe_load(PROOFS.read_text(encoding="utf-8"))
    nearest = next(item for item in payload["proofs"] if item["family_id"] == "nearest_neighbor_interpolation")
    nearest["lean_theorem_name"] = "CppAudit.Approximation.linear_interpolation_error_bound_from_remainder"
    bad = tmp_path / "bad.yaml"; bad.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(AuditError, match="FAMILY_PROOF_THEOREM_MISMATCH"):
        load_approximation_proof_registry(bad)
    with pytest.raises(AuditError, match="INTERPOLATION_PROOF_APPLIED_TO_EXTRAPOLATION"):
        resolve_approximation_proof("linear_interpolation", repository_root=ROOT,
                                    context={"interpolation_domain_status": "EXTRAPOLATION"}, kernel_checked=True)


def test_selection_estimate_cannot_become_proof_source(tmp_path: Path):
    payload = yaml.safe_load(PROOFS.read_text(encoding="utf-8"))
    payload["proofs"][0]["provenance"]["proof_uses_selection_metadata"] = True
    bad = tmp_path / "bad.yaml"; bad.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(AuditError, match="SELECTION_METADATA_USED_AS_PROOF"):
        load_approximation_proof_registry(bad)


@pytest.mark.parametrize("value", ["(M/5)*abs(h)^2", "(M/6)*abs(h)^3"])
def test_wrong_formal_coefficient_or_exponent_is_rejected(tmp_path: Path, value: str):
    payload = yaml.safe_load(PROOFS.read_text(encoding="utf-8"))
    central = next(item for item in payload["proofs"] if item["family_id"] == "central_difference_first_derivative")
    central["error_bound"] = value
    bad = tmp_path / "bad-bound.yaml"; bad.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(AuditError, match="FORMAL_BOUND_REGISTRY_MISMATCH"):
        load_approximation_proof_registry(bad)


def test_wrong_formal_order_fails_closed(tmp_path: Path):
    # Resolve from a temporary repository-shaped registry to exercise the
    # reference/formal metadata cross-check rather than editing production data.
    root = tmp_path
    (root / "registry").mkdir()
    proof_payload = yaml.safe_load(PROOFS.read_text(encoding="utf-8"))
    next(item for item in proof_payload["proofs"] if item["family_id"] == "central_difference_first_derivative")["convergence_order"] = 1
    (root / "registry" / "approximation_proofs.yaml").write_text(yaml.safe_dump(proof_payload), encoding="utf-8")
    (root / "registry" / "approximation_families.yaml").write_text(
        (ROOT / "registry" / "approximation_families.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(AuditError, match="REFERENCE_FORMAL_ORDER_MISMATCH"):
        resolve_approximation_proof("central_difference_first_derivative", repository_root=root, kernel_checked=True)


def test_phase6_fixed_selection_estimate_is_absent_from_formal_bound():
    proof = resolve_approximation_proof("central_difference_first_derivative", repository_root=ROOT, kernel_checked=True)
    serialized = json.dumps(proof.to_dict())
    assert "selection_error_estimate" not in serialized
    assert "0.000001" not in serialized


def test_phase7_latex_certificate_contains_formal_bound_and_obligations(tmp_path: Path):
    certificate = execute_audit(ROOT / "tests" / "fixtures" / "synthetic_identity_transformation.py",
        inputs={"value": 4.25}, function="preserve_value", output="normalized_value",
        mode=AuditMode.STRICT, verify_lean=False)
    proof = resolve_approximation_proof("central_difference_first_derivative", repository_root=ROOT,
        context={"h": 0.01}, kernel_checked=True)
    certificate.approximation_proofs = [proof.to_dict()]
    latex = render_latex_certificate(certificate)
    assert "Formal Approximation Proofs" in latex
    assert "central\\_difference\\_first\\_derivative" in latex
    assert "KERNEL\\_VERIFIED\\_ERROR\\_BOUND\\_UNDER\\_ASSUMPTIONS" in latex
    assert "M/6" in latex
    assert "Remaining proof obligations" in latex
    if shutil.which("pdflatex"):
        tex = tmp_path / "phase7.tex"; tex.write_text(latex, encoding="utf-8")
        proc = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
                              cwd=tmp_path, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stdout
        assert tex.with_suffix(".pdf").is_file()
