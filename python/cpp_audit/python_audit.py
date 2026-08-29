"""Static, expression-level audit frontend for research Python programs.

This module intentionally does not import or execute the audited program.  The
implementation expression is derived from Python's AST; a ``@theory`` string is
parsed on a separate path and is only introduced at comparison time.
"""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, TypeVar

from .core import AuditError, SCHEMA_VERSION
from .expression import render_expression
from .library_contracts import (ContractBinding, LibraryContractRegistry, SemanticFamily,
                                TypeEvidence)
from .bitvector import (BitRepresentation, ShiftSemantics, Signedness, bit_ir,
                        representation_for_dtype, representation_from_dict)


def _lean_invocation(root: Path, target: Path) -> tuple[list[str], dict[str, str] | None]:
    """Use the pinned local Lean binary on Windows without elan network checks."""
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
            return [str(executable), str(target.resolve())], environment
    return ["lake", "env", "lean", str(target.resolve())], None


F = TypeVar("F", bound=Callable[..., Any])


class AuditMode(str, Enum):
    STRICT = "STRICT"
    REPORT_ONLY = "REPORT_ONLY"


def theory(*, output: str, expression: str) -> Callable[[F], F]:
    """Attach a theory formula to a function without changing its behaviour."""
    if not output or not expression:
        raise ValueError("theory output and expression must be non-empty")

    def decorate(function: F) -> F:
        setattr(function, "__audit_theory__", {"output": output, "expression": expression})
        return function
    return decorate


def _constant(value: Any) -> dict[str, Any]:
    return {"op": "Constant", "value": value}


def _variable(name: str, bound: bool = False) -> dict[str, Any]:
    return {"op": "BoundVariable" if bound else "FreeVariable", "name": name}


def _indexed(name: str, indices: list[dict[str, Any]]) -> dict[str, Any]:
    return {"op": "IndexedValue", "name": name, "indices": indices}


def _span(path: Path, node: ast.AST) -> dict[str, Any]:
    line, column = getattr(node, "lineno", None) or 1, getattr(node, "col_offset", None) or 0
    return {"file": str(path), "begin_line": line, "begin_column": column + 1,
            "end_line": getattr(node, "end_lineno", None) or line,
            "end_column": (getattr(node, "end_col_offset", None) or column) + 1}


def _operator_span(path: Path, node: ast.BinOp) -> dict[str, Any] | None:
    if getattr(node.left, "end_lineno", None) != getattr(node.right, "lineno", None): return None
    line_number = getattr(node.left, "end_lineno", None)
    start = getattr(node.left, "end_col_offset", None); stop = getattr(node.right, "col_offset", None)
    tokens = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//",
              ast.Mod: "%", ast.Pow: "**", ast.MatMult: "@", ast.BitAnd: "&", ast.BitOr: "|",
              ast.BitXor: "^", ast.LShift: "<<", ast.RShift: ">>"}
    token = tokens.get(type(node.op))
    if token is None or not all(isinstance(item, int) for item in (line_number, start, stop)): return None
    try: line = path.read_text(encoding="utf-8").splitlines()[line_number - 1]
    except (OSError, UnicodeError, IndexError): return None
    index = line.find(token, start, stop)
    if index < 0: return None
    return {"file": str(path), "begin_line": line_number, "begin_column": index + 1,
            "end_line": line_number, "end_column": index + len(token) + 1,
            "role": "operator", "operator": token}


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _node_id(node: ast.AST) -> str:
    return (f"py-{getattr(node, 'lineno', 0)}-{getattr(node, 'col_offset', 0)}-"
            f"{getattr(node, 'end_lineno', 0)}-{getattr(node, 'end_col_offset', 0)}-{type(node).__name__}")


@dataclass
class BuildState:
    constraints: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    used_nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    contracts: list[dict[str, Any]] = field(default_factory=list)
    execution_operations: list[dict[str, Any]] = field(default_factory=list)


class PythonExpressionBuilder:
    """Resolve just the data dependencies needed by one requested output."""

    NUMPY_REDUCTIONS = {"np.sum": "Add", "numpy.sum": "Add", "np.prod": "Multiply",
                        "numpy.prod": "Multiply", "np.mean": "Mean", "numpy.mean": "Mean"}
    NUMPY_ELEMENTARY = {"np.abs", "np.sqrt", "np.log", "np.exp", "np.power", "np.reshape",
                        "np.transpose", "np.diff", "np.gradient", "np.where", "np.clip",
                        "numpy.abs", "numpy.sqrt", "numpy.log", "numpy.exp", "numpy.power",
                        "numpy.reshape", "numpy.transpose", "numpy.diff", "numpy.gradient",
                        "numpy.where", "numpy.clip"}
    NUMPY_CONTRACTIONS = {"np.dot", "np.matmul", "np.einsum", "numpy.dot", "numpy.matmul", "numpy.einsum"}
    NUMPY_BITWISE = {
        "np.bitwise_and": "BitAnd", "numpy.bitwise_and": "BitAnd",
        "np.bitwise_or": "BitOr", "numpy.bitwise_or": "BitOr",
        "np.bitwise_xor": "BitXor", "numpy.bitwise_xor": "BitXor",
        "np.bitwise_not": "BitNot", "numpy.bitwise_not": "BitNot",
        "np.invert": "BitNot", "numpy.invert": "BitNot",
        "np.left_shift": "ShiftLeft", "numpy.left_shift": "ShiftLeft",
        "np.bitwise_left_shift": "ShiftLeft", "numpy.bitwise_left_shift": "ShiftLeft",
        "np.right_shift": "ShiftRight", "numpy.right_shift": "ShiftRight",
        "np.bitwise_right_shift": "ShiftRight", "numpy.bitwise_right_shift": "ShiftRight",
        "np.bitwise_count": "PopCount", "numpy.bitwise_count": "PopCount"}
    XARRAY_METHODS = {"sum", "mean", "where", "sel", "isel", "transpose", "rename", "broadcast"}
    TYPE_BASES = {"geopandas.GeoDataFrame": "pandas.DataFrame",
                  "geopandas.GeoSeries": "pandas.Series"}
    SEMANTIC_STRING_CONSUMERS = {
        "eval", "builtins.eval", "exec", "builtins.exec",
        "numexpr.evaluate", "sympy.sympify", "sympy.parse_expr",
        "sympy.parsing.sympy_parser.parse_expr",
    }
    NUMERIC_ANNOTATIONS = {
        "int", "float", "complex", "bool", "numbers.Number", "typing.SupportsFloat",
        "numpy.ndarray", "np.ndarray", "numpy.typing.NDArray", "npt.NDArray",
        "xarray.DataArray", "xr.DataArray",
    }

    def __init__(self, path: Path, tree: ast.Module, *,
                 contract_registry: LibraryContractRegistry | None = None,
                 library_versions: dict[str, str] | None = None):
        self.path, self.tree = path, tree
        self._source_text: dict[Path, str] = {}
        try: self._source_text[path.resolve()] = path.read_text(encoding="utf-8")
        except OSError: pass
        for source_node in ast.walk(tree): setattr(source_node, "_formula_source_path", str(path.resolve()))
        self.functions = {node.name: node for node in tree.body
                          if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.external_functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.function_paths: dict[str, Path] = {name: path for name in self.functions}
        self.state = BuildState()
        self._call_stack: list[str] = []
        self.contract_registry = contract_registry or LibraryContractRegistry.default()
        self.library_versions = dict(library_versions or {})
        self.import_aliases: dict[str, str] = {}
        self.annotated_types: dict[str, str] = {}
        for item in tree.body:
            if isinstance(item, ast.Import):
                for alias in item.names:
                    self.import_aliases[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(item, ast.ImportFrom) and item.module:
                for alias in item.names:
                    self.import_aliases[alias.asname or alias.name] = f"{item.module}.{alias.name}"
        for item in ast.walk(tree):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for argument in [*item.args.posonlyargs, *item.args.args, *item.args.kwonlyargs]:
                    if argument.annotation is not None:
                        self.annotated_types[argument.arg] = ast.unparse(argument.annotation)
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                self.annotated_types[item.target.id] = ast.unparse(item.annotation)
        self._load_local_import_functions()

    def _has_unresolved_operator_overload(self, node: ast.AST) -> bool:
        """Return true only when source evidence identifies a custom operator owner.

        Python operators are dispatch points.  Untyped research parameters retain the
        historical symbolic-numeric interpretation, but an explicit non-numeric
        annotation must never be silently promoted to builtin arithmetic.
        """
        if not isinstance(node, ast.Name):
            return False
        annotation = self.annotated_types.get(node.id)
        if not annotation:
            return False
        base = annotation.split("[", 1)[0]
        return annotation not in self.NUMERIC_ANNOTATIONS and base not in self.NUMERIC_ANNOTATIONS

    def opaque_operator(self, node: ast.BinOp, env: dict[str, dict[str, Any]], operator: str) -> dict[str, Any]:
        self.state.diagnostics.append({
            "code": "OVERLOADED_OPERATOR_SEMANTICS_UNRESOLVED",
            "message": f"operator {operator} has an explicitly annotated custom receiver",
            "source_span": _span(self.path, node),
        })
        value = self.opaque(f"operator.{operator}", [node.left, node.right], env, node)
        value["operator_semantics"] = "UNRESOLVED_CUSTOM_DISPATCH"
        return value

    def _load_local_import_functions(self) -> None:
        """Load only explicitly imported Python modules adjacent to the audited source."""
        modules = set()
        for item in self.tree.body:
            if isinstance(item, ast.Import):
                modules.update(alias.name for alias in item.names)
            elif isinstance(item, ast.ImportFrom) and item.module and (item.level or 0) == 0:
                modules.add(item.module)
        for module in sorted(modules):
            parts = module.split(".")
            candidates = [self.path.parent.joinpath(*parts).with_suffix(".py"),
                          self.path.parent.joinpath(*parts, "__init__.py")]
            module_path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
            if module_path is None or module_path == self.path.resolve():
                continue
            try:
                local_tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path), type_comments=True)
            except (OSError, SyntaxError, UnicodeError):
                continue
            try: self._source_text[module_path] = module_path.read_text(encoding="utf-8")
            except OSError: pass
            for source_node in ast.walk(local_tree): setattr(source_node, "_formula_source_path", str(module_path))
            for function in local_tree.body:
                if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = f"{module}.{function.name}"
                    self.external_functions[qualified] = function
                    self.function_paths[qualified] = module_path

    def canonical_callable(self, node: ast.Call, env: dict[str, dict[str, Any]]) -> str:
        raw = _name(node.func)
        if isinstance(node.func, ast.Attribute):
            receiver_name = _name(node.func.value)
            receiver = env.get(receiver_name) if receiver_name else None
            if receiver is None and isinstance(node.func.value, ast.Call):
                receiver = self.expr(node.func.value, env)
            semantic_type = receiver.get("semantic_type") if isinstance(receiver, dict) else None
            if semantic_type:
                candidate = f"{semantic_type}.{node.func.attr}"
                if self.contract_registry.known_callable(candidate):
                    return candidate
                base = self.TYPE_BASES.get(str(semantic_type))
                inherited = f"{base}.{node.func.attr}" if base else ""
                return inherited if inherited and self.contract_registry.known_callable(inherited) else candidate
        if not raw:
            return raw
        first, separator, rest = raw.partition(".")
        canonical = self.import_aliases.get(first)
        return f"{canonical}.{rest}" if canonical and separator else (canonical or raw)

    def contract_for(self, callable_name: str) -> ContractBinding | None:
        package = callable_name.split(".", 1)[0]
        return self.contract_registry.resolve(callable_name, self.library_versions.get(package))

    def record_contract(self, binding: ContractBinding, node: ast.Call) -> None:
        call_id = _node_id(node)
        usage = {**binding.to_dict(), "call_id": call_id, "source_span": _span(self.path, node)}
        if not any(item["call_id"] == call_id for item in self.state.contracts):
            self.state.contracts.append(usage)
            self.state.calls.append({"call_id": call_id, "name": binding.callable,
                                     "classification": binding.resolution_kind.lower(),
                                     "reference_status": binding.provenance.reference_status})
        if binding.execution:
            operation = {**binding.execution, "callable": binding.callable, "call_id": call_id,
                         "mathematical_relation": "MATHEMATICAL_EQUIVALENCE"}
            if not any(item.get("call_id") == call_id for item in self.state.execution_operations):
                self.state.execution_operations.append(operation)

    def receiver_argument(self, node: ast.Call, env: dict[str, dict[str, Any]],
                          bound: set[str], binding: ContractBinding) -> list[dict[str, Any]]:
        if not isinstance(node.func, ast.Attribute):
            return []
        root = _name(node.func.value).split(".", 1)[0]
        if root in self.import_aliases:
            return []
        return [self.expr(node.func.value, env, bound)]

    def contract_call(self, binding: ContractBinding, node: ast.Call,
                      env: dict[str, dict[str, Any]], bound: set[str]) -> dict[str, Any]:
        self.record_contract(binding, node)
        receiver = self.receiver_argument(node, env, bound, binding)
        args = receiver + [self.expr(arg, env, bound) for arg in node.args]
        keywords = {item.arg: ast.unparse(item.value) for item in node.keywords if item.arg}
        common = {"semantic_family": binding.family, "api": binding.callable,
                  "reference_contract": binding.to_dict(), "equivalence_scope": binding.equivalence_scope,
                  "source_span": _span(self.path, node),
                  "callable_span": _span(self.path, node.func),
                  "argument_spans": [_span(self.path, item) for item in node.args],
                  "keyword_spans": {item.arg: _span(self.path, item.value) for item in node.keywords if item.arg}}
        family, bind = binding.family, binding.bind
        return_contract = binding.return_type or {}
        return_kind = return_contract.get("kind")
        receiver_type = (args[0].get("semantic_type") if receiver and args
                         and isinstance(args[0], dict) else None)
        type_evidence = str(return_contract.get("evidence", TypeEvidence.UNKNOWN.value))
        if return_kind == "receiver" and receiver_type:
            return_kind, type_evidence = receiver_type, TypeEvidence.INPUT_TYPE_DETERMINED.value
        elif return_kind == "conditional":
            argument_types: set[str] = set()
            pending = list(args)
            while pending:
                item = pending.pop()
                if isinstance(item, dict):
                    if item.get("semantic_type"):
                        argument_types.add(str(item["semantic_type"]))
                    pending.extend(value for value in item.values() if isinstance(value, (dict, list)))
                elif isinstance(item, list):
                    pending.extend(item)
            matches = {str(case.get("returns")) for case in return_contract.get("cases", [])
                       if str((case.get("when") or {}).get("input_type")) in argument_types}
            if len(matches) == 1:
                return_kind, type_evidence = matches.pop(), TypeEvidence.INPUT_TYPE_DETERMINED.value
            else:
                return_kind, type_evidence = None, TypeEvidence.AMBIGUOUS.value
        if return_kind and return_kind not in {"conditional", "receiver"}:
            common["semantic_type"] = return_kind
        if return_contract:
            common["value_type_info"] = {"kind": return_kind, "evidence": type_evidence,
                                         "lean_proof_scope": "EXCLUDED_PYTHON_TYPE_METADATA"}
        if binding.callable in {"numpy.diff", "xarray.DataArray.diff"}:
            source = args[0] if args else _variable("missing_input")
            named = binding.package == "xarray"
            dimension = (self.keyword(node, "dim") if named else self.keyword(node, "axis", -1))
            if named and dimension is None and node.args and isinstance(node.args[0], ast.Constant):
                dimension = node.args[0].value
            order = self.keyword(node, "n", 1)
            return {"op": "DiscreteDifference", "input": source, "order": order,
                    "dimension" if named else "axis": dimension,
                    "label_alignment": "PRESERVED" if named else "NOT_APPLICABLE",
                    "scaling": "ABSENT", "derivative_claim": False, **common}
        if binding.callable == "numpy.gradient":
            source = args[0] if args else _variable("missing_input")
            spacing = args[1:] or [_constant(1)]
            return {"op": "FiniteDifference", "input": source, "mathematical_operator": "Gradient",
                    "axis": self.keyword(node, "axis"), "spacing": spacing,
                    "interior_stencil": "central", "boundary_stencil": "one_sided",
                    "edge_order": self.keyword(node, "edge_order", 1), **common}
        if binding.callable == "xarray.DataArray.interp":
            source = args[0] if args else _variable("missing_input")
            return {"op": "Interpolation", "method": self.keyword(node, "method", "linear"),
                    "input": source, "coordinates": keywords,
                    "dimensions": sorted(key for key in keywords if key not in {"method", "kwargs", "assume_sorted"}),
                    "label_alignment": "PRESERVED", "domain_status": "UNRESOLVED", **common}
        if family == SemanticFamily.REDUCTION.value:
            source = args[0] if args else _variable("missing_input")
            axis_names = (("dim",) if binding.package == "xarray" else
                          ("dim", "axis") if binding.package == "torch" else ("axis",))
            axis = next((value for name in axis_names
                         if (value := self.keyword(node, name)) is not None), None)
            positional_axis = 0 if receiver else 1
            if axis is None and len(node.args) > positional_axis and isinstance(node.args[positional_axis], ast.Constant):
                axis = node.args[positional_axis].value
            keepdims_name = "keepdim" if binding.package == "torch" else "keepdims"
            keepdims = bool(self.keyword(node, keepdims_name, False))
            reducer = str(bind.get("reducer", "add"))
            reduction = {"add": "Add", "multiply": "Multiply", "mean": "Mean",
                         "minimum": "Minimum", "maximum": "Maximum"}.get(reducer, reducer.title())
            constraint = {"kind": "reduction_axis", "axis": axis, "keepdims": keepdims,
                          "relation": "axis or named dimension must exist in input shape"}
            if binding.package == "xarray":
                constraint.update({"kind": "xarray_label_alignment", "dimension": axis,
                                   "dimension_names_preserved": True})
            self.state.constraints.append(constraint)
            key = "dimensions" if binding.package == "xarray" else "axes"
            return {"op": "Reduce", "reduction": reduction, "input": source, key: axis,
                    "keepdims": keepdims, "shape_constraints": [constraint], **common}
        if family == SemanticFamily.ELEMENTWISE_FUNCTION.value:
            function_name = str(bind.get("function", binding.callable.rsplit('.', 1)[-1]))
            primitive = {"minimum": "Minimum", "maximum": "Maximum", "clip": "Clamp",
                         "clamp": "Clamp", "real": "RealPart", "imag": "ImagPart",
                         "conj": "Conjugate", "conjugate": "Conjugate", "angle": "Argument",
                         "sign": "Sign", "heaviside": "HeavisideStep"}.get(function_name)
            return ({"op": primitive, "args": args, "keywords": keywords, **common} if primitive else
                    {"op": "FunctionCall", "name": function_name, "args": args, "keywords": keywords, **common})
        if family == SemanticFamily.ELEMENTWISE_PREDICATE.value:
            return {"op": "FunctionCall", "name": str(bind.get("predicate")), "args": args,
                    "keywords": keywords, **common}
        if family == SemanticFamily.TENSOR_CONTRACTION.value:
            constraint = {"kind": "contraction_compatibility", "api": binding.callable,
                          "relation": "contracted dimensions have equal extents"}
            self.state.constraints.append(constraint)
            value = {"op": "TensorContraction", "kind": bind.get("contraction"), "args": args,
                     "shape_constraints": [constraint], **common}
            if binding.callable.endswith("einsum") and node.args and isinstance(node.args[0], ast.Constant):
                value["subscripts"] = node.args[0].value
            return value
        if family == SemanticFamily.CONDITIONAL_SELECTION.value and bind.get("selection") == "where" and len(args) >= 3:
            return {"op": "IfThenElse", "condition": args[0], "then": args[1], "else": args[2],
                    "mathematical_semantic": "Select", **common}
        if family == SemanticFamily.RANDOM_SAMPLE.value:
            distribution = {"op": "Distribution", "name": bind.get("distribution"),
                            "parameters": keywords, "positional_parameters": args}
            return {"op": "RandomSample", "distribution": distribution,
                    "shape": keywords.get(str(bind.get("shape_parameter", "size"))),
                    "equivalence": {"distribution": "DISTRIBUTION_EQUIVALENT",
                                    "sequence": "SEQUENCE_IDENTICAL_NOT_CLAIMED"}, **common}
        op_by_family = {
            SemanticFamily.SHAPE_TRANSFORM.value: "ShapeTransform",
            SemanticFamily.REPRESENTATION_MAPPING.value: "RepresentationMapping",
            SemanticFamily.NUMERIC_CAST.value: "Cast",
            SemanticFamily.INDEX_SELECTION.value: "IndexSelection",
            SemanticFamily.AXIS_MAPPING.value: "AxisMapping",
            SemanticFamily.STATISTICS.value: "Statistics",
            SemanticFamily.INTERPOLATION.value: "Interpolation",
            SemanticFamily.LINEAR_ALGEBRA_RELATION.value: "LinearAlgebraRelation",
            SemanticFamily.GRAPH_ALGORITHM.value: "GraphAlgorithm",
            SemanticFamily.SPATIAL_GEOMETRY.value: "SpatialGeometry",
            SemanticFamily.ALGORITHM_INVOCATION.value: "AlgorithmInvocation",
            SemanticFamily.PARALLEL_EXECUTION.value: "AlgorithmInvocation",
            SemanticFamily.TABLE_MAPPING.value: "TableMapping",
            SemanticFamily.GROUPING.value: "Grouping",
            SemanticFamily.AGGREGATION.value: "Aggregation",
            SemanticFamily.ALIGNMENT.value: "Alignment",
        }
        value = {"op": op_by_family.get(family, "FunctionCall"), "name": next(iter(bind.values()), binding.callable),
                 "args": args, "keywords": keywords, "binding": bind, **common}
        semantic_types = {
            "numpy.array": "numpy.ndarray", "numpy.asarray": "numpy.ndarray",
            "numpy.full": "numpy.ndarray", "numpy.zeros": "numpy.ndarray", "numpy.ones": "numpy.ndarray",
            "xarray.DataArray": "xarray.DataArray", "dask.array.from_array": "dask.array.Array",
            "numpy.random.default_rng": "numpy.random.Generator",
            "dask.distributed.Client": "dask.distributed.Client",
            "dask.distributed.Client.submit": "dask.distributed.Future",
        }
        if binding.callable in semantic_types:
            value["semantic_type"] = semantic_types[binding.callable]
        elif common.get("semantic_type"):
            value["semantic_type"] = common["semantic_type"]
        elif bind.get("result_type"):
            value["semantic_type"] = bind["result_type"]
        elif receiver and isinstance(args[0], dict) and args[0].get("semantic_type") and family in {
                SemanticFamily.SHAPE_TRANSFORM.value, SemanticFamily.REPRESENTATION_MAPPING.value,
                SemanticFamily.NUMERIC_CAST.value, SemanticFamily.INDEX_SELECTION.value,
                SemanticFamily.CONDITIONAL_SELECTION.value, SemanticFamily.TABLE_MAPPING.value,
                SemanticFamily.ALIGNMENT.value}:
            value["semantic_type"] = args[0]["semantic_type"]
        if family == SemanticFamily.NUMERIC_CAST.value:
            representation = representation_for_dtype(binding.callable.rsplit(".", 1)[-1], language=binding.package)
            if representation is not None: value["bit_representation"] = representation.to_dict()
        if binding.package == "xarray":
            constraint = {"kind": "xarray_label_alignment", "dimension_names_preserved": True,
                          "operation": binding.callable.rsplit(".", 1)[-1], "labels": keywords}
            self.state.constraints.append(constraint)
            value["alignment_constraints"] = [constraint]
        return value

    def mark(self, node: ast.AST, role: str = "numeric_dependency") -> None:
        key = _node_id(node)
        self.state.used_nodes[key] = {"id": key, "kind": type(node).__name__,
                                      "role": role, "source_span": _span(self.path, node)}

    @staticmethod
    def keyword(node: ast.Call, name: str, default: Any = None) -> Any:
        for item in node.keywords:
            if item.arg == name and isinstance(item.value, ast.Constant):
                return item.value.value
            if item.arg == name and isinstance(item.value, (ast.List, ast.Tuple)):
                values = []
                for element in item.value.elts:
                    if not isinstance(element, ast.Constant): return default
                    values.append(element.value)
                return values
        return default

    def expr(self, node: ast.AST, env: dict[str, dict[str, Any]], bound: set[str] | None = None) -> dict[str, Any]:
        bound = bound or set()
        self.mark(node)
        if isinstance(node, ast.Constant):
            value = _constant("Ellipsis" if node.value is Ellipsis else node.value)
            if isinstance(node.value, int) and not isinstance(node.value, bool):
                source_path = Path(getattr(node, "_formula_source_path", str(self.path))).resolve()
                text = self._source_text.get(source_path)
                original = ast.get_source_segment(text, node) if text else None
                lowered = (original or "").lower().replace("_", "")
                radix = 16 if lowered.startswith("0x") else 8 if lowered.startswith("0o") else 2 if lowered.startswith("0b") else 10
                value["numeral_representation"] = {"radix": radix, "original_text": original}
            return value
        if isinstance(node, ast.Name):
            if node.id in bound: return _variable(node.id, True)
            return deepcopy(env.get(node.id, _variable(node.id)))
        if isinstance(node, ast.BinOp):
            operations = {ast.Add: "Add", ast.Sub: "Subtract", ast.Mult: "Multiply",
                          ast.Div: "Divide", ast.FloorDiv: "FloorDivide", ast.Mod: "Modulo",
                          ast.Pow: "Power", ast.MatMult: "TensorContraction",
                          ast.BitAnd: "BitAnd", ast.BitOr: "BitOr", ast.BitXor: "BitXor",
                          ast.LShift: "ShiftLeft", ast.RShift: "ShiftRight"}
            op = operations.get(type(node.op))
            if not op: return self.opaque(type(node.op).__name__, [node.left, node.right], env, node)
            if self._has_unresolved_operator_overload(node.left) or self._has_unresolved_operator_overload(node.right):
                return self.opaque_operator(node, env, type(node.op).__name__)
            args = [self.expr(node.left, env, bound), self.expr(node.right, env, bound)]
            if op in {"BitAnd", "BitOr", "BitXor", "ShiftLeft", "ShiftRight"}:
                encoded = [item.get("bit_representation") for item in args if item.get("bit_representation")]
                if encoded and all(item == encoded[0] for item in encoded):
                    representation = representation_from_dict(encoded[0])
                elif all(isinstance(item, ast.Constant) and isinstance(item.value, int)
                         and not isinstance(item.value, bool) for item in (node.left, node.right)):
                    representation = BitRepresentation.python_int()
                else:
                    representation = BitRepresentation.unresolved(language="python",
                        evidence="operand dtype required to distinguish Python int from overloaded fixed-width operator")
                shift = None
                if op == "ShiftLeft": shift = ShiftSemantics.LOGICAL_LEFT
                elif op == "ShiftRight":
                    shift = (ShiftSemantics.ARITHMETIC_RIGHT if representation.signedness in {Signedness.SIGNED, Signedness.UNBOUNDED}
                             else ShiftSemantics.LOGICAL_RIGHT if representation.signedness == Signedness.UNSIGNED
                             else ShiftSemantics.LANGUAGE_DEPENDENT)
                value = bit_ir(op, *args, representation=representation, shift_semantics=shift,
                               source_operator=type(node.op).__name__)
                value["source_span"] = _span(self.path, node)
                value["argument_spans"] = [_span(self.path, node.left), _span(self.path, node.right)]
                operator_span = _operator_span(self.path, node)
                if operator_span: value["operator_span"] = operator_span
                return value
            result = {"op": op, "args": args, "source_span": _span(self.path, node),
                      "argument_spans": [_span(self.path, node.left), _span(self.path, node.right)]}
            operator_span = _operator_span(self.path, node)
            if operator_span: result["operator_span"] = operator_span
            if op == "TensorContraction": result["kind"] = "matmul"
            return result
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub): return {"op": "Negate", "args": [self.expr(node.operand, env, bound)],
                                                       "source_span": _span(self.path, node)}
            if isinstance(node.op, ast.UAdd): return self.expr(node.operand, env, bound)
            if isinstance(node.op, ast.Invert):
                operand = self.expr(node.operand, env, bound)
                encoded = operand.get("bit_representation")
                representation = (representation_from_dict(encoded) if encoded else
                    BitRepresentation.python_int() if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, int)
                    else BitRepresentation.unresolved(language="python"))
                value = bit_ir("BitNot", operand, representation=representation, source_operator="Invert")
                value["source_span"] = _span(self.path, node); return value
            if isinstance(node.op, ast.Not):
                return {"op": "LogicalNot", "args": [self.expr(node.operand, env, bound)],
                        "source_span": _span(self.path, node)}
            return self.opaque(type(node.op).__name__, [node.operand], env, node)
        if isinstance(node, ast.BoolOp):
            return {"op": "LogicalAnd" if isinstance(node.op, ast.And) else "LogicalOr",
                    "args": [self.expr(value, env, bound) for value in node.values],
                    "evaluation": "short_circuit", "source_span": _span(self.path, node)}
        if isinstance(node, ast.Compare):
            names = {ast.Gt: "GreaterThan", ast.GtE: "GreaterEqual", ast.Lt: "LessThan",
                     ast.LtE: "LessEqual", ast.Eq: "Equal", ast.NotEq: "NotEqual"}
            parts, left = [], node.left
            for operator, right in zip(node.ops, node.comparators):
                parts.append({"op": "Compare", "comparison": names.get(type(operator), type(operator).__name__),
                              "args": [self.expr(left, env, bound), self.expr(right, env, bound)],
                              "source_span": _span(self.path, node)})
                left = right
            return parts[0] if len(parts) == 1 else {"op": "LogicalAnd", "args": parts,
                                                    "evaluation": "short_circuit"}
        if isinstance(node, ast.IfExp):
            return {"op": "IfThenElse", "condition": self.expr(node.test, env, bound),
                    "then": self.expr(node.body, env, bound), "else": self.expr(node.orelse, env, bound),
                    "mathematical_semantic": "Select", "source_span": _span(self.path, node),
                    "condition_span": _span(self.path, node.test),
                    "branch_spans": {"then": _span(self.path, node.body), "else": _span(self.path, node.orelse)}}
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            if len(node.generators) != 1:
                return self.opaque(type(node).__name__, [], env, node)
            generator = node.generators[0]
            if not isinstance(generator.target, ast.Name):
                return self.opaque(type(node).__name__, [], env, node)
            index = generator.target.id
            iterable = self.expr(generator.iter, env, bound)
            body = self.expr(node.elt, env, bound | {index})
            source = iterable
            if generator.ifs:
                predicate = self.expr(generator.ifs[0], env, bound | {index})
                source = {"op": "Filter", "bound_index": index, "iterable": iterable,
                          "predicate": predicate}
            return {"op": "Map", "bound_index": index, "iterable": source, "body": body,
                    "collection_kind": "generator" if isinstance(node, ast.GeneratorExp) else ("set" if isinstance(node, ast.SetComp) else "list")}
        if isinstance(node, ast.DictComp):
            if len(node.generators) != 1 or not isinstance(node.generators[0].target, ast.Name):
                return self.opaque("DictComp", [], env, node)
            generator = node.generators[0]; index = generator.target.id
            return {"op": "Map", "bound_index": index, "iterable": self.expr(generator.iter, env, bound),
                    "key": self.expr(node.key, env, bound | {index}), "body": self.expr(node.value, env, bound | {index}),
                    "collection_kind": "dict"}
        if isinstance(node, ast.Subscript):
            base = _name(node.value)
            if not base:
                base_expr = self.expr(node.value, env, bound)
                base = base_expr.get("name", "subscript")
            indices = self.slice_expr(node.slice, env, bound)
            return {"op": "IndexedValue", "name": base, "indices": indices,
                    "shape_constraints": [{"kind": "index_within_extent", "axis": i} for i in range(len(indices))]}
        if isinstance(node, (ast.List, ast.Tuple)):
            return {"op": "FunctionCall", "name": "tuple", "args": [self.expr(x, env, bound) for x in node.elts]}
        if isinstance(node, ast.Call):
            return self.call(node, env, bound)
        if isinstance(node, ast.Attribute):
            return _variable(_name(node))
        return self.opaque(type(node).__name__, [], env, node)

    def slice_expr(self, node: ast.AST, env: dict[str, dict[str, Any]], bound: set[str]) -> list[dict[str, Any]]:
        nodes = node.elts if isinstance(node, ast.Tuple) else [node]
        result = []
        for item in nodes:
            if isinstance(item, ast.Slice):
                result.append({"op": "FunctionCall", "name": "slice", "args": [
                    self.expr(item.lower, env, bound) if item.lower else _constant(None),
                    self.expr(item.upper, env, bound) if item.upper else _constant(None),
                    self.expr(item.step, env, bound) if item.step else _constant(None)]})
            else: result.append(self.expr(item, env, bound))
        return result

    def opaque(self, name: str, args: list[ast.AST], env: dict[str, dict[str, Any]], node: ast.AST,
               keywords: dict[str, Any] | None = None) -> dict[str, Any]:
        call_id = _node_id(node)
        constraint = {"kind": "opaque_result_shape", "call_id": call_id,
                      "relation": "shape(result) is constrained by the external call contract"}
        self.state.constraints.append(constraint)
        self.state.diagnostics.append({"code": "OPAQUE_NUMERIC_CALL", "message": f"unanalysed external numeric call: {name}",
                                       "source_span": _span(self.path, node)})
        value = {"op": "OpaqueNumericCall", "name": name,
                 "args": [self.expr(arg, env) for arg in args], "shape_constraints": [constraint],
                 "resolution_trace": [
                     {"priority": 1, "stage": "Reference Simple Mapping", "status": "NO_MATCH"},
                     {"priority": 2, "stage": "Reference Detailed Contract", "status": "NO_MATCH"},
                     {"priority": 3, "stage": "Registered Contract", "status": "NO_MATCH"},
                     {"priority": 4, "stage": "Python source analysis", "status": "NO_ANALYSABLE_LOCAL_SOURCE"},
                     {"priority": 5, "stage": "Native source analysis", "status": "NOT_RESOLVED"},
                     {"priority": 6, "stage": "OpaqueNumericCall", "status": "SELECTED"},
                 ]}
        if keywords: value["keywords"] = keywords
        self.state.calls.append({"call_id": call_id, "name": name, "classification": "opaque"})
        return value

    def call(self, node: ast.Call, env: dict[str, dict[str, Any]], bound: set[str]) -> dict[str, Any]:
        name = _name(node.func)
        canonical_name = self.canonical_callable(node, env)
        if canonical_name in self.SEMANTIC_STRING_CONSUMERS or name in self.SEMANTIC_STRING_CONSUMERS:
            role = "DYNAMIC" if not node.args or not isinstance(node.args[0], ast.Constant) else "LITERAL"
            self.state.diagnostics.append({
                "code": "SEMANTIC_STRING_UNRESOLVED",
                "message": f"{canonical_name or name} consumes program text; static audit never executes it",
                "source_span": _span(self.path, node),
                "string_role": role,
            })
            value = self.opaque(canonical_name or name, [], env, node)
            value["semantic_string"] = {
                "consumer": canonical_name or name,
                "role": role,
                "executed_by_analyzer": False,
            }
            return value
        if name in {"sum", "builtins.sum"} and node.args and isinstance(node.args[0], ast.GeneratorExp):
            mapped = self.expr(node.args[0], env, bound)
            return {"op": "FoldLeft", "iterable": mapped.get("iterable"), "bound_index": mapped.get("bound_index"),
                    "initial_value": _constant(0), "operation": "Add", "body": mapped.get("body"),
                    "reduction_order": "left_to_right"}
        if name in {"min", "builtins.min", "max", "builtins.max"} and len(node.args) >= 2:
            return {"op": "Minimum" if name.endswith("min") else "Maximum",
                    "args": [self.expr(arg, env, bound) for arg in node.args]}
        if isinstance(node.func, ast.Call):
            wrapper_name = self.canonical_callable(node.func, env)
            wrapper = self.contract_for(wrapper_name)
            if wrapper and wrapper.family == SemanticFamily.PARALLEL_EXECUTION.value:
                self.record_contract(wrapper, node.func)
                if node.func.args and isinstance(node.func.args[0], ast.Name) and node.func.args[0].id in self.functions:
                    synthetic = ast.Call(func=node.func.args[0], args=node.args, keywords=node.keywords)
                    ast.copy_location(synthetic, node)
                    return self.inline_function(node.func.args[0].id, synthetic, env)
        if name in self.functions and name not in self.import_aliases:
            return self.inline_function(name, node, env)
        canonical = self.canonical_callable(node, env)
        bit_name = canonical if canonical in self.NUMPY_BITWISE else name
        if bit_name in self.NUMPY_BITWISE:
            args = [self.expr(arg, env, bound) for arg in node.args]
            representation = BitRepresentation.unresolved(language="numpy",
                evidence="NumPy dtype propagation required")
            result = bit_ir(self.NUMPY_BITWISE[bit_name], *args, representation=representation,
                            source_operator=bit_name)
            result["api"] = bit_name
            result["shape_constraints"] = [{"kind": "numpy_broadcast",
                "relation": "operands broadcast to result shape"}]
            return result
        binding = self.contract_for(canonical)
        if binding:
            if (binding.family == SemanticFamily.PARALLEL_EXECUTION.value and node.args and
                    isinstance(node.args[0], ast.Name) and node.args[0].id in self.functions):
                self.record_contract(binding, node)
                synthetic = ast.Call(func=node.args[0], args=node.args[1:], keywords=[])
                ast.copy_location(synthetic, node)
                return self.inline_function(node.args[0].id, synthetic, env)
            return self.contract_call(binding, node, env, bound)
        if canonical in self.external_functions:
            return self.inline_function(canonical, node, env)
        if canonical and self.contract_registry.known_callable(canonical):
            package = canonical.split(".", 1)[0]
            self.state.diagnostics.append({"code": "LIBRARY_CONTRACT_VERSION_MISMATCH",
                                           "message": f"no {canonical} contract matches {self.library_versions.get(package)!r}",
                                           "source_span": _span(self.path, node)})
            return self.opaque(canonical, list(node.args), env, node,
                               {item.arg: ast.unparse(item.value) for item in node.keywords if item.arg})
        if name in self.NUMPY_REDUCTIONS:
            source = self.expr(node.args[0], env, bound) if node.args else _variable("missing_input")
            axis = self.keyword(node, "axis")
            if axis is None and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                axis = node.args[1].value
            keepdims = bool(self.keyword(node, "keepdims", False))
            constraint = {"kind": "reduction_axis", "axis": axis, "keepdims": keepdims,
                          "relation": "axis must exist in input shape"}
            self.state.constraints.append(constraint)
            return {"op": "Reduce", "reduction": self.NUMPY_REDUCTIONS[name], "input": source,
                    "axes": axis, "keepdims": keepdims, "api": name, "shape_constraints": [constraint]}
        if name in self.NUMPY_CONTRACTIONS:
            args = [self.expr(arg, env, bound) for arg in node.args]
            constraint = {"kind": "contraction_compatibility", "api": name,
                          "relation": "contracted dimensions have equal extents"}
            self.state.constraints.append(constraint)
            result = {"op": "TensorContraction", "kind": name.split(".")[-1], "args": args,
                      "shape_constraints": [constraint]}
            if name.endswith("einsum") and node.args and isinstance(node.args[0], ast.Constant):
                result["subscripts"] = node.args[0].value
            return result
        if name in self.NUMPY_ELEMENTARY:
            args = [self.expr(arg, env, bound) for arg in node.args]
            short = name.split(".")[-1]
            if short == "where" and len(args) >= 3:
                return {"op": "IfThenElse", "condition": args[0], "then": args[1], "else": args[2],
                        "api": name, "mathematical_semantic": "Select"}
            if short == "clip" and len(args) >= 3:
                return {"op": "Clamp", "args": args, "api": name}
            return {"op": "FunctionCall", "name": short, "args": args,
                    "keywords": {item.arg: ast.unparse(item.value) for item in node.keywords if item.arg}}
        if (isinstance(node.func, ast.Attribute) and node.func.attr in self.XARRAY_METHODS and
                canonical.startswith("xarray.")):
            receiver = self.expr(node.func.value, env, bound)
            method = node.func.attr
            dim = self.keyword(node, "dim")
            if dim is None and node.args and isinstance(node.args[0], ast.Constant):
                dim = node.args[0].value
            kwargs = {item.arg: ast.unparse(item.value) for item in node.keywords if item.arg}
            constraint = {"kind": "xarray_label_alignment", "dimension_names_preserved": True,
                          "operation": method, "dimension": dim, "labels": kwargs}
            self.state.constraints.append(constraint)
            if method in {"sum", "mean"}:
                return {"op": "Reduce", "reduction": "Add" if method == "sum" else "Mean",
                        "input": receiver, "dimensions": dim, "api": f"xarray.{method}",
                        "alignment_constraints": [constraint]}
            return {"op": "FunctionCall", "name": f"xarray.{method}", "args": [receiver] +
                    [self.expr(arg, env, bound) for arg in node.args], "dimension_names": dim,
                    "label_arguments": kwargs, "alignment_constraints": [constraint]}
        if name in {"xr.DataArray", "xarray.DataArray"}:
            args = [self.expr(arg, env, bound) for arg in node.args]
            dims = self.keyword(node, "dims", [])
            kwargs = {item.arg: ast.unparse(item.value) for item in node.keywords if item.arg}
            constraint = {"kind": "xarray_dimensions", "dimensions": dims,
                          "coordinates": kwargs.get("coords"), "dimension_names_preserved": True}
            self.state.constraints.append(constraint)
            return {"op": "FunctionCall", "name": "xarray.DataArray", "args": args,
                    "dimension_names": dims, "label_arguments": kwargs, "alignment_constraints": [constraint]}
        if name in {"xr.broadcast", "xarray.broadcast"}:
            args = [self.expr(arg, env, bound) for arg in node.args]
            constraint = {"kind": "xarray_label_alignment", "dimension_names_preserved": True,
                          "operation": "broadcast", "relation": "align by dimension name and coordinate label"}
            self.state.constraints.append(constraint)
            return {"op": "FunctionCall", "name": "xarray.broadcast", "args": args,
                    "alignment_constraints": [constraint]}
        return self.opaque(name or ast.unparse(node.func), list(node.args), env, node,
                           {item.arg: ast.unparse(item.value) for item in node.keywords if item.arg})

    def inline_function(self, name: str, call: ast.Call, caller_env: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if name in self._call_stack:
            return self.opaque(name, list(call.args), caller_env, call)
        function = self.functions.get(name) or self.external_functions[name]
        env: dict[str, dict[str, Any]] = {}
        for parameter, argument in zip(function.args.args, call.args):
            env[parameter.arg] = self.expr(argument, caller_env)
        self._call_stack.append(name)
        original_path = self.path
        self.path = self.function_paths.get(name, self.path)
        try:
            value, _ = self.execute_block(self.backward_statements(function.body, {"__return__"}), env)
        finally:
            self.path = original_path
            self._call_stack.pop()
        if value is None:
            return self.opaque(name, list(call.args), caller_env, call)
        self.state.calls.append({"call_id": _node_id(call), "name": name, "classification": "inlined_user_function"})
        return value

    @staticmethod
    def loaded_names(node: ast.AST) -> set[str]:
        return {item.id for item in ast.walk(node)
                if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)}

    @staticmethod
    def assigned_names(node: ast.AST) -> set[str]:
        result: set[str] = set()
        for item in ast.walk(node):
            if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del)):
                result.add(item.id)
            elif isinstance(item, ast.Subscript) and isinstance(item.ctx, ast.Store):
                base = _name(item.value)
                if base: result.add(base)
            elif isinstance(item, ast.Attribute) and isinstance(item.ctx, ast.Store):
                base = _name(item.value)
                if base: result.add(base)
            elif isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and item.func.attr in {"append", "extend"}:
                base = _name(item.func.value)
                if base: result.add(base)
        return result

    def backward_statements(self, statements: list[ast.stmt], required: set[str]) -> list[ast.stmt]:
        """Conservative name-level backward slice before expression lowering."""
        alias_groups: list[set[str]] = []
        for statement in statements:
            if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name) and isinstance(statement.value, ast.Name)):
                pair = {statement.targets[0].id, statement.value.id}; overlaps = [group for group in alias_groups if group & pair]
                for group in overlaps: pair |= group; alias_groups.remove(group)
                alias_groups.append(pair)
        def expand(names: set[str]) -> set[str]:
            result = set(names)
            for group in alias_groups:
                if group & result: result |= group
            return result
        needed, selected = expand(set(required)), []
        for statement in reversed(statements):
            assigned = self.assigned_names(statement)
            keep = False
            if isinstance(statement, ast.Return):
                keep = "__return__" in needed
                if keep and statement.value: needed |= self.loaded_names(statement.value)
            elif isinstance(statement, ast.If):
                keep = "__return__" in needed or bool(assigned & needed)
                if keep:
                    needed |= self.loaded_names(statement.test)
                    needed |= self.loaded_names(statement)
            elif isinstance(statement, (ast.For, ast.While, ast.Try)):
                mutated = self.assigned_names(ast.Module(body=statement.body, type_ignores=[]))
                if isinstance(statement, ast.Try):
                    mutated |= self.assigned_names(ast.Module(body=[item for handler in statement.handlers for item in handler.body] + statement.finalbody, type_ignores=[]))
                keep = "__return__" in needed or bool(mutated & needed)
                if keep:
                    if isinstance(statement, ast.For): needed |= self.loaded_names(statement.iter)
                    elif isinstance(statement, ast.While): needed |= self.loaded_names(statement.test)
                    needed |= self.loaded_names(statement)
            else:
                keep = bool(assigned & needed)
                if keep:
                    needed -= assigned
                    needed |= self.loaded_names(statement)
            needed = expand(needed)
            if keep: selected.append(statement)
        selected.reverse()
        return selected

    def execute_block(self, statements: list[ast.stmt], env: dict[str, dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
        current = dict(env)
        for position, statement in enumerate(statements):
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                target = statement.targets[0] if isinstance(statement, ast.Assign) else statement.target
                value_node = statement.value
                if value_node is None: continue
                value = self.expr(value_node, current)
                if isinstance(target, ast.Name):
                    current[target.id] = value
                elif isinstance(target, ast.Subscript):
                    name = _name(target.value)
                    previous = current.get(name, _variable(name))
                    canonical = previous.get("name", name) if previous.get("op") == "FreeVariable" else name
                    update = {"op": "IndexedStateUpdate", "target": canonical, "previous_state": previous,
                              "indices": self.slice_expr(target.slice, current, set()), "value": value,
                              "mutation": "indexed_assignment"}
                    current[name] = update; current[canonical] = update
                    for alias, alias_value in list(current.items()):
                        if isinstance(alias_value, dict) and alias_value.get("op") == "FreeVariable" and alias_value.get("name") == canonical:
                            current[alias] = update
                elif isinstance(target, ast.Attribute):
                    name = _name(target.value)
                    previous = current.get(name, _variable(name))
                    canonical = previous.get("name", name) if previous.get("op") == "FreeVariable" else name
                    current[name] = {"op": "AttributeStateUpdate", "target": f"{canonical}.{target.attr}",
                                     "previous_state": previous, "value": value}
                    current[canonical] = current[name]
                self.mark(statement, "definition")
            elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
                operations = {ast.Add: "Add", ast.Mult: "Multiply", ast.Sub: "Subtract", ast.Div: "Divide"}
                previous = current.get(statement.target.id, _variable(statement.target.id))
                current[statement.target.id] = {"op": operations.get(type(statement.op), "FunctionCall"),
                                                "args": [previous, self.expr(statement.value, current)],
                                                "mutation": "in_place_arithmetic"}
                self.mark(statement, "definition")
            elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Subscript):
                name = _name(statement.target.value); previous_state = current.get(name, _variable(name))
                indexed = self.expr(ast.copy_location(ast.Subscript(value=statement.target.value, slice=statement.target.slice, ctx=ast.Load()), statement.target), current)
                operations = {ast.Add: "Add", ast.Mult: "Multiply", ast.Sub: "Subtract", ast.Div: "Divide"}
                value = {"op": operations.get(type(statement.op), "FunctionCall"), "args": [indexed, self.expr(statement.value, current)]}
                canonical = previous_state.get("name", name) if previous_state.get("op") == "FreeVariable" else name
                current[name] = {"op": "IndexedStateUpdate", "target": canonical, "previous_state": previous_state,
                                 "indices": self.slice_expr(statement.target.slice, current, set()), "value": value,
                                 "mutation": "indexed_in_place_arithmetic"}
                current[canonical] = current[name]
                for alias, alias_value in list(current.items()):
                    if isinstance(alias_value, dict) and alias_value.get("op") == "FreeVariable" and alias_value.get("name") == canonical:
                        current[alias] = current[name]
                self.mark(statement, "definition")
            elif isinstance(statement, ast.If):
                yes_value, yes = self.execute_block(statement.body, dict(current))
                no_value, no = self.execute_block(statement.orelse, dict(current))
                condition = self.expr(statement.test, current)
                if yes_value is not None or no_value is not None:
                    remaining = statements[position + 1:]
                    if yes_value is None: yes_value, _ = self.execute_block(remaining, yes)
                    if no_value is None: no_value, _ = self.execute_block(remaining, no)
                    return ({"op": "IfThenElse", "condition": condition,
                             "then": yes_value or _constant(None), "else": no_value or _constant(None)}, current)
                for key in yes.keys() | no.keys():
                    if yes.get(key) != no.get(key):
                        current[key] = {"op": "IfThenElse", "condition": condition,
                                        "then": yes.get(key, current.get(key, _variable(key))),
                                        "else": no.get(key, current.get(key, _variable(key)))}
            elif isinstance(statement, ast.For):
                self.execute_for(statement, current)
            elif isinstance(statement, ast.While):
                changed = self.assigned_names(ast.Module(body=statement.body, type_ignores=[]))
                for key in changed:
                    current[key] = {"op": "LoopInvocation", "kind": "while", "condition": self.expr(statement.test, current),
                                    "initial_state": current.get(key, _variable(key)), "body_source": "\n".join(ast.unparse(item) for item in statement.body),
                                    "loop_invariant_status": "LoopInvariantUnknown",
                                    "termination_status": "TerminationUnproven"}
                self.state.diagnostics.append({"code": "TERMINATION_UNPROVEN", "message": "while semantics preserved without finite normalization",
                                               "source_span": _span(self.path, statement)})
            elif isinstance(statement, ast.Try):
                try_value, try_env = self.execute_block(statement.body, dict(current))
                handler_results = [self.execute_block(handler.body, dict(current)) for handler in statement.handlers]
                handler_value = handler_results[0][0] if handler_results else None
                keys = set(try_env)
                for _, handler_env in handler_results: keys |= set(handler_env)
                for key in keys:
                    alternatives = [try_env.get(key, current.get(key, _variable(key)))] + [handler_env.get(key, current.get(key, _variable(key))) for _, handler_env in handler_results]
                    if any(value != alternatives[0] for value in alternatives[1:]):
                        current[key] = {"op": "ExceptionChoice", "try": alternatives[0], "handlers": alternatives[1:],
                                        "exception_condition": "EXCEPTION_PATH_UNRESOLVED"}
                if statement.finalbody:
                    final_value, current = self.execute_block(statement.finalbody, current)
                    if final_value is not None: return final_value, current
                if try_value is not None or handler_value is not None:
                    return {"op": "ExceptionChoice", "try": try_value or _constant(None),
                            "handlers": [value or _constant(None) for value, _ in handler_results],
                            "exception_condition": "EXCEPTION_PATH_UNRESOLVED"}, current
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and isinstance(statement.value.func, ast.Attribute) and statement.value.func.attr in {"append", "extend"}:
                name = _name(statement.value.func.value)
                current[name] = {"op": "SequenceStateUpdate", "kind": statement.value.func.attr,
                                 "previous_state": current.get(name, _variable(name)),
                                 "value": self.expr(statement.value.args[0], current) if statement.value.args else _constant(None)}
                previous = current[name].get("previous_state", {})
                if previous.get("op") == "FreeVariable": current[previous["name"]] = current[name]
            elif isinstance(statement, ast.Return):
                return (self.expr(statement.value, current) if statement.value else _constant(None), current)
        return None, current

    def execute_for(self, statement: ast.For, env: dict[str, dict[str, Any]]) -> None:
        has_jump = any(isinstance(node, (ast.Break, ast.Continue)) for child in statement.body for node in ast.walk(child))
        if has_jump or not isinstance(statement.target, ast.Name) or not isinstance(statement.iter, ast.Call) or _name(statement.iter.func) != "range":
            changed = self.assigned_names(ast.Module(body=statement.body, type_ignores=[]))
            for key in changed:
                env[key] = {"op": "LoopInvocation", "kind": "for", "iterable": self.expr(statement.iter, env),
                            "initial_state": env.get(key, _variable(key)), "body_source": "\n".join(ast.unparse(item) for item in statement.body),
                            "control_effects": [type(node).__name__ for child in statement.body for node in ast.walk(child) if isinstance(node, (ast.Break, ast.Continue))]}
            self.state.diagnostics.append({"code": "LOOP_SEMANTICS_PRESERVED", "message": "loop not normalized to a finite fold",
                                           "source_span": _span(self.path, statement)})
            return
        index = statement.target.id
        range_args = statement.iter.args
        lower_node, upper_node, step_node = ((ast.Constant(0), range_args[0], ast.Constant(1)) if len(range_args) == 1
                                             else (range_args[0], range_args[1], range_args[2] if len(range_args) > 2 else ast.Constant(1)))
        lower, upper, step = self.expr(lower_node, env), self.expr(upper_node, env), self.expr(step_node, env)
        before, body_env = deepcopy(env), deepcopy(env)
        body_env[index] = _variable(index, True)
        _, body_env = self.execute_block(statement.body, body_env)
        for key, after in body_env.items():
            if key == index or after == before.get(key): continue
            previous = before.get(key)
            op, term = self.accumulator_update(after, key, previous)
            if op is None:
                op, term = self.conditional_accumulator_update(after, key, previous)
            domain = {"lower": lower, "upper_exclusive": upper, "step": step}
            if op:
                env[key] = {"op": "FoldLeft", "bound_index": index, "index_domain": domain,
                            "initial_value": previous or _constant(0 if op == "Add" else 1),
                            "operation": op, "body": term, "reduction_order": "left_to_right"}
            elif after.get("op") == "Map":
                after["bound_index"] = index; after["index_domain"] = domain; env[key] = after
            else:
                env[key] = {"op": "Map", "bound_index": index, "index_domain": domain,
                            "output": _indexed(key, [_variable(index, True)]), "body": after}
        self.mark(statement, "control_dependency")

    @staticmethod
    def accumulator_update(node: dict[str, Any], name: str, previous: dict[str, Any] | None) -> tuple[str | None, dict[str, Any]]:
        if node.get("op") not in {"Add", "Multiply"} or len(node.get("args", [])) != 2:
            return None, node
        first, second = node["args"]
        if first == previous or first == _variable(name): return node["op"], second
        if second == previous or second == _variable(name): return node["op"], first
        return None, node

    @classmethod
    def conditional_accumulator_update(cls, node: dict[str, Any], name: str,
                                       previous: dict[str, Any] | None) -> tuple[str | None, dict[str, Any]]:
        """Recognize branch-specific accumulator updates without dropping the predicate."""
        if node.get("op") != "IfThenElse": return None, node
        yes_op, yes_term = cls.accumulator_update(node.get("then", {}), name, previous)
        no_op, no_term = cls.accumulator_update(node.get("else", {}), name, previous)
        prior = previous or _variable(name)
        if node.get("then") == prior: yes_op, yes_term = no_op, _constant(0 if no_op == "Add" else 1)
        if node.get("else") == prior: no_op, no_term = yes_op, _constant(0 if yes_op == "Add" else 1)
        if yes_op is None or no_op is None or yes_op != no_op: return None, node
        return yes_op, {"op": "IfThenElse", "condition": node["condition"],
                        "then": yes_term, "else": no_term}

    def function_theory(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str] | None:
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call) or _name(decorator.func).split(".")[-1] != "theory": continue
            values = {item.arg: item.value.value for item in decorator.keywords
                      if item.arg and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str)}
            if {"output", "expression"} <= values.keys(): return values
        return None

    def extract(self, function_name: str | None, output_name: str | None) -> tuple[dict[str, Any], dict[str, str] | None, dict[str, Any]]:
        candidates = list(self.functions.values())
        if function_name:
            function = self.functions.get(function_name)
            if not function: raise AuditError(f"PYTHON_FUNCTION_NOT_FOUND: {function_name}")
        else:
            decorated = [item for item in candidates if self.function_theory(item)]
            if len(decorated) != 1:
                raise AuditError("PYTHON_FUNCTION_AMBIGUOUS: specify --function")
            function = decorated[0]
        metadata = self.function_theory(function)
        output = output_name or (metadata or {}).get("output") or function.name
        env = {argument.arg: _variable(argument.arg) for argument in function.args.args}
        statements = self.backward_statements(function.body, {output, "__return__"})
        returned, final_env = self.execute_block(statements, env)
        value = final_env.get(output, returned)
        if value is None: raise AuditError(f"PYTHON_OUTPUT_NOT_FOUND: {output}")
        target, expression = self.lower_output(output, value)
        outputs = [{"target": target, "expression": expression}]
        status = "EXPRESSION_PARTIALLY_EXTRACTED" if self.state.diagnostics else "EXPRESSION_EXTRACTED"
        payload = {"schema_version": SCHEMA_VERSION, "status": status, "language": "python",
                   "function": function.name, "outputs": outputs,
                   "numeric_domain": {"category": "symbolic_numeric"},
                   "shape_constraints": self.state.constraints,
                   "library_contracts": self.state.contracts,
                   "execution_ir": {"schema_version": SCHEMA_VERSION,
                                    "status": "EXECUTION_SEMANTICS_EXTRACTED" if self.state.execution_operations else "NO_EXECUTION_SEMANTICS",
                                    "operations": self.state.execution_operations},
                   "source_correspondence": [{"term": "output", "implementation_node_ids": list(self.state.used_nodes),
                                               "source_spans": [item["source_span"] for item in self.state.used_nodes.values()]}],
                   "diagnostics": self.state.diagnostics}
        payload["expression_id"] = "python-expression-" + sha256(json.dumps(outputs, sort_keys=True).encode()).hexdigest()[:16]
        slice_ir = {"schema_version": SCHEMA_VERSION, "status": "OUTPUT_SLICE_EXTRACTED",
                    "language": "python", "function": function.name, "output": output,
                    "nodes": list(self.state.used_nodes.values()), "calls": self.state.calls,
                    "shape_constraints": self.state.constraints,
                    "library_contracts": self.state.contracts,
                    "execution_ir": payload["execution_ir"]}
        return payload, metadata, slice_ir

    def lower_output(self, output: str, value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if value.get("op") != "Reduce" or not isinstance(value.get("axes"), int) or value["axes"] < 1:
            return _variable(output), value
        axis = value["axes"]
        outer = [_variable("r" if i == 0 else f"o{i}", True) for i in range(axis)]
        reduction_index = _variable("i", True)
        indices = outer + [reduction_index]
        body = self.elementize(value["input"], indices, primary=True)
        upper = {"op": "FunctionCall", "name": "dim", "args": [self.first_tensor(value["input"]), _constant(axis)]}
        reduction = {"op": "FiniteSum" if value["reduction"] in {"Add", "Mean"} else "FiniteProduct",
                     "bound_index": "i", "index_domain": {"lower": _constant(0), "upper_exclusive": upper},
                     "body": body, "reduction_order": "left_to_right"}
        if value["reduction"] == "Mean":
            reduction = {"op": "Divide", "args": [reduction, upper], "normalization": "arithmetic_mean"}
        target = _indexed(output, outer)
        map_value = {"op": "Map", "bound_index": "r", "index_domain": {"lower": _constant(0),
                     "upper_exclusive": {"op": "FunctionCall", "name": "dim", "args": [self.first_tensor(value["input"]), _constant(0)]}},
                     "output": target, "body": reduction, "shape_constraints": value.get("shape_constraints", [])}
        return target, map_value

    def first_tensor(self, node: dict[str, Any]) -> dict[str, Any]:
        if node.get("op") == "FreeVariable": return deepcopy(node)
        for child in node.get("args", []):
            found = self.first_tensor(child)
            if found.get("name") != "unknown_tensor": return found
        return _variable("unknown_tensor")

    def elementize(self, node: dict[str, Any], indices: list[dict[str, Any]], primary: bool = False) -> dict[str, Any]:
        op = node.get("op")
        if op == "FreeVariable":
            used = indices if primary else [indices[-1]]
            constraint = {"kind": "broadcast_rank", "tensor": node["name"], "required_rank": len(used),
                          "relation": "trailing dimensions broadcast to reduction input"}
            self.state.constraints.append(constraint)
            return {"op": "IndexedValue", "name": node["name"], "indices": deepcopy(used),
                    "shape_constraints": [constraint]}
        if op in {"Add", "Subtract", "Multiply", "Divide", "Power"}:
            return {"op": op, "args": [self.elementize(child, indices, primary=(primary and pos == 0))
                                        for pos, child in enumerate(node.get("args", []))]}
        if op == "FunctionCall":
            return {**node, "args": [self.elementize(child, indices, primary=(primary and pos == 0))
                                      for pos, child in enumerate(node.get("args", []))]}
        return deepcopy(node)


class FormulaParser:
    """Parser for the deliberately small decorator equation DSL."""

    def __init__(self, text: str):
        self.text = text.strip()

    @staticmethod
    def split_top(text: str, separator: str) -> list[str]:
        depth, start, result = 0, 0, []
        for index, char in enumerate(text):
            depth += char in "(["
            depth -= char in ")]"
            if char == separator and depth == 0:
                result.append(text[start:index].strip()); start = index + 1
        result.append(text[start:].strip())
        return result

    def parse(self) -> dict[str, Any]:
        parts = self.split_top(self.text, "=")
        if len(parts) != 2: raise AuditError("AMBIGUOUS_FORMULA_PARSE: expected one top-level =")
        preliminary = self.term(parts[0], set())
        outer_bound = {str(item.get("name")) for item in preliminary.get("indices", [])
                       if item.get("op") in {"FreeVariable", "BoundVariable"}}
        target, expression = self.term(parts[0], outer_bound), self.term(parts[1], outer_bound)
        result = {"schema_version": SCHEMA_VERSION, "status": "EXPRESSION_EXTRACTED",
                  "outputs": [{"target": target, "expression": expression}],
                  "numeric_domain": {"category": "symbolic_numeric"}, "source_correspondence": [], "diagnostics": []}
        return result

    def term(self, text: str, bound: set[str]) -> dict[str, Any]:
        text = text.strip()
        for name, op in (("sum", "FiniteSum"), ("prod", "FiniteProduct")):
            if text.startswith(name + "(") and text.endswith(")"):
                inside = text[len(name) + 1:-1]
                pieces = self.split_top(inside, ",")
                if len(pieces) != 2 or "=" not in pieces[0] or ".." not in pieces[0]:
                    raise AuditError("AMBIGUOUS_FORMULA_PARSE: reduction syntax is sum(i=0..N-1, body)")
                index, domain = pieces[0].split("=", 1); lower, upper = domain.split("..", 1)
                upper_exclusive = self.upper_exclusive(upper.strip(), bound)
                return {"op": op, "bound_index": index.strip(),
                        "index_domain": {"lower": self.term(lower, bound), "upper_exclusive": upper_exclusive},
                        "body": self.term(pieces[1], bound | {index.strip()}), "reduction_order": "left_to_right"}
        try:
            parsed = ast.parse(text, mode="eval").body
        except SyntaxError as exc:
            raise AuditError(f"AMBIGUOUS_FORMULA_PARSE: {exc}") from exc
        return self.python_term(parsed, bound)

    def upper_exclusive(self, text: str, bound: set[str]) -> dict[str, Any]:
        parsed = self.term(text, bound)
        if parsed.get("op") == "Subtract" and parsed.get("args", [None, None])[1] == _constant(1):
            return parsed["args"][0]
        return {"op": "Add", "args": [parsed, _constant(1)]}

    def python_term(self, node: ast.AST, bound: set[str]) -> dict[str, Any]:
        if isinstance(node, ast.Constant): return _constant(node.value)
        if isinstance(node, ast.Name): return _variable(node.id, node.id in bound)
        if isinstance(node, ast.Subscript):
            indices = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return _indexed(_name(node.value), [self.python_term(item, bound) for item in indices])
        if isinstance(node, ast.BinOp):
            operations = {ast.Add: "Add", ast.Sub: "Subtract", ast.Mult: "Multiply", ast.Div: "Divide", ast.Pow: "Power"}
            return {"op": operations[type(node.op)], "args": [self.python_term(node.left, bound), self.python_term(node.right, bound)]}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return {"op": "Negate", "args": [self.python_term(node.operand, bound)]}
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            operations = {ast.Gt: "GreaterThan", ast.GtE: "GreaterEqual", ast.Lt: "LessThan",
                          ast.LtE: "LessEqual", ast.Eq: "Equal", ast.NotEq: "NotEqual"}
            return {"op": "Compare", "comparison": operations.get(type(node.ops[0]), type(node.ops[0]).__name__),
                    "args": [self.python_term(node.left, bound), self.python_term(node.comparators[0], bound)]}
        if isinstance(node, ast.IfExp):
            return {"op": "IfThenElse", "condition": self.python_term(node.test, bound),
                    "then": self.python_term(node.body, bound), "else": self.python_term(node.orelse, bound)}
        if isinstance(node, ast.Call):
            return {"op": "FunctionCall", "name": _name(node.func), "args": [self.python_term(x, bound) for x in node.args]}
        raise AuditError(f"AMBIGUOUS_FORMULA_PARSE: unsupported {type(node).__name__}")


IGNORED_COMPARE_KEYS = {"source_node_ids", "source_spans", "shape_constraints", "alignment_constraints",
                        "api", "reduction_order", "original_index", "normalization", "semantic_family",
                        "reference_contract", "equivalence_scope", "mutation", "numeral_representation",
                        "mathematical_semantic", "source_span", "operator_span", "callable_span", "argument_spans", "keyword_spans",
                        "condition_span", "branch_spans"}


def _strip_map(output: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(output)
    expression = value["expression"]
    if expression.get("op") == "Map":
        value["target"], value["expression"] = expression["output"], expression["body"]
    value["expression"] = _comparison_normalize(value["expression"])
    return value


def _comparison_normalize(node: Any) -> Any:
    if isinstance(node, list): return [_comparison_normalize(item) for item in node]
    if not isinstance(node, dict): return node
    result = {key: _comparison_normalize(value) for key, value in node.items()}
    step = result.get("step")
    if isinstance(step, dict) and step.get("op") == "Constant" and step.get("value") == 1 and {"lower", "upper_exclusive"} <= result.keys():
        result.pop("step")
    if result.get("op") == "FoldLeft" and result.get("operation") in {"Add", "Multiply"}:
        identity = 0 if result["operation"] == "Add" else 1
        initial = result.get("initial_value")
        if isinstance(initial, dict) and initial.get("op") == "Constant" and initial.get("value") in {identity, float(identity)}:
            result = {"op": "FiniteSum" if result["operation"] == "Add" else "FiniteProduct",
                      "bound_index": result["bound_index"], "index_domain": result["index_domain"],
                      "body": result["body"], "reduction_order": result.get("reduction_order", "left_to_right")}
    return result


def compare_symbolic(implementation: dict[str, Any], human: dict[str, Any]) -> dict[str, Any]:
    """Find a bijective alpha/symbol rename while preserving expression graph shape."""
    mappings: dict[str, dict[str, str]] = {"symbols": {}, "bound_indices": {}}
    reverse: dict[str, dict[str, str]] = {"symbols": {}, "bound_indices": {}}

    def bind(kind: str, left: str, right: str) -> bool:
        old, back = mappings[kind].get(left), reverse[kind].get(right)
        if (old is not None and old != right) or (back is not None and back != left): return False
        mappings[kind][left] = right; reverse[kind][right] = left; return True

    def match(left: Any, right: Any) -> bool:
        if isinstance(left, list) or isinstance(right, list):
            return isinstance(left, list) and isinstance(right, list) and len(left) == len(right) and all(match(a, b) for a, b in zip(left, right))
        if not isinstance(left, dict) or not isinstance(right, dict): return left == right
        if left.get("op") == "FunctionCall" and left.get("name") == "dim" and right.get("op") == "FreeVariable":
            dim_name = "dim(" + ",".join(str(item.get("name", item.get("value", "?"))) for item in left.get("args", [])) + ")"
            return bind("symbols", dim_name, str(right.get("name")))
        if right.get("op") == "FunctionCall" and right.get("name") == "dim" and left.get("op") == "FreeVariable":
            dim_name = "dim(" + ",".join(str(item.get("name", item.get("value", "?"))) for item in right.get("args", [])) + ")"
            return bind("symbols", str(left.get("name")), dim_name)
        if left.get("op") != right.get("op"): return False
        op = left.get("op")
        if op == "BoundVariable": return bind("bound_indices", str(left.get("name")), str(right.get("name")))
        if op in {"FreeVariable", "IndexedValue"}:
            if not bind("symbols", str(left.get("name")), str(right.get("name"))): return False
        if op in {"FiniteSum", "FiniteProduct", "FoldLeft", "Map"}:
            if not bind("bound_indices", str(left.get("bound_index")), str(right.get("bound_index"))): return False
        left_keys = set(left) - IGNORED_COMPARE_KEYS - ({"name"} if op in {"FreeVariable", "BoundVariable", "IndexedValue"} else set()) - ({"bound_index"} if op in {"FiniteSum", "FiniteProduct", "FoldLeft", "Map"} else set())
        right_keys = set(right) - IGNORED_COMPARE_KEYS - ({"name"} if op in {"FreeVariable", "BoundVariable", "IndexedValue"} else set()) - ({"bound_index"} if op in {"FiniteSum", "FiniteProduct", "FoldLeft", "Map"} else set())
        if left_keys != right_keys: return False
        if op in {"Add", "Multiply"} and set(left_keys) == {"op", "args"}:
            def flattened(value: dict[str, Any]) -> list[Any]:
                return [term for argument in value.get("args", [])
                        for term in (flattened(argument) if isinstance(argument, dict) and argument.get("op") == op else [argument])]
            left_terms, right_terms = flattened(left), flattened(right)
            if len(left_terms) != len(right_terms): return False
            def pair(remaining_left: list[Any], remaining_right: list[Any]) -> bool:
                if not remaining_left: return True
                for index, candidate in enumerate(remaining_right):
                    snapshot = deepcopy((mappings, reverse))
                    if match(remaining_left[0], candidate) and pair(remaining_left[1:], remaining_right[:index] + remaining_right[index + 1:]):
                        return True
                    mappings.clear(); mappings.update(snapshot[0]); reverse.clear(); reverse.update(snapshot[1])
                return False
            return pair(left_terms, right_terms)
        return all(match(left[key], right[key]) for key in left_keys)

    left = _strip_map(implementation["outputs"][0]); right = _strip_map(human["outputs"][0])
    def symbols(value: Any) -> set[str]:
        if isinstance(value, list): return set().union(*(symbols(item) for item in value)) if value else set()
        if not isinstance(value, dict): return set()
        own = {str(value["name"])} if value.get("op") in {"FreeVariable", "IndexedValue"} and "name" in value else set()
        return own | set().union(*(symbols(item) for item in value.values()))
    # Same-named free symbols denote the same visible input.  Leaving them free
    # would incorrectly accept branch/input swaps as an alpha rename.
    for shared in sorted(symbols(left) & symbols(right)):
        bind("symbols", shared, shared)
    matched = match(left, right)
    return {"status": "EQUIVALENT_BY_EXACT_TRANSFORMATIONS" if matched else "NO_ALLOWED_APPROXIMATION_FOUND",
            "match": matched, "mapping": mappings if matched else {},
            "checks": {"alpha_rename": matched, "expression_graph_isomorphism": matched,
                       "finite_sum_map_normalization": matched, "simple_algebraic_equivalence": matched},
            "implementation": left, "human": right}


def _lean_name(name: str) -> str:
    cleaned = re.sub(r"\W", "_", name)
    if not cleaned or cleaned[0].isdigit(): cleaned = "v_" + cleaned
    if cleaned in {"def", "theorem", "if", "then", "else", "match", "namespace"}: cleaned = "v_" + cleaned
    return cleaned


def _lean_inventory(nodes: list[dict[str, Any]], rename: dict[str, str]) -> tuple[dict[str, int], set[str], set[str], dict[str, int]]:
    arrays: dict[str, int] = {}
    naturals: set[str] = set()
    scalars: set[str] = set()
    functions: dict[str, int] = {}

    def mapped(name: str) -> str: return rename.get(name, name)

    def walk(node: Any, local: set[str], natural_context: bool = False) -> None:
        if isinstance(node, list):
            for item in node: walk(item, local, natural_context)
            return
        if not isinstance(node, dict): return
        op = node.get("op")
        if op == "IndexedValue":
            name = mapped(str(node["name"])); arrays[name] = max(arrays.get(name, 0), len(node.get("indices", [])))
            for item in node.get("indices", []): walk(item, local, True)
            return
        if op in {"FreeVariable", "BoundVariable"}:
            name = mapped(str(node["name"]))
            if name not in local: (naturals if natural_context or op == "BoundVariable" else scalars).add(name)
            return
        if op in {"FiniteSum", "FiniteProduct"}:
            domain, index = node["index_domain"], str(node["bound_index"])
            walk(domain["lower"], local, True); walk(domain["upper_exclusive"], local, True)
            walk(node["body"], local | {mapped(index)}, False); return
        if op == "FunctionCall" and node.get("name") == "dim":
            key = "dim(" + ",".join(str(item.get("name", item.get("value", "?"))) for item in node.get("args", [])) + ")"
            naturals.add(mapped(key)); return
        if op == "FunctionCall":
            functions[str(node.get("name"))] = max(functions.get(str(node.get("name")), 0), len(node.get("args", [])))
        for key, value in node.items():
            if key not in IGNORED_COMPARE_KEYS: walk(value, local, natural_context)

    for root in nodes: walk(root, set())
    scalars -= naturals
    scalars -= set(arrays)
    naturals -= set(arrays)
    return arrays, naturals, scalars, functions


def _lean_expression(node: dict[str, Any], rename: dict[str, str], local: set[str] | None = None) -> str:
    local = local or set()
    op = node.get("op")
    mapped = lambda name: _lean_name(rename.get(str(name), str(name)))
    if op == "Constant":
        value = node.get("value")
        if value is None: return "0"
        if isinstance(value, float) and value.is_integer(): value = int(value)
        return str(value)
    if op in {"FreeVariable", "BoundVariable"}: return mapped(node.get("name"))
    if op == "IndexedValue":
        args = " ".join(f"({_lean_expression(item, rename, local)})" for item in node.get("indices", []))
        return f"{mapped(node.get('name'))} {args}".rstrip()
    if op in {"Add", "Subtract", "Multiply", "Divide", "Power"}:
        symbol = {"Add": "+", "Subtract": "-", "Multiply": "*", "Divide": "/", "Power": "^"}[op]
        return "(" + f" {symbol} ".join(_lean_expression(item, rename, local) for item in node.get("args", [])) + ")"
    if op == "Negate": return f"(-{_lean_expression(node['args'][0], rename, local)})"
    if op == "Compare":
        symbol = {"GreaterThan": ">", "GreaterEqual": ">=", "LessThan": "<", "LessEqual": "<=",
                  "Equal": "=", "NotEqual": "≠"}.get(node.get("comparison"), "=")
        return f"({_lean_expression(node['args'][0], rename, local)} {symbol} {_lean_expression(node['args'][1], rename, local)})"
    if op == "IfThenElse":
        return f"(if {_lean_expression(node['condition'], rename, local)} then {_lean_expression(node['then'], rename, local)} else {_lean_expression(node['else'], rename, local)})"
    if op in {"FiniteSum", "FiniteProduct"}:
        index = str(node["bound_index"]); lean_index = mapped(index)
        upper = _lean_expression(node["index_domain"]["upper_exclusive"], rename, local)
        lower = node["index_domain"].get("lower", _constant(0))
        if not (isinstance(lower, dict) and lower.get("op") == "Constant" and lower.get("value") == 0):
            raise AuditError("LEAN_UNSUPPORTED_EXPRESSION: non-zero reduction lower bound")
        body = _lean_expression(node["body"], rename, local | {rename.get(index, index)})
        reducer = "sumN" if op == "FiniteSum" else "productN"
        return f"{reducer} ({upper}) (fun {lean_index} => {body})"
    if op == "FunctionCall" and node.get("name") == "dim":
        key = "dim(" + ",".join(str(item.get("name", item.get("value", "?"))) for item in node.get("args", [])) + ")"
        return mapped(key)
    if op == "FunctionCall":
        args = " ".join(f"({_lean_expression(item, rename, local)})" for item in node.get("args", []))
        return f"{_lean_name(str(node.get('name')))} {args}".rstrip()
    raise AuditError(f"LEAN_UNSUPPORTED_EXPRESSION: {op}")


def generate_lean(comparison: dict[str, Any], source_hash: str) -> str:
    """Translate both compared IR graphs and emit their kernel-checkable equality."""
    if not comparison.get("match"):
        return "-- No theorem emitted: implementation and theory expressions did not match.\n"
    symbol_rename = {**comparison["mapping"]["symbols"], **comparison["mapping"]["bound_indices"]}
    implementation_node, theory_node = comparison["implementation"]["expression"], comparison["human"]["expression"]
    left_inventory = _lean_inventory([implementation_node], symbol_rename)
    right_inventory = _lean_inventory([theory_node], {})
    arrays = {**left_inventory[0], **right_inventory[0]}
    naturals = left_inventory[1] | right_inventory[1]
    scalars = left_inventory[2] | right_inventory[2]
    functions = {**left_inventory[3], **right_inventory[3]}
    parameters = []
    for name in sorted(naturals): parameters.append(f"({_lean_name(name)} : Nat)")
    for name, arity in sorted(arrays.items()):
        parameters.append(f"({_lean_name(name)} : {'Nat → ' * arity}Int)")
    for name in sorted(scalars): parameters.append(f"({_lean_name(name)} : Int)")
    for name, arity in sorted(functions.items()): parameters.append(f"({_lean_name(name)} : {'Int → ' * arity}Int)")
    parameter_text = " ".join(parameters)
    argument_text = " ".join(_lean_name(name) for name in sorted(naturals))
    argument_text += (" " if argument_text and arrays else "") + " ".join(_lean_name(name) for name in sorted(arrays))
    argument_text += (" " if argument_text and scalars else "") + " ".join(_lean_name(name) for name in sorted(scalars))
    argument_text += (" " if argument_text and functions else "") + " ".join(_lean_name(name) for name in sorted(functions))
    implementation_expression = _lean_expression(implementation_node, symbol_rename)
    theory_expression = _lean_expression(theory_node, {})
    mapping = json.dumps(comparison["mapping"], ensure_ascii=False, sort_keys=True)
    return f'''import CppAudit.Semantics.Fold

namespace CppAudit.Generated.PythonAudit

/-- SHA-256 of the Python source whose AST produced the implementation IR. -/
def implementationSourceHash : String := "{source_hash}"

/-- Auditable symbol correspondence found by graph isomorphism. -/
def symbolMapping : String := {json.dumps(mapping)}

def sumN (n : Nat) (f : Nat → Int) : Int :=
  (List.range n).foldl (fun acc i => acc + f i) 0

def productN (n : Nat) (f : Nat → Int) : Int :=
  (List.range n).foldl (fun acc i => acc * f i) 1

def implementationExpression {parameter_text} : Int :=
  {implementation_expression}

def theoryExpression {parameter_text} : Int :=
  {theory_expression}

/-- The kernel checks the two separately translated expression graphs. -/
theorem extracted_expression_matches_theory {parameter_text} :
    implementationExpression {argument_text} = theoryExpression {argument_text} := by
  simp [implementationExpression, theoryExpression, Int.add_comm, Int.mul_comm]

end CppAudit.Generated.PythonAudit
'''


@dataclass
class PythonAuditResult:
    status: str
    mode: str
    implementation: dict[str, Any]
    theory: dict[str, Any] | None
    comparison: dict[str, Any] | None
    output_slice: dict[str, Any]
    renderings: dict[str, str]
    lean: dict[str, Any]
    diagnostics: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.__dict__)


def audit_python(source: str | Path, *, output: str | None = None, function: str | None = None,
                 mode: AuditMode | str = AuditMode.STRICT, lean_file: str | Path | None = None,
                 verify_lean: bool = True,
                 library_registry: LibraryContractRegistry | None = None,
                 library_versions: dict[str, str] | None = None) -> PythonAuditResult:
    path = Path(source)
    text = path.read_text(encoding="utf-8")
    mode = AuditMode(mode)
    tree = ast.parse(text, filename=str(path), type_comments=True)
    builder = PythonExpressionBuilder(path.resolve(), tree, contract_registry=library_registry,
                                      library_versions=library_versions)
    implementation, metadata, output_slice = builder.extract(function, output)
    theory_ir = FormulaParser(metadata["expression"]).parse() if metadata else None
    comparison = compare_symbolic(implementation, theory_ir) if theory_ir else None
    diagnostics = list(implementation["diagnostics"])
    if theory_ir is None:
        diagnostics.append({"code": "THEORY_NOT_REGISTERED", "message": "no @audit.theory decorator was found"})
    elif not comparison["match"]:
        diagnostics.append({"code": "THEORY_IMPLEMENTATION_MISMATCH", "message": "independently extracted and registered expressions differ"})
    source_hash = sha256(text.encode()).hexdigest()
    lean_source = generate_lean(comparison or {}, source_hash)
    lean_result: dict[str, Any] = {"status": "NOT_RUN", "kernel_verified": False, "source": lean_source}
    if lean_file:
        lean_path = Path(lean_file)
        lean_path.parent.mkdir(parents=True, exist_ok=True)
        lean_path.write_text(lean_source, encoding="utf-8")
        lean_result["file"] = str(lean_path.resolve())
    if verify_lean and comparison and comparison.get("match"):
        target = Path(lean_file) if lean_file else path.parent / ".python-audit-certificate.lean"
        if not lean_file: target.write_text(lean_source, encoding="utf-8")
        try:
            lean_root = Path(__file__).resolve().parents[2]
            command, environment = _lean_invocation(lean_root, target)
            process = subprocess.run(command, cwd=lean_root, env=environment,
                                     text=True, capture_output=True, timeout=60, check=False)
            lean_result.update({"status": "LEAN_KERNEL_VERIFIED" if process.returncode == 0 else "LEAN_VERIFICATION_FAILED",
                                "kernel_verified": process.returncode == 0, "returncode": process.returncode,
                                "stdout": process.stdout, "stderr": process.stderr})
            if process.returncode: diagnostics.append({"code": "LEAN_VERIFICATION_FAILED", "message": process.stderr.strip()})
        except (OSError, subprocess.TimeoutExpired) as exc:
            lean_result.update({"status": "LEAN_UNAVAILABLE", "error": str(exc)})
            diagnostics.append({"code": "LEAN_UNAVAILABLE", "message": str(exc)})
        finally:
            if not lean_file and target.exists(): target.unlink()
    failed = (not comparison or not comparison.get("match") or not lean_result.get("kernel_verified"))
    status = "FAIL" if mode is AuditMode.STRICT and failed else ("PASS_WITH_FINDINGS" if diagnostics else "PASS")
    renderings = {fmt: render_expression(implementation, fmt) for fmt in ("latex", "unicode", "markdown", "json")}
    return PythonAuditResult(status, mode.value, implementation, theory_ir, comparison, output_slice,
                             renderings, lean_result, diagnostics)


def render_python_report(result: PythonAuditResult) -> str:
    comparison = result.comparison or {"status": "NOT_COMPARED", "mapping": {}}
    lines = ["# Python numeric expression audit", "", f"Status: **{result.status}**", f"Mode: `{result.mode}`", "",
             "## Independently extracted implementation", "", "```text", result.renderings["unicode"].strip(), "```", "",
             "## Registered theory", "", "```text",
             render_expression(result.theory, "unicode").strip() if result.theory else "not registered", "```", "",
             "## Comparison", "", f"`{comparison['status']}`", "", "```json",
             json.dumps(comparison.get("mapping", {}), indent=2, ensure_ascii=False), "```", "",
             "## Library reference contracts", "", "```json",
             json.dumps(result.implementation.get("library_contracts", []), indent=2, ensure_ascii=False), "```", "",
             "## Execution semantics", "", "```json",
             json.dumps(result.implementation.get("execution_ir", {}), indent=2, ensure_ascii=False), "```", "",
             "## Lean", "", f"`{result.lean['status']}`", "", "## Shape and alignment constraints", "", "```json",
             json.dumps(result.implementation.get("shape_constraints", []), indent=2, ensure_ascii=False), "```", "",
             "## Diagnostics", ""]
    lines += [f"- `{item['code']}`: {item['message']}" for item in result.diagnostics] or ["- None"]
    return "\n".join(lines) + "\n"
