"""Execution certificates for independently extracted Python numeric expressions.

The executor is intentionally small and never imports or executes the audited module.
It interprets the supported numeric AST with caller supplied values, while the formula
continues to come from :mod:`python_audit`'s backward slice.
"""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import os
from typing import Any

from .core import AuditError
from .expression import render_expression
from .python_audit import (AuditMode, FormulaParser, audit_python, compare_symbolic,
                           generate_lean)
from .python_cfg import build_python_cfg
from .numeric_types import analyze_numeric_types
from .ieee754 import RoundingMode, analyze_ieee754
from .parallel_semantics import analyze_parallel_semantics
from .transformations import apply_transformation_set
from .approximation_proofs import approximation_proof_coverage, resolve_approximation_proof
from .error_ir import build_error_analysis


class ConstantKind(str, Enum):
    LITERAL_CONSTANT = "LITERAL_CONSTANT"
    NAMED_CONSTANT = "NAMED_CONSTANT"
    DEFAULT_ARGUMENT = "DEFAULT_ARGUMENT"
    CONFIG_CONSTANT = "CONFIG_CONSTANT"
    FILE_LOADED_PARAMETER = "FILE_LOADED_PARAMETER"
    DERIVED_CONSTANT = "DERIVED_CONSTANT"


class ClaimStatus(str, Enum):
    KERNEL_VERIFIED = "KERNEL_VERIFIED"
    KERNEL_VERIFIED_UNDER_ASSUMPTIONS = "KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
    REFERENCE_CONTRACT_ONLY = "REFERENCE_CONTRACT_ONLY"
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    FAILED = "FAILED"


@dataclass
class ConstantNode:
    symbol: str
    kind: str
    definition: dict[str, Any]
    dependencies: list[str]
    resolved_value: Any
    exact_rational: dict[str, int] | None
    expanded_exact_rational: dict[str, int] | None
    approximate_value: float | None
    exactness: str
    source: dict[str, Any]


@dataclass
class ConstantDependencyGraph:
    nodes: list[ConstantNode] = field(default_factory=list)
    edges: list[dict[str, str]] = field(default_factory=list)

    def validate(self) -> None:
        names = {node.symbol for node in self.nodes}
        if len(names) != len(self.nodes):
            raise AuditError("DUPLICATE_CONSTANT_SYMBOL")
        incoming = {name: 0 for name in names}
        outgoing = {name: [] for name in names}
        for edge in self.edges:
            if edge["source"] not in names or edge["target"] not in names:
                raise AuditError("UNKNOWN_CONSTANT_DEPENDENCY")
            incoming[edge["target"]] += 1
            outgoing[edge["source"]].append(edge["target"])
        ready = [name for name, count in incoming.items() if count == 0]
        visited = 0
        while ready:
            current = ready.pop(); visited += 1
            for target in outgoing[current]:
                incoming[target] -= 1
                if incoming[target] == 0: ready.append(target)
        if visited != len(names):
            raise AuditError("CONSTANT_DEPENDENCY_CYCLE")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"nodes": [asdict(node) for node in self.nodes], "edges": deepcopy(self.edges)}

    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass
class AuditCertificate:
    status: str
    audit_id: str
    target: dict[str, Any]
    control_flow_summary: dict[str, Any]
    numeric_type_semantics: dict[str, Any]
    ieee754_semantics: dict[str, Any]
    parallel_semantics: dict[str, Any]
    allowed_transformation_sets: list[dict[str, Any]]
    transformation_trace: dict[str, Any]
    transformed_theory: dict[str, Any] | None
    applied_rules: list[dict[str, Any]]
    rejected_rules: list[dict[str, Any]]
    remaining_obligations: list[dict[str, Any]]
    comparison_relation: str
    residual_candidate: dict[str, Any] | None
    approximation_proofs: list[dict[str, Any]]
    approximation_coverage: list[dict[str, Any]]
    residual_expression: dict[str, Any]
    error_specification: dict[str, Any]
    error_components: list[dict[str, Any]]
    error_composition: dict[str, Any]
    proof_obligations: list[dict[str, Any]]
    graph_enclosure: dict[str, Any]
    error_summary: dict[str, Any]
    inputs: list[dict[str, Any]]
    constants: dict[str, Any]
    theory: dict[str, Any] | None
    implementation: dict[str, Any]
    comparison: dict[str, Any] | None
    output: dict[str, Any]
    library_contracts: list[dict[str, Any]]
    lean: dict[str, Any]
    verification_certificate: dict[str, Any]
    diagnostics: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(asdict(self))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return sha256(_canonical(value).encode()).hexdigest()


def _ir_constant(value: Any) -> dict[str, Any]:
    return {"op": "Constant", "value": value}


def _ir_name(name: str) -> dict[str, Any]:
    return {"op": "FreeVariable", "name": name}


def _expr_ir(node: ast.AST) -> dict[str, Any]:
    if isinstance(node, ast.Constant): return _ir_constant(node.value)
    if isinstance(node, ast.Name): return _ir_name(node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return {"op": "Negate", "args": [_expr_ir(node.operand)]}
    if isinstance(node, ast.BinOp):
        names = {ast.Add: "Add", ast.Sub: "Subtract", ast.Mult: "Multiply", ast.Div: "Divide", ast.Pow: "Power"}
        if type(node.op) not in names: raise AuditError("UNSUPPORTED_CONSTANT_EXPRESSION")
        return {"op": names[type(node.op)], "args": [_expr_ir(node.left), _expr_ir(node.right)]}
    if isinstance(node, ast.Subscript):
        indices = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        return {"op": "IndexedValue", "name": ast.unparse(node.value), "indices": [_expr_ir(item) for item in indices]}
    raise AuditError(f"UNSUPPORTED_CONSTANT_EXPRESSION: {type(node).__name__}")


def _fraction(node: ast.AST, values: dict[str, Fraction]) -> Fraction:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Fraction(str(node.value))
    if isinstance(node, ast.Name) and node.id in values: return values[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub): return -_fraction(node.operand, values)
    if isinstance(node, ast.BinOp):
        left, right = _fraction(node.left, values), _fraction(node.right, values)
        if isinstance(node.op, ast.Add): return left + right
        if isinstance(node.op, ast.Sub): return left - right
        if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node.op, ast.Div): return left / right
        if isinstance(node.op, ast.Pow) and right.denominator == 1: return left ** right.numerator
    raise AuditError("NON_EXACT_CONSTANT_EXPRESSION")


def _unreduced_fraction(node: ast.AST, values: dict[str, Fraction]) -> tuple[int, int]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        value = Fraction(str(node.value)); return value.numerator, value.denominator
    if isinstance(node, ast.Name) and node.id in values:
        value = values[node.id]; return value.numerator, value.denominator
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        numerator, denominator = _unreduced_fraction(node.operand, values); return -numerator, denominator
    if isinstance(node, ast.BinOp):
        an, ad = _unreduced_fraction(node.left, values); bn, bd = _unreduced_fraction(node.right, values)
        if isinstance(node.op, ast.Add): return an * bd + bn * ad, ad * bd
        if isinstance(node.op, ast.Sub): return an * bd - bn * ad, ad * bd
        if isinstance(node.op, ast.Mult): return an * bn, ad * bd
        if isinstance(node.op, ast.Div): return an * bd, ad * bn
    raise AuditError("NON_EXACT_CONSTANT_EXPRESSION")


def _names(node: ast.AST) -> set[str]:
    return {part.id for part in ast.walk(node) if isinstance(part, ast.Name)}


def _numeric_literals(node: ast.AST) -> list[ast.Constant]:
    """Numeric expression literals, excluding API-control metadata such as axis."""
    if isinstance(node, ast.Constant): return [node] if isinstance(node.value, (int, float)) else []
    if isinstance(node, ast.Call):
        return [literal for arg in node.args for literal in _numeric_literals(arg)]
    if isinstance(node, ast.keyword): return []
    result: list[ast.Constant] = []
    for child in ast.iter_child_nodes(node): result.extend(_numeric_literals(child))
    return result


def _selected_function(tree: ast.Module, function: str | None) -> ast.FunctionDef:
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    matches = [node for node in functions if function is None or node.name == function]
    if not matches: raise AuditError("PYTHON_FUNCTION_NOT_FOUND")
    if function is None and len(matches) > 1:
        decorated = [node for node in matches if any("theory" in ast.unparse(d) for d in node.decorator_list)]
        if len(decorated) == 1: return decorated[0]
        raise AuditError("PYTHON_FUNCTION_AMBIGUOUS")
    return matches[0]


def _slice_names(fn: ast.FunctionDef, output: str | None) -> set[str]:
    assignments: dict[str, ast.AST] = {}
    returned: ast.AST | None = None
    for stmt in fn.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            value = stmt.value
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for target in targets:
                if isinstance(target, ast.Name): assignments[target.id] = value
        elif isinstance(stmt, ast.Return): returned = stmt.value
    pending = [output] if output else list(_names(returned) if returned else [])
    used: set[str] = set()
    while pending:
        name = pending.pop()
        if not name or name in used: continue
        used.add(name)
        if name in assignments: pending.extend(_names(assignments[name]) - used)
    return used


def extract_constant_graph(text: str, *, function: str | None = None, output: str | None = None,
                           config_constants: dict[str, Any] | None = None,
                           file_parameters: dict[str, Any] | None = None) -> ConstantDependencyGraph:
    tree = ast.parse(text); fn = _selected_function(tree, function); used = _slice_names(fn, output)
    config_constants, file_parameters = config_constants or {}, file_parameters or {}
    assignments: list[tuple[str, ast.AST, int]] = []
    for stmt in [*tree.body, *fn.body]:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            assignments.append((stmt.targets[0].id, stmt.value, stmt.lineno))
    assignment_map = {name: expr for name, expr, _ in assignments if name in used}
    visiting: set[str] = set(); visited: set[str] = set()
    def check_cycle(name: str) -> None:
        if name in visiting: raise AuditError("CONSTANT_DEPENDENCY_CYCLE")
        if name in visited or name not in assignment_map: return
        visiting.add(name)
        for dependency in _names(assignment_map[name]) & assignment_map.keys(): check_cycle(dependency)
        visiting.remove(name); visited.add(name)
    for name in assignment_map: check_cycle(name)
    defaults = dict(zip([arg.arg for arg in fn.args.args][-len(fn.args.defaults):], fn.args.defaults)) if fn.args.defaults else {}
    nodes: list[ConstantNode] = []; exact: dict[str, Fraction] = {}; known: set[str] = set()

    def add(symbol: str, kind: ConstantKind, expr: ast.AST, value: Any, provenance: dict[str, Any]) -> None:
        deps = sorted(_names(expr) & known)
        try:
            frac = _fraction(expr, exact)
            rational = {"numerator": frac.numerator, "denominator": frac.denominator}
            expanded_pair = _unreduced_fraction(expr, exact)
            expanded = {"numerator": expanded_pair[0], "denominator": expanded_pair[1]}
            exact[symbol] = frac
        except (AuditError, ZeroDivisionError): rational, expanded = None, None
        is_float = isinstance(value, float)
        nodes.append(ConstantNode(symbol, kind.value, _expr_ir(expr), deps, value, rational, expanded,
                                  float(value) if is_float else (float(frac) if rational and kind is ConstantKind.DERIVED_CONSTANT else None),
                                  "EXACT_RATIONAL_WITH_FLOAT_PRESENTATION" if rational and is_float else ("EXACT_RATIONAL" if rational else "APPROXIMATE_ONLY"), provenance))
        known.add(symbol)

    for symbol, expr in defaults.items():
        if symbol in used and isinstance(expr, ast.Constant) and isinstance(expr.value, (int, float)):
            add(symbol, ConstantKind.DEFAULT_ARGUMENT, expr, expr.value, {"kind": "function_default", "line": expr.lineno})
    changed = True
    while changed:
        changed = False
        for symbol, expr, line in assignments:
            if symbol in known or symbol not in used or symbol == output: continue
            deps = _names(expr)
            if isinstance(expr, ast.Constant) and isinstance(expr.value, (int, float)):
                add(symbol, ConstantKind.NAMED_CONSTANT, expr, expr.value, {"kind": "source_assignment", "line": line}); changed = True
            elif deps and deps <= known:
                try: value = float(_fraction(expr, exact))
                except (AuditError, ZeroDivisionError): continue
                add(symbol, ConstantKind.DERIVED_CONSTANT, expr, value, {"kind": "derived_assignment", "line": line}); changed = True
    assigned_constant_locations = {(expr.lineno, expr.col_offset) for _, expr, _ in assignments
                                   if isinstance(expr, ast.Constant)}
    literal_seen: set[tuple[int, int]] = set()
    for symbol, expr, _ in assignments:
        if symbol not in used: continue
        for literal in _numeric_literals(expr):
            location = (getattr(literal, "lineno", -1), getattr(literal, "col_offset", -1))
            if (isinstance(literal, ast.Constant) and isinstance(literal.value, (int, float))
                    and location not in assigned_constant_locations and location not in literal_seen):
                literal_seen.add(location)
                add(f"literal_{location[0]}_{location[1]}", ConstantKind.LITERAL_CONSTANT, literal, literal.value,
                    {"kind": "inline_literal", "line": location[0], "column": location[1]})
    external = [(config_constants, ConstantKind.CONFIG_CONSTANT), (file_parameters, ConstantKind.FILE_LOADED_PARAMETER)]
    for mapping, kind in external:
        for source_expr, raw in mapping.items():
            if source_expr not in text: continue
            item = raw if isinstance(raw, dict) else {"value": raw}
            symbol = item.get("symbol") or "external_" + "".join(c if c.isalnum() else "_" for c in source_expr).strip("_")
            value = item["value"]
            try:
                fraction = Fraction(str(value))
                rational = {"numerator": fraction.numerator, "denominator": fraction.denominator}
                exactness = "EXACT_RATIONAL_WITH_FLOAT_PRESENTATION" if isinstance(value, float) else "EXACT_RATIONAL"
            except (ValueError, TypeError): rational, exactness = None, "APPROXIMATE_ONLY"
            expression_ast = ast.parse(source_expr, mode="eval").body
            nodes.append(ConstantNode(str(symbol), kind.value, _expr_ir(expression_ast), [], value, rational, rational,
                                      float(value) if isinstance(value, float) else None, exactness,
                                      {"kind": kind.value.lower(), "expression": source_expr, "source": item.get("source")}))
            known.add(str(symbol))
    edges = [{"source": dep, "target": node.symbol} for node in nodes for dep in node.dependencies]
    graph = ConstantDependencyGraph(nodes, edges); graph.validate(); return graph


def _shape(value: Any) -> list[int]:
    result = []
    while isinstance(value, (list, tuple)):
        result.append(len(value)); value = value[0] if value else None
    return result


def _flatten(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)): return [x for item in value for x in _flatten(item)]
    return [value]


def summarize_value(name: str, value: Any, source: str) -> dict[str, Any]:
    flat = _flatten(value); numeric = [x for x in flat if isinstance(x, (int, float))]
    dtype = "float" if any(isinstance(x, float) for x in flat) else "int" if numeric else type(value).__name__
    result = {"name": name, "source": source, "shape": _shape(value), "dtype": dtype,
              "sha256": _digest(value), "element_count": len(flat)}
    if not isinstance(value, (list, tuple)): result["scalar"] = value
    else:
        result["summary"] = {"minimum": min(numeric) if numeric else None, "maximum": max(numeric) if numeric else None,
                             "sample": flat[:8]}
        if len(flat) <= 16: result["values"] = value
    return result


def _elementwise(left: Any, right: Any, op: ast.operator) -> Any:
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        left_rank, right_rank = len(_shape(left)), len(_shape(right))
        if left_rank > right_rank: return [_elementwise(item, right, op) for item in left]
        if right_rank > left_rank: return [_elementwise(left, item, op) for item in right]
        if len(left) != len(right): raise AuditError("EXECUTION_SHAPE_MISMATCH")
        return [_elementwise(a, b, op) for a, b in zip(left, right)]
    if isinstance(left, (list, tuple)): return [_elementwise(a, right, op) for a in left]
    if isinstance(right, (list, tuple)): return [_elementwise(left, b, op) for b in right]
    if isinstance(op, ast.Add): return left + right
    if isinstance(op, ast.Sub): return left - right
    if isinstance(op, ast.Mult): return left * right
    if isinstance(op, ast.Div): return left / right
    if isinstance(op, ast.Pow): return left ** right
    raise AuditError("EXECUTION_UNSUPPORTED_OPERATOR")


class SafeNumericExecutor:
    def __init__(self, values: dict[str, Any]): self.values = deepcopy(values)

    def expr(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant): return node.value
        if isinstance(node, ast.Name):
            if node.id not in self.values: raise AuditError(f"EXECUTION_INPUT_MISSING: {node.id}")
            return self.values[node.id]
        if isinstance(node, ast.BinOp): return _elementwise(self.expr(node.left), self.expr(node.right), node.op)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub): return _elementwise(0, self.expr(node.operand), ast.Sub())
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not): return not self.expr(node.operand)
        if isinstance(node, ast.Compare):
            left = self.expr(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right = self.expr(comparator)
                ok = ((left < right) if isinstance(operator, ast.Lt) else (left <= right) if isinstance(operator, ast.LtE)
                      else (left > right) if isinstance(operator, ast.Gt) else (left >= right) if isinstance(operator, ast.GtE)
                      else (left == right) if isinstance(operator, ast.Eq) else (left != right))
                if not ok: return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            values = [self.expr(value) for value in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.IfExp): return self.expr(node.body if self.expr(node.test) else node.orelse)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = [self.expr(item) for item in node.elts]
            return tuple(values) if isinstance(node, ast.Tuple) else set(values) if isinstance(node, ast.Set) else values
        if isinstance(node, ast.Dict): return {self.expr(key): self.expr(value) for key, value in zip(node.keys, node.values)}
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            values = self.comprehension(node.elt, node.generators)
            return set(values) if isinstance(node, ast.SetComp) else values
        if isinstance(node, ast.DictComp):
            pairs = self.comprehension(ast.Tuple(elts=[node.key, node.value], ctx=ast.Load()), node.generators)
            return dict(pairs)
        if isinstance(node, ast.Subscript):
            base, index = self.expr(node.value), self.expr(node.slice)
            return base[index]
        if isinstance(node, ast.Attribute):
            base = self.expr(node.value)
            return base[node.attr] if isinstance(base, dict) else getattr(base, node.attr)
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func); args = [self.expr(arg) for arg in node.args]
            kwargs = {kw.arg: self.expr(kw.value) for kw in node.keywords}
            if name in {"np.sum", "numpy.sum", "sum"}: return self.reduce(args[0], kwargs.get("axis"), sum)
            if name in {"np.mean", "numpy.mean"}:
                return self.reduce(args[0], kwargs.get("axis"), lambda xs: sum(xs) / len(xs))
            if name in {"np.prod", "numpy.prod"}:
                def product(xs: list[Any]) -> Any:
                    value = 1
                    for item in xs: value *= item
                    return value
                return self.reduce(args[0], kwargs.get("axis"), product)
            if name in {"abs", "np.abs", "numpy.abs"}: return self.map(args[0], abs)
            if name in {"np.where", "numpy.where"}:
                condition, yes, no = args
                if isinstance(condition, (list, tuple)):
                    return [y if c else n for c, y, n in zip(condition, yes, no)]
                return yes if condition else no
            if name == "range": return list(range(*args))
            if name == "enumerate": return list(enumerate(*args))
            if name == "zip": return list(zip(*args))
            if name == "list": return list(args[0]) if args else []
            if name == "set": return set(args[0]) if args else set()
            if name in {"min", "max"}: return (min if name == "min" else max)(*args)
            raise AuditError(f"EXECUTION_OPAQUE_CALL: {name}")
        raise AuditError(f"EXECUTION_UNSUPPORTED_AST: {type(node).__name__}")

    def comprehension(self, element: ast.AST, generators: list[ast.comprehension], position: int = 0) -> list[Any]:
        if position == len(generators): return [self.expr(element)]
        generator = generators[position]; result = []
        for value in self.expr(generator.iter):
            self.assign(generator.target, value)
            if all(self.expr(condition) for condition in generator.ifs):
                result.extend(self.comprehension(element, generators, position + 1))
        return result

    def map(self, value: Any, fn: Any) -> Any:
        return [self.map(x, fn) for x in value] if isinstance(value, (list, tuple)) else fn(value)

    def reduce(self, value: Any, axis: Any, fn: Any) -> Any:
        if axis is None: return fn(_flatten(value))
        if axis == 1: return [fn(list(row)) for row in value]
        if axis == 0: return [fn([row[i] for row in value]) for i in range(len(value[0]))]
        raise AuditError("EXECUTION_UNSUPPORTED_AXIS")

    def assign(self, target: ast.AST, value: Any) -> None:
        if isinstance(target, ast.Name): self.values[target.id] = value; return
        if isinstance(target, (ast.Tuple, ast.List)):
            for item, part in zip(target.elts, value): self.assign(item, part)
            return
        if isinstance(target, ast.Subscript):
            base, index = self.expr(target.value), self.expr(target.slice); base[index] = value; return
        if isinstance(target, ast.Attribute):
            base = self.expr(target.value)
            if isinstance(base, dict): base[target.attr] = value
            else: setattr(base, target.attr, value)
            return
        raise AuditError("EXECUTION_UNKNOWN_MUTATION_TARGET")

    def block(self, statements: list[ast.stmt]) -> tuple[str | None, Any]:
        for stmt in statements:
            if isinstance(stmt, ast.Assign):
                value = self.expr(stmt.value)
                for target in stmt.targets: self.assign(target, value)
            elif isinstance(stmt, ast.AnnAssign): self.assign(stmt.target, self.expr(stmt.value))
            elif isinstance(stmt, ast.AugAssign):
                self.assign(stmt.target, _elementwise(self.expr(stmt.target), self.expr(stmt.value), stmt.op))
            elif isinstance(stmt, ast.If):
                signal, value = self.block(stmt.body if self.expr(stmt.test) else stmt.orelse)
                if signal: return signal, value
            elif isinstance(stmt, ast.For):
                broke = False
                for item in self.expr(stmt.iter):
                    self.assign(stmt.target, item); signal, value = self.block(stmt.body)
                    if signal == "return": return signal, value
                    if signal == "break": broke = True; break
                    if signal == "continue": continue
                if not broke:
                    signal, value = self.block(stmt.orelse)
                    if signal: return signal, value
            elif isinstance(stmt, ast.While):
                iterations, broke = 0, False
                while self.expr(stmt.test):
                    iterations += 1
                    if iterations > 100000: raise AuditError("EXECUTION_WHILE_LIMIT_EXCEEDED")
                    signal, value = self.block(stmt.body)
                    if signal == "return": return signal, value
                    if signal == "break": broke = True; break
                    if signal == "continue": continue
                if not broke:
                    signal, value = self.block(stmt.orelse)
                    if signal: return signal, value
            elif isinstance(stmt, ast.Try):
                try:
                    signal, value = self.block(stmt.body)
                except Exception as exc:
                    signal, value = None, None
                    matched = False
                    for handler in stmt.handlers:
                        if handler.type is None or type(exc).__name__ == ast.unparse(handler.type):
                            matched = True
                            if handler.name: self.values[handler.name] = exc
                            signal, value = self.block(handler.body); break
                    if not matched: raise
                else:
                    if not signal: signal, value = self.block(stmt.orelse)
                finally:
                    final_signal, final_value = self.block(stmt.finalbody)
                    if final_signal: signal, value = final_signal, final_value
                if signal: return signal, value
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Attribute):
                receiver = self.expr(stmt.value.func.value); args = [self.expr(arg) for arg in stmt.value.args]
                if stmt.value.func.attr == "append": receiver.append(args[0])
                elif stmt.value.func.attr == "extend": receiver.extend(args[0])
                else: raise AuditError(f"EXECUTION_OPAQUE_CALL: {ast.unparse(stmt.value.func)}")
            elif isinstance(stmt, ast.Return): return "return", self.expr(stmt.value) if stmt.value else None
            elif isinstance(stmt, ast.Break): return "break", None
            elif isinstance(stmt, ast.Continue): return "continue", None
            elif isinstance(stmt, ast.Pass): continue
            else: raise AuditError(f"EXECUTION_UNSUPPORTED_STATEMENT: {type(stmt).__name__}")
        return None, None

    def run(self, fn: ast.FunctionDef) -> Any:
        if fn.args.defaults:
            names = [arg.arg for arg in fn.args.args][-len(fn.args.defaults):]
            for name, default in zip(names, fn.args.defaults):
                if name not in self.values: self.values[name] = self.expr(default)
        signal, value = self.block(fn.body)
        if signal == "return": return value
        raise AuditError("EXECUTION_NO_RETURN")


def _replace_constants(node: Any, replacements: list[ConstantNode]) -> Any:
    if isinstance(node, list): return [_replace_constants(x, replacements) for x in node]
    if not isinstance(node, dict): return node
    if node.get("op") == "FunctionCall" and node.get("name") == "dim": return deepcopy(node)
    def semantic(value: Any) -> Any:
        if isinstance(value, list): return [semantic(x) for x in value]
        if not isinstance(value, dict): return value
        return {key: semantic(child) for key, child in value.items()
                if key not in {"shape_constraints", "alignment_constraints", "source_spans", "source_node_ids",
                               "source_span", "operator_span", "callable_span", "argument_spans", "keyword_spans", "condition_span"}}
    for item in replacements:
        if semantic(node) == semantic(item.definition): return _ir_name(item.symbol)
        if node.get("op") == "Constant" and item.kind != ConstantKind.DERIVED_CONSTANT.value and node.get("value") == item.resolved_value:
            return _ir_name(item.symbol)
    return {key: _replace_constants(value, replacements) for key, value in node.items()}


def _registry_hash(root: Path) -> str:
    values = []
    for path in sorted(root.glob("*.yaml")):
        values.append({"path": path.name, "sha256": sha256(path.read_bytes()).hexdigest()})
    return _digest(values)


def _constant_lean(graph: ConstantDependencyGraph) -> tuple[str, list[str]]:
    lines, theorems = [], []
    fractions = {node.symbol: node.exact_rational for node in graph.nodes if node.exact_rational}

    def rational_expression(node: dict[str, Any]) -> tuple[str, str]:
        if node.get("op") == "Constant":
            value = Fraction(str(node["value"])); return str(value.numerator), str(value.denominator)
        if node.get("op") == "FreeVariable" and node.get("name") in fractions:
            value = fractions[node["name"]]; return str(value["numerator"]), str(value["denominator"])
        if node.get("op") == "Negate":
            numerator, denominator = rational_expression(node["args"][0]); return f"(-{numerator})", denominator
        if node.get("op") in {"Add", "Subtract", "Multiply", "Divide"}:
            an, ad = rational_expression(node["args"][0]); bn, bd = rational_expression(node["args"][1])
            if node["op"] == "Add": return f"(({an})*({bd})+({bn})*({ad}))", f"(({ad})*({bd}))"
            if node["op"] == "Subtract": return f"(({an})*({bd})-({bn})*({ad}))", f"(({ad})*({bd}))"
            if node["op"] == "Multiply": return f"(({an})*({bn}))", f"(({ad})*({bd}))"
            return f"(({an})*({bd}))", f"(({ad})*({bn}))"
        raise AuditError("LEAN_UNSUPPORTED_CONSTANT_EXPRESSION")

    for index, node in enumerate(graph.nodes):
        if node.kind != ConstantKind.DERIVED_CONSTANT.value or not node.exact_rational: continue
        theorem = f"derived_constant_{index}_{''.join(c if c.isalnum() else '_' for c in node.symbol)}"
        fraction = node.exact_rational
        numerator, denominator = rational_expression(node.definition)
        lines.extend([f"theorem {theorem} :", f"    (({numerator}) : Int) * {fraction['denominator']} = {fraction['numerator']} * ({denominator}) := by", "  decide", ""])
        theorems.append(theorem)
    return "\n".join(lines), theorems


def _library_lean(contracts: list[dict[str, Any]]) -> tuple[str, list[str], set[str]]:
    supported = {
        "numpy.sum": ("library_semantic_mapping_numpy_sum", "CppAudit.LibraryMapping.numpy_sum_simple_mapping"),
    }
    lines: list[str] = []; theorems: list[str] = []; callables: set[str] = set()
    for contract in contracts:
        callable_name = str(contract.get("callable", ""))
        reference = str(contract.get("reference_status") or contract.get("provenance", {}).get("reference_status", ""))
        if callable_name not in supported or "LEAN_VERIFIED" not in reference: continue
        theorem, source_theorem = supported[callable_name]
        lines.extend([f"theorem {theorem} (values : List Int) :",
                      "    CppAudit.LibraryMapping.numpySumReference values = CppAudit.LibraryMapping.simpleReductionAdd values := by",
                      f"  exact {source_theorem} values", ""])
        theorems.append(theorem); callables.add(callable_name)
    return "\n".join(lines), theorems, callables


def _control_flow_lean(summary: dict[str, Any]) -> tuple[str, list[str]]:
    lines = ["namespace CppAudit.Generated.ControlFlowCertificate", ""]
    theorems: list[str] = []
    if summary["branch_count"] and not summary["unresolved_control_flow"]:
        lines.extend(["theorem branch_normalization {α : Type} (condition : Bool) (yes no : α) :",
                      "    (if condition then yes else no) = match condition with | true => yes | false => no := by",
                      "  cases condition <;> rfl", ""])
        theorems.append("CppAudit.Generated.ControlFlowCertificate.branch_normalization")
    if summary["loop_count"] and "LOOP_NORMALIZED" in summary["statuses"]:
        lines.extend(["theorem finite_fold_step (initial head : Int) (tail : List Int) :",
                      "    CppAudit.foldLeft (fun acc value => acc + value) initial (head :: tail) =",
                      "      CppAudit.foldLeft (fun acc value => acc + value) (initial + head) tail := by",
                      "  rfl", ""])
        theorems.append("CppAudit.Generated.ControlFlowCertificate.finite_fold_step")
    if summary["mutation_count"] and summary["alias_status"] == "ALIASES_RESOLVED":
        lines.extend(["def indexedStateUpdate (state : Nat → α) (index : Nat) (value : α) : Nat → α :=",
                      "  fun query => if query = index then value else state query", "",
                      "theorem indexed_state_update_at (state : Nat → α) (index : Nat) (value : α) :",
                      "    indexedStateUpdate state index value index = value := by",
                      "  simp [indexedStateUpdate]", "",
                      "theorem indexed_state_update_other (state : Nat → α) (index query : Nat) (value : α)",
                      "    (different : query ≠ index) : indexedStateUpdate state index value query = state query := by",
                      "  simp [indexedStateUpdate, different]", ""])
        theorems.extend(["CppAudit.Generated.ControlFlowCertificate.indexed_state_update_at",
                         "CppAudit.Generated.ControlFlowCertificate.indexed_state_update_other"])
    lines.extend(["end CppAudit.Generated.ControlFlowCertificate", ""])
    return "\n".join(lines), theorems


def _lean_versions(root: Path) -> tuple[str, str]:
    try:
        command, environment = _lean_command(root, ["--version"])
        proc = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=15)
        mathlib_version = "NOT_USED"
        manifest = root / "lake-manifest.json"
        if manifest.is_file():
            packages = json.loads(manifest.read_text(encoding="utf-8")).get("packages", [])
            mathlib = next((item for item in packages if item.get("name") == "mathlib"), None)
            if mathlib: mathlib_version = str(mathlib.get("rev", "UNVERIFIED"))
        return (proc.stdout.strip().splitlines()[0] if proc.returncode == 0 else "UNVERIFIED", mathlib_version)
    except (OSError, subprocess.TimeoutExpired): return "UNVERIFIED", "NOT_USED"


def _lean_command(root: Path, arguments: list[str]) -> tuple[list[str], dict[str, str] | None]:
    """Prefer the pinned local executable, avoiding elan's network update check."""
    toolchain_file = root / "lean-toolchain"
    if os.name == "nt" and toolchain_file.is_file():
        toolchain = toolchain_file.read_text(encoding="utf-8").strip().replace("/", "--").replace(":", "---")
        executable = Path.home() / ".elan" / "toolchains" / toolchain / "bin" / "lean.exe"
        if executable.is_file():
            environment = os.environ.copy()
            package_libs = sorted((root / ".lake" / "packages").glob("*/.lake/build/lib/lean"))
            lean_paths = [str(path.resolve()) for path in package_libs if path.is_dir()]
            lean_paths.append(str((root / ".lake" / "build" / "lib" / "lean").resolve()))
            if environment.get("LEAN_PATH"): lean_paths.append(environment["LEAN_PATH"])
            environment["LEAN_PATH"] = os.pathsep.join(lean_paths)
            return [str(executable), *arguments], environment
    return ["lake", "env", "lean", *arguments], None


def execute_audit(source: str | Path, *, inputs: dict[str, Any], output: str | None = None,
                  function: str | None = None, mode: AuditMode | str = AuditMode.STRICT,
                  input_dtypes: dict[str, str | dict[str, Any]] | None = None,
                  rounding_mode: RoundingMode | str = RoundingMode.ROUND_TO_NEAREST_TIES_TO_EVEN,
                  transformation_set: dict[str, Any] | str | Path | None = None,
                  requested_transformations: list[str] | None = None,
                  transformation_assumptions: list[str] | None = None,
                  transformation_context: dict[str, Any] | None = None,
                  error_specification: dict[str, Any] | None = None,
                  error_propagation: dict[str, Any] | None = None,
                  selection_profile: str = "minimum_cost",
                  config_constants: dict[str, Any] | None = None,
                  file_parameters: dict[str, Any] | None = None,
                  verify_lean: bool = True, lean_file: str | Path | None = None,
                  source_provenance: dict[str, Any] | None = None) -> AuditCertificate:
    path = Path(source); text = path.read_text(encoding="utf-8"); source_hash = sha256(text.encode()).hexdigest()
    repository_root = Path(__file__).resolve().parents[2]
    tree = ast.parse(text, filename=str(path)); fn = _selected_function(tree, function)
    cfg = build_python_cfg(path, function=fn.name, output=output)
    type_analysis = analyze_numeric_types(path, function=fn.name, output=output,
                                          inputs=inputs, input_dtypes=input_dtypes)
    static = audit_python(path, output=output, function=fn.name, mode=AuditMode.REPORT_ONLY, verify_lean=False)
    graph = extract_constant_graph(text, function=fn.name, output=output,
                                   config_constants=config_constants, file_parameters=file_parameters)
    implementation = deepcopy(static.implementation)
    implementation["control_flow_ir"] = cfg.to_dict()
    # Anonymous literals lack stable source correspondence in the current expression
    # IR; global value replacement could rewrite axis/bounds with the same number.
    given_constants = [node for node in graph.nodes if node.kind not in {ConstantKind.DERIVED_CONSTANT.value,
                                                                         ConstantKind.LITERAL_CONSTANT.value}]
    derived_constants = [node for node in graph.nodes if node.kind == ConstantKind.DERIVED_CONSTANT.value]
    implementation["outputs"] = _replace_constants(implementation["outputs"], given_constants)
    implementation["outputs"] = _replace_constants(implementation["outputs"], list(reversed(derived_constants)))
    theory_ir = static.theory
    comparison = compare_symbolic(implementation, theory_ir) if theory_ir else None
    transformation_spec = transformation_set
    if isinstance(transformation_set, (str, Path)) and not Path(transformation_set).is_file():
        built_in_set = repository_root / "registry" / "transformations" / "sets" / f"{transformation_set}.yaml"
        if built_in_set.is_file(): transformation_spec = built_in_set
    transformation = (apply_transformation_set(theory_ir, implementation, transformation_spec,
        rules_root=repository_root / "registry" / "transformations" / "rules",
        requested_rule_ids=requested_transformations, assumptions=transformation_assumptions or [],
        context=transformation_context, selection_profile=selection_profile)
        if transformation_spec is not None and theory_ir is not None else None)
    effective_comparison = (transformation.comparison if transformation and transformation.comparison and
                            transformation.comparison.get("match") else comparison)
    ieee754 = analyze_ieee754(path, function=fn.name, inputs=inputs, numeric_types=type_analysis,
                              implementation_ir=implementation, theory_ir=theory_ir,
                              mathematical_match=bool(comparison and comparison.get("match")),
                              rounding_mode=rounding_mode)
    parallel = analyze_parallel_semantics(path, function=fn.name, numeric_types=type_analysis)
    execution_values = deepcopy(inputs)
    for node in graph.nodes:
        execution_values[node.symbol] = node.resolved_value
        if node.kind in {ConstantKind.CONFIG_CONSTANT.value, ConstantKind.FILE_LOADED_PARAMETER.value}:
            try:
                external = ast.parse(str(node.source.get("expression")), mode="eval").body
                if isinstance(external, ast.Subscript) and isinstance(external.value, ast.Name) and isinstance(external.slice, ast.Constant):
                    execution_values.setdefault(external.value.id, {})[external.slice.value] = node.resolved_value
            except (SyntaxError, TypeError): pass
    try:
        result_value = SafeNumericExecutor(execution_values).run(fn)
        execution_error = None
    except AuditError as exc:
        result_value, execution_error = None, str(exc)
    base_lean = generate_lean(effective_comparison or {}, source_hash)
    primary_expression_theorem = "extracted_expression_matches_theory"
    if transformation and transformation.applied_rules:
        primary_expression_theorem = "transformed_expression_matches_implementation"
        base_lean = base_lean.replace("extracted_expression_matches_theory", primary_expression_theorem)
    constant_lean, constant_theorems = _constant_lean(graph)
    library_lean, library_theorems, kernel_library_callables = _library_lean(implementation.get("library_contracts", []))
    control_flow_lean, control_flow_theorems = _control_flow_lean(cfg.summary)
    approximation_theorems = {
        "forward_difference_first_derivative": "CppAudit.Semantics.NumericalApproximation.generated_forward_is_registered",
        "backward_difference_first_derivative": "CppAudit.Semantics.NumericalApproximation.generated_backward_is_registered",
        "central_difference_first_derivative": "CppAudit.Semantics.NumericalApproximation.generated_central_is_registered",
        "central_difference_second_derivative": "CppAudit.Semantics.NumericalApproximation.generated_second_central_is_registered",
        "left_rectangle_rule": "CppAudit.Semantics.NumericalApproximation.generated_left_rectangle_is_registered",
        "right_rectangle_rule": "CppAudit.Semantics.NumericalApproximation.generated_right_rectangle_is_registered",
        "midpoint_rule": "CppAudit.Semantics.NumericalApproximation.generated_midpoint_is_registered",
        "trapezoidal_rule": "CppAudit.Semantics.NumericalApproximation.generated_trapezoidal_is_registered",
        "simpson_rule": "CppAudit.Semantics.NumericalApproximation.generated_simpson_is_registered",
        "linear_interpolation": "CppAudit.Semantics.NumericalApproximation.generated_linear_interpolation_is_registered",
        "nearest_neighbor_interpolation": "CppAudit.Semantics.NumericalApproximation.generated_nearest_is_registered",
        "multilinear_interpolation": "CppAudit.Semantics.NumericalApproximation.generated_multilinear2D_is_registered",
    }
    selected_approximation_theorems = list(dict.fromkeys(approximation_theorems[rule["rule_id"]]
        for rule in (transformation.applied_rules if transformation else []) if rule.get("rule_id") in approximation_theorems))
    error_theorems = {
        "forward_difference_first_derivative": "CppAudit.Approximation.forward_difference_error_bound",
        "backward_difference_first_derivative": "CppAudit.Approximation.backward_difference_error_bound",
        "central_difference_first_derivative": "CppAudit.Approximation.central_difference_error_bound",
        "trapezoidal_rule": "CppAudit.Approximation.composite_trapezoidal_error_bound",
        "nearest_neighbor_interpolation": "CppAudit.Approximation.nearest_interpolation_error_bound",
        "linear_interpolation": "CppAudit.Approximation.linear_interpolation_error_bound_from_remainder",
    }
    selected_error_theorems = list(dict.fromkeys(error_theorems[rule["rule_id"]]
        for rule in (transformation.applied_rules if transformation else []) if rule.get("rule_id") in error_theorems))
    selected_convergence_theorems = (["CppAudit.Approximation.polynomial_error_bound_implies_convergence"]
                                    if selected_error_theorems else [])
    approximation_lean = "\n".join(f"#check {name}" for name in
                                     [*selected_approximation_theorems, *selected_error_theorems, *selected_convergence_theorems])
    residual_theorems = ["CppAudit.Error.exact_equivalence_has_zero_residual",
                         "CppAudit.Error.zero_residual_has_zero_absolute_error",
                         "CppAudit.Error.absolute_error_nonnegative",
                         "CppAudit.Error.componentwise_zero_implies_linf_zero",
                         "CppAudit.Error.absolute_error_triangle"]
    composition_theorems = ["CppAudit.ErrorComposition.add_error_bound",
                            "CppAudit.ErrorComposition.sub_error_bound",
                            "CppAudit.ErrorComposition.scale_error_bound",
                            "CppAudit.ErrorComposition.sum_error_bound",
                            "CppAudit.ErrorComposition.mean_error_bound",
                            "CppAudit.ErrorComposition.mul_error_bound",
                            "CppAudit.ErrorComposition.linear_map_error_bound",
                            "CppAudit.ErrorComposition.linf_sum_bound",
                            "CppAudit.ErrorComposition.linf_to_l1_bound",
                            "CppAudit.ErrorComposition.safe_exact_cancellation"]
    residual_lean = "\n".join(f"#check {name}" for name in [*residual_theorems, *composition_theorems])
    lean_source = "import CppAudit.LibraryMapping\nimport CppAudit.Semantics.NumericDomain\nimport CppAudit.Semantics.FloatingPoint\nimport CppAudit.Semantics.Parallel\nimport CppAudit.Semantics.Transformation\nimport CppAudit.Semantics.NumericalApproximation\nimport CppAudit.Approximation.FiniteDifference\nimport CppAudit.Approximation.Quadrature\nimport CppAudit.Approximation.Interpolation\nimport CppAudit.Error.Residual\nimport CppAudit.ErrorComposition\n" + base_lean + "\n" + constant_lean + "\n" + library_lean + "\n" + control_flow_lean + "\n" + approximation_lean + "\n" + residual_lean
    theorem_names = (([primary_expression_theorem] if effective_comparison and effective_comparison.get("match") else [])
                     + constant_theorems + library_theorems + control_flow_theorems)
    if ieee754.operations:
        theorem_names.append("CppAudit.Semantics.FloatingPoint.evaluated_add_within_contract")
    if parallel.operations:
        theorem_names.append("CppAudit.Semantics.Parallel.parallel_map_equivalent")
    if transformation and any(rule.get("rule_kind") == "EXACT" for rule in transformation.applied_rules):
        theorem_names.extend(dict.fromkeys(rule.get("reference", {}).get("theorem_reference")
                             for rule in transformation.applied_rules if rule.get("rule_kind") == "EXACT" and
                             rule.get("reference", {}).get("theorem_reference")))
    theorem_names.extend(selected_approximation_theorems)
    theorem_names.extend(selected_error_theorems)
    theorem_names.extend(selected_convergence_theorems)
    theorem_names.extend(residual_theorems)
    theorem_names.extend(composition_theorems)
    kernel_verified = False; lean_status = "NOT_RUN"; lean_error = None
    target = Path(lean_file) if lean_file else None
    if target:
        target.parent.mkdir(parents=True, exist_ok=True); target.write_text(lean_source, encoding="utf-8")
    if verify_lean and theorem_names:
        temporary = None
        if target is None:
            temporary = tempfile.NamedTemporaryFile(suffix=".lean", delete=False); temporary.close(); target = Path(temporary.name)
            target.write_text(lean_source, encoding="utf-8")
        root = Path(__file__).resolve().parents[2]
        command, environment = _lean_command(root, [str(target.resolve())])
        try:
            proc = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=60)
            kernel_verified, lean_status = proc.returncode == 0, "KERNEL_VERIFIED" if proc.returncode == 0 else "FAILED"
            if proc.returncode: lean_error = proc.stderr.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            lean_status, lean_error = "UNVERIFIED", str(exc)
        if temporary: target.unlink(missing_ok=True)
    claims = []
    for claim in ("ALPHA_ISOMORPHISM", "EXPRESSION_GRAPH_ISOMORPHISM", "ALGEBRAIC_EQUIVALENCE"):
        status = ClaimStatus.KERNEL_VERIFIED.value if kernel_verified and effective_comparison and effective_comparison.get("match") else (ClaimStatus.UNVERIFIED.value if effective_comparison and effective_comparison.get("match") else ClaimStatus.FAILED.value)
        claims.append({"claim": claim, "status": status})
    constant_assumptions = [node.symbol for node in graph.nodes if node.kind in {ConstantKind.CONFIG_CONSTANT.value, ConstantKind.FILE_LOADED_PARAMETER.value}]
    transformation_conditions = sorted({obligation["statement"] for rule in (transformation.applied_rules if transformation else [])
                                        for obligation in [*rule.get("discharged_obligations", []), *rule.get("remaining_obligations", [])]})
    assumptions = [*constant_assumptions, *transformation_conditions]
    transformation_requires_assumptions = bool(transformation and any(
        rule.get("rule_kind") in {"EXACT_UNDER_ASSUMPTIONS", "APPROXIMATION"} for rule in transformation.applied_rules))
    claims.append({"claim": "CONSTANT_CORRESPONDENCE", "status": (ClaimStatus.KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value if constant_assumptions else ClaimStatus.KERNEL_VERIFIED.value) if kernel_verified and graph.nodes else ClaimStatus.NOT_APPLICABLE.value})
    claims.append({"claim": "DERIVED_CONSTANT_EVALUATION", "status": ClaimStatus.KERNEL_VERIFIED.value if kernel_verified and constant_theorems else ClaimStatus.NOT_APPLICABLE.value})
    for contract in implementation.get("library_contracts", []):
        claims.append({"claim": "LIBRARY_SEMANTIC_MAPPING", "callable": contract.get("qualified_callable") or contract.get("callable"),
                       "status": ClaimStatus.KERNEL_VERIFIED.value if kernel_verified and contract.get("callable") in kernel_library_callables else ClaimStatus.REFERENCE_CONTRACT_ONLY.value})
    unresolved_codes = {item["code"] for item in cfg.summary["unresolved_control_flow"]}
    claims.extend([
        {"claim": "BRANCH_NORMALIZATION", "status": (ClaimStatus.FAILED.value if "BRANCH_MERGE_UNRESOLVED" in unresolved_codes else ClaimStatus.KERNEL_VERIFIED.value if kernel_verified and cfg.summary["branch_count"] else ClaimStatus.NOT_APPLICABLE.value)},
        {"claim": "FINITE_FOLD_NORMALIZATION", "status": (ClaimStatus.KERNEL_VERIFIED.value if kernel_verified and "LOOP_NORMALIZED" in cfg.summary["statuses"] else ClaimStatus.UNVERIFIED.value if cfg.summary["loop_count"] else ClaimStatus.NOT_APPLICABLE.value)},
        {"claim": "STATE_UPDATE_SEMANTICS", "status": (ClaimStatus.FAILED.value if cfg.summary["alias_status"] != "ALIASES_RESOLVED" else ClaimStatus.KERNEL_VERIFIED.value if kernel_verified and cfg.summary["mutation_count"] else ClaimStatus.NOT_APPLICABLE.value)},
        {"claim": "TERMINATION", "status": ClaimStatus.UNVERIFIED.value if cfg.summary["termination_status"] == "TERMINATION_UNPROVEN" else ClaimStatus.NOT_APPLICABLE.value},
        {"claim": "MATHEMATICAL_EXECUTION_DOMAIN_SEPARATION", "status": ClaimStatus.KERNEL_VERIFIED.value if kernel_verified and type_analysis.status == "TYPE_RESOLVED" else ClaimStatus.UNVERIFIED.value},
        {"claim": "IEEE754_ABSTRACT_ROUNDING_CONTRACT", "status": ClaimStatus.KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value if kernel_verified and ieee754.operations else ClaimStatus.NOT_APPLICABLE.value},
        {"claim": "PARALLEL_MAP_SEMANTICS", "status": ClaimStatus.KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value if kernel_verified and parallel.operations and not parallel.diagnostics else ClaimStatus.FAILED.value if parallel.diagnostics else ClaimStatus.NOT_APPLICABLE.value},
        {"claim": "TRANSFORMATION_APPLICATION_SOUNDNESS", "status": ClaimStatus.KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value if kernel_verified and transformation_requires_assumptions else ClaimStatus.KERNEL_VERIFIED.value if kernel_verified and transformation and transformation.applied_rules else ClaimStatus.NOT_APPLICABLE.value},
        {"claim": "DISCRETE_FAMILY_SEMANTICS", "status": ClaimStatus.KERNEL_VERIFIED.value if kernel_verified and selected_approximation_theorems else ClaimStatus.NOT_APPLICABLE.value},
        {"claim": "APPROXIMATION_ERROR_BOUND", "status": ClaimStatus.KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value if kernel_verified and selected_error_theorems else ClaimStatus.NOT_APPLICABLE.value},
        {"claim": "APPROXIMATION_CONVERGENCE", "status": ClaimStatus.KERNEL_VERIFIED_UNDER_ASSUMPTIONS.value if kernel_verified and selected_convergence_theorems else ClaimStatus.NOT_APPLICABLE.value},
        {"claim": "RESIDUAL_ERROR_IR_GENERAL_LEMMAS", "status": ClaimStatus.KERNEL_VERIFIED.value if kernel_verified else ClaimStatus.UNVERIFIED.value},
        {"claim": "ERROR_COMPOSITION_GENERAL_LEMMAS", "status": ClaimStatus.KERNEL_VERIFIED.value if kernel_verified else ClaimStatus.UNVERIFIED.value},
        {"claim": "EXACT_ZERO_RESIDUAL", "status": (ClaimStatus.KERNEL_VERIFIED.value if kernel_verified else ClaimStatus.UNVERIFIED.value)
         if effective_comparison and effective_comparison.get("match") and
            (not transformation or transformation.comparison_relation in {"EXACT_EQUAL", "EQUIVALENT_UNDER_ASSUMPTIONS"})
         else ClaimStatus.NOT_APPLICABLE.value},
    ])
    root = Path(__file__).resolve().parents[2]; lean_version, mathlib_version = _lean_versions(root)
    lean = {"status": lean_status, "kernel_verified": kernel_verified, "source": lean_source,
            "source_sha256": sha256(lean_source.encode()).hexdigest(), "lean_version": lean_version,
            "mathlib_version": mathlib_version, "theorem_names": theorem_names,
            "assumptions": assumptions,
            "claims": claims}
    if target and lean_file: lean["file"] = str(target.resolve())
    diagnostics = [item for item in static.diagnostics if item.get("code") not in {"THEORY_IMPLEMENTATION_MISMATCH", "LEAN_UNAVAILABLE"}]
    diagnostics.extend({"code": item["code"], "message": "critical output control-flow semantics unresolved",
                        "source_span": item.get("source_span")} for item in cfg.summary["unresolved_control_flow"])
    diagnostics.extend(type_analysis.diagnostics)
    diagnostics.extend(ieee754.diagnostics)
    diagnostics.extend(parallel.diagnostics)
    if transformation: diagnostics.extend(transformation.diagnostics)
    if execution_error: diagnostics.append({"code": "EXECUTION_FAILED", "message": execution_error})
    if lean_error: diagnostics.append({"code": "LEAN_VERIFICATION_FAILED", "message": lean_error})
    if theory_ir and not (effective_comparison and effective_comparison.get("match")): diagnostics.append({"code": "THEORY_IMPLEMENTATION_MISMATCH", "message": "symbolic formulas differ after allowed transformations"})
    transformation_failed = bool(transformation and transformation.comparison_relation in {"INCONSISTENT_WITH", "NOT_COMPARABLE"})
    failed = (execution_error or cfg.summary["unresolved_control_flow"] or type_analysis.status != "TYPE_RESOLVED" or ieee754.status != "IEEE754_CONTRACT_RESOLVED" or parallel.diagnostics or transformation_failed or not effective_comparison or not effective_comparison.get("match")
              or (verify_lean and not kernel_verified))
    if failed:
        status = "VERIFICATION_FAILED"
    elif kernel_verified and (assumptions or transformation_requires_assumptions):
        status = "LEAN_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
    elif kernel_verified:
        status = "LEAN_KERNEL_VERIFIED"
    elif effective_comparison and effective_comparison.get("match"):
        status = "PARTIALLY_KERNEL_VERIFIED"
    else:
        status = "REFERENCE_CONTRACT_VERIFIED"
    audit_id = sha256(f"{source_hash}:{output or ''}:{fn.name}".encode()).hexdigest()[:20]
    graph_dict = graph.to_dict()
    target_meta = {"source": str(path.resolve()), "source_sha256": source_hash, "function": fn.name, "selected_output": output,
                   "provenance": source_provenance or {}}
    implementation["renderings"] = {fmt: render_expression(implementation, fmt) for fmt in ("latex", "unicode", "markdown", "json")}
    theory = None if theory_ir is None else {"ir": theory_ir, "renderings": {fmt: render_expression(theory_ir, fmt) for fmt in ("latex", "unicode", "markdown", "json")}}
    output_summary = summarize_value(output or "return", result_value, "restricted AST execution") if execution_error is None else {"error": execution_error}
    selected_family_ids = list(dict.fromkeys(rule.get("reference", {}).get("approximation_family", {}).get("family_id")
        for rule in (transformation.applied_rules if transformation else [])
        if rule.get("reference", {}).get("approximation_family", {}).get("family_id")))
    approximation_proofs = [resolve_approximation_proof(family_id, repository_root=root,
        context=transformation_context or {}, kernel_checked=kernel_verified).to_dict() for family_id in selected_family_ids]
    proof_coverage = approximation_proof_coverage(root, kernel_checked=kernel_verified)
    comparison_relation = transformation.comparison_relation if transformation else ("EXACT_EQUAL" if comparison and comparison.get("match") else "INCONSISTENT_WITH")
    empty_trace = {"source_expression_id": theory_ir.get("expression_id") if theory_ir else None,
                   "target_expression_id": theory_ir.get("expression_id") if theory_ir else None, "applications": []}
    error_analysis = build_error_analysis(theory_ir=theory_ir, implementation_ir=implementation,
        output=output or "return", comparison_relation=comparison_relation, comparison=effective_comparison,
        numeric_type_semantics=type_analysis.to_dict(), ieee754_semantics=ieee754.to_dict(),
        parallel_semantics=parallel.to_dict(), library_contracts=implementation.get("library_contracts", []),
        approximation_proofs=approximation_proofs,
        transformation_trace=(transformation.to_dict()["transformation_trace"] if transformation else empty_trace),
        propagation_context=error_propagation or (transformation_context or {}).get("error_propagation"),
        kernel_checked=kernel_verified,
        specification=error_specification)
    error_data = error_analysis.to_dict()
    hashes = {"theory_expression_hash": _digest(theory_ir), "implementation_expression_hash": _digest(implementation["outputs"]),
              "constant_graph_hash": graph.digest(), "numeric_type_semantics_hash": _digest(type_analysis.to_dict()),
              "ieee754_semantics_hash": _digest(ieee754.to_dict()),
              "parallel_semantics_hash": _digest(parallel.to_dict()),
              "transformation_trace_hash": _digest(transformation.to_dict() if transformation else {}),
              "error_ir_hash": _digest(error_data),
              "library_contract_registry_hash": _registry_hash(root / "registry" / "libraries")}
    verification_certificate = {"audit_id": audit_id, "source_hash": source_hash, **hashes,
        "lean_source_hash": lean["source_sha256"], "lean_version": lean_version, "mathlib_version": mathlib_version,
        "verified_theorem_names": theorem_names if kernel_verified else [], "assumptions": assumptions, "result": status}
    certificate = AuditCertificate(status, audit_id, target_meta, cfg.summary, type_analysis.to_dict(), ieee754.to_dict(), parallel.to_dict(),
        transformation.allowed_transformation_sets if transformation else [],
        transformation.to_dict()["transformation_trace"] if transformation else empty_trace,
        transformation.transformed_theory if transformation else theory_ir,
        transformation.applied_rules if transformation else [], transformation.rejected_rules if transformation else [],
        transformation.remaining_obligations if transformation else [],
        comparison_relation,
        transformation.residual_candidate if transformation else None,
        approximation_proofs, proof_coverage,
        error_data["residual_expression"], error_data["error_specification"], error_data["error_components"],
        error_data["error_composition"], error_data["proof_obligations"], error_data["graph_enclosure"],
        {"component_status": error_data["component_status"], "total_status": error_data["total_status"],
         "known_error_bound": error_data["graph_enclosure"]["known_output_bound"],
         "composition_status": error_data["error_composition"]["status"],
         "enclosure_status": error_data["graph_enclosure"]["status"],
         "error_budget": error_data["graph_enclosure"]["error_budget"]},
        [summarize_value(name, value, "caller supplied") for name, value in inputs.items()],
        {**graph_dict, "sha256": graph.digest()}, theory, implementation, effective_comparison, output_summary,
        implementation.get("library_contracts", []), lean, verification_certificate, diagnostics)
    certificate.target["certificate_hashes"] = hashes
    return certificate


def _latex_escape(value: Any) -> str:
    text = str(value)
    for old, new in (("\\", r"\textbackslash{}"), ("_", r"\_"), ("%", r"\%"), ("&", r"\&"), ("#", r"\#"),
                     ("^", r"\textasciicircum{}")):
        text = text.replace(old, new)
    return text


def _latex_safe_ir(value: Any) -> Any:
    if isinstance(value, list): return [_latex_safe_ir(item) for item in value]
    if not isinstance(value, dict): return value
    result = {key: _latex_safe_ir(child) for key, child in value.items()}
    for key in ("name", "bound_index"):
        name = result.get(key)
        if isinstance(name, str) and "_" in name:
            result[key] = r"\mathrm{" + name.replace("_", r"\_") + "}"
    return result


def _error_bound_latex(value: Any) -> str:
    if value is None: return r"\mathrm{unresolved}"
    if isinstance(value, (int, float)): return str(value)
    if isinstance(value, str): return _latex_escape(value)
    if not isinstance(value, dict): return _latex_escape(value)
    if value.get("op") == "Constant": return str(value.get("value"))
    args = value.get("args", [])
    if value.get("op") == "AddBounds": return " + ".join(_error_bound_latex(item) for item in args)
    if value.get("op") == "MultiplyBounds": return r" \, ".join(_error_bound_latex(item) for item in args)
    if value.get("op") == "DivideBounds" and len(args) == 2:
        return r"\frac{%s}{%s}" % (_error_bound_latex(args[0]), _error_bound_latex(args[1]))
    if value.get("op") == "PowerBound" and len(args) == 2:
        return r"\left(%s\right)^{%s}" % (_error_bound_latex(args[0]), _error_bound_latex(args[1]))
    if value.get("op") == "Negate" and args: return "-" + _error_bound_latex(args[0])
    return r"\mathtt{%s}" % _latex_escape(value.get("op", "bound"))


def render_latex_certificate(certificate: AuditCertificate) -> str:
    data = certificate.to_dict(); constants = data["constants"]["nodes"]
    given = [x for x in constants if x["kind"] != ConstantKind.DERIVED_CONSTANT.value]
    derived = [x for x in constants if x["kind"] == ConstantKind.DERIVED_CONSTANT.value]
    lines = [r"\documentclass{article}", r"\usepackage{amsmath}", r"\usepackage[T1]{fontenc}", r"\begin{document}",
             r"\section*{Audit Target}", r"\texttt{%s::%s} (output: \texttt{%s})\\SHA-256: \texttt{%s}" %
             (_latex_escape(Path(data["target"]["source"]).name), _latex_escape(data["target"]["function"]),
              _latex_escape(data["target"]["selected_output"]), data["target"]["source_sha256"]),
             r"\section*{Control Flow Summary}",
             "CFG: \\texttt{%s}; branches: %s; loops: %s; mutations: %s; aliases: \\texttt{%s}" %
             (_latex_escape(data["control_flow_summary"]["cfg_status"]), data["control_flow_summary"]["branch_count"],
              data["control_flow_summary"]["loop_count"], data["control_flow_summary"]["mutation_count"],
              _latex_escape(data["control_flow_summary"]["alias_status"])),
             r"\section*{Inputs}"]
    for item in data["inputs"]: lines.append(r"\texttt{%s}: shape=%s, dtype=%s, SHA-256=%s\\" % (_latex_escape(item["name"]), item["shape"], item["dtype"], item["sha256"]))
    lines.append(r"\section*{Numeric Representation}")
    for name, item in data["numeric_type_semantics"]["inputs"].items():
        lines.append(r"\texttt{%s}: execution=\texttt{%s}, mathematical=\texttt{%s}, overflow=\texttt{%s}, underflow=\texttt{%s}\\" %
                     (_latex_escape(name), _latex_escape(item["dtype"]), _latex_escape(item["mathematical_domain"]),
                      _latex_escape(item["overflow"]), _latex_escape(item["underflow"])))
    lines.append(r"\section*{Floating-Point Equivalence}")
    for name, item in data["ieee754_semantics"]["equivalence"].items():
        lines.append(r"\texttt{%s}: \texttt{%s}\\" % (_latex_escape(name), _latex_escape(item["status"])))
    lines.append(r"\section*{Parallel Numerical Semantics}")
    lines.append(r"Policy: \texttt{%s}\\" % _latex_escape(data["parallel_semantics"]["overall_policy"]))
    lines.append(r"\section*{Given Constants}")
    for item in given: lines.append(r"\[%s = %s\]\texttt{%s}" % (_latex_escape(item["symbol"]), item["resolved_value"], _latex_escape(item["kind"])))
    lines.append(r"\section*{Derived Constants}")
    for item in derived:
        fraction = item.get("exact_rational")
        exact = (r"\frac{%s}{%s}" % (fraction["numerator"], fraction["denominator"])) if fraction else r"\text{unverified}"
        definition_ir = {"outputs": [{"target": _ir_name(item["symbol"]), "expression": item["definition"]}]}
        lines.append(r"\[" + render_expression(_latex_safe_ir(definition_ir), "latex").strip() + r"\]")
        expanded = item.get("expanded_exact_rational")
        expanded_text = (r"\frac{%s}{%s}" % (expanded["numerator"], expanded["denominator"])) if expanded else r"\text{unverified}"
        if item["exactness"] == "APPROXIMATE_ONLY":
            lines.append(r"\[%s \approx %s\]" % (_latex_escape(item["symbol"]), item["approximate_value"]))
        else:
            decimal = (r" \approx %s" % item["approximate_value"]) if item["approximate_value"] is not None else ""
            lines.append(r"\[%s = %s = %s%s\]" % (_latex_escape(item["symbol"]), expanded_text, exact, decimal))
    theory_latex = render_expression(_latex_safe_ir(data["theory"]["ir"]), "latex").strip() if data["theory"] else r"\text{not registered}"
    implementation_latex = render_expression(_latex_safe_ir({"outputs": data["implementation"]["outputs"]}), "latex").strip()
    lines.extend([r"\section*{Theory Formula}", r"\[" + theory_latex + r"\]", r"\section*{Transformation Trace}"])
    if data["transformation_trace"]["applications"]:
        for step in data["transformation_trace"]["applications"]:
            lines.append(r"\[\Downarrow\quad\text{%s}\]" % _latex_escape(step["rule_id"]))
    else:
        lines.append(r"\textit{No explicitly selected TransformationSet.}")
    lines.append(r"\section*{Transformed Theory}")
    transformed_latex = (render_expression(_latex_safe_ir(data["transformed_theory"]), "latex").strip()
                         if data.get("transformed_theory") else theory_latex)
    lines.append(r"\[" + transformed_latex + r"\]")
    approximation_rules = [rule for rule in data["applied_rules"]
                           if rule.get("reference", {}).get("approximation_family")]
    if approximation_rules:
        lines.append(r"\section*{Numerical Approximation}")
        for rule in approximation_rules:
            family = rule["reference"]["approximation_family"]
            lines.append(r"Family: \texttt{%s}\\" % _latex_escape(family["family_id"]))
            lines.append(r"Discrete semantics: \texttt{%s}\\" % _latex_escape(family["approximation_kind"]))
            if family.get("convergence_order") is not None:
                lines.append(r"Convergence metadata: order %s in \texttt{%s}\\" %
                             (family["convergence_order"], _latex_escape(family.get("convergence_parameter") or "unspecified")))
            axis = rule.get("parameters", {}).get("axis")
            dimension = rule.get("parameters", {}).get("dimension")
            if axis is not None: lines.append(r"Positional axis: \texttt{%s}\\" % _latex_escape(axis))
            if dimension is not None: lines.append(r"Named dimension: \texttt{%s}\\" % _latex_escape(dimension))
            lines.append(r"Convergence proof: \textbf{NOT YET ESTABLISHED}\\")
            lines.append(r"Error verification: \textbf{NOT YET PROVEN}\\")
    if data["approximation_proofs"]:
        lines.append(r"\section*{Formal Approximation Proofs}")
        for proof in data["approximation_proofs"]:
            lines.append(r"\subsection*{%s}" % _latex_escape(proof["family_id"]))
            lines.append(r"Formal theorem: \texttt{%s}\\" % _latex_escape(proof["evidence"].get("lean_theorem_name") or "REFERENCE ONLY"))
            lines.append(r"\[\left|\mathrm{error}\right| \leq \text{%s}\]" % _latex_escape(proof["error_bound"].get("bound") or "unresolved"))
            lines.append(r"Proof status: \texttt{%s}\\" % _latex_escape(proof["proof_status"]))
            lines.append(r"Convergence: \texttt{%s}\\" % _latex_escape(proof["convergence"]["status"]))
            lines.append(r"\textbf{Assumptions}\\")
            for assumption in proof["assumptions"]:
                lines.append(r"\texttt{%s}: %s\\" % (_latex_escape(assumption["discharge_status"]), _latex_escape(assumption["statement"])))
            if proof["remaining_obligations"]:
                lines.append(r"\textbf{Remaining proof obligations: %s}\\" % len(proof["remaining_obligations"]))
    lines.extend([r"\section*{Implementation Formula}", r"\[" + implementation_latex + r"\]",
                  r"\section*{Transformation Comparison}",
                  r"Relation: \texttt{%s}\\" % _latex_escape(data["comparison_relation"])])
    if data["remaining_obligations"]:
        lines.append(r"\textbf{Approximation/error obligations remain unproven.}")
        for obligation in data["remaining_obligations"]:
            lines.append(r"\[%s\]" % _latex_escape(obligation["statement"]))
    lines.append(r"\section*{Residual and Error Analysis}")
    residual = data["residual_expression"]
    if residual.get("expression", {}).get("op") == "Constant" and residual["expression"].get("value") == 0:
        lines.append(r"\[\mathcal{R} = 0\]")
    else:
        lines.append(r"Residual status: \texttt{%s}\\" % _latex_escape(residual["status"]))
    lines.append(r"Metric: \texttt{%s}; component status: \texttt{%s}; total status: \texttt{%s}\\" %
                 (_latex_escape(data["error_specification"]["metric"]),
                  _latex_escape(data["error_summary"]["component_status"]),
                  _latex_escape(data["error_summary"]["total_status"])))
    for component in data["error_components"]:
        lines.append(r"\texttt{%s}: source=\texttt{%s}, bound=\texttt{%s}, proof=\texttt{%s}\\" %
                     (_latex_escape(component["component_id"]), _latex_escape(component["source"]),
                      _latex_escape(component["bound"]["status"]), _latex_escape(component["proof_status"])))
    if data["proof_obligations"]:
        lines.append(r"\textbf{Error proof obligations}\\")
        for obligation in data["proof_obligations"]:
            lines.append(r"\texttt{%s}: %s\\" %
                         (_latex_escape(obligation["kind"]), _latex_escape(obligation["description"])))
    lines.append(r"\section*{Error Source Composition}")
    composition = data["error_composition"]
    lines.append(r"Operation: \texttt{%s}; proof rule: \texttt{%s}; status: \texttt{%s}\\" %
                 (_latex_escape(composition["operation"]), _latex_escape(composition.get("proof_rule") or "unresolved"),
                  _latex_escape(composition["status"])))
    known = data["graph_enclosure"].get("known_output_bound") or {}
    lines.append(r"\[|e_{\mathrm{known}}| \le %s\]" % _error_bound_latex(known.get("symbolic_expression")))
    lines.append(r"Known bound: \texttt{%s}\\" % _latex_escape(known.get("status", "UNRESOLVED")))
    lines.append(r"Total error: \texttt{%s}\\" % _latex_escape(data["error_summary"]["total_status"]))
    budget = data["graph_enclosure"].get("error_budget", {})
    lines.append(r"Tolerance: \texttt{%s}; total tolerance: \texttt{%s}\\" %
                 (_latex_escape(budget.get("known_bound_status", "NOT EVALUATED")),
                  _latex_escape(budget.get("total_tolerance_status", "NOT PROVEN"))))
    if data["graph_enclosure"].get("propagation_trace"):
        lines.append(r"\textbf{Propagation trace}\\")
        for step in data["graph_enclosure"]["propagation_trace"]:
            lines.append(r"\texttt{%s} $\xrightarrow{\mathrm{%s}}$ \texttt{%s} (%s)\\" %
                         (_latex_escape(step["source_component"]), _latex_escape(step["propagation_rule"]),
                          _latex_escape((step["result_bound"] or {}).get("bound_id", "unresolved")),
                          _latex_escape(step["kind"])))
    lines.append(r"\section*{Symbol Correspondence}")
    mapping = (data["comparison"] or {}).get("mapping", {})
    for category in ("symbols", "bound_indices"):
        for left, right in mapping.get(category, {}).items():
            lines.append(r"\[%s \leftrightarrow %s\]" % (_latex_escape(left), _latex_escape(right)))
    lines.extend([
                  r"\section*{Output / Result}", r"\begin{verbatim}", json.dumps(data["output"], ensure_ascii=False, indent=2), r"\end{verbatim}",
                  r"\section*{Library Contracts Used}"])
    for contract in data["library_contracts"]:
        provenance = contract.get("provenance", {})
        lines.append(r"\texttt{%s} $\rightarrow$ %s $\rightarrow$ \texttt{%s}\\" %
                     (_latex_escape(contract.get("callable", "unknown")), _latex_escape(contract.get("family", "unknown")),
                      _latex_escape(provenance.get("reference_status", "UNVERIFIED"))))
    lines.extend([r"\section*{Lean Verification}", r"\begin{verbatim}", json.dumps(data["lean"]["claims"], ensure_ascii=False, indent=2), r"\end{verbatim}",
                  r"\section*{Overall Verification Status}", r"\textbf{%s}" % _latex_escape(data["status"]), r"\end{document}", ""])
    return "\n".join(lines)


def write_certificate(certificate: AuditCertificate, *, json_path: str | Path, latex_path: str | Path) -> None:
    json_target, latex_target = Path(json_path), Path(latex_path)
    json_target.parent.mkdir(parents=True, exist_ok=True); latex_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(certificate.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latex_target.write_text(render_latex_certificate(certificate), encoding="utf-8")
