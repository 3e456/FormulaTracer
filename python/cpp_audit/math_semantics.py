"""Semantic objects for functions, infinite processes, and transforms.

The objects in this module are evidence carrying descriptions.  A declaration is
never promoted to a verified claim merely because it was supplied by a caller.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from math import ceil, log
from typing import Any, Iterable, Mapping


def _native_math(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "F",
            "operation": "LEGACY_MATH_SEMANTICS", "action": action, **payload})["result"]


class EvidenceStatus(str, Enum):
    DECLARED = "DECLARED"
    DERIVED = "DERIVED"
    CONTRACT_VERIFIED = "CONTRACT_VERIFIED"
    KERNEL_VERIFIED = "KERNEL_VERIFIED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class SourceOrigin:
    source: str
    span: tuple[int, int] | None = None
    surface: str = "canonical"


@dataclass
class OriginSet:
    origins: list[SourceOrigin] = field(default_factory=list)

    def merged(self, *others: "OriginSet") -> "OriginSet":
        values = _native_math("ORIGIN_MERGE", groups=[[asdict(item) for item in group.origins]
                                                       for group in (self, *others)])
        return OriginSet([SourceOrigin(item["source"], tuple(item["span"]) if item.get("span") else None,
                                      item.get("surface", "canonical")) for item in values])


@dataclass(frozen=True)
class MathematicalDebugLocation:
    status: str
    semantic_path: tuple[Any, ...]
    source_spans: tuple[tuple[int, int], ...]
    origins: tuple[SourceOrigin, ...]


def localize_mathematical_node(path: Iterable[Any], origins: OriginSet) -> MathematicalDebugLocation:
    value = _native_math("LOCALIZE", path=list(path), origins=[asdict(item) for item in origins.origins])
    return MathematicalDebugLocation(value["status"], tuple(value["semantic_path"]),
        tuple(tuple(item) for item in value["source_spans"]), tuple(origins.origins))


@dataclass(frozen=True)
class Domain:
    description: str
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class CertifiedRange:
    lower: Any
    upper: Any
    evidence: EvidenceStatus = EvidenceStatus.DECLARED
    proof_reference: str | None = None


@dataclass
class FunctionProperties:
    name: str
    domain: Domain | None = None
    codomain: Domain | None = None
    certified_range: CertifiedRange | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    periods: tuple[Any, ...] = ()
    evidence: dict[str, EvidenceStatus] = field(default_factory=dict)

    @property
    def usable_for_verification(self) -> bool:
        return bool(_native_math("USABLE_PROPERTIES", evidence={key: value.value for key, value in self.evidence.items()}))


KNOWN_FUNCTIONS: dict[str, FunctionProperties] = {
    "exp": FunctionProperties("exp", Domain("Real"), Domain("PositiveReal"),
        CertifiedRange(0, "+inf", EvidenceStatus.CONTRACT_VERIFIED),
        {"positive": True, "strictly_monotone": True}, evidence={"positive": EvidenceStatus.CONTRACT_VERIFIED}),
    "log": FunctionProperties("log", Domain("PositiveReal", ("x > 0",)), Domain("Real"),
        properties={"strictly_monotone": True}, evidence={"domain": EvidenceStatus.CONTRACT_VERIFIED}),
    "sin": FunctionProperties("sin", Domain("Real"), Domain("Real"),
        CertifiedRange(-1, 1, EvidenceStatus.CONTRACT_VERIFIED), {"odd": True}, ("2*pi",),
        {"range": EvidenceStatus.CONTRACT_VERIFIED, "period": EvidenceStatus.CONTRACT_VERIFIED}),
    "cos": FunctionProperties("cos", Domain("Real"), Domain("Real"),
        CertifiedRange(-1, 1, EvidenceStatus.CONTRACT_VERIFIED), {"even": True}, ("2*pi",),
        {"range": EvidenceStatus.CONTRACT_VERIFIED, "period": EvidenceStatus.CONTRACT_VERIFIED}),
    "sqrt": FunctionProperties("sqrt", Domain("NonnegativeReal", ("x >= 0",)), Domain("NonnegativeReal"),
        CertifiedRange(0, "+inf", EvidenceStatus.CONTRACT_VERIFIED),
        {"nonnegative": True, "monotone": True}, evidence={"domain": EvidenceStatus.CONTRACT_VERIFIED}),
    "abs": FunctionProperties("abs", Domain("Real"), Domain("NonnegativeReal"),
        CertifiedRange(0, "+inf", EvidenceStatus.CONTRACT_VERIFIED), {"nonnegative": True},
        evidence={"range": EvidenceStatus.CONTRACT_VERIFIED}),
}


def _function_from(value: dict[str, Any]) -> FunctionProperties:
    make_domain = lambda item: Domain(item["description"], tuple(item.get("constraints", []))) if item else None
    return FunctionProperties(value["name"], make_domain(value.get("domain")),
        make_domain(value.get("codomain")),
        CertifiedRange(value["certified_range"]["lower"], value["certified_range"]["upper"],
                       EvidenceStatus(value["certified_range"]["evidence"]), value["certified_range"].get("proof_reference"))
        if value.get("certified_range") else None, value.get("properties", {}), tuple(value.get("periods", [])),
        {key: EvidenceStatus(item) for key, item in value.get("evidence", {}).items()})


def function_properties(name: str) -> FunctionProperties:
    return _function_from(_native_math("FUNCTION_PROPERTIES", name=name))


def propagate_properties(expression: dict[str, Any]) -> FunctionProperties:
    """Derive only elementary range/property facts with explicit evidence."""
    return _function_from(_native_math("PROPAGATE", expression=expression))


def range_condition_status(condition: dict[str, Any]) -> str:
    """Return a CFG reachability fact only when a certified range entails it."""
    return str(_native_math("RANGE_STATUS", condition=condition))


@dataclass(frozen=True)
class MathematicalRelation:
    kind: str
    left: Any
    right: Any
    conditions: tuple[str, ...] = ()
    evidence: EvidenceStatus = EvidenceStatus.DECLARED


@dataclass
class Sequence:
    index: str
    term: dict[str, Any]
    lower: Any = 0


@dataclass
class InfiniteProcess:
    kind: str
    sequence: Sequence
    convergence: MathematicalRelation | None = None
    rate: dict[str, Any] | None = None
    origins: OriginSet = field(default_factory=OriginSet)

    def partial(self, stop: Any) -> dict[str, Any]:
        return _native_math("PARTIAL", process=asdict(self), stop=stop)

    def partial_symmetric(self, radius: int) -> dict[str, Any]:
        return _native_math("PARTIAL_SYMMETRIC", process=asdict(self), radius=radius)

    def tail(self, start: Any) -> dict[str, Any]:
        return _native_math("TAIL", process=asdict(self), start=start)


@dataclass(frozen=True)
class PowerSeries:
    coefficient: dict[str, Any]
    variable: str
    center: Any
    index: str = "n"

    def term(self) -> dict[str, Any]:
        return _native_math("POWER_TERM", series=asdict(self))


@dataclass(frozen=True)
class TaylorSeries:
    function: str
    variable: str = "x"
    center: Any = 0
    index: str = "n"

    def process(self) -> InfiniteProcess:
        return _process_from(_native_math("TAYLOR_PROCESS", series=asdict(self)))


@dataclass(frozen=True)
class FourierSeries:
    function: str
    variable: str = "x"
    period: Any = "2*pi"
    convention: str = "complex_exponential"

    def process(self) -> InfiniteProcess:
        return _process_from(_native_math("FOURIER_PROCESS", series=asdict(self)))


def _relation_from(value: dict[str, Any] | None) -> MathematicalRelation | None:
    return None if value is None else MathematicalRelation(value["kind"], value.get("left"), value.get("right"),
        tuple(value.get("conditions", [])), EvidenceStatus(value.get("evidence", "UNRESOLVED")))


def _process_from(value: dict[str, Any]) -> InfiniteProcess:
    sequence = value["sequence"]
    origins = OriginSet([SourceOrigin(**item) for item in value.get("origins", {}).get("origins", [])])
    return InfiniteProcess(value["kind"], Sequence(sequence["index"], sequence["term"], sequence.get("lower", 0)),
                           _relation_from(value.get("convergence")), value.get("rate"), origins)


def series_evaluation_candidates(process: InfiniteProcess) -> list[dict[str, Any]]:
    return _native_math("SERIES_CANDIDATES", process=asdict(process))


@dataclass(frozen=True)
class ConvergenceResult:
    status: str
    test: str
    conditions: tuple[str, ...]
    evidence: EvidenceStatus
    tail_bound: dict[str, Any] | None = None


def analyze_convergence(process: InfiniteProcess, assumptions: Iterable[str] = ()) -> ConvergenceResult:
    """Apply deliberately small, sound convergence contracts.

    Metadata such as ``family_id`` may select a theorem, but theorem conditions
    must still occur in the supplied assumptions.
    """
    value = _native_math("ANALYZE_CONVERGENCE", process=asdict(process), assumptions=list(assumptions))
    return ConvergenceResult(value["status"], value["test"], tuple(value["conditions"]),
                             EvidenceStatus(value["evidence"]), value.get("tail_bound"))


@dataclass(frozen=True)
class TruncationRequirement:
    tolerance: float
    uniform_domain: tuple[float, float] | None = None
    norm: str = "absolute"


@dataclass(frozen=True)
class TruncationSolution:
    status: str
    minimum_terms: int | None
    remainder_bound: str | None
    distinction: str = "CERTIFIED_REMAINDER_NOT_TERM_MAGNITUDE"


class TruncationRequirementSolver:
    def solve(self, convergence: ConvergenceResult, requirement: TruncationRequirement,
              *, parameters: Mapping[str, float] | None = None) -> TruncationSolution:
        value = _native_math("SOLVE_TRUNCATION", convergence=asdict(convergence), requirement=asdict(requirement),
                             parameters=dict(parameters or {}))
        if value["status"] == "TRUNCATION_REQUIRES_SYMBOLIC_SOLVER":
            value["remainder_bound"] = str(convergence.tail_bound)
        return TruncationSolution(**value)


@dataclass(frozen=True)
class TransformSemantics:
    name: str
    variable: str
    frequency: str
    kernel: dict[str, Any]
    domain: Domain
    inverse: str | None = None
    region_of_convergence: tuple[str, ...] = ()


TRANSFORMS = {
    "fourier": TransformSemantics("FourierTransform", "t", "omega",
        {"op": "FunctionCall", "name": "exp", "args": [{"op": "Multiply", "args": [
            {"op": "Constant", "value": "-i"}, {"op": "Multiply", "args": [
                {"op": "FreeVariable", "name": "omega"}, {"op": "FreeVariable", "name": "t"}]}]}]},
        Domain("IntegrableFunctions"), "InverseFourierTransform"),
    "laplace": TransformSemantics("LaplaceTransform", "t", "s",
        {"op": "FunctionCall", "name": "exp", "args": [{"op": "Negate", "args": [
            {"op": "Multiply", "args": [{"op": "FreeVariable", "name": "s"},
                                           {"op": "FreeVariable", "name": "t"}]}]}]},
        Domain("ExponentialOrderFunctions"), "InverseLaplaceTransform", ("Re(s) > growth_bound",)),
}


def integral_transform(name: str, function: dict[str, Any]) -> dict[str, Any]:
    return _native_math("INTEGRAL_TRANSFORM", name=name, function=function)


def inverse_mapping(transform: dict[str, Any], *, assumptions: Iterable[str] = ()) -> MathematicalRelation:
    return _relation_from(_native_math("INVERSE_MAPPING", transform=transform, assumptions=list(assumptions)))


def convolution(left: dict[str, Any], right: dict[str, Any], *, domain: str = "discrete") -> dict[str, Any]:
    return _native_math("CONVOLUTION", left=left, right=right, domain=domain)


def discrete_transform_layers(kind: str = "dft") -> dict[str, Any]:
    return _native_math("DISCRETE_LAYERS", kind=kind)


PRIMITIVES = frozenset({
    "Factorial", "Binomial", "GCD", "LCM", "Floor", "Ceil", "Min", "Max", "Abs",
    "Limit", "Derivative", "PartialDerivative", "Integral", "Gamma", "Exp", "Log",
    "Sin", "Cos", "Tan", "Sinh", "Cosh", "FiniteSum", "FiniteProduct",
})
