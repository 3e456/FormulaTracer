"""Small, explicitly bounded probability/estimator audit layer."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics
from typing import Any, Callable, Iterable, Mapping, Sequence


class DistributionKind(str, Enum):
    NORMAL = "Normal"
    UNIFORM = "Uniform"
    DISCRETE_UNIFORM = "DiscreteUniform"
    CATEGORICAL = "Categorical"
    FINITE_POPULATION_SAMPLE = "FinitePopulationSample"
    RANDOM_PERMUTATION = "RandomPermutation"
    USER_DEFINED = "UserDefinedDistribution"
    USER_RANDOM_SOURCE = "UserDefinedRandomSource"


@dataclass
class KnownDistribution:
    distribution_id: str
    kind: str
    api: str
    parameters: dict[str, Any]
    support: Any
    contract_status: str = "REFERENCE_CONTRACT"


@dataclass
class UserDefinedDistribution:
    pdf: str | None = None
    pmf: Mapping[Any, float] | None = None
    cdf: str | None = None
    support: tuple[float, float] | Sequence[Any] | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    name: str = "user_distribution"


@dataclass
class DistributionValidation:
    definition_status: str
    nonnegative_status: str
    normalization_status: str
    support_status: str
    sampler_conformance_status: str = "SAMPLER_CONFORMANCE_NOT_PROVEN"
    evidence_level: str = "NUMERICALLY_CHECKED"
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EmpiricalDistributionValidation:
    status: str
    empirical_cdf_distance: float | None
    wasserstein_distance: float | None
    sample_size: int
    progression: list[dict[str, Any]]
    threshold: float
    evidence_level: str = "EMPIRICALLY_SUPPORTED"


@dataclass
class IndependenceValidation:
    status: str
    lag_correlations: dict[int, float | None]
    threshold: float
    sample_size: int
    evidence_level: str = "EMPIRICALLY_SUPPORTED"


@dataclass
class CLTValidation:
    status: str
    progression: list[dict[str, Any]]
    evidence_level: str = "EMPIRICALLY_SUPPORTED"


@dataclass
class Expectation:
    expression: Any
    distribution_id: str | None


@dataclass
class Variance:
    expression: Any
    distribution_id: str | None


@dataclass
class Covariance:
    left: Any
    right: Any
    distribution_id: str | None


@dataclass
class EstimatorTarget:
    target_id: str
    relation: str
    expression: Any
    authority: str


@dataclass
class Estimator:
    estimator_id: str
    expression: Any
    kind: str
    sample_size: Any
    target: EstimatorTarget | None
    status: str


@dataclass
class EmpiricalEstimator:
    estimator: Estimator
    estimate: float
    sample_size: int
    observed_variance: float | None
    evidence_level: str = "NUMERICALLY_CHECKED"


@dataclass
class SamplingError:
    epsilon: float
    alpha: float
    method: str
    assumptions: list[str]
    status: str


@dataclass
class ProbabilisticEnclosure:
    lower: float
    upper: float
    coverage_probability: float
    claim: str
    proof_authority: str


@dataclass
class MonteCarloEstimate:
    estimate: float
    target: EstimatorTarget | None
    sample_size: int
    sampling_error: SamplingError
    enclosure: ProbabilisticEnclosure | None
    status: str


@dataclass
class ParallelRandomness:
    shared_rng_state: str
    stream_policy: str
    independence_status: str
    sequence_reproducibility: str
    obligations: list[str] = field(default_factory=list)


@dataclass
class ProbabilityAuditResult:
    distribution: Any
    definition_validation: DistributionValidation | None
    empirical_validation: EmpiricalDistributionValidation | None
    independence: IndependenceValidation | None
    clt: CLTValidation | None
    estimator: Estimator | None
    empirical_estimator: EmpiricalEstimator | None
    monte_carlo: MonteCarloEstimate | None
    parallel_randomness: ParallelRandomness | None
    status: str

    def to_dict(self) -> dict[str, Any]: return _serial(self)
    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=True) + "\n"
    def write_json(self, path: str | Path) -> Path:
        target = Path(path); target.write_text(self.to_json(), encoding="utf-8"); return target
    def to_latex(self) -> str:
        def esc(value: Any) -> str:
            chars = {"_": r"\_", "%": r"\%", "&": r"\&", "#": r"\#", "$": r"\$"}
            return "".join(chars.get(char, char) for char in str(value))
        distribution = self.distribution.kind if hasattr(self.distribution, "kind") else DistributionKind.USER_DEFINED.value
        def row(label: str, value: Any) -> str:
            return rf"\noindent {label}: \texttt{{{esc(value)}}}\par"
        lines = [r"\documentclass{article}", r"\usepackage[T1]{fontenc}", r"\usepackage[margin=0.75in]{geometry}",
                 r"\begin{document}", r"\section*{FormulaTracer Probability Audit}",
                 row("Overall status", self.status), row("Distribution", distribution),
                 r"\section*{Formal / reference boundary}"]
        if self.definition_validation:
            lines += [row("Definition", self.definition_validation.definition_status),
                      row("Sampler conformance", self.definition_validation.sampler_conformance_status)]
        if self.empirical_validation:
            lines += [r"\section*{Empirical distribution validation}",
                      row("Status", self.empirical_validation.status),
                      rf"\noindent Sample size: {self.empirical_validation.sample_size}\par",
                      rf"\noindent Empirical CDF distance: {self.empirical_validation.empirical_cdf_distance:.6g}\par"]
        if self.independence:
            lines += [r"\section*{Dependence diagnostics}",
                      row("Status", self.independence.status)]
        if self.monte_carlo:
            lines += [r"\section*{Estimator / Monte Carlo}",
                      rf"\noindent Estimate: {self.monte_carlo.estimate:.8g}\par",
                      row("Sampling claim", self.monte_carlo.status)]
        lines += [r"\section*{Trust boundary}",
                  r"Empirical support is not a distribution proof. PRNG internals and physical randomness are not kernel verified.",
                  r"\end{document}", ""]
        return "\n".join(lines)
    def write_latex(self, path: str | Path) -> Path:
        target = Path(path); target.write_text(self.to_latex(), encoding="utf-8"); return target


_KNOWN = {
    "numpy.random.normal": (DistributionKind.NORMAL.value, (-math.inf, math.inf)),
    "numpy.random.Generator.normal": (DistributionKind.NORMAL.value, (-math.inf, math.inf)),
    "scipy.stats.norm.rvs": (DistributionKind.NORMAL.value, (-math.inf, math.inf)),
    "jax.random.normal": (DistributionKind.NORMAL.value, (-math.inf, math.inf)),
    "torch.normal": (DistributionKind.NORMAL.value, (-math.inf, math.inf)),
    "numpy.random.uniform": (DistributionKind.UNIFORM.value, "parameterized_interval"),
    "jax.random.uniform": (DistributionKind.UNIFORM.value, "parameterized_interval"),
    "torch.rand": (DistributionKind.UNIFORM.value, (0.0, 1.0)),
    "cupy.random.uniform": (DistributionKind.UNIFORM.value, "parameterized_interval"),
    "numpy.random.randint": (DistributionKind.DISCRETE_UNIFORM.value, "parameterized_integers"),
    "numpy.random.Generator.integers": (DistributionKind.DISCRETE_UNIFORM.value, "parameterized_integers"),
    "numpy.random.choice": (DistributionKind.CATEGORICAL.value, "finite_categories"),
    "random.sample": (DistributionKind.FINITE_POPULATION_SAMPLE.value, "finite_population"),
    "numpy.random.permutation": (DistributionKind.RANDOM_PERMUTATION.value, "finite_population"),
}

def _native_probability(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version":"1.0","kernel":"C",
            "operation":"LEGACY_PROBABILITY","action":action,**payload})["result"]


def _serial(value: Any) -> Any:
    if isinstance(value, Enum): return value.value
    if is_dataclass(value): return {key: _serial(item) for key, item in asdict(value).items()}
    if isinstance(value, dict): return {str(key): _serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_serial(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value): return str(value)
    return value


def _id(prefix: str, value: Any) -> str:
    return prefix + ":" + sha256(json.dumps(_serial(value), sort_keys=True).encode()).hexdigest()[:16]


def classify_random_source(api: str, parameters: Mapping[str, Any] | None = None) -> KnownDistribution | None:
    record = _native_probability("CLASSIFY_SOURCE", api=api, parameters=dict(parameters or {}))
    if record is None: return None
    support = record["support"]
    if support == ["-inf", "inf"]: support = (-math.inf, math.inf)
    return KnownDistribution(record["distribution_id"], record["kind"], record["api"], record["parameters"], support,
                             record["contract_status"])


_ALLOWED = {ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Constant,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.Call}


def _numeric_function(text: str, parameters: Mapping[str, Any]) -> Callable[[float], float]:
    tree = ast.parse(text, mode="eval")
    if any(type(node) not in _ALLOWED for node in ast.walk(tree)):
        raise ValueError("UNSUPPORTED_DISTRIBUTION_EXPRESSION")
    functions: dict[str, Callable[..., float]] = {
        "exp": math.exp, "sqrt": math.sqrt, "log": math.log, "abs": abs,
    }
    constants = {name: float(value) for name, value in parameters.items()
                 if isinstance(value, (int, float)) and not isinstance(value, bool)}

    def visit(node: ast.AST, x: float) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body, x)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id == "x":
                return x
            if node.id in constants:
                return constants[node.id]
            raise ValueError("UNSUPPORTED_DISTRIBUTION_NAME")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -visit(node.operand, x)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left, x), visit(node.right, x)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right
            if isinstance(node.op, ast.Pow): return left ** right
            raise ValueError("UNSUPPORTED_DISTRIBUTION_OPERATOR")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in functions and not node.keywords:
            return float(functions[node.func.id](*(visit(arg, x) for arg in node.args)))
        raise ValueError("UNSUPPORTED_DISTRIBUTION_EXPRESSION")

    def evaluate(x: float) -> float:
        return float(visit(tree, float(x)))
    return evaluate


def validate_distribution(distribution: UserDefinedDistribution, *, grid_size: int = 2001) -> DistributionValidation:
    support = distribution.support
    if distribution.pmf is not None:
        values = list(distribution.pmf.values())
        nonnegative = all(isinstance(value, (int, float)) and value >= 0 for value in values)
        normalized = math.isclose(sum(values), 1.0, rel_tol=1e-9, abs_tol=1e-9)
        consistent = support is None or set(distribution.pmf).issubset(set(support))
        valid = nonnegative and normalized and consistent
        return DistributionValidation("DISTRIBUTION_DEFINITION_VALID" if valid else "DISTRIBUTION_DEFINITION_INVALID",
            "NONNEGATIVE_NUMERICALLY_CHECKED" if nonnegative else "NEGATIVITY_DETECTED",
            "NORMALIZATION_NUMERICALLY_CHECKED" if normalized else "NORMALIZATION_FAILED",
            "SUPPORT_CONSISTENT" if consistent else "SUPPORT_INCONSISTENT")
    if distribution.pdf is not None and isinstance(support, tuple) and len(support) == 2:
        lower, upper = map(float, support)
        if not lower < upper: return DistributionValidation("DISTRIBUTION_DEFINITION_INVALID", "UNRESOLVED", "UNRESOLVED", "SUPPORT_INCONSISTENT")
        try: function = _numeric_function(distribution.pdf, distribution.parameters)
        except (SyntaxError, ValueError):
            return DistributionValidation("DISTRIBUTION_DEFINITION_UNRESOLVED", "UNRESOLVED", "UNRESOLVED", "SUPPORT_CONSISTENT",
                diagnostics=[{"code": "PDF_EXPRESSION_UNSUPPORTED"}])
        step = (upper - lower) / (grid_size - 1); values = [function(lower + index * step) for index in range(grid_size)]
        nonnegative = min(values) >= -1e-12
        integral = step * (sum(values) - (values[0] + values[-1]) / 2)
        normalized = math.isclose(integral, 1.0, rel_tol=2e-3, abs_tol=2e-3)
        valid = nonnegative and normalized
        return DistributionValidation("DISTRIBUTION_DEFINITION_NUMERICALLY_VALIDATED" if valid else "DISTRIBUTION_DEFINITION_INVALID",
            "NONNEGATIVE_NUMERICALLY_CHECKED" if nonnegative else "NEGATIVITY_DETECTED",
            "NORMALIZATION_NUMERICALLY_CHECKED" if normalized else "NORMALIZATION_FAILED", "SUPPORT_CONSISTENT",
            evidence_level="NUMERICALLY_CHECKED")
    return DistributionValidation("DISTRIBUTION_DEFINITION_UNRESOLVED", "UNRESOLVED", "UNRESOLVED",
        "SUPPORT_UNRESOLVED", diagnostics=[{"code": "PDF_PMF_OR_CDF_WITH_SUPPORT_REQUIRED"}])


def _target_cdf(distribution: UserDefinedDistribution) -> Callable[[float], float] | None:
    if distribution.cdf:
        try: return _numeric_function(distribution.cdf, distribution.parameters)
        except (SyntaxError, ValueError): return None
    if distribution.pmf is not None:
        ordered = sorted((float(key), float(value)) for key, value in distribution.pmf.items())
        return lambda x: sum(probability for value, probability in ordered if value <= x)
    if distribution.pdf and isinstance(distribution.support, tuple):
        function = _numeric_function(distribution.pdf, distribution.parameters); lower, upper = map(float, distribution.support)
        def cdf(x: float) -> float:
            if x <= lower: return 0.0
            if x >= upper: return 1.0
            n = 500; step = (x - lower) / n
            values = [function(lower + index * step) for index in range(n + 1)]
            return max(0.0, min(1.0, step * (sum(values) - (values[0] + values[-1]) / 2)))
        return cdf
    return None


def validate_empirical_distribution(samples: Sequence[float], distribution: UserDefinedDistribution,
                                    *, threshold: float | None = None) -> EmpiricalDistributionValidation:
    values = sorted(float(item) for item in samples); n = len(values); cdf = _target_cdf(distribution)
    if not values or cdf is None: return EmpiricalDistributionValidation("DISTRIBUTION_VALIDATION_INCONCLUSIVE", None, None, n, [], threshold or 0.1)
    threshold = threshold if threshold is not None else min(0.2, 1.63 / math.sqrt(n))
    def distance(prefix: Sequence[float]) -> float:
        ordered = sorted(prefix); size = len(ordered)
        return max(max(abs(index / size - cdf(value)), abs((index - 1) / size - cdf(value)))
                   for index, value in enumerate(ordered, 1))
    points = sorted(set([max(20, n // 4), max(20, n // 2), n])); points = [point for point in points if point <= n]
    progression = [{"sample_size": point, "empirical_cdf_distance": distance(values[:point])} for point in points]
    final = distance(values)
    quantiles = [(index - 0.5) / n for index in range(1, n + 1)]
    wasserstein = sum(abs(cdf(value) - probability) for value, probability in zip(values, quantiles)) / n
    status = "DISTRIBUTION_EMPIRICALLY_SUPPORTED" if final <= threshold else "DISTRIBUTION_EMPIRICALLY_INCONSISTENT"
    return EmpiricalDistributionValidation(status, final, wasserstein, n, progression, threshold)


def validate_independence(samples: Sequence[float], *, max_lag: int = 5, threshold: float | None = None) -> IndependenceValidation:
    values = [float(item) for item in samples]; n = len(values); threshold = threshold or (2 / math.sqrt(n) if n else 1)
    correlations = {}
    for lag in range(1, min(max_lag, max(0, n - 2)) + 1):
        left, right = values[:-lag], values[lag:]
        try: correlations[lag] = statistics.correlation(left, right)
        except statistics.StatisticsError: correlations[lag] = None
    finite = [abs(value) for value in correlations.values() if value is not None]
    status = ("INDEPENDENCE_INCONCLUSIVE" if n < 30 or not finite else
              "INDEPENDENCE_EMPIRICALLY_SUPPORTED" if max(finite) <= threshold else
              "INDEPENDENCE_EMPIRICALLY_INCONSISTENT")
    return IndependenceValidation(status, correlations, threshold, n)


def validate_clt(replicate_means: Mapping[int, Sequence[float]]) -> CLTValidation:
    progression = []
    for sample_size, samples in sorted(replicate_means.items()):
        values = [float(item) for item in samples]
        if len(values) < 20: continue
        mean, variance = statistics.mean(values), statistics.pvariance(values)
        progression.append({"sample_size": sample_size, "replicates": len(values), "mean": mean, "variance": variance})
    if len(progression) < 2: status = "CLT_INCONCLUSIVE"
    else:
        variance_decreases = all(right["variance"] <= left["variance"] * 1.25 for left, right in zip(progression, progression[1:]))
        status = "CLT_EMPIRICALLY_SUPPORTED" if variance_decreases else "CLT_EMPIRICALLY_INCONSISTENT"
    return CLTValidation(status, progression)


def extract_estimator(expression: Any, *, target: EstimatorTarget | None = None) -> Estimator:
    result = _native_probability("EXTRACT_ESTIMATOR", expression=expression, target=_serial(target) if target else None)
    return Estimator(result["estimator_id"], result["expression"], result["kind"], result.get("sample_size"), target, result["status"])


def monte_carlo_estimate(samples: Sequence[float], *, target: EstimatorTarget | None = None,
                         support: tuple[float, float] | None = None, alpha: float = 0.05) -> tuple[EmpiricalEstimator, MonteCarloEstimate]:
    native_support = list(support) if support and all(math.isfinite(float(item)) for item in support) else None
    result = _native_probability("MONTE_CARLO", samples=[float(item) for item in samples],
        target=_serial(target) if target else None, support=native_support, alpha=alpha)
    raw_estimator = result["empirical"]["estimator"]
    estimator = Estimator(raw_estimator["estimator_id"], raw_estimator["expression"], raw_estimator["kind"],
        raw_estimator.get("sample_size"), target, raw_estimator["status"])
    empirical = EmpiricalEstimator(estimator, result["empirical"]["estimate"], result["empirical"]["sample_size"],
        result["empirical"].get("observed_variance"), result["empirical"]["evidence_level"])
    raw_error = result["monte_carlo"]["sampling_error"]
    epsilon = math.inf if raw_error["epsilon"] == "inf" else float(raw_error["epsilon"])
    error = SamplingError(epsilon, raw_error["alpha"], raw_error["method"], raw_error["assumptions"], raw_error["status"])
    raw_enclosure = result["monte_carlo"].get("enclosure")
    enclosure = ProbabilisticEnclosure(**raw_enclosure) if raw_enclosure else None
    monte = MonteCarloEstimate(result["monte_carlo"]["estimate"], target, result["monte_carlo"]["sample_size"],
        error, enclosure, result["monte_carlo"]["status"])
    return empirical, monte


def audit_probability(*, distribution: KnownDistribution | UserDefinedDistribution,
                      samples: Sequence[float] | None = None, estimator_expression: Any = None,
                      estimator_target: EstimatorTarget | None = None,
                      parallel_randomness: ParallelRandomness | None = None,
                      replicate_means: Mapping[int, Sequence[float]] | None = None,
                      alpha: float = 0.05) -> ProbabilityAuditResult:
    definition = validate_distribution(distribution) if isinstance(distribution, UserDefinedDistribution) else None
    empirical = (validate_empirical_distribution(samples, distribution)
                 if samples is not None and isinstance(distribution, UserDefinedDistribution) else None)
    independence = validate_independence(samples) if samples is not None else None
    clt = validate_clt(replicate_means) if replicate_means is not None else None
    estimator = extract_estimator(estimator_expression, target=estimator_target) if estimator_expression else None
    empirical_estimator = monte_carlo = None
    support = distribution.support if isinstance(distribution.support, tuple) else None
    if samples is not None:
        empirical_estimator, monte_carlo = monte_carlo_estimate(samples, target=estimator_target, support=support, alpha=alpha)
        estimator = estimator or empirical_estimator.estimator
    inconsistent = empirical and empirical.status == "DISTRIBUTION_EMPIRICALLY_INCONSISTENT"
    status = _native_probability("AUDIT_STATUS", empirical_status=empirical.status if empirical else None,
        known_distribution=isinstance(distribution, KnownDistribution))["status"]
    return ProbabilityAuditResult(distribution, definition, empirical, independence, clt, estimator,
                                  empirical_estimator, monte_carlo, parallel_randomness, status)
