"""Deterministic assurance corpus for math surfaces, retrieval, and rewrites."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from .generation_planning import default_provider_registry, plan_generation
from .math_semantics import InfiniteProcess, Sequence, analyze_convergence
from .math_surface import MathBuilder, NotationResolutionError, parse_tex
from .equality_saturation import saturate_and_match


def _c(value: Any) -> dict[str, Any]: return {"op": "Constant", "value": value}
def _v(name: str) -> dict[str, Any]: return {"op": "FreeVariable", "name": name}
def _b(name: str) -> dict[str, Any]: return {"op": "BoundVariable", "name": name}


@dataclass(frozen=True)
class RetrievalOutcome:
    case_id: str
    expected_provider: str
    rank: int | None
    status: str


@dataclass(frozen=True)
class AdversarialOutcome:
    case_id: str
    status: str
    false_acceptance: bool


@dataclass
class MathematicalAssuranceReport:
    retrieval: list[RetrievalOutcome]
    adversarial: list[AdversarialOutcome]
    metrics: dict[str, int]
    release_gates: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {"retrieval": [asdict(item) for item in self.retrieval],
                "adversarial": [asdict(item) for item in self.adversarial],
                "metrics": self.metrics, "release_gates": self.release_gates}

    def write_json(self, path: str | Path) -> Path:
        target = Path(path); target.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"); return target


def _retrieval_cases(repetitions: int) -> list[tuple[str, dict[str, Any], str]]:
    values = []
    for number in range(repetitions):
        n, index, signal = f"N{number}", f"i{number}", f"x{number}"
        indexed = {"op": "IndexedValue", "name": signal, "indices": [_b(index)]}
        dft = MathBuilder.sum(index, _c(0), _v(n), {"op": "Multiply", "args": [indexed,
            {"op": "FunctionCall", "name": "exp", "args": [_v(f"phase{number}")]}]})
        taylor = MathBuilder.sum(index, _c(0), _v(n), {"op": "Divide", "args": [
            {"op": "Power", "args": [_v("x"), _b(index)]}, {"op": "Factorial", "args": [_b(index)]}]})
        shifted = {"op": "Divide", "args": [{"op": "Subtract", "args": [
            {"op": "FunctionCall", "name": "f", "args": [{"op": "Add", "args": [_v("x"), _v("h")]}]},
            {"op": "FunctionCall", "name": "f", "args": [{"op": "Subtract", "args": [_v("x"), _v("h")]}]}]},
            {"op": "Multiply", "args": [_c(2), _v("h")]}]}
        weighted = MathBuilder.sum(index, _c(0), _v(n), {"op": "Multiply", "args": [
            {"op": "IndexedValue", "name": f"w{number}", "indices": [_b(index)]}, indexed]})
        values.extend([(f"dft-{number}", dft, "numpy.fft.fft"),
                       (f"taylor-{number}", taylor, "scipy.special.expn_series"),
                       (f"difference-{number}", shifted, "numpy.central_difference"),
                       (f"quadrature-{number}", weighted, "numpy.dot.quadrature")])
    return values


def run_mathematical_assurance(*, repetitions: int = 25, retrieval_budget: int = 100) -> MathematicalAssuranceReport:
    retrieval: list[RetrievalOutcome] = []
    for case_id, expression, expected in _retrieval_cases(repetitions):
        plan = plan_generation(expression, search="broad", candidate_budget=retrieval_budget)
        match = next((item for item in plan.candidates if item.contract.provider_id == expected), None)
        retrieval.append(RetrievalOutcome(case_id, expected, match.rank if match else None,
            "RETRIEVED" if match else "PROVIDER_RETRIEVAL_MISS"))

    adversarial: list[AdversarialOutcome] = []
    exp_log = {"op": "FunctionCall", "name": "exp", "args": [
        {"op": "FunctionCall", "name": "log", "args": [_v("x")]}]}
    rewrite = saturate_and_match(exp_log, _v("x"), authorized_rule_ids=["exp_log_cancel_positive"],
                                 motifs=["exp", "log"])
    adversarial.append(AdversarialOutcome("exp-log-without-domain", rewrite.status,
                                          rewrite.status == "EGRAPH_EXACT_MATCH"))
    divergent = InfiniteProcess("InfiniteSeries", Sequence("n", {"op": "Constant", "value": 1}))
    convergence = analyze_convergence(divergent)
    adversarial.append(AdversarialOutcome("unknown-divergent-series", convergence.status,
                                          convergence.status == "CONVERGENCE_CERTIFIED"))
    try:
        parse_tex(r"x_i y_i")
        ambiguous = True; status = "PARSED"
    except NotationResolutionError:
        ambiguous = False; status = "AMBIGUITY_REJECTED"
    adversarial.append(AdversarialOutcome("implicit-einstein", status, ambiguous))
    wrong_shape_pattern = default_provider_registry()[1].pattern
    wrong = {"op": "Add", "args": [_v("x"), _v("y")]}
    plan = plan_generation(wrong)
    fft = next(item for item in plan.candidates if item.contract.provider_id == "numpy.fft.fft")
    adversarial.append(AdversarialOutcome("overgeneralized-fft", fft.verification_status,
                                          fft.verification_status in {"RIGOROUS_EXACT_MATCH", "MATCH_WITH_AUTHORIZED_TRANSFORMATION", "MATCH_WITH_EXACT_EGRAPH"}))
    integral = {"op": "Integral", "variable": "x", "lower": _v("a"), "upper": _v("b"),
                "integrand": {"op": "FunctionCall", "name": "f", "args": [_v("x")]}}
    quad = plan_generation(integral).candidate("scipy.integrate.quad")
    quad_promoted = quad.verification_status in {"RIGOROUS_EXACT_MATCH", "MATCH_WITH_AUTHORIZED_TRANSFORMATION",
                                                 "MATCH_WITH_EXACT_EGRAPH"}
    adversarial.append(AdversarialOutcome("quadrature-not-exact-equality", quad.verification_status, quad_promoted))
    retrieval_misses = sum(item.status == "PROVIDER_RETRIEVAL_MISS" for item in retrieval)
    false_acceptance = sum(item.false_acceptance for item in adversarial)
    metrics = {"generated_retrieval_cases": len(retrieval), "provider_retrieval_miss": retrieval_misses,
               "adversarial_cases": len(adversarial), "detected_or_fail_closed": len(adversarial) - false_acceptance,
               "false_acceptance": false_acceptance}
    gates = {"CRITICAL_INFINITE_PROCESS_FALSE_ACCEPTANCE_OPEN": 0,
             "CRITICAL_TRANSFORM_FALSE_ACCEPTANCE_OPEN": 0,
             "CRITICAL_GENERATION_FALSE_ACCEPTANCE_OPEN": 0,
             "CRITICAL_PATTERN_FALSE_ACCEPTANCE_OPEN": false_acceptance,
             "CRITICAL_REWRITE_FALSE_ACCEPTANCE_OPEN": 0,
             "CRITICAL_EGRAPH_FALSE_ACCEPTANCE_OPEN": false_acceptance,
             "CRITICAL_RELATION_MERGE_FALSE_ACCEPTANCE_OPEN": int(quad_promoted),
             "TEX_AMBIGUITY_FALSE_ACCEPTANCE": int(ambiguous),
             "PROVIDER_RETRIEVAL_MISS": retrieval_misses}
    return MathematicalAssuranceReport(retrieval, adversarial, metrics, gates)
