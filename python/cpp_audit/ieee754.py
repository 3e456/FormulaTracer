"""IEEE-754 execution-contract analysis kept separate from exact mathematics."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from enum import Enum
import math
from pathlib import Path
from typing import Any

from .core import AuditError
from .numeric_types import NumericTypeAnalysis


class RoundingMode(str, Enum):
    ROUND_TO_NEAREST_TIES_TO_EVEN = "ROUND_TO_NEAREST_TIES_TO_EVEN"
    TOWARD_ZERO = "TOWARD_ZERO"
    TOWARD_POSITIVE = "TOWARD_POSITIVE"
    TOWARD_NEGATIVE = "TOWARD_NEGATIVE"
    UNKNOWN = "UNKNOWN"


class EquivalenceStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    ESTABLISHED_UNDER_CONTRACT = "ESTABLISHED_UNDER_CONTRACT"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"
    NOT_EQUIVALENT = "NOT_EQUIVALENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class FloatingOperation:
    operation: str
    source_span: dict[str, int]
    evaluation_order: str
    rounding: str
    exceptional_values: list[str]
    overflow: str
    underflow: str
    fma: str


@dataclass
class IEEE754Analysis:
    status: str
    formats: dict[str, dict[str, Any]]
    operations: list[FloatingOperation]
    evaluation_order: str
    rounding_contract: dict[str, Any]
    special_value_observations: list[dict[str, Any]]
    non_associativity_risks: list[dict[str, Any]]
    fma_contract: str
    equivalence: dict[str, dict[str, Any]]
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "formats": self.formats,
                "operations": [asdict(item) for item in self.operations],
                "evaluation_order": self.evaluation_order,
                "rounding_contract": self.rounding_contract,
                "special_value_observations": self.special_value_observations,
                "non_associativity_risks": self.non_associativity_risks,
                "fma_contract": self.fma_contract, "equivalence": self.equivalence,
                "diagnostics": self.diagnostics}


_FORMAT = {
    "float16": {"radix": 2, "precision_bits": 11, "exponent_bits": 5},
    "float32": {"radix": 2, "precision_bits": 24, "exponent_bits": 8},
    "float64": {"radix": 2, "precision_bits": 53, "exponent_bits": 11},
    "python.float": {"radix": 2, "precision_bits": 53, "exponent_bits": 11},
    "complex64": {"component_dtype": "float32"},
    "complex128": {"component_dtype": "float64"},
    "python.complex": {"component_dtype": "python.float"},
}


def _native_ieee754(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "A",
            "operation": "LEGACY_IEEE754", "action": action, **payload})["result"]


def _span(node: ast.AST) -> dict[str, int]:
    return {"line": getattr(node, "lineno", 0), "column": getattr(node, "col_offset", 0),
            "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
            "end_column": getattr(node, "end_col_offset", getattr(node, "col_offset", 0))}


def _selected_function(tree: ast.Module, function: str | None) -> ast.FunctionDef:
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    selected = next((node for node in functions if node.name == function), None) if function else (functions[0] if len(functions) == 1 else None)
    if selected is None: raise AuditError("IEEE754_FUNCTION_NOT_FOUND_OR_AMBIGUOUS")
    return selected


def _expression_shape(value: Any) -> Any:
    if not isinstance(value, dict): return None
    op = value.get("op")
    if op in {"FreeVariable", "BoundVariable", "Constant", "IndexedValue"}: return "VALUE"
    if op == "IfThenElse": return (op, _expression_shape(value.get("condition")), _expression_shape(value.get("then")), _expression_shape(value.get("else")))
    args = value.get("args")
    if isinstance(args, list): return (op, *[_expression_shape(item) for item in args])
    if op == "Reduce": return (op, value.get("reduction"), _expression_shape(value.get("input")))
    if op in {"FoldLeft", "Map"}: return (op, _expression_shape(value.get("body")))
    return op


def _root_expression(ir: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ir: return None
    outputs = ir.get("outputs", [])
    return outputs[0].get("expression") if outputs else None


def _special_values(name: str, value: Any) -> list[dict[str, Any]]:
    result = []
    def walk(item: Any, index: list[int]) -> None:
        if isinstance(item, (list, tuple)):
            for position, child in enumerate(item): walk(child, [*index, position])
        elif isinstance(item, float):
            if math.isnan(item): kind = "NaN"
            elif math.isinf(item): kind = "+Inf" if item > 0 else "-Inf"
            elif item == 0.0 and math.copysign(1.0, item) < 0: kind = "SIGNED_NEGATIVE_ZERO"
            elif 0.0 < abs(item) < float.fromhex("0x1.0p-1022"): kind = "SUBNORMAL_BINARY64"
            else: return
            result.append({"input": name, "index": index, "kind": kind})
    walk(value, [])
    return result


def analyze_ieee754(source: str | Path, *, function: str | None = None,
                    inputs: dict[str, Any] | None = None,
                    numeric_types: NumericTypeAnalysis,
                    implementation_ir: dict[str, Any] | None = None,
                    theory_ir: dict[str, Any] | None = None,
                    mathematical_match: bool = False,
                    rounding_mode: RoundingMode | str = RoundingMode.ROUND_TO_NEAREST_TIES_TO_EVEN) -> IEEE754Analysis:
    path = Path(source); tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected = _selected_function(tree, function)
    mode = RoundingMode(rounding_mode)
    input_dtypes = {name: item.dtype for name, item in numeric_types.inputs.items()}
    output_dtypes = {name: item.dtype for name, item in numeric_types.outputs.items()}
    floating = any(dtype in _FORMAT for dtype in [*input_dtypes.values(), *output_dtypes.values()])
    operations: list[FloatingOperation] = []
    risks: list[dict[str, Any]] = []
    op_names = {ast.Add: "ADD", ast.Sub: "SUBTRACT", ast.Mult: "MULTIPLY", ast.Div: "DIVIDE", ast.Pow: "POWER", ast.MatMult: "MATMUL"}
    if floating:
        for node in ast.walk(selected):
            if isinstance(node, ast.BinOp) and type(node.op) in op_names:
                fma = "SEPARATE_MULTIPLY_ADD" if isinstance(node.op, (ast.Add, ast.Sub)) and isinstance(node.left, ast.BinOp) and isinstance(node.left.op, ast.Mult) else "NOT_APPLICABLE"
                operations.append(FloatingOperation(op_names[type(node.op)], _span(node), "PYTHON_OPERAND_LEFT_TO_RIGHT",
                    mode.value, ["NaN", "+Inf", "-Inf", "+0", "-0"], "MAY_PRODUCE_INFINITY", "MAY_PRODUCE_SUBNORMAL_OR_ZERO", fma))
            elif isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                short = name.rsplit(".", 1)[-1]
                if short in {"sum", "prod", "mean", "dot", "matmul", "einsum"}:
                    operations.append(FloatingOperation(short.upper(), _span(node), "LIBRARY_REDUCTION_OR_CONTRACTION_ORDER",
                        mode.value, ["NaN", "+Inf", "-Inf", "+0", "-0"], "MAY_PRODUCE_INFINITY", "MAY_PRODUCE_SUBNORMAL_OR_ZERO", "BACKEND_FMA_CONTRACTION_UNRESOLVED"))
                    risks.append({"code": "FLOAT_REDUCTION_REORDERING", "operation": name, "source_span": _span(node),
                                  "message": "floating reduction/contraction grouping may affect the result"})
                if short == "fma":
                    operations.append(FloatingOperation("FMA", _span(node), "ARGUMENTS_LEFT_TO_RIGHT_THEN_SINGLE_ROUNDING",
                        mode.value, ["NaN", "+Inf", "-Inf", "+0", "-0"], "MAY_PRODUCE_INFINITY", "MAY_PRODUCE_SUBNORMAL_OR_ZERO", "EXPLICIT_FUSED_MULTIPLY_ADD"))
    impl_shape, theory_shape = _expression_shape(_root_expression(implementation_ir)), _expression_shape(_root_expression(theory_ir))
    observations = []
    for name, value in (inputs or {}).items(): observations.extend(_special_values(name, value))
    value = _native_ieee754("ANALYZE", input_dtypes=input_dtypes, output_dtypes=output_dtypes,
        operations=[asdict(item) for item in operations], risks=risks,
        implementation_shape=impl_shape, theory_shape=theory_shape,
        mathematical_match=mathematical_match, rounding_mode=mode.value,
        special_value_observations=observations)
    return IEEE754Analysis(value["status"], value["formats"], [FloatingOperation(**item) for item in value["operations"]],
        value["evaluation_order"], value["rounding_contract"], value["special_value_observations"],
        value["non_associativity_risks"], value["fma_contract"], value["equivalence"], value["diagnostics"])
