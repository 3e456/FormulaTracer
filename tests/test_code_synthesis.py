from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from formulatracer import (FormulaTracer, ImplementationConstraints, TheorySpecification,
                           propose_repair, synthesize, synthesize_cross_language,
                           verify_repair, verify_round_trip)


ROOT = Path(__file__).resolve().parents[1]


def arithmetic_theory():
    return TheorySpecification("y", {"op": "Add", "args": [
        {"op": "Multiply", "args": [{"op": "Constant", "value": 3},
                                      {"op": "FreeVariable", "name": "x"}]},
        {"op": "Constant", "value": 2}]}, ["x"])


@pytest.mark.parametrize("language", ["python", "rust", "cpp"])
def test_theory_to_language_round_trip_uses_real_frontend(language):
    result = synthesize(arithmetic_theory(), language=language)
    assert result.status == "ROUND_TRIP_VERIFIED"
    assert result.round_trip.comparison["match"]
    assert result.pipeline_trace[-1]["stage"] == "OBSERVED_MATHEMATICAL_IR"


def test_cross_language_generation_has_same_canonical_ir():
    result = synthesize_cross_language(arithmetic_theory())
    assert result.canonical_ir_status == "SAME_CANONICAL_MATHEMATICAL_IR"
    assert set(result.results) == {"python", "rust", "cpp"}


def test_broken_generator_is_localized_at_reextraction():
    result = synthesize(arithmetic_theory(), language="python", verify=False)
    result.generated.source = result.generated.source.replace(" * ", " / ")
    round_trip = verify_round_trip(result)
    assert round_trip.status == "ROUND_TRIP_DIVERGENCE_LOCALIZED"
    assert round_trip.first_synthesis_divergence.type == "FRONTEND_REEXTRACTION_DIVERGENCE"


def test_unauthorized_approximation_is_rejected():
    theory = TheorySpecification("d", {"op": "DiscreteDifference",
        "family_id": "central_difference_first_derivative", "function": "f", "variable": "x", "spacing": "h"},
        ["x", "h"])
    with pytest.raises(ValueError, match="APPROXIMATION_NOT_AUTHORIZED"):
        synthesize(theory, language="python")
    allowed = ImplementationConstraints("python", allowed_approximations=["central_difference_first_derivative"])
    assert synthesize(theory, language="python", constraints=allowed, verify=False).status == "SOURCE_GENERATED"


def test_map_filter_and_reduction_have_canonical_source_without_false_round_trip_claim():
    domain = {"lower": {"op": "Constant", "value": 0}, "upper_exclusive": {"op": "FreeVariable", "name": "n"}}
    mapped = TheorySpecification("y", {"op": "Map", "bound_index": "i", "index_domain": domain,
        "body": {"op": "Multiply", "args": [{"op": "FreeVariable", "name": "i"}, {"op": "Constant", "value": 2}]}}, ["n"])
    source = synthesize(mapped, language="python", verify=False).generated.source
    assert "for i in range" in source
    reduction = TheorySpecification("y", {"op": "FiniteSum", "bound_index": "i", "index_domain": domain,
        "body": {"op": "FreeVariable", "name": "i"}}, ["n"])
    result = synthesize(reduction, language="python")
    assert "result +=" in result.generated.source
    assert result.round_trip.status != "ROUND_TRIP_VERIFIED"


def test_local_repair_is_candidate_until_full_reanalysis(tmp_path: Path):
    bad = tmp_path / "bad.py"
    bad.write_text("import cpp_audit as audit\n@audit.theory(output='y', expression='y = x + 1000')\ndef compute(x):\n    y = x + 100\n    return y\n", encoding="utf-8")
    debug = FormulaTracer(bad, project_root=tmp_path).analyze(ranges={"x": (0, 1)}).debug()
    candidate = propose_repair(debug.findings[0])
    assert candidate.status == "CANDIDATE_ONLY" and candidate.replacement_text == "1000"
    repaired = tmp_path / "repaired.py"
    repaired.write_text("import cpp_audit as audit\n@audit.theory(output='y', expression='y = x + 1000')\ndef compute(x):\n    y = x + 1000\n    return y\n", encoding="utf-8")
    verified = verify_repair(candidate, repaired, project_root=tmp_path, analyze_options={"ranges": {"x": (0, 1)}})
    assert verified.status == "REPAIR_VERIFIED"


def test_synthesis_schema_and_object_wrapper():
    tracer = FormulaTracer(ROOT / "examples" / "end_to_end_audit" / "exact.py")
    result = tracer.synthesize(theory=arithmetic_theory(), language="python")
    schema = json.loads((ROOT / "schemas" / "code-synthesis-result.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(result.to_dict())
