from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from formulatracer import (Domain, EvidenceStatus, FormulaTracer, InfiniteProcess, MathBuilder,
    NotationResolutionError, SearchBudget, Sequence, SymbolDeclaration, TruncationRequirement,
    TruncationRequirementSolver, analyze_convergence, bounded_rewrite_search, canonical_equal,
    discrete_transform_layers, function_properties, generalize, load_rewrite_catalog,
    mathematical_features, plan_generation, typed_unify)
from formulatracer import propagate_properties, range_condition_status, run_mathematical_assurance
from formulatracer import anti_unify
from formulatracer import FourierSeries, TaylorSeries, integral_transform, inverse_mapping, series_evaluation_candidates

ROOT = Path(__file__).resolve().parents[1]


def c(value): return {"op": "Constant", "value": value}
def v(name): return {"op": "FreeVariable", "name": name}
def b(name): return {"op": "BoundVariable", "name": name}


def test_tex_dsl_builder_and_round_trip_share_canonical_ir():
    tex = FormulaTracer.from_tex(r"\sum_{i=0}^{N-1} x_i")
    built = MathBuilder.sum("j", c(0), v("M"), {"op": "IndexedValue", "name": "values", "indices": [b("j")]})
    assert canonical_equal(tex.expression, built)
    assert "\\sum" in tex.to_tex()
    assert '"FiniteSum"' in tex.to_dsl()
    assert "Σ" in tex.to_unicode()
    assert tex.to_markdown().startswith("$$")
    assert json.loads(tex.to_json())["op"] == "FiniteSum"
    reparsed = FormulaTracer.from_tex(tex.to_tex())
    assert canonical_equal(tex.expression, reparsed.expression)


def test_surface_supports_integral_limit_and_infinite_series():
    integral = FormulaTracer.from_tex(r"\int_{0}^{1} x\,dx")
    limit = FormulaTracer.from_tex(r"\lim_{x\to0} x")
    series = FormulaTracer.from_tex(r"\sum_{n=0}^{\infty} x^n")
    assert integral.expression["op"] == "Integral"
    assert limit.expression["op"] == "Limit"
    assert series.expression["op"] == "InfiniteSeries"
    assert series.truncate(8).expression["op"] == "FiniteSum"
    with pytest.raises(ValueError, match="REQUIRES_CERTIFIED_FINITE_LOWERING"):
        series.generate(auto_select=True)
    assert integral.plan_generation(language="python").candidate("python.builtin.direct").verification_status == "GENERATION_LOWERING_UNSUPPORTED"


def test_ambiguous_implicit_einstein_notation_fails_closed():
    with pytest.raises(NotationResolutionError, match="AMBIGUOUS_IMPLICIT_EINSTEIN"):
        FormulaTracer.from_tex(r"x_i y_i")
    explicit = FormulaTracer.from_tex(r"x_i y_i", assumptions=["einstein"])
    assert explicit.expression["op"] == "Multiply"


def test_overloaded_tex_notation_is_role_resolved_or_fails_closed():
    assert FormulaTracer.from_tex(r"x^2").expression["op"] == "Power"
    assert FormulaTracer.from_tex(r"\sin x").expression["op"] == "FunctionCall"
    ambiguous = (r"A^T", r"A^{-1}", r"x_i", r"T_1", r"|x|", r"<x,y>",
                 r"f'", r"\bar{x}", r"x*y", r"x \cdot y", r"x \times y")
    for tex in ambiguous:
        with pytest.raises(NotationResolutionError, match="AMBIGUOUS_NOTATION"):
            FormulaTracer.from_tex(tex)


def test_typed_generalization_is_alpha_invariant_and_shape_checked():
    left = MathBuilder.sum("i", c(0), v("N"), {"op": "IndexedValue", "name": "x", "indices": [b("i")]})
    right = MathBuilder.sum("k", c(0), v("K"), {"op": "IndexedValue", "name": "q", "indices": [b("k")]})
    assert typed_unify(generalize(left), generalize(right).pattern).status == "TYPED_UNIFICATION_SUCCEEDED"
    matrix = {"op": "IndexedValue", "name": "A", "indices": [b("i"), b("j")]}
    pattern = generalize(matrix, {"A": SymbolDeclaration("A", role="tensor", shape=(None, None))})
    assert typed_unify(pattern, {"op": "IndexedValue", "name": "x", "indices": [b("i")]}).status == "TYPED_UNIFICATION_FAILED"
    assert anti_unify(v("x"), v("y")).status == "ANTI_UNIFICATION_SUCCEEDED"
    assert anti_unify(c(1), c(2)).status == "ANTI_UNIFICATION_REJECTED"


def test_surface_provenance_supports_exact_debug_location():
    formula = FormulaTracer.from_tex("x + y")
    location = formula.debug(("args", 0))
    assert location.status == "EXACT_SOURCE_SPAN"
    assert location.semantic_path == ("args", 0)
    assert formula.inspect()["surface"]["original_tex"] == "x + y"


def test_function_properties_keep_domain_and_evidence_separate():
    log = function_properties("log")
    assert log.domain.constraints == ("x > 0",)
    assert log.evidence["domain"] == EvidenceStatus.CONTRACT_VERIFIED
    assert function_properties("unknown_external").evidence["contract"] == EvidenceStatus.UNRESOLVED
    condition = {"op": "Compare", "comparison": "LessThan", "args": [
        {"op": "FunctionCall", "name": "exp", "args": [v("x")]}, c(0)]}
    assert range_condition_status(condition) == "THEN_BRANCH_PROVABLY_UNREACHABLE"


def test_convergence_and_truncation_fail_closed_then_certify_geometric():
    term = {"op": "Power", "args": [v("r"), b("n")], "family_id": "geometric", "ratio": v("r")}
    process = InfiniteProcess("InfiniteSeries", Sequence("n", term))
    assert analyze_convergence(process).status == "CONVERGENCE_UNRESOLVED"
    convergence = analyze_convergence(process, ["abs(r) < 1"])
    solved = TruncationRequirementSolver().solve(convergence, TruncationRequirement(1e-6), parameters={"r": 0.5})
    assert solved.status == "TRUNCATION_CERTIFIED" and solved.minimum_terms > 0
    assert solved.distinction == "CERTIFIED_REMAINDER_NOT_TERM_MAGNITUDE"
    uniform = TruncationRequirementSolver().solve(convergence, TruncationRequirement(1e-6, (-0.75, 0.5)))
    assert uniform.status == "TRUNCATION_CERTIFIED" and uniform.minimum_terms >= solved.minimum_terms
    divergent = InfiniteProcess("InfiniteSeries", Sequence("n", c(1)))
    assert analyze_convergence(divergent).status == "DIVERGENCE_CERTIFIED"


def test_transform_layers_do_not_conflate_dft_fft_and_roundoff():
    layers = discrete_transform_layers("fft")
    assert layers["mathematics"]["op"] == "DiscreteFourierTransform"
    assert layers["algorithm"]["op"] == "FFT"
    assert layers["error"]["status"] == "REQUIRES_NUMERIC_TYPE_AND_LENGTH"
    laplace = FormulaTracer.from_expression(FormulaTracer.from_tex("x").expression).laplace("f")
    assert laplace.expression["region_of_convergence"]
    unresolved = inverse_mapping(laplace.expression)
    assert unresolved.evidence == EvidenceStatus.UNRESOLVED
    resolved = inverse_mapping(laplace.expression, assumptions=list(laplace.expression["region_of_convergence"]))
    assert resolved.evidence == EvidenceStatus.CONTRACT_VERIFIED


def test_taylor_fourier_objects_are_infinite_until_explicitly_lowered():
    taylor = TaylorSeries("exp").process()
    fourier = FourierSeries("f").process()
    assert taylor.kind == "InfiniteSeries" and fourier.kind == "BilateralInfiniteSeries"
    strategies = series_evaluation_candidates(taylor)
    assert strategies[0]["algorithm"]["op"] == "FiniteSum"
    assert strategies[1]["status"] == "CANDIDATE_NOT_VERIFIED"
    assert FormulaTracer.from_expression({"op": "BilateralInfiniteSeries", "bound_index": "n",
        "lower": c("-inf"), "body": b("n")}).truncate_symmetric(3).expression["index_domain"]["lower"] == c(-3)


def test_broad_retrieval_uses_ranking_budget_not_similarity_threshold():
    expression = MathBuilder.sum("n", c(0), v("N"), {"op": "Multiply", "args": [
        {"op": "IndexedValue", "name": "signal", "indices": [b("n")]},
        {"op": "FunctionCall", "name": "exp", "args": [v("phase")]}]})
    plan = plan_generation(expression, search="broad", candidate_budget=3)
    assert len(plan.candidates) == 3
    assert any(item.contract.provider_id == "numpy.fft.fft" for item in plan.candidates)
    assert all(item.score >= plan.candidates[-1].score for item in plan.candidates[:-1])
    assert all(item.verification_status != "RIGOROUS_EXACT_MATCH" for item in plan.candidates
               if item.contract.provider_id == "numpy.fft.fft")


def test_fourier_sign_and_normalization_are_not_generalized_away():
    registry = next(item for item in __import__("formulatracer").default_provider_registry()
                    if item.provider_id == "numpy.fft.fft")
    mutated = json.loads(json.dumps(registry.pattern))
    mutated["body"]["args"][1]["args"][0]["args"][0]["args"][0]["value"] = "+2*pi*i"
    candidate = plan_generation(mutated).candidate("numpy.fft.fft")
    assert candidate.verification_status == "NOT_VERIFIED"


def test_external_provider_contract_obligations_block_selection_until_supplied():
    provider = next(item for item in __import__("formulatracer").default_provider_registry()
                    if item.provider_id == "numpy.fft.fft")
    formula = FormulaTracer.from_expression(provider.pattern)
    unresolved = formula.plan_generation().candidate(provider.provider_id)
    assert unresolved.verification_status == "CONTRACT_OBLIGATIONS_REMAINING"
    with pytest.raises(ValueError, match="NO_RIGOROUSLY_VERIFIED"):
        formula.plan_generation().select(provider.provider_id)
    formula.assume(*provider.constraints)
    selected = formula.plan_generation().select(provider.provider_id)
    assert selected.verification_status == "RIGOROUS_EXACT_MATCH"
    assert formula.generate(provider=provider.provider_id).status == "SOURCE_GENERATED_UNVERIFIED"


def test_subexpression_retrieval_finds_transform_motif_inside_large_formula():
    sub = MathBuilder.sum("n", c(0), v("N"), {"op": "Multiply", "args": [
        {"op": "IndexedValue", "name": "x", "indices": [b("n")]},
        {"op": "FunctionCall", "name": "exp", "args": [v("phase")]}]})
    large = {"op": "Add", "args": [v("A"), {"op": "Add", "args": [sub, v("C")]}]}
    candidate = next(item for item in plan_generation(large, search="broad").candidates
                     if item.contract.provider_id == "numpy.fft.fft")
    assert candidate.matched_path
    assert "shared mathematical motif: complex_exponential" in candidate.reasons


def test_bounded_bidirectional_rewrite_finds_factored_form_and_records_trace():
    distributed = FormulaTracer.from_tex(r"\frac{x}{a}+\frac{y}{a}").expression
    factored = FormulaTracer.from_tex(r"\frac{x+y}{a}").expression
    result = bounded_rewrite_search(distributed, factored,
        authorized_rule_ids=["factor_common_denominator"], relevant_motifs=["add", "divide"])
    assert result.status == "REWRITE_PATH_FOUND"
    assert "factor_common_denominator" in result.left_state.provenance


def test_domain_conditioned_rewrite_is_not_used_without_assumption():
    expression = {"op": "FunctionCall", "name": "exp", "args": [
        {"op": "FunctionCall", "name": "log", "args": [v("x")]}]}
    unresolved = bounded_rewrite_search(expression, v("x"),
        authorized_rule_ids=["exp_log_cancel_positive"], relevant_motifs=["exp", "log"])
    assert unresolved.status != "REWRITE_PATH_FOUND"
    resolved = bounded_rewrite_search(expression, v("x"), assumptions=["x > 0"],
        authorized_rule_ids=["exp_log_cancel_positive"], relevant_motifs=["exp", "log"])
    assert resolved.status == "REWRITE_PATH_FOUND"


def test_selection_requires_rigorous_match_and_generation_requires_reaudit():
    formula = FormulaTracer.from_tex("x + 2")
    plan = formula.plan_generation()
    assert plan.select().contract.provider_id == "python.builtin.direct"
    generated = formula.generate(auto_select=True)
    assert generated.status == "SOURCE_GENERATED_UNVERIFIED"
    assert generated.verify().status == "INDEPENDENTLY_REAUDITED_VERIFIED"
    generated.source = generated.source.replace(" + ", " - ")
    assert generated.verify().status == "INDEPENDENT_REAUDIT_DIVERGENCE"


def test_project_default_target_does_not_return_loop_initializer(tmp_path):
    source = tmp_path / "loop.py"
    source.write_text("def compute(N, x):\n    result = 0.0\n    for i in range(N):\n        result += x[i]\n    return result\n", encoding="utf-8")
    result = FormulaTracer(source, project_root=tmp_path).analyze()
    assert result.outputs[0].formula["op"] == "FoldLeft"


@pytest.mark.parametrize("language", ["rust", "cpp"])
def test_native_direct_provider_uses_same_planning_and_reaudit(language):
    formula = FormulaTracer.from_tex("x + 2")
    plan = formula.plan_generation(language=language)
    assert plan.select().contract.language == language
    generated = formula.generate(language=language, auto_select=True, verify=True)
    assert generated.status == "INDEPENDENTLY_REAUDITED_VERIFIED"


def test_registry_is_broad_and_every_rule_has_assurance_metadata():
    rules = load_rewrite_catalog()
    assert len(rules) >= 40
    families = {motif for rule in rules for motif in rule.motifs}
    assert {"fourier", "laplace", "factorial", "convolution", "variance", "matmul"} <= families
    for rule in rules:
        values = asdict(rule)
        assert {"rule_id", "relation_kind", "preconditions", "domain_constraints", "type_constraints",
                "shape_constraints", "assumptions", "cost", "priority", "evidence", "inverse_rule"} <= values.keys()


def test_schema_and_large_generated_assurance_gates():
    raw = yaml.safe_load((ROOT / "registry/transformations/rewrite_catalog.yaml").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/rewrite-catalog.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(raw)
    surface = FormulaTracer.from_tex("x + y").surface
    surface_schema = json.loads((ROOT / "schemas/math-surface-ast.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(surface_schema).validate(json.loads(json.dumps(asdict(surface))))
    report = run_mathematical_assurance(repetitions=5)
    plan = FormulaTracer.from_tex("x + y").plan_generation()
    plan_schema = json.loads((ROOT / "schemas/generation-plan.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(plan_schema).validate(plan.to_dict())
    assurance_schema = json.loads((ROOT / "schemas/mathematical-assurance-report.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(assurance_schema).validate(report.to_dict())
    assert report.metrics["generated_retrieval_cases"] == 20
    assert report.metrics["false_acceptance"] == 0
    assert all(value == 0 for value in report.release_gates.values())
