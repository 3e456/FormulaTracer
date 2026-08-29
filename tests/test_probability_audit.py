from __future__ import annotations

import json
import math
from pathlib import Path

import jsonschema

from formulatracer import (EstimatorTarget, ParallelRandomness, UserDefinedDistribution,
                           audit_probability, classify_random_source, extract_estimator,
                           monte_carlo_estimate, validate_clt, validate_distribution,
                           validate_empirical_distribution, validate_independence)


ROOT = Path(__file__).resolve().parents[1]


def beta22_quantile(probability: float) -> float:
    lower, upper = 0.0, 1.0
    for _ in range(50):
        middle = (lower + upper) / 2
        cdf = 3 * middle * middle - 2 * middle * middle * middle
        if cdf < probability: lower = middle
        else: upper = middle
    return (lower + upper) / 2


def test_known_random_sources_use_reference_contracts():
    assert classify_random_source("numpy.random.normal").kind == "Normal"
    assert classify_random_source("jax.random.uniform").kind == "Uniform"
    assert classify_random_source("torch.rand").contract_status == "REFERENCE_CONTRACT"
    assert classify_random_source("custom.rng") is None


def test_user_pdf_definition_validity_is_not_sampler_proof():
    distribution = UserDefinedDistribution(pdf="6*x*(1-x)", support=(0, 1))
    validation = validate_distribution(distribution)
    assert validation.definition_status == "DISTRIBUTION_DEFINITION_NUMERICALLY_VALIDATED"
    assert validation.sampler_conformance_status == "SAMPLER_CONFORMANCE_NOT_PROVEN"
    invalid = validate_distribution(UserDefinedDistribution(pmf={0: 0.8, 1: 0.8}, support=[0, 1]))
    assert invalid.definition_status == "DISTRIBUTION_DEFINITION_INVALID"


def test_user_distribution_expression_is_interpreted_without_python_eval():
    valid = validate_distribution(UserDefinedDistribution(
        pdf="scale*x*(1-x)", support=(0, 1), parameters={"scale": 6}
    ))
    assert valid.definition_status == "DISTRIBUTION_DEFINITION_NUMERICALLY_VALIDATED"
    malicious = validate_distribution(UserDefinedDistribution(
        pdf="__import__('os').getcwd()", support=(0, 1)
    ))
    assert malicious.definition_status == "DISTRIBUTION_DEFINITION_UNRESOLVED"
    assert malicious.diagnostics == [{"code": "PDF_EXPRESSION_UNSUPPORTED"}]


def test_empirical_cdf_progression_and_dependence_are_separate():
    distribution = UserDefinedDistribution(pdf="6*x*(1-x)", cdf="3*x**2-2*x**3", support=(0, 1))
    samples = [beta22_quantile((index + 0.5) / 400) for index in range(400)]
    empirical = validate_empirical_distribution(samples, distribution)
    independence = validate_independence(samples)
    assert empirical.status == "DISTRIBUTION_EMPIRICALLY_SUPPORTED"
    assert len(empirical.progression) == 3
    assert independence.status == "INDEPENDENCE_EMPIRICALLY_INCONSISTENT"


def test_estimator_and_monte_carlo_claim_keep_reference_assumptions():
    target = EstimatorTarget("expectation:f", "ESTIMATOR_OF", {"op": "Expectation", "body": "f(X)"}, "USER_PROVIDED")
    expression = {"op": "Divide", "args": [{"op": "FiniteSum", "body": {"op": "FreeVariable", "name": "sample"}},
                                                  {"op": "FreeVariable", "name": "n"}]}
    assert extract_estimator(expression, target=target).status == "ESTIMATOR_TARGET_IDENTIFIED"
    empirical, monte_carlo = monte_carlo_estimate([0.1, 0.2, 0.3, 0.4], target=target, support=(0, 1), alpha=0.05)
    assert empirical.evidence_level == "NUMERICALLY_CHECKED"
    assert monte_carlo.status == "MONTE_CARLO_PROBABILISTIC_ENCLOSURE_UNDER_ASSUMPTIONS"
    assert monte_carlo.enclosure.proof_authority == "REFERENCE_THEOREM"
    assert "IID" in monte_carlo.sampling_error.assumptions
    _, unresolved = monte_carlo_estimate([0.1, 0.2], target=target, support=(-math.inf, math.inf))
    assert unresolved.status == "MONTE_CARLO_ENCLOSURE_UNRESOLVED"


def test_clt_is_empirical_support_not_independence_proof():
    result = validate_clt({1: [-2, -1, 0, 1, 2] * 10,
                           4: [-1, -0.5, 0, 0.5, 1] * 10,
                           16: [-0.4, -0.2, 0, 0.2, 0.4] * 10})
    assert result.status == "CLT_EMPIRICALLY_SUPPORTED"
    assert result.evidence_level == "EMPIRICALLY_SUPPORTED"


def test_probability_e2e_parallel_metadata_schema_and_latex(tmp_path: Path):
    distribution = UserDefinedDistribution(pdf="1", cdf="x", support=(0, 1))
    samples = [(index + 0.5) / 200 for index in range(200)]
    parallel = ParallelRandomness("NO_SHARED_STATE", "SEPARATE_STREAMS",
                                  "INDEPENDENCE_UNRESOLVED", "SEED_REPRODUCIBLE",
                                  ["stream splitting contract required"])
    result = audit_probability(distribution=distribution, samples=samples, parallel_randomness=parallel)
    assert result.status == "PROBABILITY_AUDIT_EMPIRICALLY_SUPPORTED"
    assert result.parallel_randomness.independence_status == "INDEPENDENCE_UNRESOLVED"
    schema = json.loads((ROOT / "schemas" / "probability-audit-result.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(result.to_dict())
    latex = result.to_latex()
    assert "Empirical distribution validation" in latex
    assert latex.count(r"\par") >= 6
    assert "}\\\n" not in latex
    result.write_json(tmp_path / "probability.json"); result.write_latex(tmp_path / "probability.tex")
