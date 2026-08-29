from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import jsonschema

from formulatracer import FormulaTracer, build_end_to_end_claims


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "semantic_debugger"


def analyze(name: str, **options):
    path = EXAMPLES / name
    return FormulaTracer(path, project_root=path.parent).analyze(**options)


def test_a_wrong_operator_localizes_first_semantic_divergence_and_region():
    result = analyze("wrong_operator.py", ranges={"kg": (-10, 100)})
    debug = result.debug(); finding = debug.findings[0]
    assert debug.status == "SEMANTIC_DIVERGENCE_LOCALIZED"
    assert finding.type == "OPERATOR_MISMATCH"
    assert finding.expected["op"] == "Divide" and finding.actual["op"] == "Multiply"
    assert finding.source["begin_line"] == 6
    assert finding.affected_outputs[0].name == "converted"
    search = debug.search_counterexamples(max_depth=3)
    assert search.status == "FAILURE_REGION_LOCALIZED"
    assert search.failure_regions and search.counterexample_candidates
    assert all(item.evidence_level == "NUMERICALLY_CHECKED" for item in search.counterexample_candidates)
    search_schema = json.loads((ROOT / "schemas" / "counterexample-search-result.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(search_schema).validate(search.to_dict())


def test_b_wrong_constant_uses_cross_file_definition_correspondence():
    path = EXAMPLES / "cross_file" / "model.py"
    result = FormulaTracer(path, project_root=path.parent).analyze(ranges={"kg": (0, 100)})
    finding = result.debug().findings[0]
    assert finding.type == "CONSTANT_MISMATCH"
    assert Path(finding.source["file"]).name == "constants.py"
    assert finding.parameters["source_symbol"].endswith("constants.SCALE")


def test_c_axis_mismatch_preserves_positional_axis():
    result = analyze("wrong_operator.py", ranges={"kg": (0, 1)})
    output = result.outputs[0]
    output.residual["theory_expression"] = {"op": "Reduce", "reduction": "Add", "axes": 1,
                                             "input": {"op": "FreeVariable", "name": "x"}}
    output.formula = {"op": "Reduce", "reduction": "Add", "axes": 0,
                      "input": {"op": "FreeVariable", "name": "x"}}
    finding = result.debug().findings[0]
    assert finding.type == "AXIS_MISMATCH"
    assert finding.expected["axes"] == 1 and finding.actual["axes"] == 0


def test_d_approximation_family_invalidates_formal_bound():
    result = analyze("wrong_operator.py", ranges={"kg": (0, 1)})
    output = result.outputs[0]
    output.residual["theory_expression"] = {"op": "DiscreteDifference", "family_id": "central_difference_first_derivative"}
    output.formula = {"op": "DiscreteDifference", "family_id": "forward_difference_first_derivative"}
    finding = result.debug().findings[0]
    assert finding.type == "APPROXIMATION_FAMILY_MISMATCH"
    assert "CERTIFIED_BOUND_INVALIDATED" in finding.invalidated_claims


def test_e_error_contributors_and_first_division_amplification():
    result = analyze("wrong_operator.py", ranges={"kg": (1, 2)})
    output = result.outputs[0]
    output.formula = {"op": "Divide", "args": [{"op": "FreeVariable", "name": "kg"},
                                                  {"op": "Constant", "value": 0.01}]}
    output.end_to_end_claim["tolerance_status"] = "TOTAL_TOLERANCE_NOT_PROVEN"
    output.error_components = [{"component_id": "division", "source": "ROUNDING_ERROR",
        "semantic_cause_id": "division", "proof_status": "KERNEL_VERIFIED",
        "bound": {"symmetric_bound": {"op": "Constant", "value": 0.75}}}]
    debug = result.debug()
    finding = next(item for item in debug.findings if item.type == "ERROR_BOUND_VIOLATION")
    assert finding.error_contributions[0].magnitude == 0.75
    assert finding.amplification_points[0].amplification_factor == 100


def test_f_shared_multi_output_root_cause_is_not_duplicated():
    result = analyze("wrong_operator.py", ranges={"kg": (0, 1)})
    first = result.outputs[0]; second = deepcopy(first)
    second.output_id = "output:downstream"; second.name = "total"
    result.outputs.append(second); result.roots[0].outputs.append(second)
    result = build_end_to_end_claims(result)
    debug = result.debug()
    assert len([item for item in debug.root_causes if item.divergence_type == "OPERATOR_MISMATCH"]) == 1
    assert {item.name for item in debug.root_causes[0].downstream_affected_outputs} == {"converted", "total"}


def test_g_unresolved_ffi_stops_cross_language_localization():
    result = FormulaTracer(ROOT / "examples" / "cross_language_cpp_audit" / "analysis.py").analyze(
        ranges={"signal": {"lower": 0, "upper": 1, "shape": [8]}})
    finding = next(item for item in result.debug().findings if item.type == "FFI_BOUNDARY_UNRESOLVED")
    assert finding.confidence == "BLOCKED_BY_UNRESOLVED_SEMANTICS"


def test_negative_runtime_mismatch_is_not_proven_and_range_is_not_theory_mismatch():
    path = ROOT / "examples" / "end_to_end_audit" / "exact.py"
    result = FormulaTracer(path, project_root=path.parent).analyze(
        ranges={"x": (1, 2)}, observed_results={"y": 999999})
    range_finding = next(item for item in result.debug().findings if item.type == "RANGE_VIOLATION")
    assert range_finding.confidence == "POSSIBLE_ROOT_CAUSE"
    assert range_finding.type != "OPERATOR_MISMATCH"


def test_verified_case_has_no_finding_but_retains_e2e_status():
    path = ROOT / "examples" / "end_to_end_audit" / "exact.py"
    debug = FormulaTracer(path, project_root=path.parent).analyze(ranges={"x": (1, 2)}).debug()
    assert debug.status == "NO_SEMANTIC_DIVERGENCE_FOUND"
    assert not debug.findings
    assert debug.end_to_end_status == "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"


def test_json_schema_and_latex_report(tmp_path: Path):
    debug = analyze("wrong_operator.py", ranges={"kg": (0, 1)}).debug()
    payload = debug.to_dict()
    schema = json.loads((ROOT / "schemas" / "audit-debug-result.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert {"status", "findings", "first_divergences", "minimal_divergent_subgraphs", "root_causes",
            "affected_outputs", "debug_traces", "invalidated_claims"} <= payload.keys()
    latex = debug.to_latex()
    assert "First" not in latex or "Finding" in latex
    assert "Expected" in latex and "Actual" in latex and "Affected outputs" in latex
    assert "[U+" not in latex and "wrong\\_operator.py" in latex
    assert "exact.compute" not in latex and "wrong_operator.compute" not in latex
    debug.write_json(tmp_path / "debug.json"); debug.write_latex(tmp_path / "debug.tex")
