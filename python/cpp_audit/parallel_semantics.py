"""Static parallel numerical execution semantics for research Python."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .core import AuditError
from .numeric_types import NumericTypeAnalysis


class ExecutionPolicy(str, Enum):
    SEQUENTIAL = "SEQUENTIAL"
    PARALLEL_DETERMINISTIC = "PARALLEL_DETERMINISTIC"
    PARALLEL_REORDERABLE = "PARALLEL_REORDERABLE"
    PARALLEL_NONDETERMINISTIC = "PARALLEL_NONDETERMINISTIC"
    DISTRIBUTED = "DISTRIBUTED"
    GPU_PARALLEL = "GPU_PARALLEL"
    UNKNOWN_EXECUTION_POLICY = "UNKNOWN_EXECUTION_POLICY"


@dataclass(frozen=True)
class ParallelOperation:
    callable: str
    kind: str
    policy: str
    source_span: dict[str, int]
    worker: str | None
    scheduler_contract: str
    claims: dict[str, str]


@dataclass
class ParallelSemantics:
    status: str
    overall_policy: str
    operations: list[ParallelOperation]
    claims: dict[str, str]
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "overall_policy": self.overall_policy,
                "operations": [asdict(item) for item in self.operations],
                "claims": self.claims, "diagnostics": self.diagnostics}


def _span(node: ast.AST) -> dict[str, int]:
    return {"line": getattr(node, "lineno", 0), "column": getattr(node, "col_offset", 0),
            "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
            "end_column": getattr(node, "end_col_offset", getattr(node, "col_offset", 0))}


def _function_effects(function: ast.FunctionDef | None) -> tuple[bool, bool]:
    """Return (potential data race, cross-iteration dependency)."""
    if function is None: return False, False
    parameters = {arg.arg for arg in function.args.args}
    local = set(parameters)
    race = any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(function))
    cross = False
    for node in ast.walk(function):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name): local.add(target.id)
                elif isinstance(target, (ast.Subscript, ast.Attribute)): race = True; cross = True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"append", "extend", "update", "add"}:
            race = True; cross = True
    loaded = {node.id for node in ast.walk(function) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    if loaded - local - {"range", "len", "abs", "min", "max", "sum"}: race = True
    return race, cross


def _function_features(function: ast.FunctionDef | None) -> dict[str, Any] | None:
    """Serialize syntax facts only; Rust decides race/dependency semantics."""
    if function is None: return None
    local = {arg.arg for arg in function.args.args}
    target_kinds: list[str] = []
    for node in ast.walk(function):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                target_kinds.append(type(target).__name__)
                if isinstance(target, ast.Name): local.add(target.id)
    return {"has_global_nonlocal": any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(function)),
            "assignment_target_kinds": target_kinds,
            "mutating_call": any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                                 and node.func.attr in {"append", "extend", "update", "add"} for node in ast.walk(function)),
            "loaded_names": sorted({node.id for node in ast.walk(function)
                                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}),
            "local_names": sorted(local)}


def _native(**payload: Any) -> dict[str, Any]:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version":"1.0","kernel":"C",
            "operation":"PARALLEL_ANALYZE","action":"ANALYZE",**payload})["result"]


def _aggregate_policy(operations: list[ParallelOperation]) -> str:
    if not operations: return ExecutionPolicy.SEQUENTIAL.value
    precedence = [ExecutionPolicy.PARALLEL_NONDETERMINISTIC, ExecutionPolicy.UNKNOWN_EXECUTION_POLICY,
                  ExecutionPolicy.GPU_PARALLEL, ExecutionPolicy.DISTRIBUTED,
                  ExecutionPolicy.PARALLEL_REORDERABLE, ExecutionPolicy.PARALLEL_DETERMINISTIC]
    present = {ExecutionPolicy(item.policy) for item in operations}
    return next(item.value for item in precedence if item in present)


def analyze_parallel_semantics(source: str | Path, *, function: str | None = None,
                               numeric_types: NumericTypeAnalysis | None = None) -> ParallelSemantics:
    path = Path(source); tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    selected = functions.get(function) if function else (next(iter(functions.values())) if len(functions) == 1 else None)
    if selected is None: raise AuditError("PARALLEL_FUNCTION_NOT_FOUND_OR_AMBIGUOUS")
    floating = bool(numeric_types and any(item.kind in {"float", "complex"} for item in [*numeric_types.inputs.values(), *numeric_types.outputs.values()]))
    calls: list[dict[str, Any]] = []
    for node in ast.walk(selected):
        if not isinstance(node, ast.Call): continue
        name = ast.unparse(node.func); short = name.rsplit(".", 1)[-1]
        worker_name = ast.unparse(node.args[0]) if node.args and isinstance(node.args[0], (ast.Name, ast.Attribute)) else None
        worker = functions.get(worker_name or "")
        calls.append({"callable":name,"short":short,"source_span":_span(node),"worker":worker_name,
                      "worker_features":_function_features(worker)})
    value = _native(floating=floating, calls=calls)
    return ParallelSemantics(value["status"], value["overall_policy"],
        [ParallelOperation(**item) for item in value["operations"]], value["claims"], value["diagnostics"])
