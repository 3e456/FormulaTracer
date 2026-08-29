"""Language-neutral symbolic range and interval enclosure analysis.

The engine consumes only Mathematical Expression IR.  Python, Rust, and C++
frontend types never enter the interval rules.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Any, Iterable, Mapping

from .core import AuditError


class RangeStatus(str, Enum):
    EXACT_SINGLETON = "EXACT_SINGLETON"
    KERNEL_VERIFIED_INTERVAL = "KERNEL_VERIFIED_INTERVAL"
    KERNEL_VERIFIED_INTERVAL_UNDER_ASSUMPTIONS = "KERNEL_VERIFIED_INTERVAL_UNDER_ASSUMPTIONS"
    SYMBOLIC_INTERVAL = "SYMBOLIC_INTERVAL"
    INTERVAL_ARITHMETIC_VERIFIED = "INTERVAL_ARITHMETIC_VERIFIED"
    REFERENCE_CONTRACT_INTERVAL = "REFERENCE_CONTRACT_INTERVAL"
    USER_PROVIDED_INTERVAL = "USER_PROVIDED_INTERVAL"
    NUMERICALLY_OBSERVED_ONLY = "NUMERICALLY_OBSERVED_ONLY"
    INTERVAL_UNRESOLVED = "INTERVAL_UNRESOLVED"
    INTERVAL_INVALID = "INTERVAL_INVALID"


class IntervalProofStatus(str, Enum):
    INTERVAL_RULE_KERNEL_VERIFIED = "INTERVAL_RULE_KERNEL_VERIFIED"
    INTERVAL_PROPAGATION_KERNEL_VERIFIED = "INTERVAL_PROPAGATION_KERNEL_VERIFIED"
    INTERVAL_PROPAGATION_SYMBOLIC = "INTERVAL_PROPAGATION_SYMBOLIC"
    INTERVAL_PROPAGATION_PARTIAL = "INTERVAL_PROPAGATION_PARTIAL"
    INTERVAL_UNRESOLVED = "INTERVAL_UNRESOLVED"


class BranchStatus(str, Enum):
    BRANCH_PROVEN_TRUE = "BRANCH_PROVEN_TRUE"
    BRANCH_PROVEN_FALSE = "BRANCH_PROVEN_FALSE"
    BRANCH_INTERVAL_SPLIT = "BRANCH_INTERVAL_SPLIT"
    BRANCH_FEASIBILITY_UNRESOLVED = "BRANCH_FEASIBILITY_UNRESOLVED"


def _native_interval(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "C",
            "operation": "LEGACY_INTERVAL", "action": action, **payload})["result"]


def _interval_payload(value: "Interval") -> dict[str, Any]:
    return asdict(value)


def _interval_from_native(value: dict[str, Any]) -> "Interval":
    return Interval(**{key: item for key, item in value.items() if key in Interval.__dataclass_fields__})


@dataclass(frozen=True)
class SymbolicBound:
    expression: Any
    assumptions: list[str] = field(default_factory=list)


@dataclass
class IntervalEvidence:
    evidence_id: str
    kind: str
    status: str
    theorem_reference: str | None = None
    assumptions: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    proof_authority: bool = False


@dataclass
class IntervalObligation:
    obligation_id: str
    kind: str
    description: str
    status: str = "UNRESOLVED"
    expression: Any | None = None
    required_evidence: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class Interval:
    lower: Any
    upper: Any
    lower_closed: bool = True
    upper_closed: bool = True
    numeric_domain: str = "MATHEMATICAL_RANGE"
    proof_status: str = IntervalProofStatus.INTERVAL_PROPAGATION_SYMBOLIC.value
    provenance: dict[str, Any] = field(default_factory=dict)
    status: str = RangeStatus.SYMBOLIC_INTERVAL.value
    assumptions: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    interval_id: str = ""

    def __post_init__(self) -> None:
        if not self.interval_id:
            self.interval_id = _id("interval", [self.lower, self.upper, self.lower_closed, self.upper_closed,
                                                 self.numeric_domain, self.status, self.assumptions, self.dimensions])
        meta = _native_interval("META", interval=asdict(self))
        if meta["invalid_order"]:
            self.status = RangeStatus.INTERVAL_INVALID.value
            self.proof_status = IntervalProofStatus.INTERVAL_UNRESOLVED.value

    @property
    def resolved(self) -> bool:
        return bool(_native_interval("META", interval=asdict(self))["resolved"])

    @property
    def singleton(self) -> bool:
        return bool(_native_interval("META", interval=asdict(self))["singleton"])

    def to_dict(self) -> dict[str, Any]:
        return _serial(self)


@dataclass
class ValueInterval:
    interval: Interval
    symbol: str
    scope: dict[str, str] = field(default_factory=dict)
    kind: str = "VALUE_INTERVAL"

    def to_dict(self) -> dict[str, Any]: return _serial(self)


@dataclass
class ErrorInterval:
    interval: Interval
    output: str
    component_ids: list[str] = field(default_factory=list)
    total: bool = False
    kind: str = "ERROR_INTERVAL"

    def to_dict(self) -> dict[str, Any]: return _serial(self)


@dataclass
class RangeEnclosure:
    output: str
    value_interval: ValueInterval
    error_interval: ErrorInterval
    true_value_enclosure: Interval
    status: str
    proof_status: str
    obligations: list[IntervalObligation] = field(default_factory=list)
    constraint_status: str | None = None
    kind: str = "TRUE_VALUE_ENCLOSURE"

    def to_dict(self) -> dict[str, Any]: return _serial(self)


@dataclass
class IntervalPropagation:
    output: str
    steps: list[dict[str, Any]]
    evidence: list[IntervalEvidence]
    obligations: list[IntervalObligation]
    status: str
    propagation_id: str = ""

    def __post_init__(self) -> None:
        if not self.propagation_id: self.propagation_id = _id("interval-propagation", [self.output, self.steps])

    def to_dict(self) -> dict[str, Any]: return _serial(self)


@dataclass(frozen=True)
class AffineForm:
    center: Any
    coefficients: dict[str, Any]
    remainder: Interval | None = None
    status: str = "AFFINE_EXTENSION_POINT"


@dataclass
class DependencyAwareRange:
    interval: Interval
    symbol_instances: list[str]
    affine_form: AffineForm | None = None


@dataclass
class InputRange:
    name: str
    lower: Any
    upper: Any
    lower_closed: bool = True
    upper_closed: bool = True
    module: str | None = None
    function: str | None = None
    root: str | None = None
    dimensions: list[str] = field(default_factory=list)
    shape: list[int] = field(default_factory=list)
    item_count: int | None = None
    assumptions: list[str] = field(default_factory=list)
    status: str = RangeStatus.USER_PROVIDED_INTERVAL.value
    provenance: dict[str, Any] = field(default_factory=lambda: {"kind": "USER_RANGE_SPECIFICATION"})

    def interval(self) -> Interval:
        lower, upper = _bound(self.lower), _bound(self.upper)
        return _interval_from_native(_native_interval("INPUT_RANGE", lower=lower, upper=upper,
            lower_closed=self.lower_closed, upper_closed=self.upper_closed, status=self.status,
            provenance=self.provenance, assumptions=self.assumptions, dimensions=self.dimensions))

    @property
    def count(self) -> int | None:
        if self.item_count is not None: return self.item_count
        return math.prod(self.shape) if self.shape else None


@dataclass
class OutputRangeConstraint:
    output: str
    lower: Any
    upper: Any
    lower_closed: bool = True
    upper_closed: bool = True


@dataclass
class RangeSpecification:
    ranges: list[InputRange] = field(default_factory=list)
    output_constraints: list[OutputRangeConstraint] = field(default_factory=list)
    error_ranges: dict[str, InputRange] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)

    @classmethod
    def from_value(cls, value: Any = None, *, output_ranges: Mapping[str, Any] | None = None) -> "RangeSpecification":
        if isinstance(value, cls):
            result = deepcopy(value)
        elif value is None:
            result = cls()
        elif isinstance(value, (list, tuple)) and all(isinstance(item, InputRange) for item in value):
            result = cls(list(value))
        elif isinstance(value, Mapping):
            result = cls(); raw = dict(value)
            constraints = raw.pop("expected_outputs", raw.pop("output_constraints", {}))
            errors = raw.pop("error_ranges", {})
            assumptions = raw.pop("assumptions", [])
            result.assumptions = list(assumptions) if isinstance(assumptions, (list, tuple)) else [str(assumptions)]
            for name, item in raw.items(): result.ranges.append(_input_range(str(name), item))
            for name, item in dict(constraints or {}).items(): result.output_constraints.append(_output_constraint(str(name), item))
            for name, item in dict(errors or {}).items(): result.error_ranges[str(name)] = _input_range(str(name), item)
        else:
            raise AuditError("INVALID_RANGE_SPECIFICATION")
        for name, item in dict(output_ranges or {}).items(): result.output_constraints.append(_output_constraint(str(name), item))
        return result

    def resolve(self, symbol: str) -> InputRange | None:
        exact = [item for item in self.ranges if item.name == symbol]
        if len(exact) == 1: return exact[0]
        short = symbol.replace("::", ".").rsplit(".", 1)[-1]
        candidates = [item for item in self.ranges if item.name == short and
                      (not item.module or item.module in symbol) and (not item.function or item.function in symbol) and
                      (not item.root or item.root in symbol)]
        return candidates[0] if len(candidates) == 1 else None

    def constraint(self, output: str) -> OutputRangeConstraint | None:
        values = [item for item in self.output_constraints if item.output == output]
        return values[0] if len(values) == 1 else None


def _input_range(name: str, value: Any) -> InputRange:
    if isinstance(value, InputRange): return value
    if isinstance(value, (tuple, list)) and len(value) == 2: return InputRange(name, value[0], value[1])
    if isinstance(value, Mapping):
        raw = dict(value); raw.setdefault("name", name)
        try: return InputRange(**raw)
        except TypeError as exc: raise AuditError(f"INVALID_INPUT_RANGE: {name}: {exc}") from exc
    raise AuditError(f"INVALID_INPUT_RANGE: {name}")


def _output_constraint(name: str, value: Any) -> OutputRangeConstraint:
    if isinstance(value, OutputRangeConstraint): return value
    if isinstance(value, (tuple, list)) and len(value) == 2: return OutputRangeConstraint(name, value[0], value[1])
    if isinstance(value, Mapping): return OutputRangeConstraint(name, value["lower"], value["upper"],
        bool(value.get("lower_closed", True)), bool(value.get("upper_closed", True)))
    raise AuditError(f"INVALID_OUTPUT_RANGE_CONSTRAINT: {name}")


def _id(prefix: str, value: Any) -> str:
    return prefix + ":" + sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _set_dimensions(value: Interval, dimensions: Iterable[str]) -> Interval:
    value.dimensions = list(dict.fromkeys(dimensions))
    value.interval_id = _id("interval", [value.lower, value.upper, value.lower_closed, value.upper_closed,
                                          value.numeric_domain, value.status, value.assumptions, value.dimensions])
    return value


def _serial(value: Any) -> Any:
    if isinstance(value, Enum): return value.value
    if isinstance(value, SymbolicBound): return {"expression": _serial(value.expression), "assumptions": list(value.assumptions)}
    if hasattr(value, "__dataclass_fields__"): return {key: _serial(item) for key, item in asdict(value).items()}
    if isinstance(value, dict): return {key: _serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_serial(item) for item in value]
    return value


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _same(left: Any, right: Any) -> bool:
    return json.dumps(_serial(left), sort_keys=True, default=str) == json.dumps(_serial(right), sort_keys=True, default=str)


def _bound(value: Any) -> Any:
    if isinstance(value, SymbolicBound): return deepcopy(value.expression)
    if isinstance(value, str): return {"op": "FreeVariable", "name": value}
    return deepcopy(value)


def _expr(op: str, *args: Any) -> dict[str, Any]: return {"op": op, "args": [deepcopy(item) for item in args]}


def _down(value: float) -> float: return math.nextafter(value, -math.inf)
def _up(value: float) -> float: return math.nextafter(value, math.inf)


def _numeric_binary(op: str, left: Any, right: Any, upward: bool) -> Any:
    if isinstance(left, int) and isinstance(right, int) and op in {"Add", "Subtract", "Multiply"}:
        return {"Add": left + right, "Subtract": left - right, "Multiply": left * right}[op]
    value = {"Add": lambda: float(left) + float(right), "Subtract": lambda: float(left) - float(right),
             "Multiply": lambda: float(left) * float(right), "Divide": lambda: float(left) / float(right)}[op]()
    return _up(value) if upward else _down(value)


def _endpoint(op: str, left: Any, right: Any, upward: bool = False) -> Any:
    return _numeric_binary(op, left, right, upward) if _number(left) and _number(right) else _expr(op, left, right)


def unresolved_interval(code: str, expression: Any = None) -> Interval:
    return _interval_from_native(_native_interval("UNRESOLVED", code=code, expression=expression))


def singleton(value: Any, *, provenance: dict[str, Any] | None = None) -> Interval:
    return _interval_from_native(_native_interval("SINGLETON", value=value,
        provenance=provenance or {"kind": "EXACT_CONSTANT"}))


def _result(lower: Any, upper: Any, rule: str, *inputs: Interval, closed: tuple[bool, bool] = (True, True)) -> Interval:
    return _interval_from_native(_native_interval("COMBINE", lower=lower, upper=upper, rule=rule,
        inputs=[_interval_payload(item) for item in inputs], lower_closed=closed[0], upper_closed=closed[1]))


def interval_add(left: Interval, right: Interval) -> Interval:
    return _interval_from_native(_native_interval("ADD", left=_interval_payload(left), right=_interval_payload(right)))


def interval_neg(value: Interval) -> Interval:
    return _interval_from_native(_native_interval("NEG", value=_interval_payload(value)))


def interval_sub(left: Interval, right: Interval) -> Interval:
    return _interval_from_native(_native_interval("SUB", left=_interval_payload(left), right=_interval_payload(right)))


def interval_mul(left: Interval, right: Interval) -> Interval:
    return _interval_from_native(_native_interval("MUL", left=_interval_payload(left), right=_interval_payload(right)))


def _contains_zero(value: Interval) -> bool:
    return bool(_native_interval("CONTAINS_ZERO", value=_interval_payload(value))["contains_zero"])


def interval_div(left: Interval, right: Interval) -> Interval:
    return _interval_from_native(_native_interval("DIV", left=_interval_payload(left), right=_interval_payload(right)))


def interval_abs(value: Interval) -> Interval:
    return _interval_from_native(_native_interval("ABS", value=_interval_payload(value)))


def interval_power(value: Interval, exponent: Any) -> Interval:
    return _interval_from_native(_native_interval("POWER", value=_interval_payload(value), exponent=exponent))


def interval_hull(values: Iterable[Interval], rule: str = "interval_hull") -> Interval:
    return _interval_from_native(_native_interval("HULL", values=[_interval_payload(item) for item in values], rule=rule))


def simplify_expression(node: Any) -> Any:
    return _native_interval("SIMPLIFY", node=node)


class IntervalEngine:
    def __init__(self, specification: RangeSpecification):
        self.specification = specification; self.steps: list[dict[str, Any]] = []; self.obligations: list[IntervalObligation] = []
        self.evidence: list[IntervalEvidence] = []; self._counter = 0

    def obligation(self, kind: str, description: str, expression: Any = None, required: list[str] | None = None) -> None:
        self._counter += 1; self.obligations.append(IntervalObligation(f"range-obligation:{self._counter}", kind, description,
            expression=deepcopy(expression), required_evidence=list(required or [])))

    def record(self, node: Any, result: Interval, rule: str) -> Interval:
        self.steps.append({"step": len(self.steps), "operation": node.get("op") if isinstance(node, dict) else type(node).__name__,
                           "rule": rule, "result": result.to_dict()})
        theorem = result.provenance.get("theorem")
        if theorem and theorem not in {item.theorem_reference for item in self.evidence}:
            self.evidence.append(IntervalEvidence(_id("interval-evidence", theorem), "LEAN_GENERAL_INTERVAL_RULE",
                "KERNEL_VERIFIED_RULE", theorem, proof_authority=True))
        return result

    def _resolve_name(self, name: str, env: Mapping[str, Interval]) -> Interval:
        if name in env: return env[name]
        short = name.replace("::", ".").rsplit(".", 1)[-1]
        env_matches = [value for key, value in env.items() if key.replace("::", ".").rsplit(".", 1)[-1] == short]
        if len(env_matches) == 1: return env_matches[0]
        spec = self.specification.resolve(name)
        if spec:
            interval = spec.interval()
            if spec.assumptions:
                self.obligation("INTERVAL_ASSUMPTION_REQUIRES_DISCHARGE",
                                f"Input interval for {name} depends on declared assumptions",
                                {"symbol": name, "assumptions": spec.assumptions}, ["ASSUMPTION_PROOF"])
            return interval
        self.obligation("INPUT_INTERVAL_REQUIRED", f"No interval was provided for {name}", {"symbol": name})
        return unresolved_interval("INPUT_INTERVAL_REQUIRED", name)

    def _indexed(self, node: dict[str, Any], env: Mapping[str, Interval]) -> Interval:
        name = str(node.get("name") or node.get("base") or "")
        return self._resolve_name(name, env)

    def _elementary(self, operation: str, value: Interval, node: dict[str, Any]) -> Interval:
        result = _interval_from_native(_native_interval("ELEMENTARY", function=operation,
            value=_interval_payload(value), node=node))
        diagnostic = result.provenance.get("diagnostic")
        details = {
            "SQRT_NEGATIVE_DOMAIN": ("SQRT_DOMAIN_VIOLATION", "sqrt requires a nonnegative lower bound", []),
            "LOG_NONPOSITIVE_DOMAIN": ("LOG_DOMAIN_VIOLATION", "log requires a strictly positive lower bound", []),
            "EXP_RANGE_OVERFLOW": ("EXP_RANGE_OVERFLOW", "exp endpoint exceeds representable host arithmetic", ["SYMBOLIC_EXP_BOUND"]),
            "ELEMENTARY_FUNCTION_RANGE_UNRESOLVED": ("ELEMENTARY_FUNCTION_NUMERIC_DOMAIN_REQUIRED", f"Numeric endpoints required for {operation}", []),
        }
        if diagnostic in details:
            kind, description, required = details[diagnostic]
            self.obligation(kind, description, node, required)
        return _set_dimensions(result, value.dimensions)

    def _condition(self, node: dict[str, Any], env: Mapping[str, Interval]) -> tuple[str, tuple[str, str, float] | None]:
        if node.get("op") != "Compare" or len(node.get("args", [])) != 2: return BranchStatus.BRANCH_FEASIBILITY_UNRESOLVED.value, None
        left_node, right_node = node["args"]; left, right = self.evaluate(left_node, env), self.evaluate(right_node, env)
        native = _native_interval("CONDITION", operator=str(node.get("operator") or node.get("comparison")),
            left=_interval_payload(left), right=_interval_payload(right), left_node=left_node, right_node=right_node)
        refinement = tuple(native["refinement"]) if native.get("refinement") else None
        return native["status"], refinement

    def _refine(self, env: Mapping[str, Interval], refinement: tuple[str, str, float] | None, truth: bool) -> dict[str, Interval]:
        result = dict(env)
        if not refinement: return result
        name, operator, cutoff = refinement; current = result.get(name)
        if current is None:
            specification = self.specification.resolve(name)
            if specification is not None:
                current = specification.interval()
                result[name] = current
        if current is None: return result
        if operator in {"Gt", ">", "GtE", ">="}:
            lower_side = truth
        elif operator in {"Lt", "<", "LtE", "<="}:
            lower_side = not truth
        else: return result
        result[name] = _interval_from_native(_native_interval("REFINE", name=name, operator=operator,
            cutoff=cutoff, truth=truth, value=_interval_payload(current)))
        return result

    def _count(self, node: dict[str, Any], env: Mapping[str, Interval]) -> int | None:
        domain = node.get("index_domain") or {}
        if domain:
            lower, upper = self.evaluate(domain.get("lower", {"op": "Constant", "value": 0}), env), self.evaluate(domain.get("upper_exclusive"), env)
            if lower.singleton and upper.singleton and _number(lower.lower) and _number(upper.lower):
                count = upper.lower - lower.lower
                if float(count).is_integer() and count >= 0: return int(count)
        names = []
        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("op") in {"FreeVariable", "IndexedValue"} and value.get("name"): names.append(value["name"])
                for child in value.values(): visit(child)
            elif isinstance(value, list):
                for child in value: visit(child)
        visit(node)
        specifications = [spec for name in names if (spec := self.specification.resolve(str(name)))]
        axis = node.get("axes", node.get("axis"))
        if isinstance(axis, int):
            axis_counts = [spec.shape[axis] for spec in specifications if spec.shape and -len(spec.shape) <= axis < len(spec.shape)]
            if axis_counts and len(set(axis_counts)) == 1: return axis_counts[0]
        if isinstance(axis, str):
            axis_counts = [spec.shape[spec.dimensions.index(axis)] for spec in specifications
                           if axis in spec.dimensions and len(spec.shape) == len(spec.dimensions)]
            if axis_counts and len(set(axis_counts)) == 1: return axis_counts[0]
        counts = [spec.count for spec in specifications if spec.count]
        return counts[0] if counts and len(set(counts)) == 1 else None

    @staticmethod
    def _reduced_dimensions(node: dict[str, Any], value: Interval) -> list[str]:
        dimensions = list(value.dimensions)
        axes = node.get("axes", node.get("axis"))
        if axes is None:
            return []
        axes = axes if isinstance(axes, (list, tuple)) else [axes] if axes is not None else []
        names = {axis for axis in axes if isinstance(axis, str)}
        indices = {axis % len(dimensions) for axis in axes if isinstance(axis, int) and dimensions}
        return [name for index, name in enumerate(dimensions) if name not in names and index not in indices]

    def evaluate(self, raw: Any, env: Mapping[str, Interval] | None = None) -> Interval:
        env = dict(env or {}); node = simplify_expression(raw)
        if not isinstance(node, dict): return singleton(node) if _number(node) else unresolved_interval("INVALID_EXPRESSION_IR", node)
        op = node.get("op")
        boundary = node.get("language_boundary")
        if isinstance(boundary, dict) and boundary.get("representation_mapping") not in {
            "RANGE_PRESERVING", "REPRESENTATION_MAPPING_VERIFIED", "EXACT_WIDENING"
        }:
            self.obligation(
                "FFI_REPRESENTATION_RANGE_UNRESOLVED",
                "Cross-language range preservation requires verified representation evidence",
                boundary,
                ["FFI_REPRESENTATION_EVIDENCE"],
            )
        if op == "Constant": return self.record(node, singleton(node.get("value")), "exact_constant")
        if op in {"FreeVariable", "BoundVariable"}: return self.record(node, self._resolve_name(str(node.get("name")), env), "input_interval")
        if op == "IndexedValue": return self.record(node, self._indexed(node, env), "tensor_element_interval")
        args = node.get("args", [])
        if op in {"Add", "Subtract", "Multiply", "Divide"} and len(args) >= 2:
            left, right = self.evaluate(args[0], env), self.evaluate(args[1], env)
            result = {"Add": interval_add, "Subtract": interval_sub, "Multiply": interval_mul, "Divide": interval_div}[op](left, right)
            if op == "Divide" and result.provenance.get("diagnostic") == "DIVISION_INTERVAL_CROSSES_ZERO":
                self.obligation("DIVISION_INTERVAL_CROSSES_ZERO", "A denominator interval contains zero", node,
                                ["DENOMINATOR_LOWER_BOUND"])
            return self.record(node, result, f"interval_{op.lower()}")
        if op in {"Negate", "UnaryMinus"}:
            child = node.get("arg") or (args[0] if args else None); return self.record(node, interval_neg(self.evaluate(child, env)), "interval_neg")
        if op in {"Cast", "NumericCast"}:
            child = node.get("arg") or node.get("value") or (args[0] if args else None)
            source = self.evaluate(child, env)
            semantics = node.get("semantics") or node.get("cast_semantics")
            if semantics in {"EXACT_WIDENING", "RANGE_PRESERVING"}:
                return self.record(node, source, "exact_widening_cast")
            self.obligation("CAST_RANGE_UNRESOLVED", "Cast range is not proven range-preserving", node,
                            ["TARGET_TYPE_CAST_SEMANTICS"])
            return self.record(node, unresolved_interval("CAST_RANGE_UNRESOLVED", node), "cast_unresolved")
        if op in {"Abs", "Sqrt", "Log", "Exp", "Sin", "Cos"}:
            child = node.get("arg") or (args[0] if args else None); return self.record(node, self._elementary(op, self.evaluate(child, env), node), f"interval_{op.lower()}")
        if op == "Power" and len(args) == 2:
            base, exponent = self.evaluate(args[0], env), self.evaluate(args[1], env)
            value = exponent.lower if exponent.singleton else None
            result = interval_power(base, int(value)) if _number(value) and float(value).is_integer() else unresolved_interval("POWER_DOMAIN_UNRESOLVED", node)
            if not result.resolved: self.obligation("POWER_DOMAIN_UNRESOLVED", "Only integer powers are certified without additional domain evidence", node)
            return self.record(node, result, "interval_integer_power")
        if op in {"Min", "Max"} and args:
            values = [self.evaluate(item, env) for item in args]
            if not all(item.resolved for item in values): return unresolved_interval("INTERVAL_INPUT_UNRESOLVED", node)
            lowers, uppers = [item.lower for item in values], [item.upper for item in values]
            if all(_number(item) for item in lowers + uppers):
                result = _result(min(lowers), min(uppers), "interval_min", *values) if op == "Min" else _result(max(lowers), max(uppers), "interval_max", *values)
            else:
                result = _result({"op": op, "args": lowers}, {"op": op, "args": uppers}, f"interval_{op.lower()}", *values)
            return self.record(node, result, f"interval_{op.lower()}")
        if op == "IfThenElse":
            status, refinement = self._condition(node.get("condition", {}), env)
            if status == BranchStatus.BRANCH_PROVEN_TRUE.value:
                result = self.evaluate(node.get("then"), self._refine(env, refinement, True))
            elif status == BranchStatus.BRANCH_PROVEN_FALSE.value:
                result = self.evaluate(node.get("else"), self._refine(env, refinement, False))
            else:
                then = self.evaluate(node.get("then"), self._refine(env, refinement, True)); otherwise = self.evaluate(node.get("else"), self._refine(env, refinement, False))
                result = interval_hull([then, otherwise], "branch_interval_hull")
                if status == BranchStatus.BRANCH_FEASIBILITY_UNRESOLVED.value:
                    self.obligation(status, "Branch feasibility could not be proven", node.get("condition"))
            result.provenance["branch_status"] = status
            return self.record(node, result, "branch_sensitive_interval")
        if op == "Match":
            values = [self.evaluate(item.get("value"), env) for item in node.get("arms", [])]
            self.obligation("BRANCH_FEASIBILITY_UNRESOLVED", "Match arm feasibility requires discriminant evidence", node)
            return self.record(node, interval_hull(values, "match_arm_hull"), "match_interval")
        if op in {"Map", "Filter"}:
            iterable = self.evaluate(node.get("iterable") or node.get("input"), env)
            local = dict(env); local[str(node.get("bound_index", "item"))] = iterable
            result = self.evaluate(node.get("body") or node.get("predicate"), local)
            return self.record(node, result, "map_element_interval")
        reduction_kind = str(node.get("reduction") or node.get("name") or "").lower()
        if op == "Reduce" and reduction_kind.endswith("mean"):
            value = self.evaluate(node.get("input") or node.get("iterable"), env); count = self._count(node, env)
            if count is None or count <= 0:
                self.obligation("MEAN_POSITIVE_COUNT_REQUIRED", "Mean requires a proven positive element count", node)
                return unresolved_interval("MEAN_POSITIVE_COUNT_REQUIRED", node)
            return self.record(node, _set_dimensions(value, self._reduced_dimensions(node, value)), "mean_preserves_range")
        if op in {"FiniteSum", "FiniteProduct", "TransformReduce", "Reduce", "FoldLeft", "TransformReduce"}:
            term_node = node.get("transform") or node.get("body") or node.get("input") or node.get("iterable")
            term = self.evaluate(term_node, env); count = self._count(node, env)
            if count is None:
                self.obligation("REDUCTION_COUNT_REQUIRED", "Finite reduction element count is unresolved", node,
                                ["FINITE_ITERATION_COUNT"])
                return self.record(node, unresolved_interval("REDUCTION_COUNT_REQUIRED", node), "interval_sum")
            if op == "FiniteProduct" or reduction_kind.endswith("prod"):
                result = (
                    interval_power(term, count)
                    if _number(term.lower) and term.lower >= 0
                    else unresolved_interval("PRODUCT_REDUCTION_SIGN_UNRESOLVED", node)
                )
            else:
                result = interval_mul(singleton(count), term)
                result.provenance.update({"rule": "interval_sum", "term_count": count, "theorem": "CppAudit.Interval.interval_sum"})
            _set_dimensions(result, self._reduced_dimensions(node, term))
            return self.record(node, result, "interval_sum")
        if op in {"Mean", "mean"}:
            value = self.evaluate(node.get("input") or (args[0] if args else None), env); count = self._count(node, env)
            if count is None or count <= 0:
                self.obligation("MEAN_POSITIVE_COUNT_REQUIRED", "Mean requires a proven positive element count", node)
                return unresolved_interval("MEAN_POSITIVE_COUNT_REQUIRED", node)
            return self.record(node, _set_dimensions(value, self._reduced_dimensions(node, value)), "mean_preserves_range")
        if op in {"TensorContraction", "Dot", "MatMul"}:
            values = [self.evaluate(item, env) for item in args]
            count = self._count(node, env)
            if len(values) < 2 or count is None:
                self.obligation("LINEAR_MAP_COMPONENT_BOUNDS_REQUIRED", "Dot/matmul requires component intervals and contraction extent", node)
                return unresolved_interval("DOT_INTERVAL_UNRESOLVED", node)
            return self.record(node, interval_mul(singleton(count), interval_mul(values[0], values[1])), "componentwise_dot_interval")
        if op == "FunctionCall":
            name = str(node.get("name") or node.get("function") or "").rsplit(".", 1)[-1]
            child_args = node.get("args", [])
            if name in {"abs", "sqrt", "log", "ln", "exp", "sin", "cos"} and child_args:
                return self.record(node, self._elementary(name, self.evaluate(child_args[0], env), node), f"interval_{name}")
            if name in {"sum", "prod", "mean"} and child_args:
                synthetic = {"op": "Mean" if name == "mean" else "FiniteProduct" if name == "prod" else "FiniteSum",
                             "input": child_args[0]}
                return self.evaluate(synthetic, env)
        if op in {"Collection", "Iterator", "Enumerate", "Zip", "Collect"}:
            children = node.get("args") or ([node.get("input")] if node.get("input") is not None else [])
            values = [self.evaluate(item, env) for item in children if item is not None]
            return self.record(node, interval_hull(values, "collection_element_hull"), "collection_interval")
        if op == "ControlFlowSequence":
            if node.get("effects"):
                self.obligation("LOOP_RANGE_INVARIANT_REQUIRED", "General loop effects require a supplied invariant", node.get("effects"),
                                ["LOOP_INVARIANT"])
            return self.record(node, self.evaluate(node.get("result"), env), "loop_result_partial")
        self.obligation("INTERVAL_RULE_UNRESOLVED", f"No interval rule is registered for {op}", node)
        return self.record(node, unresolved_interval("INTERVAL_RULE_UNRESOLVED", node), "unresolved")


def _error_interval(output: Any, specification: RangeSpecification, engine: IntervalEngine) -> tuple[ErrorInterval, bool]:
    explicit = specification.error_ranges.get(output.name)
    if explicit:
        interval = explicit.interval(); interval.provenance["kind"] = "USER_PROVIDED_ERROR_INTERVAL"
        authoritative = explicit.status in {
            RangeStatus.EXACT_SINGLETON.value,
            RangeStatus.KERNEL_VERIFIED_INTERVAL.value,
            RangeStatus.KERNEL_VERIFIED_INTERVAL_UNDER_ASSUMPTIONS.value,
            RangeStatus.REFERENCE_CONTRACT_INTERVAL.value,
        }
        return ErrorInterval(interval, output.name, [], authoritative), authoritative
    components = list(output.error_components or [])
    if not components: return ErrorInterval(singleton(0, provenance={"kind": "NO_ERROR_COMPONENTS"}), output.name, [], True), True
    known: list[Interval] = []; component_ids = []; all_verified = True
    verified_statuses = {"EXACT_ZERO_BOUND", "KERNEL_VERIFIED_BOUND", "KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS",
                         "REFERENCE_CONTRACT_BOUND", "INTERVAL_BOUND"}
    seen_causes: set[str] = set()
    for component in components:
        cause = str(component.get("semantic_cause_id") or component.get("origin_id") or component.get("component_id"))
        if cause in seen_causes:
            continue
        seen_causes.add(cause)
        bound = component.get("bound") or {}; status = bound.get("status"); proof = str(component.get("proof_status", ""))
        component_ids.append(str(component.get("component_id")))
        verified = status in verified_statuses and proof not in {"UNRESOLVED", "FAILED"}
        if not verified:
            all_verified = False; continue
        lower = bound.get("lower_bound"); upper = bound.get("upper_bound")
        if lower is None and upper is None and bound.get("exact_value") == 0: lower = upper = 0
        if lower is None or upper is None:
            expression = bound.get("symmetric_bound") or bound.get("expression")
            if expression is None: all_verified = False; continue
            upper = expression; lower = {"op": "Negate", "arg": deepcopy(expression)}
        known.append(Interval(_bound(lower), _bound(upper), numeric_domain="ERROR_RANGE",
            proof_status=IntervalProofStatus.INTERVAL_PROPAGATION_SYMBOLIC.value,
            provenance={"component_id": component.get("component_id"), "bound_status": status},
            status=RangeStatus.KERNEL_VERIFIED_INTERVAL.value if status.startswith("KERNEL") else RangeStatus.REFERENCE_CONTRACT_INTERVAL.value,
            assumptions=list(component.get("assumptions") or [])))
    if not known:
        return ErrorInterval(unresolved_interval("ERROR_INTERVAL_UNRESOLVED"), output.name, component_ids, False), False
    total = known[0]
    for item in known[1:]: total = interval_add(total, item)
    return ErrorInterval(total, output.name, component_ids, all_verified), all_verified


def _constraint_status(interval: Interval, constraint: OutputRangeConstraint | None) -> str | None:
    if not constraint: return None
    lower, upper = _bound(constraint.lower), _bound(constraint.upper)
    return _native_interval("CONSTRAINT_STATUS", interval=_interval_payload(interval), lower=lower, upper=upper)["status"]


def _execution_checks(output: Any, value: Interval, engine: IntervalEngine) -> dict[str, Any]:
    result = {"kind": "EXECUTION_RANGE", "status": "EXECUTION_RANGE_UNRESOLVED", "interval": None}
    if not value.resolved or not (_number(value.lower) and _number(value.upper)): return result
    implementation = output.implementation if isinstance(output.implementation, dict) else {}
    numeric = implementation.get("numeric_execution") or implementation.get("numeric_type_semantics") or {}
    types = numeric.get("cpp_types") or []
    dtype = str(numeric.get("dtype") or numeric.get("output_dtype") or "")
    selected = "float32" if "float32" in dtype or ("float" in types and "double" not in types) else "float64" if "float64" in dtype or "double" in types else None
    if not selected: return result
    maximum = 3.4028234663852886e38 if selected == "float32" else 1.7976931348623157e308
    minimum_normal = 1.1754943508222875e-38 if selected == "float32" else 2.2250738585072014e-308
    if value.lower < -maximum or value.upper > maximum:
        engine.obligation("OVERFLOW_POSSIBLE", "Mathematical range exceeds the finite execution dtype", value.to_dict(),
                          ["OVERFLOW_RANGE_INTERSECTION"])
        return {"kind": "EXECUTION_RANGE", "status": "FINITE_EXECUTION_ENCLOSURE_INVALIDATED", "interval": None,
                "dtype": selected, "diagnostic": "OVERFLOW_POSSIBLE"}
    subnormal = ((0 < abs(value.lower) < minimum_normal) or (0 < abs(value.upper) < minimum_normal) or
                 (value.lower < 0 < value.upper))
    if subnormal: engine.obligation("SUBNORMAL_RANGE_POSSIBLE", "Range intersects the subnormal or underflow region", value.to_dict())
    return {"kind": "EXECUTION_RANGE", "status": "EXECUTION_RANGE_FINITE", "interval": value.to_dict(),
            "dtype": selected, "subnormal_possible": subnormal}


def analyze_project_ranges(project: Any, ranges: Any = None, *, output_ranges: Mapping[str, Any] | None = None) -> Any:
    specification = RangeSpecification.from_value(ranges, output_ranges=output_ranges)
    project.provenance["range_specification"] = _serial(specification)
    project.provenance["interval_engine_version"] = "formulatracer-interval-v1"
    for output in project.outputs:
        engine = IntervalEngine(specification); simplified = simplify_expression(output.formula)
        value = engine.evaluate(simplified)
        error, all_errors = _error_interval(output, specification, engine)
        if value.resolved and error.interval.resolved:
            true_interval = interval_add(value, error.interval)
            true_interval.numeric_domain = "TRUE_VALUE_RANGE"
            enclosure_status = ("TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED" if all_errors else "PARTIAL_TRUE_VALUE_ENCLOSURE")
        else:
            true_interval = unresolved_interval("TOTAL_TRUE_VALUE_ENCLOSURE_UNRESOLVED")
            enclosure_status = "TOTAL_TRUE_VALUE_ENCLOSURE_UNRESOLVED"
        if not all_errors:
            engine.obligation("UNRESOLVED_ERROR_COMPONENT", "At least one error component lacks a verified interval",
                              {"output": output.name}, ["VERIFIED_ERROR_BOUND"])
        execution = _execution_checks(output, value, engine)
        constraint = _constraint_status(value, specification.constraint(output.name))
        if constraint and constraint != "OUTPUT_RANGE_CONSTRAINT_PROVEN":
            engine.obligation(constraint, f"Output range constraint for {output.name} was not proven", value.to_dict())
        proof_status = (IntervalProofStatus.INTERVAL_PROPAGATION_PARTIAL.value if engine.obligations else
                        IntervalProofStatus.INTERVAL_PROPAGATION_SYMBOLIC.value)
        value_wrapper = ValueInterval(value, output.name, {"output_id": output.output_id})
        enclosure = RangeEnclosure(output.name, value_wrapper, error, true_interval, enclosure_status,
                                   proof_status, list(engine.obligations), constraint)
        propagation = IntervalPropagation(output.name, engine.steps, engine.evidence, engine.obligations, proof_status)
        output.value_interval = value_wrapper.to_dict(); output.error_interval = error.to_dict()
        output.true_value_enclosure = true_interval.to_dict(); output.range_status = enclosure_status
        output.range_obligations = [_serial(item) for item in engine.obligations]
        output.interval_propagation = propagation.to_dict(); output.execution_range = execution
        output.range_constraint_status = constraint
    for artifact in project.artifacts:
        candidates = [output for output in project.outputs if output.name in {artifact.payload_symbol, artifact.dataset_variable}]
        for dataset in getattr(artifact, "dataset_outputs", []):
            candidates.extend(output for output in project.outputs if output.name == dataset.name)
        candidates = list({item.output_id: item for item in candidates}.values())
        if len(candidates) == 1:
            output = candidates[0]; artifact.certified_payload_range = deepcopy(output.value_interval)
            artifact.range_status = output.range_status; artifact.range_obligations = list(output.range_obligations)
            if artifact.dtype and isinstance(output.implementation, dict):
                output_dtype = str((output.implementation.get("numeric_execution") or {}).get("dtype") or "")
                if output_dtype and output_dtype != artifact.dtype:
                    obligation = {"kind": "SERIALIZATION_CAST", "status": "UNRESOLVED", "from": output_dtype, "to": artifact.dtype}
                    artifact.serialization_cast = obligation; artifact.range_obligations.append(obligation)
                    artifact.range_status = "SERIALIZATION_RANGE_UNRESOLVED"
        elif candidates:
            artifact.range_status = "ARTIFACT_PAYLOAD_RANGE_AMBIGUOUS"
    if getattr(project, "end_to_end_claims", None):
        from .end_to_end import build_end_to_end_claims
        return build_end_to_end_claims(project)
    return project
