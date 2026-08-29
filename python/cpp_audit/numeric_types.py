"""Conservative execution-dtype analysis for Python scientific calculations.

This module does not change Mathematical Expression IR.  It records the concrete
execution representation beside that IR and fails closed when a dtype transition
cannot be derived from an explicit rule.
"""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .core import AuditError


class OverflowSemantics(str, Enum):
    UNBOUNDED_INTEGER = "UNBOUNDED_INTEGER"
    MODULAR_WRAP = "MODULAR_WRAP"
    IEEE_INFINITY = "IEEE_INFINITY"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNRESOLVED = "UNRESOLVED"


class UnderflowSemantics(str, Enum):
    GRADUAL_SUBNORMAL = "GRADUAL_SUBNORMAL"
    FLUSH_TO_ZERO_POSSIBLE = "FLUSH_TO_ZERO_POSSIBLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class NumericExecutionType:
    dtype: str
    kind: str
    bits: int | None
    signed: bool | None
    mathematical_domain: str
    container: str = "python.scalar"
    shape: list[int] | None = None
    dimensions: list[str] | None = None
    overflow: str = OverflowSemantics.UNRESOLVED.value
    underflow: str = UnderflowSemantics.UNRESOLVED.value
    provenance: str = "inferred"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NumericCast:
    source: str
    target: str
    expression: str
    explicit: bool
    exact: str
    source_span: dict[str, int]


@dataclass(frozen=True)
class PromotionRule:
    left: str
    right: str
    result: str
    operator: str
    rule: str
    source_span: dict[str, int]


@dataclass
class NumericTypeAnalysis:
    status: str
    mathematical_domain: dict[str, Any]
    inputs: dict[str, NumericExecutionType]
    values: dict[str, NumericExecutionType]
    outputs: dict[str, NumericExecutionType]
    casts: list[NumericCast] = field(default_factory=list)
    promotions: list[PromotionRule] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mathematical_domain": deepcopy(self.mathematical_domain),
            "inputs": {name: value.to_dict() for name, value in self.inputs.items()},
            "values": {name: value.to_dict() for name, value in self.values.items()},
            "outputs": {name: value.to_dict() for name, value in self.outputs.items()},
            "casts": [asdict(item) for item in self.casts],
            "promotion_rules": [asdict(item) for item in self.promotions],
            "diagnostics": deepcopy(self.diagnostics),
        }


_DTYPES: dict[str, tuple[str, int | None, bool | None, str, str, str]] = {
    "bool": ("bool", 1, None, "Boolean", OverflowSemantics.NOT_APPLICABLE.value, UnderflowSemantics.NOT_APPLICABLE.value),
    "int8": ("integer", 8, True, "Integer", OverflowSemantics.MODULAR_WRAP.value, UnderflowSemantics.NOT_APPLICABLE.value),
    "int16": ("integer", 16, True, "Integer", OverflowSemantics.MODULAR_WRAP.value, UnderflowSemantics.NOT_APPLICABLE.value),
    "int32": ("integer", 32, True, "Integer", OverflowSemantics.MODULAR_WRAP.value, UnderflowSemantics.NOT_APPLICABLE.value),
    "int64": ("integer", 64, True, "Integer", OverflowSemantics.MODULAR_WRAP.value, UnderflowSemantics.NOT_APPLICABLE.value),
    "uint8": ("integer", 8, False, "Natural", OverflowSemantics.MODULAR_WRAP.value, UnderflowSemantics.NOT_APPLICABLE.value),
    "uint16": ("integer", 16, False, "Natural", OverflowSemantics.MODULAR_WRAP.value, UnderflowSemantics.NOT_APPLICABLE.value),
    "uint32": ("integer", 32, False, "Natural", OverflowSemantics.MODULAR_WRAP.value, UnderflowSemantics.NOT_APPLICABLE.value),
    "uint64": ("integer", 64, False, "Natural", OverflowSemantics.MODULAR_WRAP.value, UnderflowSemantics.NOT_APPLICABLE.value),
    "float16": ("float", 16, True, "Real", OverflowSemantics.IEEE_INFINITY.value, UnderflowSemantics.GRADUAL_SUBNORMAL.value),
    "float32": ("float", 32, True, "Real", OverflowSemantics.IEEE_INFINITY.value, UnderflowSemantics.GRADUAL_SUBNORMAL.value),
    "float64": ("float", 64, True, "Real", OverflowSemantics.IEEE_INFINITY.value, UnderflowSemantics.GRADUAL_SUBNORMAL.value),
    "complex64": ("complex", 64, True, "Complex", OverflowSemantics.IEEE_INFINITY.value, UnderflowSemantics.GRADUAL_SUBNORMAL.value),
    "complex128": ("complex", 128, True, "Complex", OverflowSemantics.IEEE_INFINITY.value, UnderflowSemantics.GRADUAL_SUBNORMAL.value),
    "python.int": ("integer", None, True, "Integer", OverflowSemantics.UNBOUNDED_INTEGER.value, UnderflowSemantics.NOT_APPLICABLE.value),
    "python.float": ("float", 64, True, "Real", OverflowSemantics.IEEE_INFINITY.value, UnderflowSemantics.GRADUAL_SUBNORMAL.value),
    "python.complex": ("complex", 128, True, "Complex", OverflowSemantics.IEEE_INFINITY.value, UnderflowSemantics.GRADUAL_SUBNORMAL.value),
    "unknown": ("unknown", None, None, "Unknown", OverflowSemantics.UNRESOLVED.value, UnderflowSemantics.UNRESOLVED.value),
}

_ALIASES = {
    "int": "python.int", "float": "python.float", "complex": "python.complex",
    "boolean": "bool", "double": "float64", "single": "float32",
    "np.bool_": "bool", "numpy.bool_": "bool",
}


def _native_numeric(action: str, **payload: Any) -> dict[str, Any]:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "F",
            "operation": "LEGACY_NUMERIC_TYPES", "action": action, **payload})["result"]


def _type_from_dict(value: dict[str, Any]) -> NumericExecutionType:
    return NumericExecutionType(**value)


def _span(node: ast.AST) -> dict[str, int]:
    return {"line": getattr(node, "lineno", 0), "column": getattr(node, "col_offset", 0),
            "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
            "end_column": getattr(node, "end_col_offset", getattr(node, "col_offset", 0))}


def _shape(value: Any) -> list[int]:
    result: list[int] = []
    while isinstance(value, (list, tuple)):
        result.append(len(value))
        if not value:
            break
        value = value[0]
    return result


def _flatten(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        result: list[Any] = []
        for item in value:
            result.extend(_flatten(item))
        return result
    return [value]


def _literal_shape(node: ast.AST) -> list[int] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int): return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)) and all(isinstance(item, ast.Constant) and isinstance(item.value, int) for item in node.elts):
        return [item.value for item in node.elts]
    return None


def execution_type(dtype: str, *, container: str = "python.scalar", shape: list[int] | None = None,
                   dimensions: list[str] | None = None, provenance: str = "declared") -> NumericExecutionType:
    return _type_from_dict(_native_numeric("EXECUTION_TYPE", dtype=dtype, container=container,
                                          shape=shape, dimensions=dimensions, provenance=provenance))


def infer_value_type(value: Any, override: str | dict[str, Any] | None = None) -> NumericExecutionType:
    if isinstance(override, dict):
        return execution_type(str(override.get("dtype", "unknown")),
                              container=str(override.get("container", "numpy.ndarray")),
                              shape=list(override.get("shape", _shape(value))),
                              dimensions=list(override["dimensions"]) if override.get("dimensions") else None,
                              provenance="caller dtype contract")
    container = "python.list" if isinstance(value, (list, tuple)) else "python.scalar"
    values = _flatten(value)
    if override:
        return execution_type(override, container="numpy.ndarray" if isinstance(value, (list, tuple)) else "numpy.scalar",
                              shape=_shape(value), provenance="caller dtype contract")
    profile = {"container": container, "shape": _shape(value),
               "has_complex": any(isinstance(item, complex) for item in values),
               "has_float": any(isinstance(item, float) for item in values),
               "all_bool": bool(values) and all(isinstance(item, bool) for item in values),
               "all_int": bool(values) and all(isinstance(item, int) and not isinstance(item, bool) for item in values)}
    return _type_from_dict(_native_numeric("INFER_VALUE", profile=profile))


def _replace(value: NumericExecutionType, **changes: Any) -> NumericExecutionType:
    data = value.to_dict(); data.update(changes)
    return NumericExecutionType(**data)


def _promoted_dtype(left: NumericExecutionType, right: NumericExecutionType) -> tuple[str, str] | None:
    if "unknown" in {left.dtype, right.dtype}:
        return None
    # Python scalars retain Python arithmetic when no array/scalar library dtype participates.
    if left.dtype.startswith("python.") and right.dtype.startswith("python."):
        order = {"python.int": 0, "python.float": 1, "python.complex": 2}
        result = max((left.dtype, right.dtype), key=lambda item: order[item])
        return result, "PYTHON_NUMERIC_TOWER"
    # Python scalar precision is weak, but a higher numeric kind still widens.
    if left.dtype.startswith("python.") != right.dtype.startswith("python."):
        scalar, concrete = (left, right) if left.dtype.startswith("python.") else (right, left)
        rank = {"bool": 0, "integer": 1, "float": 2, "complex": 3}
        if rank[scalar.kind] <= rank[concrete.kind]:
            return concrete.dtype, "WEAK_PYTHON_SCALAR_REQUIRES_REPRESENTABILITY"
        if scalar.kind == "float": return "float64", "PYTHON_SCALAR_KIND_WIDENING"
        if scalar.kind == "complex":
            return ("complex64" if (concrete.bits or 64) <= 32 else "complex128"), "PYTHON_SCALAR_KIND_WIDENING"
        return concrete.dtype, "WEAK_PYTHON_SCALAR_REQUIRES_REPRESENTABILITY"
    if left.dtype == "bool": return right.dtype, "BOOL_PROMOTION"
    if right.dtype == "bool": return left.dtype, "BOOL_PROMOTION"
    if left.kind == "complex" or right.kind == "complex":
        bits = max((item.bits or 0) if item.kind == "complex" else 2 * (item.bits or 0) for item in (left, right))
        return ("complex128" if bits > 64 else "complex64"), "COMPLEX_WIDENING"
    if left.kind == "float" or right.kind == "float":
        bits = max(item.bits or 0 for item in (left, right))
        return ("float64" if bits > 32 else "float32" if bits > 16 else "float16"), "FLOAT_WIDENING"
    if left.kind == right.kind == "integer":
        if left.signed == right.signed:
            prefix = "int" if left.signed else "uint"
            return f"{prefix}{max(left.bits or 0, right.bits or 0)}", "INTEGER_WIDENING"
        signed = left if left.signed else right
        unsigned = right if left.signed else left
        if (signed.bits or 0) > (unsigned.bits or 0):
            return signed.dtype, "SIGNED_UNSIGNED_SAFE_WIDENING"
        for bits in (16, 32, 64):
            if bits > (unsigned.bits or 0): return f"int{bits}", "SIGNED_UNSIGNED_SAFE_WIDENING"
        return "float64", "SIGNED_UNSIGNED_NO_INTEGER_SUPERTYPE"
    return None


class _Analyzer:
    def __init__(self, path: Path, inputs: dict[str, NumericExecutionType]):
        self.path = path
        self.inputs = inputs
        self.env = deepcopy(inputs)
        self.casts: list[NumericCast] = []
        self.promotions: list[PromotionRule] = []
        self.diagnostics: list[dict[str, Any]] = []
        self.return_type: NumericExecutionType | None = None

    def unresolved(self, code: str, node: ast.AST, message: str) -> NumericExecutionType:
        self.diagnostics.append({"code": code, "message": message, "source_span": {"file": str(self.path), **_span(node)}})
        return execution_type("unknown", provenance=code)

    def promote(self, left: NumericExecutionType, right: NumericExecutionType, node: ast.AST) -> NumericExecutionType:
        decision = _native_numeric("PROMOTE", left=left.to_dict(), right=right.to_dict())
        if decision["status"] != "RESOLVED":
            return self.unresolved(decision["code"], node, decision["message"])
        result = _type_from_dict(decision["type"])
        self.promotions.append(PromotionRule(left.dtype, right.dtype, result.dtype, type(node).__name__, decision["rule"], _span(node)))
        return result

    def expr(self, node: ast.AST) -> NumericExecutionType:
        if isinstance(node, ast.Constant):
            return infer_value_type(node.value)
        if isinstance(node, ast.Name):
            return self.env.get(node.id) or self.unresolved("TYPE_UNRESOLVED", node, f"dtype of {node.id} is unknown")
        if isinstance(node, ast.UnaryOp): return self.expr(node.operand)
        if isinstance(node, ast.Compare):
            operands = [self.expr(part) for part in [node.left, *node.comparators]]
            return _type_from_dict(_native_numeric("BOOLEAN_RESULT", vectorized=any(value.shape for value in operands)))
        if isinstance(node, ast.BoolOp):
            for value in node.values: self.expr(value)
            return _type_from_dict(_native_numeric("BOOLEAN_RESULT", vectorized=False))
        if isinstance(node, ast.IfExp):
            self.expr(node.test); return self.promote(self.expr(node.body), self.expr(node.orelse), node)
        if isinstance(node, ast.BinOp):
            left, right = self.expr(node.left), self.expr(node.right)
            decision = _native_numeric("BINARY_RESULT", left=left.to_dict(), right=right.to_dict(),
                                       operator=type(node.op).__name__)
            if decision["status"] != "RESOLVED":
                return self.unresolved(decision["code"], node, decision["message"])
            result = _type_from_dict(decision["type"])
            self.promotions.append(PromotionRule(left.dtype, right.dtype, decision["promotion_type"]["dtype"], type(node.op).__name__,
                                                  decision["rule"], _span(node.op)))
            return result
        if isinstance(node, ast.Subscript): return self.expr(node.value)
        if isinstance(node, (ast.List, ast.Tuple)):
            if not node.elts: return execution_type("unknown", container="python.list", shape=[0])
            result = self.expr(node.elts[0])
            for item in node.elts[1:]: result = self.promote(result, self.expr(item), node)
            return _replace(result, container="python.list", shape=[len(node.elts), *(result.shape or [])])
        if isinstance(node, ast.Call): return self.call(node)
        if isinstance(node, ast.Attribute): return self.expr(node.value)
        return self.unresolved("TYPE_UNRESOLVED", node, f"unsupported dtype AST: {type(node).__name__}")

    def call(self, node: ast.Call) -> NumericExecutionType:
        name = ast.unparse(node.func)
        short = name.rsplit(".", 1)[-1]
        # dtype syntax in ``astype`` is frontend metadata, not a numeric operand.
        args = [] if short == "astype" else [self.expr(arg) for arg in node.args]
        receiver = None
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in self.env:
            receiver = self.expr(node.func.value)
        dtype = None; dimensions = None
        for keyword in node.keywords:
            if keyword.arg == "dtype":
                dtype = keyword.value.value if isinstance(keyword.value, ast.Constant) else ast.unparse(keyword.value).rsplit(".", 1)[-1]
            if keyword.arg == "dims" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                dimensions = [str(item.value) for item in keyword.value.elts if isinstance(item, ast.Constant)]
        if short == "astype" and node.args:
            dtype_node = node.args[0]
            dtype = dtype_node.value if isinstance(dtype_node, ast.Constant) else ast.unparse(dtype_node).rsplit(".", 1)[-1]
        if short == "full" and dtype is None and len(args) > 1: dtype = args[1].dtype
        decision = _native_numeric("CALL_RESULT", name=name, short=short,
                                   args=[value.to_dict() for value in args],
                                   receiver=receiver.to_dict() if receiver else None,
                                   dtype=str(dtype) if dtype is not None else None,
                                   dimensions=dimensions,
                                   literal_shape=_literal_shape(node.args[0]) if node.args else None)
        if decision["status"] != "RESOLVED":
            return self.unresolved(decision["code"], node, decision["message"])
        result = _type_from_dict(decision["type"])
        cast = decision.get("cast")
        if cast:
            self.casts.append(NumericCast(cast["source"], cast["target"], ast.unparse(node),
                                          cast["explicit"], cast["exact"], _span(node)))
        return result

    def assign(self, target: ast.AST, value: NumericExecutionType) -> None:
        if isinstance(target, ast.Name): self.env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts: self.assign(item, value)

    def block(self, statements: list[ast.stmt]) -> None:
        for stmt in statements:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                value = self.expr(stmt.value)
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets: self.assign(target, value)
            elif isinstance(stmt, ast.AugAssign):
                self.assign(stmt.target, self.promote(self.expr(stmt.target), self.expr(stmt.value), stmt.op))
            elif isinstance(stmt, ast.Return): self.return_type = self.expr(stmt.value) if stmt.value else None
            elif isinstance(stmt, ast.If):
                self.expr(stmt.test); before = deepcopy(self.env)
                self.block(stmt.body); left = deepcopy(self.env); self.env = deepcopy(before)
                self.block(stmt.orelse); right = deepcopy(self.env)
                self.env = before
                for name in left.keys() & right.keys(): self.env[name] = self.promote(left[name], right[name], stmt)
            elif isinstance(stmt, (ast.For, ast.While)):
                if isinstance(stmt, ast.While): self.expr(stmt.test)
                elif isinstance(stmt.target, ast.Name): self.env[stmt.target.id] = execution_type("python.int", provenance="loop induction variable")
                self.block(stmt.body); self.block(stmt.orelse)
            elif isinstance(stmt, ast.Expr): self.expr(stmt.value)


def analyze_numeric_types(source: str | Path, *, function: str | None = None, output: str | None = None,
                          inputs: dict[str, Any] | None = None,
                          input_dtypes: dict[str, str | dict[str, Any]] | None = None) -> NumericTypeAnalysis:
    path = Path(source)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    selected = next((node for node in functions if node.name == function), None) if function else (functions[0] if len(functions) == 1 else None)
    if not isinstance(selected, ast.FunctionDef): raise AuditError("NUMERIC_TYPE_FUNCTION_NOT_FOUND_OR_AMBIGUOUS")
    supplied = inputs or {}; overrides = input_dtypes or {}
    defaults = {arg.arg: default for arg, default in zip(selected.args.args[-len(selected.args.defaults):], selected.args.defaults)} if selected.args.defaults else {}
    input_types: dict[str, NumericExecutionType] = {}
    for arg in selected.args.args:
        if arg.arg in supplied or arg.arg in overrides:
            input_types[arg.arg] = infer_value_type(supplied.get(arg.arg), overrides.get(arg.arg))
        elif arg.arg in defaults and isinstance(defaults[arg.arg], ast.Constant):
            input_types[arg.arg] = _replace(infer_value_type(defaults[arg.arg].value), provenance="default argument")
    analyzer = _Analyzer(path, input_types)
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)) and isinstance(statement.value, ast.Constant):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                if isinstance(target, ast.Name): analyzer.env[target.id] = _replace(infer_value_type(statement.value.value), provenance="module constant")
    analyzer.block(selected.body)
    outputs: dict[str, NumericExecutionType] = {}
    if output and output in analyzer.env: outputs[output] = analyzer.env[output]
    elif analyzer.return_type: outputs[output or "return"] = analyzer.return_type
    else: analyzer.diagnostics.append({"code": "OUTPUT_DTYPE_UNRESOLVED", "message": f"dtype of selected output {output!r} is unknown"})
    summary = _native_numeric("ANALYSIS_SUMMARY", outputs={name: value.to_dict() for name, value in outputs.items()},
                              diagnostics=analyzer.diagnostics,
                              domains=[value.mathematical_domain for value in [*input_types.values(), *outputs.values()]])
    return NumericTypeAnalysis(summary["status"], summary["mathematical_domain"],
        input_types, analyzer.env, outputs, analyzer.casts, analyzer.promotions, analyzer.diagnostics)
