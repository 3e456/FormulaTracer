"""Mathematical predicates, Boolean logic, selection, and piecewise domains."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


COMPARISONS = frozenset({"Equal", "NotEqual", "LessThan", "LessEqual",
                         "GreaterThan", "GreaterEqual"})
BOOLEAN_OPERATORS = frozenset({"LogicalAnd", "LogicalOr", "LogicalNot",
                               "LogicalXor", "Implies", "Equivalent"})


def _native(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        request = {"schema_version": "1.0", "kernel": "A", "operation": "LOGIC",
                   "action": action, **payload}
        return context.execute_kernel(request)["result"]


def predicate(expression: dict[str, Any], *, domain: str = "Boolean") -> dict[str, Any]:
    return _native("PREDICATE", expression=expression, domain=domain)


def select(condition: dict[str, Any], then: dict[str, Any], otherwise: dict[str, Any], *,
           source_form: str | None = None) -> dict[str, Any]:
    return _native("SELECT", condition=condition, then=then, otherwise=otherwise,
                   source_form=source_form)


def piecewise(cases: Iterable[tuple[dict[str, Any], dict[str, Any]]],
              otherwise: dict[str, Any] | None = None) -> dict[str, Any]:
    values = [{"condition": condition, "expression": expression} for condition, expression in cases]
    return _native("PIECEWISE", cases=values, otherwise=otherwise)


def indicator(condition: dict[str, Any], *, true_value: Any = 1, false_value: Any = 0) -> dict[str, Any]:
    return _native("INDICATOR", condition=condition, true_value=true_value, false_value=false_value)


def canonicalize_logic(node: Any) -> Any:
    return _native("CANONICALIZE", node=node)


@dataclass(frozen=True)
class BranchDomain:
    branch: str
    assumptions: tuple[dict[str, Any], ...]
    expression: dict[str, Any]


@dataclass
class PiecewiseDomainAnalysis:
    branches: list[BranchDomain] = field(default_factory=list)
    global_assumptions: list[dict[str, Any]] = field(default_factory=list)
    status: str = "BRANCH_DOMAINS_PRESERVED"


def analyze_piecewise_domains(node: dict[str, Any]) -> PiecewiseDomainAnalysis:
    value = _native("ANALYZE_DOMAINS", node=node)
    return PiecewiseDomainAnalysis(
        branches=[BranchDomain(item["branch"], tuple(item["assumptions"]), item["expression"])
                  for item in value["branches"]],
        global_assumptions=list(value["global_assumptions"]), status=value["status"])


def evaluate_logic(node: dict[str, Any], env: dict[str, Any],
                   evaluator: Callable[[dict[str, Any], dict[str, Any]], Any]) -> Any:
    op = node.get("op")
    if op == "Predicate":
        return _native("EVALUATE_BOOLEAN", operator=op,
                       values=[bool(evaluator(node["expression"], env))])["value"]
    if op in BOOLEAN_OPERATORS:
        values = [bool(evaluator(item, env)) for item in node.get("args", ())]
        return _native("EVALUATE_BOOLEAN", operator=op, values=values)["value"]
    if op == "Select":
        branch = _native("SELECT_BRANCH", condition=evaluate_logic(node["condition"], env, evaluator))["branch"]
        return evaluator(node[branch], env)
    if op == "Indicator":
        branch = _native("SELECT_BRANCH", condition=evaluate_logic(node["predicate"], env, evaluator))["branch"]
        return node.get("true_value", 1) if branch == "then" else node.get("false_value", 0)
    raise ValueError(f"UNSUPPORTED_LOGIC_OPERATION:{op}")
