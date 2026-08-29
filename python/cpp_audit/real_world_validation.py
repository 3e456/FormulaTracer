"""Read-only corpus inventory and empirical FormulaTracer validation harness.

The scanner reads source and project metadata only.  It never imports audited
modules, opens referenced research datasets, or writes beneath the corpus root.
Copied mutation sources live in a temporary output directory and are removed.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
import gc
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import tracemalloc
from typing import Any, Callable, Iterable

from .library_contracts import LibraryContractRegistry
from .project import FormulaTracer
from .python_audit import compare_symbolic
from .semantic_debugger import _compare, _semantic_signature


SOURCE_SUFFIXES = {".py": "Python", ".rs": "Rust", ".cpp": "C++", ".cc": "C++",
                   ".cxx": "C++", ".hpp": "C++", ".h": "C++"}
METADATA_NAMES = {"Cargo.toml", "CMakeLists.txt", "pyproject.toml"}
ENVIRONMENT_PREFIXES = ("requirements", "environment")
EXCLUDED_DIRECTORY_NAMES = {
    ".git", ".venv", "venv", "env", "site-packages", "node_modules", "__pycache__",
    "target", "build", "dist", ".deps", "vendor", "third_party", "extern", "external",
    ".mypy_cache", ".pytest_cache", "$recycle.bin",
    "system volume information", "found.000", "found.001", "found.002", "found.003",
    "found.004", "found.005",
}
EXCLUDED_PATH_FRAGMENTS = {
    ("transport_router_data", "staging"),
    ("data", "_faostat_cache"),
}
NUMERIC_PREFIXES = {
    "numpy", "scipy", "pandas", "xarray", "dask", "geopandas", "shapely", "rasterio",
    "pyproj", "netcdf4", "igraph", "numba", "jax", "torch", "cupy", "sympy", "sklearn",
    "statsmodels", "networkx", "polars", "pyarrow", "h5py", "zarr", "xgboost", "lightgbm",
}
SINK_NAMES = {"to_csv", "to_parquet", "to_netcdf", "save", "savez", "dump", "write", "export"}
STATUS_BUCKETS = (
    "END_TO_END_KERNEL_VERIFIED", "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS",
    "END_TO_END_ENCLOSURE_VERIFIED", "PARTIAL_END_TO_END_VERIFICATION",
    "END_TO_END_UNRESOLVED", "END_TO_END_FAILED",
)
UNRESOLVED_TAXONOMY = (
    "THEORY_MISSING", "UNSUPPORTED_SYNTAX", "DYNAMIC_IMPORT", "REFLECTION", "ALIAS_UNRESOLVED",
    "LOOP_INVARIANT_REQUIRED", "LIBRARY_REFERENCE_INSUFFICIENT", "UNKNOWN_LIBRARY",
    "SHAPE_UNRESOLVED", "RANGE_UNRESOLVED", "ROUNDING_BOUND_UNRESOLVED", "FFI_UNRESOLVED",
    "SERIALIZATION_UNRESOLVED", "INPUT_RANGE_MISSING", "EXTERNAL_DATA_REQUIRED", "OTHER",
)


def _json(value: Any) -> Any:
    if hasattr(value, "to_dict"): return _json(value.to_dict())
    if isinstance(value, Path): return str(value)
    if isinstance(value, ast.AST): return ast.unparse(value)
    if isinstance(value, dict): return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)): return [_json(item) for item in value]
    return value


def _hash(value: Any) -> str:
    return sha256(json.dumps(_json(value), sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _compact_ir(value: Any) -> Any:
    if isinstance(value, ast.AST): return ast.unparse(value)
    if isinstance(value, list): return [_compact_ir(item) for item in value]
    if not isinstance(value, dict): return value
    omitted = {"__env__", "__ast__", "__module__", "__span__", "__canonical__"}
    return {key: _compact_ir(item) for key, item in value.items() if key not in omitted}


def _excluded(path: Path, root: Path) -> str | None:
    try: parts = tuple(part.lower() for part in path.relative_to(root).parts)
    except ValueError: return "OUTSIDE_CORPUS_ROOT"
    for part in parts:
        if part in EXCLUDED_DIRECTORY_NAMES: return f"EXCLUDED_DIRECTORY:{part}"
    for fragment in EXCLUDED_PATH_FRAGMENTS:
        lowered = tuple(item.lower() for item in fragment)
        if any(parts[index:index + len(lowered)] == lowered for index in range(len(parts) - len(lowered) + 1)):
            return "EXCLUDED_DEPENDENCY_OR_GENERATED_SOURCE:" + "/".join(fragment)
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _canonical_call(raw: str, aliases: dict[str, str]) -> str:
    if not raw: return raw
    first, *rest = raw.split(".")
    canonical = aliases.get(first, first)
    return ".".join([canonical, *rest]) if rest else canonical


def _python_inventory(path: Path, text: str) -> dict[str, Any]:
    try: tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return {"parse_status": "FRONTEND_FAILED", "parse_error": str(exc), "functions": [], "imports": [],
                "calls": [], "numeric_calls": [], "io_sinks": [], "candidate_roots": [], "candidate_outputs": []}
    aliases: dict[str, str] = {}; imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
                imports.append(item.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for item in node.names:
                aliases[item.asname or item.name] = f"{module}.{item.name}".strip(".")
                imports.append(module)
    calls = []; numeric_calls = []; sinks = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call): continue
        raw = _call_name(node.func); canonical = _canonical_call(raw, aliases)
        record = {"callable": canonical, "raw": raw, "line": getattr(node, "lineno", 1)}
        calls.append(record)
        package = canonical.split(".", 1)[0].lower()
        if package in NUMERIC_PREFIXES: numeric_calls.append(record)
        if raw.rsplit(".", 1)[-1].lower() in SINK_NAMES:
            sinks.append({**record, "kind": "I/O_SINK"})
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent): parents[child] = parent
    functions = []; roots = []; outputs = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        returns = [item for item in ast.walk(node) if isinstance(item, ast.Return) and item.value is not None]
        function_calls = [_canonical_call(_call_name(item.func), aliases) for item in ast.walk(node) if isinstance(item, ast.Call)]
        numeric = any(call.split(".", 1)[0].lower() in NUMERIC_PREFIXES for call in function_calls)
        arithmetic = any(isinstance(item, (ast.BinOp, ast.UnaryOp, ast.Compare, ast.Subscript)) for item in ast.walk(node))
        decorators = [_call_name(item.func if isinstance(item, ast.Call) else item) for item in node.decorator_list]
        theory = any(name.endswith("theory") for name in decorators)
        function_sinks = [call for call in function_calls if call.rsplit(".", 1)[-1].lower() in SINK_NAMES]
        record = {"name": node.name, "line": node.lineno, "public": not node.name.startswith("_"),
                  "return_count": len(returns), "numeric": numeric or arithmetic, "theory": theory,
                  "sink_count": len(function_sinks)}
        functions.append(record)
        reasons = []
        if theory: reasons.append("THEORY_DECORATED")
        if record["public"] and returns and record["numeric"]: reasons.append("PUBLIC_CALCULATION_FUNCTION")
        if function_sinks: reasons.append("ARTIFACT_PRODUCER")
        if reasons: roots.append({"symbol": node.name, "line": node.lineno, "reasons": reasons})
        for returned in returns:
            name = returned.value.id if isinstance(returned.value, ast.Name) else f"return@{returned.lineno}"
            outputs.append({"name": name, "function": node.name, "line": returned.lineno, "kind": "RETURN_OUTPUT"})
    main = any(isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and "__name__" in ast.unparse(node.test)
               for node in tree.body)
    if main: roots.append({"symbol": "<module>", "line": 1, "reasons": ["MAIN_SCRIPT"]})
    for sink in sinks: outputs.append({"name": sink["raw"], "function": None, "line": sink["line"], "kind": "I/O_SINK"})
    return {"parse_status": "PARSED", "parse_error": None, "functions": functions,
            "imports": sorted(set(imports)), "calls": calls, "numeric_calls": numeric_calls,
            "io_sinks": sinks, "candidate_roots": roots, "candidate_outputs": outputs}


def _nearest_metadata_root(path: Path, corpus_root: Path) -> Path | None:
    for parent in (path.parent, *path.parents):
        if parent == corpus_root: break
        if any((parent / name).is_file() for name in METADATA_NAMES): return parent
    return None


def _heuristic_project_root(path: Path, corpus_root: Path) -> Path:
    metadata = _nearest_metadata_root(path, corpus_root)
    if metadata: return metadata
    relative = path.relative_to(corpus_root); parts = relative.parts
    if not parts or len(parts) == 1: return corpus_root
    # Unmarked source trees are grouped by their nearest directory.  Private
    # corpus naming conventions must be supplied outside the public package.
    return path.parent


def inventory_corpus(root: str | Path) -> dict[str, Any]:
    root = Path(root).resolve(); source_records = []; exclusions = Counter(); projects: dict[str, dict[str, Any]] = {}
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept = []
        for name in directories:
            reason = _excluded(current_path / name, root)
            if reason: exclusions[reason] += 1
            else: kept.append(name)
        directories[:] = kept
        for name in files:
            path = current_path / name
            is_metadata = name in METADATA_NAMES or name.lower().startswith(ENVIRONMENT_PREFIXES)
            language = SOURCE_SUFFIXES.get(path.suffix.lower())
            if not language and not is_metadata: continue
            reason = _excluded(path, root)
            if reason: exclusions[reason] += 1; continue
            stat = path.stat(); record: dict[str, Any] = {
                "path": str(path), "relative_path": str(path.relative_to(root)), "language": language or "metadata",
                "bytes": stat.st_size, "sha256": sha256(path.read_bytes()).hexdigest(), "metadata": is_metadata,
            }
            if language:
                text = path.read_text(encoding="utf-8", errors="replace")
                record["loc"] = len(text.splitlines()); record["nonblank_loc"] = sum(bool(line.strip()) for line in text.splitlines())
                if language == "Python": record.update(_python_inventory(path, text))
                else:
                    record.update({"parse_status": "SOURCE_INVENTORIED", "functions": [], "imports": [], "calls": [],
                                   "numeric_calls": [], "io_sinks": [], "candidate_roots": [], "candidate_outputs": []})
            source_records.append(record)
            project_root = _heuristic_project_root(path, root)
            project = projects.setdefault(str(project_root), {"project_root": str(project_root), "source_files": [],
                "metadata_files": [], "languages": Counter(), "loc": 0, "functions": 0, "imports": Counter(),
                "numeric_calls": Counter(), "io_sinks": 0, "candidate_roots": [], "candidate_outputs": []})
            (project["metadata_files"] if is_metadata else project["source_files"]).append(str(path))
            if language:
                project["languages"][language] += 1; project["loc"] += record["loc"]
                project["functions"] += len(record["functions"]); project["imports"].update(record["imports"])
                project["numeric_calls"].update(item["callable"] for item in record["numeric_calls"])
                project["io_sinks"] += len(record["io_sinks"])
                project["candidate_roots"].extend({"source": str(path), **item} for item in record["candidate_roots"])
                project["candidate_outputs"].extend({"source": str(path), **item} for item in record["candidate_outputs"])
    project_values = []
    for project in projects.values():
        project["languages"] = dict(project["languages"]); project["imports"] = dict(project["imports"])
        project["numeric_calls"] = dict(project["numeric_calls"])
        files = len(project["source_files"]); project["size"] = "small" if files <= 3 else "medium" if files <= 20 else "large"
        project["project_id"] = "project:" + _hash(project["project_root"])[:16]
        project_values.append(project)
    project_values.sort(key=lambda item: item["project_root"].lower())
    return {"schema_version": "1.0", "corpus_root": str(root), "scan_mode": "READ_ONLY_SOURCE_AND_METADATA",
            "exclusion_policy": {"directory_names": sorted(EXCLUDED_DIRECTORY_NAMES),
                                 "path_fragments": [list(item) for item in sorted(EXCLUDED_PATH_FRAGMENTS)]},
            "exclusion_counts": dict(exclusions), "source_files": source_records, "projects": project_values}


def _status_bucket(value: str | None) -> str:
    raw = str(value or "").upper()
    if raw in STATUS_BUCKETS: return raw
    if "KERNEL_VERIFIED_UNDER_ASSUMPTIONS" in raw or "VERIFIED_UNDER_ASSUMPTIONS" in raw:
        return "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
    if "ENCLOSURE_VERIFIED" in raw: return "END_TO_END_ENCLOSURE_VERIFIED"
    if "KERNEL_VERIFIED" in raw or raw.endswith("FULLY_VERIFIED"): return "END_TO_END_KERNEL_VERIFIED"
    if "PARTIAL" in raw: return "PARTIAL_END_TO_END_VERIFICATION"
    if "FAILED" in raw: return "END_TO_END_FAILED"
    return "END_TO_END_UNRESOLVED"


def _unresolved_causes(values: Iterable[Any]) -> list[str]:
    text = json.dumps(_json(list(values)), ensure_ascii=False, default=str).upper(); causes = []
    mapping = {
        "THEORY_MISSING": ("THEORY_NOT_PROVIDED", "THEORY_MISSING"),
        "UNSUPPORTED_SYNTAX": ("UNSUPPORTED", "SYNTAX"), "DYNAMIC_IMPORT": ("DYNAMIC_IMPORT",),
        "REFLECTION": ("REFLECTION",), "ALIAS_UNRESOLVED": ("ALIAS", "AMBIGUOUS_REEXPORT"),
        "LOOP_INVARIANT_REQUIRED": ("LOOP_INVARIANT",),
        "LIBRARY_REFERENCE_INSUFFICIENT": ("REFERENCE_INSUFFICIENT",),
        "UNKNOWN_LIBRARY": ("UNKNOWN_LIBRARY", "OPAQUE_NUMERIC_CALL", "OPAQUENUMERICCALL"),
        "SHAPE_UNRESOLVED": ("SHAPE_UNRESOLVED", "SHAPE_CONSTRAINT"),
        "RANGE_UNRESOLVED": ("RANGE_UNRESOLVED",),
        "ROUNDING_BOUND_UNRESOLVED": ("ROUNDING", "NUMERICAL_ERROR_UNRESOLVED"),
        "FFI_UNRESOLVED": ("FFI", "BINARY_ONLY"), "SERIALIZATION_UNRESOLVED": ("SERIALIZATION",),
        "INPUT_RANGE_MISSING": ("INPUT_RANGE",), "EXTERNAL_DATA_REQUIRED": ("EXTERNAL_DATA", "RUNTIME_INPUT"),
    }
    for cause, tokens in mapping.items():
        if any(token in text for token in tokens): causes.append(cause)
    return sorted(set(causes or ["OTHER"]))


def _layer_statuses(result: Any) -> dict[str, str]:
    outputs = result.outputs; theory = any(output.theory is not None for output in outputs)
    formulas = [output.formula for output in outputs]
    extracted = any(isinstance(item, dict) and item.get("op") not in {None, "UnresolvedOutput"} for item in formulas)
    graph_unresolved = bool(result.project_graph.diagnostics)
    contracts = any("library_contract" in json.dumps(_json(output), default=str) for output in outputs)
    return {
        "frontend": "PARSED" if result.modules else "FRONTEND_FAILED",
        "project_resolution": "UNRESOLVED" if graph_unresolved else "RESOLVED",
        "library_contracts": "RESOLVED_OR_NOT_REQUIRED" if contracts or extracted else "UNRESOLVED",
        "theory_binding": "THEORY_BOUND" if theory else "THEORY_NOT_PROVIDED",
        "mathematical_ir": "EXTRACTED" if extracted else "UNRESOLVED",
        "transformation": "APPLIED_OR_NOT_REQUIRED" if extracted else "UNRESOLVED",
        "approximation": "RECORDED_OR_NOT_APPLICABLE",
        "error": "ANALYZED" if any(output.error_components for output in outputs) else "UNRESOLVED",
        "range": "ANALYZED" if any(output.range_status for output in outputs) else "INPUT_RANGE_MISSING",
        "numeric_execution": "NOT_EXECUTED_STATIC_VALIDATION",
        "parallel": "RECORDED_OR_NOT_APPLICABLE", "ffi": "UNRESOLVED" if "FFI" in json.dumps(result.diagnostics).upper() else "RESOLVED_OR_NOT_APPLICABLE",
        "serialization": "ANALYZED" if result.artifacts else "NOT_APPLICABLE",
        "artifact": "DISCOVERED" if result.artifacts else "NOT_APPLICABLE",
        "lean": "APPLICABLE" if any(output.lean_status not in {None, "NOT_RUN"} for output in outputs) else "NOT_APPLICABLE",
    }


def _entry_records(project: dict[str, Any], inventory: dict[str, Any]) -> list[dict[str, Any]]:
    by_path = {item["path"]: item for item in inventory["source_files"]}
    result = []
    for path in project["source_files"]:
        item = by_path[path]
        if item["language"] == "Python" and item["parse_status"] == "PARSED" and item["candidate_roots"]:
            result.append({"entry": path, "candidate_count": len(item["candidate_roots"]), "selection": "STATIC_CANDIDATE_ROOTS"})
        elif item["language"] in {"Rust", "C++"} and Path(path).suffix.lower() in {".rs", ".cpp", ".cc", ".cxx"}:
            result.append({"entry": path, "candidate_count": 1, "selection": "LANGUAGE_SOURCE_ENTRY"})
    if not result:
        python_files = [path for path in project["source_files"] if by_path[path]["language"] == "Python"]
        if len(python_files) == 1: result.append({"entry": python_files[0], "candidate_count": 0, "selection": "SOLE_SOURCE_FALLBACK"})
    return result


def analyze_inventory(inventory: dict[str, Any], *, max_projects: int | None = None,
                      progress: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    projects = inventory["projects"][:max_projects] if max_projects else inventory["projects"]
    analyses = []; analysis_started = time.perf_counter()
    for project_index, project in enumerate(projects, start=1):
        entries = _entry_records(project, inventory); entry_results = []
        for entry in entries:
            started = time.perf_counter(); tracemalloc.start()
            try:
                result = FormulaTracer(entry["entry"], project_root=project["project_root"]).analyze()
                _, peak = tracemalloc.get_traced_memory(); elapsed = time.perf_counter() - started
                outputs = []
                for output in result.outputs:
                    outputs.append({"output_id": output.output_id, "name": output.name, "kind": output.kind,
                        "status": output.status, "end_to_end_status": output.end_to_end_status,
                        "status_bucket": _status_bucket(output.end_to_end_status or output.status),
                        "theory_status": "THEORY_BOUND" if output.theory is not None else "THEORY_NOT_PROVIDED",
                        "formula": _compact_ir(output.formula), "implementation": _compact_ir(output.implementation),
                        "range_status": output.range_status, "lean_status": output.lean_status,
                        "remaining_obligations": output.remaining_obligations})
                debug = result.debug() if any(item["status_bucket"] in {"PARTIAL_END_TO_END_VERIFICATION", "END_TO_END_UNRESOLVED", "END_TO_END_FAILED"} for item in outputs) else None
                provenance_graph = result.provenance.get("research_provenance_graph", {})
                lineage = result.provenance.get("data_lineage", {})
                entry_results.append({**entry, "status": result.status, "end_to_end_status": result.end_to_end_status,
                    "root_count": len(result.roots), "output_count": len(outputs), "graph_nodes": len(result.project_graph.modules) + len(result.project_graph.symbols),
                    "dependency_edges": len(result.project_graph.edges), "outputs": outputs,
                    "layers": _layer_statuses(result), "diagnostics": result.diagnostics,
                    "unresolved_causes": _unresolved_causes([result.diagnostics, outputs]),
                    "debug": (_compact_ir(debug.to_dict()) if debug else None),
                    "research_provenance": {"node_count": len(provenance_graph.get("nodes", [])),
                        "edge_count": len(provenance_graph.get("edges", [])),
                        "node_kinds": sorted({item.get("kind") for item in provenance_graph.get("nodes", [])}),
                        "schema_snapshots": len(result.provenance.get("output_schemas", [])),
                        "lineage_transformations": len(lineage.get("transformations", [])),
                        "lineage_field_edges": len(lineage.get("field_edges", []))},
                    "debug_localization_metrics": debug.localization_metrics if debug else {},
                    "wall_time_seconds": elapsed,
                    "peak_memory_bytes": peak, "result_hash": _hash(result.to_dict())})
            except Exception as exc:
                _, peak = tracemalloc.get_traced_memory(); elapsed = time.perf_counter() - started
                entry_results.append({**entry, "status": "ANALYSIS_EXCEPTION_FAIL_CLOSED", "end_to_end_status": "END_TO_END_FAILED",
                    "root_count": 0, "output_count": 0, "graph_nodes": 0, "dependency_edges": 0, "outputs": [],
                    "layers": {"frontend": "FRONTEND_FAILED"}, "diagnostics": [{"code": type(exc).__name__, "message": str(exc)}],
                    "unresolved_causes": _unresolved_causes([str(exc)]), "debug": None,
                    "wall_time_seconds": elapsed, "peak_memory_bytes": peak, "result_hash": None})
            finally: tracemalloc.stop()
        analyses.append({"project_id": project["project_id"], "project_root": project["project_root"],
                         "size": project["size"], "languages": project["languages"], "loc": project["loc"],
                         "source_file_count": len(project["source_files"]), "candidate_root_count": len(project["candidate_roots"]),
                         "candidate_output_count": len(project["candidate_outputs"]), "entry_status": "ENTRYPOINT_AMBIGUOUS" if len(entries) > 1 else "ENTRYPOINT_SELECTED" if entries else "NO_ENTRYPOINT_DISCOVERED",
                         "entries": entry_results})
        if progress is not None:
            progress({"stage": "PROJECT_ANALYSIS", "projects_completed": project_index,
                      "projects_total": len(projects), "project_id": project["project_id"],
                      "entries_completed": len(entry_results),
                      "elapsed_seconds": time.perf_counter() - analysis_started})
    return analyses


class _MutationTransformer(ast.NodeTransformer):
    def __init__(self, kind: str): self.kind = kind; self.changed = False; self.original_span = None
    def mark(self, node: ast.AST) -> None:
        self.changed = True; self.original_span = {"line": getattr(node, "lineno", 1), "column": getattr(node, "col_offset", 0) + 1}
    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        swaps = {"ADD_SUB": (ast.Add, ast.Sub), "SUB_ADD": (ast.Sub, ast.Add),
                 "MUL_DIV": (ast.Mult, ast.Div), "DIV_MUL": (ast.Div, ast.Mult)}
        if not self.changed and self.kind in swaps and isinstance(node.op, swaps[self.kind][0]):
            self.mark(node); node.op = swaps[self.kind][1]()
        elif not self.changed and self.kind == "WRONG_DENOMINATOR" and isinstance(node.op, ast.Div):
            self.mark(node); node.right = ast.BinOp(left=node.right, op=ast.Mult(), right=ast.Constant(value=10))
        elif not self.changed and self.kind == "UNIT_FACTOR_X10" and isinstance(node.op, (ast.Mult, ast.Div)) and isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float)):
            self.mark(node); node.right.value *= 10
        elif not self.changed and self.kind == "UNIT_FACTOR_DIV10" and isinstance(node.op, (ast.Mult, ast.Div)) and isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float)):
            self.mark(node); node.right.value /= 10
        elif not self.changed and self.kind == "UNIT_CONVERSION_REMOVAL" and isinstance(node.op, (ast.Mult, ast.Div)) and isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float)):
            self.mark(node); return node.left
        return node
    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if not self.changed and self.kind == "CONSTANT_PERTURBATION" and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            self.mark(node); node.value = node.value + 1
        elif not self.changed and self.kind == "DTYPE_NARROWING" and node.value == "float64":
            self.mark(node); node.value = "float32"
        return node
    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        mapping = {ast.Lt: ast.GtE, ast.LtE: ast.Gt, ast.Gt: ast.LtE, ast.GtE: ast.Lt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
        if not self.changed and self.kind == "COMPARISON_CHANGE" and node.ops and type(node.ops[0]) in mapping:
            self.mark(node); node.ops[0] = mapping[type(node.ops[0])]()
        return node
    def visit_If(self, node: ast.If) -> ast.AST:
        self.generic_visit(node)
        if not self.changed and self.kind == "BRANCH_INVERSION": self.mark(node); node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
        return node
    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        self.generic_visit(node)
        if not self.changed and self.kind == "INDEX_PLUS_ONE":
            self.mark(node); node.slice = ast.BinOp(left=node.slice, op=ast.Add(), right=ast.Constant(value=1))
        return node
    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node); name = _call_name(node.func)
        if not self.changed and self.kind == "SUM_MEAN" and name.rsplit(".", 1)[-1] in {"sum", "mean"}:
            self.mark(node); replacement = "mean" if name.endswith("sum") else "sum"
            if isinstance(node.func, ast.Attribute): node.func.attr = replacement
            elif isinstance(node.func, ast.Name): node.func.id = replacement
        elif not self.changed and self.kind in {"AXIS_CHANGE", "DIMENSION_CHANGE"}:
            keys = {"AXIS_CHANGE": {"axis"}, "DIMENSION_CHANGE": {"dim", "dims"}}[self.kind]
            for keyword in node.keywords:
                if keyword.arg in keys and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, int):
                    self.mark(keyword); keyword.value.value += 1; break
        elif not self.changed and self.kind == "INTERPOLATION_METHOD_CHANGE" and any(token in name.lower() for token in ("interp", "interpolate")):
            for keyword in node.keywords:
                if keyword.arg in {"method", "kind"} and isinstance(keyword.value, ast.Constant):
                    self.mark(keyword); keyword.value.value = "nearest" if keyword.value.value != "nearest" else "linear"; break
        elif not self.changed and self.kind == "FINITE_DIFFERENCE_STENCIL" and name.rsplit(".", 1)[-1] in {"diff", "gradient"}:
            self.mark(node); replacement = "gradient" if name.endswith("diff") else "diff"
            if isinstance(node.func, ast.Attribute): node.func.attr = replacement
            elif isinstance(node.func, ast.Name): node.func.id = replacement
        elif not self.changed and self.kind == "REDUCTION_ORDER_CHANGE":
            for keyword in node.keywords:
                if keyword.arg in {"reduction_order", "order"} and isinstance(keyword.value, ast.Constant):
                    self.mark(keyword); keyword.value.value = "reorderable"; break
        return node


MUTATION_KINDS = ("ADD_SUB", "SUB_ADD", "MUL_DIV", "DIV_MUL", "CONSTANT_PERTURBATION", "INDEX_PLUS_ONE",
                  "AXIS_CHANGE", "DIMENSION_CHANGE", "BRANCH_INVERSION", "COMPARISON_CHANGE",
                  "UNIT_CONVERSION_REMOVAL", "UNIT_FACTOR_X10", "UNIT_FACTOR_DIV10",
                  "SUM_MEAN", "WRONG_DENOMINATOR", "FINITE_DIFFERENCE_STENCIL", "INTERPOLATION_METHOD_CHANGE",
                  "DTYPE_NARROWING", "REDUCTION_ORDER_CHANGE")


def _mutation_source(text: str, kind: str) -> tuple[str | None, dict[str, Any] | None]:
    try: tree = ast.parse(text)
    except SyntaxError: return None, None
    transformer = _MutationTransformer(kind); mutated = transformer.visit(tree); ast.fix_missing_locations(mutated)
    if not transformer.changed: return None, None
    return ast.unparse(mutated) + "\n", transformer.original_span


def _copy_project_sources(project: dict[str, Any], root: Path, destination: Path) -> None:
    for raw in [*project["source_files"], *project["metadata_files"]]:
        source = Path(raw); relative = source.relative_to(root); target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)


def _formula_map(outputs: Iterable[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for item in outputs:
        if isinstance(item, dict): name, kind, formula = item.get("name"), item.get("kind"), item.get("formula")
        else: name, kind, formula = item.name, item.kind, item.formula
        if isinstance(formula, dict) and formula.get("op") not in {None, "UnresolvedOutput"}:
            result.setdefault((str(name), str(kind)), _compact_ir(formula))
    return result


def _symbolically_equivalent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    def wrapper(expression: dict[str, Any]) -> dict[str, Any]:
        return {"outputs": [{"target": {"op": "FreeVariable", "name": "result"}, "expression": expression}]}
    try: return bool(compare_symbolic(wrapper(left), wrapper(right))["match"])
    except (KeyError, TypeError, ValueError): return not _compare(left, right)


def mutation_validation(inventory: dict[str, Any], analyses: list[dict[str, Any]], output_root: str | Path,
                        *, max_cases: int = 120) -> dict[str, Any]:
    corpus_root = Path(inventory["corpus_root"]); output_root = Path(output_root)
    results = []; applicability = Counter(); outside_slice = Counter(); generated_attempts = 0
    project_map = {item["project_id"]: item for item in inventory["projects"]}
    analysis_map = {(project["project_id"], entry["entry"]): entry for project in analyses for entry in project["entries"]}
    with tempfile.TemporaryDirectory(prefix="mutation-corpus-", dir=output_root) as temporary:
        temp_root = Path(temporary)
        for project_id, project in project_map.items():
            if generated_attempts >= max_cases: break
            _copy_project_sources(project, corpus_root, temp_root)
            for raw in project["source_files"]:
                if generated_attempts >= max_cases: break
                source = Path(raw)
                if source.suffix.lower() != ".py" or (project_id, raw) not in analysis_map: continue
                original_entry = analysis_map[(project_id, raw)]; original_formulas = _formula_map(original_entry.get("outputs", []))
                if not original_formulas: continue
                text = source.read_text(encoding="utf-8", errors="replace")
                for kind in MUTATION_KINDS:
                    if generated_attempts >= max_cases: break
                    mutated_text, span = _mutation_source(text, kind)
                    if mutated_text is None: continue
                    generated_attempts += 1; applicability[kind] += 1; copied = temp_root / source.relative_to(corpus_root)
                    copied.write_text(mutated_text, encoding="utf-8")
                    try:
                        mutated = FormulaTracer(copied, project_root=temp_root / Path(project["project_root"]).relative_to(corpus_root)).analyze()
                        mutated_formulas = _formula_map(mutated.outputs)
                        common = sorted(set(original_formulas) & set(mutated_formulas))
                        changed = [key for key in common
                                   if _semantic_signature(original_formulas[key]) != _semantic_signature(mutated_formulas[key])]
                        if not mutated_formulas:
                            original_formula = next(iter(original_formulas.values())); mutated_formula = None
                            classification = "UNRESOLVED_FAIL_CLOSED"; differences = []
                        elif not changed:
                            outside_slice[kind] += 1; copied.write_text(text, encoding="utf-8"); continue
                        else:
                            key = changed[0]; original_formula, mutated_formula = original_formulas[key], mutated_formulas[key]
                            differences = _compare(original_formula, mutated_formula)
                            if _symbolically_equivalent(original_formula, mutated_formula): classification = "FALSE_ACCEPTANCE"
                            elif differences: classification = "DETECTED_MISMATCH"
                            else: classification = "FALSE_ACCEPTANCE"
                        results.append({"mutation_id": "mutation:" + _hash([raw, kind, span])[:16], "project_id": project_id,
                            "source": raw, "operator": kind, "original_source_span": span,
                            "original_mathematical_ir": original_formula, "mutated_mathematical_ir": mutated_formula,
                            "expected_semantic_difference": True, "ground_truth_status": "AST_MUTATION_AND_IR_CHANGE_CHECKED",
                            "classification": classification, "difference_types": [item.get("type") for item in differences],
                            "mutated_source_sha256": sha256(mutated_text.encode()).hexdigest()})
                    except Exception as exc:
                        results.append({"mutation_id": "mutation:" + _hash([raw, kind, span])[:16], "project_id": project_id,
                            "source": raw, "operator": kind, "original_source_span": span,
                            "original_mathematical_ir": next(iter(original_formulas.values())), "mutated_mathematical_ir": None,
                            "expected_semantic_difference": True, "ground_truth_status": "AST_MUTATION_APPLIED",
                            "classification": "FRONTEND_FAILURE", "diagnostic": f"{type(exc).__name__}: {exc}"})
                    finally:
                        copied.write_text(text, encoding="utf-8")
                        if "mutated" in locals(): del mutated
                        gc.collect()
    counts = Counter(item["classification"] for item in results)
    return {"schema_version": "1.0", "temporary_corpus_removed": True, "cases": results,
            "counts": dict(counts), "applicability": {kind: applicability[kind] for kind in MUTATION_KINDS},
            "generated_outside_audited_slice": {kind: outside_slice[kind] for kind in MUTATION_KINDS},
            "generated_attempts": generated_attempts, "evaluated_case_count": len(results),
            "false_acceptance_count": counts["FALSE_ACCEPTANCE"],
            "detection_rate": ((counts["DETECTED_MISMATCH"] + counts["DETECTED_RANGE_FAILURE"] + counts["DETECTED_ERROR_FAILURE"])
                               / len(results) if results else 0.0)}


class _AlphaRename(ast.NodeTransformer):
    def __init__(self): self.mapping = {}; self.changed = False
    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if not self.changed:
            candidates = [arg.arg for arg in node.args.args]
            if candidates: self.mapping[candidates[0]] = "ft_alpha_renamed"; self.changed = True
        return self.generic_visit(node)
    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self.mapping: node.id = self.mapping[node.id]
        return node
    def visit_arg(self, node: ast.arg) -> ast.AST:
        if node.arg in self.mapping: node.arg = self.mapping[node.arg]
        return node


class _TemporaryIntroduction(ast.NodeTransformer):
    def __init__(self): self.changed = False
    def visit_Return(self, node: ast.Return) -> Any:
        if self.changed or node.value is None: return node
        self.changed = True; temporary = "ft_temporary_value"
        return [ast.Assign(targets=[ast.Name(id=temporary, ctx=ast.Store())], value=node.value),
                ast.Return(value=ast.Name(id=temporary, ctx=ast.Load()))]


def _metamorphic_source(text: str, kind: str) -> str | None:
    try: tree = ast.parse(text)
    except SyntaxError: return None
    transformer = _AlphaRename() if kind == "ALPHA_RENAME" else _TemporaryIntroduction()
    result = transformer.visit(tree); ast.fix_missing_locations(result)
    return ast.unparse(result) + "\n" if transformer.changed else None


def metamorphic_validation(inventory: dict[str, Any], analyses: list[dict[str, Any]], output_root: str | Path,
                           *, max_cases: int = 40) -> dict[str, Any]:
    corpus_root = Path(inventory["corpus_root"]); output_root = Path(output_root); results = []
    project_map = {item["project_id"]: item for item in inventory["projects"]}
    analysis_map = {(project["project_id"], entry["entry"]): entry for project in analyses for entry in project["entries"]}
    with tempfile.TemporaryDirectory(prefix="metamorphic-corpus-", dir=output_root) as temporary:
        temp_root = Path(temporary)
        for project_id, project in project_map.items():
            if len(results) >= max_cases: break
            _copy_project_sources(project, corpus_root, temp_root)
            for raw in project["source_files"]:
                if len(results) >= max_cases: break
                source = Path(raw); original_entry = analysis_map.get((project_id, raw))
                original_formulas = _formula_map((original_entry or {}).get("outputs", []))
                if source.suffix.lower() != ".py" or not original_formulas: continue
                text = source.read_text(encoding="utf-8", errors="replace")
                for kind in ("ALPHA_RENAME", "TEMPORARY_VARIABLE_INTRODUCTION"):
                    transformed = _metamorphic_source(text, kind)
                    if transformed is None: continue
                    copied = temp_root / source.relative_to(corpus_root); copied.write_text(transformed, encoding="utf-8")
                    try:
                        changed = FormulaTracer(copied, project_root=temp_root / Path(project["project_root"]).relative_to(corpus_root)).analyze()
                        changed_formulas = _formula_map(changed.outputs); common = sorted(set(original_formulas) & set(changed_formulas))
                        if not common:
                            classification = "UNRESOLVED"; original_formula = next(iter(original_formulas.values())); changed_formula = None
                        else:
                            comparisons = [(original_formulas[key], changed_formulas[key]) for key in common]
                            original_formula, changed_formula = comparisons[0]
                            classification = ("TRUE_ACCEPTANCE" if all(_symbolically_equivalent(left, right) for left, right in comparisons)
                                              else "FALSE_REJECTION")
                        results.append({"case_id": "metamorphic:" + _hash([raw, kind])[:16], "project_id": project_id,
                            "source": raw, "transformation": kind, "expected_semantics_preserved": True,
                            "original_mathematical_ir": original_formula, "transformed_mathematical_ir": changed_formula,
                            "classification": classification})
                    except Exception as exc:
                        results.append({"case_id": "metamorphic:" + _hash([raw, kind])[:16], "project_id": project_id,
                            "source": raw, "transformation": kind, "expected_semantics_preserved": True,
                            "classification": "UNRESOLVED", "diagnostic": f"{type(exc).__name__}: {exc}"})
                    finally: copied.write_text(text, encoding="utf-8")
    counts = Counter(item["classification"] for item in results)
    return {"schema_version": "1.0", "temporary_corpus_removed": True, "cases": results, "counts": dict(counts),
            "false_rejection_count": counts["FALSE_REJECTION"],
            "false_rejection_rate": counts["FALSE_REJECTION"] / len(results) if results else 0.0}


def assurance_obligations(mutations: dict[str, Any], metamorphic: dict[str, Any]) -> list[dict[str, Any]]:
    mutation_available = {item["operator"] for item in mutations["cases"]}
    meta_available = {item["transformation"] for item in metamorphic["cases"]}
    obligations = [
        ("WRONG_AXIS", "AXIS_CHANGE" in mutation_available), ("BROADCAST_MISTAKE", False),
        ("OFF_BY_ONE", "INDEX_PLUS_ONE" in mutation_available), ("WRONG_DENOMINATOR", "WRONG_DENOMINATOR" in mutation_available),
        ("WRONG_UNIT", "UNIT_FACTOR_X10" in mutation_available), ("NAN_MASKING_MISTAKE", False),
        ("WRONG_DTYPE", "DTYPE_NARROWING" in mutation_available), ("PARALLEL_REDUCTION_ISSUE", "REDUCTION_ORDER_CHANGE" in mutation_available),
        ("WRONG_INTERPOLATION", "INTERPOLATION_METHOD_CHANGE" in mutation_available),
        ("WRONG_DERIVATIVE_STENCIL", "FINITE_DIFFERENCE_STENCIL" in mutation_available),
        ("ALPHA_RENAME", "ALPHA_RENAME" in meta_available),
        ("TEMPORARY_VARIABLE_INTRODUCTION", "TEMPORARY_VARIABLE_INTRODUCTION" in meta_available),
    ]
    return [{"obligation": name, "classification": "EXECUTABLE_NOW" if executed else
             "REQUIRES_MANUAL_GROUND_TRUTH" if name in {"BROADCAST_MISTAKE", "NAN_MASKING_MISTAKE"} else
             "OUT_OF_SCOPE_BY_DESIGN" if name == "PARALLEL_REDUCTION_ISSUE" else "REQUIRES_EXTERNAL_ENVIRONMENT",
             "executed": executed} for name, executed in obligations]


def summarize(inventory: dict[str, Any], analyses: list[dict[str, Any]], mutations: dict[str, Any],
              metamorphic: dict[str, Any], obligations: list[dict[str, Any]]) -> dict[str, Any]:
    sources = [item for item in inventory["source_files"] if item["language"] != "metadata"]
    entries = [entry for project in analyses for entry in project["entries"]]
    outputs = [output for entry in entries for output in entry.get("outputs", [])]
    status_counts = Counter(output["status_bucket"] for output in outputs)
    layers: dict[str, Counter] = defaultdict(Counter)
    for entry in entries:
        for layer, status in entry.get("layers", {}).items(): layers[layer][status] += 1
    causes = Counter(cause for entry in entries for cause in entry.get("unresolved_causes", []))
    debugger = Counter(finding["type"] for entry in entries if entry.get("debug") for finding in entry["debug"].get("findings", []))
    provenance_kinds = {kind for entry in entries for kind in entry.get("research_provenance", {}).get("node_kinds", [])}
    localization = Counter()
    for entry in entries:
        localization.update({key: value for key, value in entry.get("debug_localization_metrics", {}).items()
                             if isinstance(value, (int, float))})
    languages = Counter(item["language"] for item in sources)
    libraries = Counter(); registry = LibraryContractRegistry.coverage_expansion()
    contract_resolved = Counter(); reference_only = Counter()
    for item in sources:
        for call in item.get("numeric_calls", []):
            package = call["callable"].split(".", 1)[0]; libraries[package] += 1
            contract = registry.resolve(call["callable"])
            if contract:
                reference_status = str(contract.to_dict().get("provenance", {}).get("reference_status", ""))
                if reference_status in {"LEAN_VERIFIED_MAPPING", "FORMALIZED"}: contract_resolved[package] += 1
                else: reference_only[package] += 1
    algorithms = Counter()
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            op = node.get("op")
            if op:
                family = ("Reduction" if op in {"Reduce", "FiniteSum", "FiniteProduct", "Mean"} else
                          "Tensor contraction" if op in {"Dot", "MatMul", "Einsum"} else
                          "Interpolation" if op == "Interpolation" else "Finite difference" if op in {"Derivative", "DiscreteDifference"} else
                          "Elementwise" if op in {"Add", "Subtract", "Multiply", "Divide", "Power"} else "Other")
                algorithms[family] += 1
            for value in node.values(): walk(value)
        elif isinstance(node, list):
            for value in node: walk(value)
    for output in outputs: walk(output.get("formula"))
    parseable = sum(item.get("parse_status") in {"PARSED", "SOURCE_INVENTORIED"} for item in sources)
    extracted = sum(isinstance(output.get("formula"), dict) and output["formula"].get("op") not in {None, "UnresolvedOutput"} for output in outputs)
    analyzed_projects = sum(bool(project["entries"]) for project in analyses)
    successful_entries = [entry for entry in entries if entry.get("layers", {}).get("frontend") == "PARSED"]
    total_library_calls = sum(libraries.values()); resolved_library_calls = sum(contract_resolved.values()) + sum(reference_only.values())
    by_size = {}
    for size in ("small", "medium", "large"):
        selected = [project for project in analyses if project["size"] == size]
        size_outputs = [output for project in selected for entry in project["entries"] for output in entry.get("outputs", [])]
        size_extracted = sum(isinstance(output.get("formula"), dict) and output["formula"].get("op") not in {None, "UnresolvedOutput"} for output in size_outputs)
        by_size[size] = {"projects": len(selected), "source_files": sum(project["source_file_count"] for project in selected),
                         "loc": sum(project["loc"] for project in selected), "audit_roots": sum(entry.get("root_count", 0) for project in selected for entry in project["entries"]),
                         "outputs": len(size_outputs), "mathematical_ir_resolution_rate": size_extracted / len(size_outputs) if size_outputs else 0.0}
    return {"schema_version": "1.0", "status": "PRIVATE_CORPUS_VALIDATION_COMPLETED",
        "critical_false_acceptance_open": mutations["false_acceptance_count"],
        "corpus": {"projects_discovered": len(inventory["projects"]), "projects_analyzed": analyzed_projects,
                   "source_files": len(sources), "loc": sum(item.get("loc", 0) for item in sources),
                   "languages": dict(languages), "excluded": inventory["exclusion_counts"]},
        "audit": {"entries": len(entries), "audit_roots": sum(entry.get("root_count", 0) for entry in entries),
                  "outputs": len(outputs), "verification_status": {key: status_counts[key] for key in STATUS_BUCKETS},
                  "layer_status": {key: dict(value) for key, value in layers.items()},
                  "unresolved_causes": dict(causes), "debugger_findings": dict(debugger),
                  "debugger_localization": dict(localization)},
        "coverage": {"project_discovery_rate": 1.0, "project_analysis_rate": analyzed_projects / len(inventory["projects"]) if inventory["projects"] else 0,
                     "source_parse_rate": parseable / len(sources) if sources else 0,
                     "cross_file_resolution_rate": sum(entry.get("layers", {}).get("project_resolution") == "RESOLVED" for entry in successful_entries) / len(successful_entries) if successful_entries else 0,
                     "audit_root_discovery_rate": sum(bool(project["candidate_roots"]) for project in inventory["projects"]) / len(inventory["projects"]) if inventory["projects"] else 0,
                     "output_discovery_rate": sum(bool(project["candidate_outputs"]) for project in inventory["projects"]) / len(inventory["projects"]) if inventory["projects"] else 0,
                     "mathematical_ir_extraction_rate": extracted / len(outputs) if outputs else 0,
                     "library_contract_resolution_rate": resolved_library_calls / total_library_calls if total_library_calls else 0,
                     "range_analysis_rate": sum(entry.get("layers", {}).get("range") == "ANALYZED" for entry in successful_entries) / len(successful_entries) if successful_entries else 0,
                     "error_analysis_rate": sum(entry.get("layers", {}).get("error") == "ANALYZED" for entry in successful_entries) / len(successful_entries) if successful_entries else 0,
                     "lean_applicable_rate": sum(entry.get("layers", {}).get("lean") == "APPLICABLE" for entry in successful_entries) / len(successful_entries) if successful_entries else 0,
                     "end_to_end_verification_rate": (status_counts["END_TO_END_KERNEL_VERIFIED"] + status_counts["END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"] + status_counts["END_TO_END_ENCLOSURE_VERIFIED"]) / len(outputs) if outputs else 0,
                     "research_provenance_node_kinds": sorted(provenance_kinds),
                     "research_provenance_node_count": sum(entry.get("research_provenance", {}).get("node_count", 0) for entry in entries),
                     "schema_snapshot_count": sum(entry.get("research_provenance", {}).get("schema_snapshots", 0) for entry in entries),
                     "data_lineage_transformation_count": sum(entry.get("research_provenance", {}).get("lineage_transformations", 0) for entry in entries),
                     "field_lineage_edge_count": sum(entry.get("research_provenance", {}).get("lineage_field_edges", 0) for entry in entries)},
        "libraries": {package: {"calls_observed": count, "contract_resolved": contract_resolved[package],
                                "reference_only": reference_only[package],
                                "unresolved": count - contract_resolved[package] - reference_only[package]} for package, count in libraries.most_common()},
        "algorithm_families": dict(algorithms),
        "project_size": by_size,
        "mutation": {key: value for key, value in mutations.items() if key != "cases"},
        "metamorphic": {key: value for key, value in metamorphic.items() if key != "cases"},
        "assurance_obligations": obligations,
        "performance": {"total_wall_time_seconds": sum(entry.get("wall_time_seconds", 0) for entry in entries),
                        "max_entry_wall_time_seconds": max((entry.get("wall_time_seconds", 0) for entry in entries), default=0),
                        "max_peak_memory_bytes": max((entry.get("peak_memory_bytes", 0) for entry in entries), default=0)},
        "trust_boundary": {"research_code_assumed_correct": False, "formal_guarantee_equals_empirical_validation": False,
                           "data_file_content_read": False, "corpus_modified": False}}


def write_validation(root: str | Path, output: str | Path, *, max_projects: int | None = None,
                     max_mutations: int = 120, max_metamorphic: int = 40,
                     progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    inventory = inventory_corpus(root)
    (output / "inventory.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    if progress is not None:
        progress({"stage": "INVENTORY_COMPLETE", "projects_discovered": len(inventory["projects"]),
                  "source_files_discovered": len(inventory["source_files"]),
                  "elapsed_seconds": time.perf_counter() - started})
    analyses = analyze_inventory(inventory, max_projects=max_projects, progress=progress)
    (output / "project-results.json").write_text(
        json.dumps(_json(analyses), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    if progress is not None:
        progress({"stage": "PROJECT_ANALYSIS_COMPLETE", "projects_analyzed": len(analyses),
                  "elapsed_seconds": time.perf_counter() - started})
    mutations = mutation_validation(inventory, analyses, output, max_cases=max_mutations)
    (output / "mutation-results.json").write_text(
        json.dumps(_json(mutations), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    if progress is not None:
        progress({"stage": "MUTATION_COMPLETE", "cases": len(mutations.get("cases", [])),
                  "elapsed_seconds": time.perf_counter() - started})
    metamorphic = metamorphic_validation(inventory, analyses, output, max_cases=max_metamorphic)
    (output / "metamorphic-results.json").write_text(
        json.dumps(_json(metamorphic), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    if progress is not None:
        progress({"stage": "METAMORPHIC_COMPLETE", "cases": len(metamorphic.get("cases", [])),
                  "elapsed_seconds": time.perf_counter() - started})
    obligations = assurance_obligations(mutations, metamorphic)
    summary = summarize(inventory, analyses, mutations, metamorphic, obligations)
    artifacts = {"project-results.json": analyses, "mutation-results.json": mutations,
                 "metamorphic-results.json": metamorphic,
                 "unresolved-causes.json": summary["audit"]["unresolved_causes"],
                 "performance.json": summary["performance"], "assurance-obligations.json": obligations,
                 "summary.json": summary, "real_world_validation.json": {"summary": summary,
                    "artifacts": {"inventory": "inventory.json", "projects": "project-results.json",
                                  "mutations": "mutation-results.json", "metamorphic": "metamorphic-results.json",
                                  "unresolved_causes": "unresolved-causes.json", "performance": "performance.json"},
                    "artifact_hashes": {"inventory": _hash(inventory), "projects": _hash(analyses),
                                        "mutations": _hash(mutations), "metamorphic": _hash(metamorphic)}}}
    for name, value in artifacts.items():
        (output / name).write_text(json.dumps(_json(value), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    if progress is not None:
        progress({"stage": "COMPLETE", "status": summary["status"],
                  "elapsed_seconds": time.perf_counter() - started})
    return summary
