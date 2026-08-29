"""Project-wide, language-neutral audit discovery and Python implementation.

The resolver is deliberately static: audited modules are parsed but never imported.
This keeps project resolution independent from the process ``sys.path`` and prevents
research scripts from running as a side effect of an audit.
"""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from .core import AuditError
from .error_composition import propagate_expression_graph
from .error_ir import (BoundStatus, ErrorBound, ErrorComponent, ErrorMetric, ErrorSource,
                       build_error_analysis)
from .library_contracts import LibraryContractRegistry
from .python_audit import AuditMode, audit_python
from .expression import render_expression


def _digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return sha256(data).hexdigest()


def _serial(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _serial(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serial(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, ast.AST):
        return ast.unparse(value)
    return value


def _span(path: Path, node: ast.AST) -> dict[str, Any]:
    begin_line = getattr(node, "lineno", None) or 1
    begin_column = getattr(node, "col_offset", None) or 0
    end_line = getattr(node, "end_lineno", None) or begin_line
    end_column = getattr(node, "end_col_offset", None)
    if end_column is None: end_column = begin_column
    return {"file": str(path), "begin_line": begin_line,
            "begin_column": begin_column + 1, "end_line": end_line,
            "end_column": end_column + 1}


def _operator_span(path: Path, node: ast.BinOp, lines: Sequence[str] | None = None) -> dict[str, Any] | None:
    if getattr(node.left, "end_lineno", None) != getattr(node.right, "lineno", None): return None
    line_number = getattr(node.left, "end_lineno", None)
    start = getattr(node.left, "end_col_offset", None); stop = getattr(node.right, "col_offset", None)
    if not isinstance(line_number, int) or not isinstance(start, int) or not isinstance(stop, int): return None
    tokens = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//",
              ast.Mod: "%", ast.Pow: "**", ast.MatMult: "@", ast.BitAnd: "&", ast.BitOr: "|",
              ast.BitXor: "^", ast.LShift: "<<", ast.RShift: ">>"}
    token = tokens.get(type(node.op))
    if token is None: return None
    try: line = (lines if lines is not None else path.read_text(encoding="utf-8").splitlines())[line_number - 1]
    except (OSError, UnicodeError, IndexError): return None
    index = line.find(token, start, stop)
    if index < 0: return None
    return {"file": str(path), "begin_line": line_number, "begin_column": index + 1,
            "end_line": line_number, "end_column": index + len(token) + 1,
            "role": "operator", "operator": token}


def _ast_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _ast_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


class ProjectStatus(str, Enum):
    FULLY_VERIFIED = "PROJECT_FULLY_VERIFIED"
    VERIFIED_UNDER_ASSUMPTIONS = "PROJECT_VERIFIED_UNDER_ASSUMPTIONS"
    PARTIALLY_VERIFIED = "PROJECT_PARTIALLY_VERIFIED"
    UNRESOLVED = "PROJECT_UNRESOLVED"
    FAILED = "PROJECT_FAILED"


class OutputTargetKind(str, Enum):
    RETURN_OUTPUT = "RETURN_OUTPUT"
    VARIABLE_OUTPUT = "VARIABLE_OUTPUT"
    EXPRESSION_OUTPUT = "EXPRESSION_OUTPUT"
    FILE_OUTPUT = "FILE_OUTPUT"
    DATASET_OUTPUT = "DATASET_OUTPUT"
    STREAM_OUTPUT = "STREAM_OUTPUT"


class SharedDependencyKind(str, Enum):
    SHARED_CONSTANT = "SHARED_CONSTANT"
    SHARED_INPUT = "SHARED_INPUT"
    SHARED_FUNCTION = "SHARED_FUNCTION"
    SHARED_DATA_SOURCE = "SHARED_DATA_SOURCE"
    SHARED_INTERMEDIATE = "SHARED_INTERMEDIATE"
    SHARED_ERROR_CAUSE = "SHARED_ERROR_CAUSE"
    ROOT_DEPENDENCY = "ROOT_DEPENDENCY"
    DISCONNECTED = "DISCONNECTED"
    DEPENDENCE_UNKNOWN = "DEPENDENCE_UNKNOWN"


@dataclass(frozen=True)
class OutputTarget:
    kind: str
    name: str
    module: str | None = None
    function: str | None = None
    expression: str | None = None
    definition_line: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.kind, OutputTargetKind):
            object.__setattr__(self, "kind", self.kind.value)
        if self.kind not in {item.value for item in OutputTargetKind}:
            raise ValueError(f"UNKNOWN_OUTPUT_TARGET_KIND: {self.kind}")


@dataclass(frozen=True)
class VariableTarget(OutputTarget):
    def __init__(self, name: str, module: str | None = None, function: str | None = None,
                 definition_line: int | None = None):
        object.__setattr__(self, "kind", OutputTargetKind.VARIABLE_OUTPUT.value)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "module", module)
        object.__setattr__(self, "function", function)
        object.__setattr__(self, "expression", None)
        object.__setattr__(self, "definition_line", definition_line)


@dataclass(frozen=True)
class ExpressionTarget(OutputTarget):
    def __init__(self, expression: str, module: str | None = None, function: str | None = None):
        parsed = ast.parse(expression, mode="eval")
        forbidden = (ast.Call, ast.Lambda, ast.NamedExpr, ast.Await, ast.Yield)
        if any(isinstance(node, forbidden) for node in ast.walk(parsed)):
            raise AuditError("UNSAFE_EXPRESSION_TARGET")
        object.__setattr__(self, "kind", OutputTargetKind.EXPRESSION_OUTPUT.value)
        object.__setattr__(self, "name", expression)
        object.__setattr__(self, "module", module)
        object.__setattr__(self, "function", function)
        object.__setattr__(self, "expression", expression)
        object.__setattr__(self, "definition_line", None)


@dataclass
class ModuleNode:
    module_id: str
    name: str
    path: str
    language: str = "python"
    is_package: bool = False
    source_hash: str = ""
    status: str = "RESOLVED"


@dataclass
class SymbolNode:
    symbol_id: str
    module: str
    name: str
    kind: str
    canonical_name: str
    public: bool
    source_span: dict[str, Any]
    language: str | None = None


@dataclass
class DependencyEdge:
    source: str
    target: str
    kind: str
    alias: str | None = None
    canonical_name: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


class ImportEdge(DependencyEdge):
    def __init__(self, source: str, target: str, **kwargs: Any):
        super().__init__(source, target, "IMPORT", **kwargs)


class IncludeEdge(DependencyEdge):
    def __init__(self, source: str, target: str, **kwargs: Any):
        super().__init__(source, target, "INCLUDE", **kwargs)


class CallEdge(DependencyEdge):
    def __init__(self, source: str, target: str, **kwargs: Any):
        super().__init__(source, target, "CALL", **kwargs)


class ValueDependencyEdge(DependencyEdge):
    def __init__(self, source: str, target: str, **kwargs: Any):
        super().__init__(source, target, "VALUE_DEPENDENCY", **kwargs)


class DefinitionEdge(DependencyEdge):
    def __init__(self, source: str, target: str, **kwargs: Any):
        super().__init__(source, target, "DEFINITION", **kwargs)


class ReExportEdge(DependencyEdge):
    def __init__(self, source: str, target: str, **kwargs: Any):
        super().__init__(source, target, "RE_EXPORT", **kwargs)


class CrossLanguageCallEdge(DependencyEdge):
    def __init__(self, source: str, target: str, **kwargs: Any):
        super().__init__(source, target, "CROSS_LANGUAGE_CALL", **kwargs)


@dataclass
class ExternalSymbol:
    symbol_id: str
    language: str
    module: str
    name: str
    canonical_name: str
    resolution_status: str


@dataclass
class LanguageBoundary:
    boundary_id: str
    source_language: str
    target_language: str
    source_symbol: str
    target_symbol: str
    resolution_status: str
    representation_mapping: str
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class FFIBoundary(LanguageBoundary):
    ffi_framework: str = "UNKNOWN"
    dtype_mapping: dict[str, Any] = field(default_factory=dict)
    proof_obligations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class NativeExtension:
    name: str
    framework: str
    manifest_path: str | None
    source_root: str | None
    resolution_status: str
    exported_symbols: list[str] = field(default_factory=list)


@dataclass
class RuntimeEvidence:
    evidence_id: str
    kind: str
    status: str
    producer: dict[str, Any]
    observations: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)
    proof_authority: bool = False


@dataclass
class ProjectDependencyGraph:
    modules: list[ModuleNode] = field(default_factory=list)
    symbols: list[SymbolNode] = field(default_factory=list)
    edges: list[DependencyEdge] = field(default_factory=list)
    external_modules: list[str] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = _serial(self)
        value["graph_hash"] = _digest(value)
        return value

    @property
    def graph_hash(self) -> str:
        return self.to_dict()["graph_hash"]


@dataclass
class IOProvenance:
    module: str
    file: str
    callable: str
    source_span: dict[str, Any]


@dataclass
class SerializationBoundary:
    boundary_id: str
    mathematical_payload: Any
    serializer: str
    library_contract: dict[str, Any] | None
    status: str = "SERIALIZATION_SEPARATED_FROM_MATHEMATICAL_IR"


@dataclass
class DatasetOutput:
    name: str
    payload_symbol: str
    dimensions: list[str] = field(default_factory=list)
    dtype: str | None = None
    source_span: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutputSink:
    sink_id: str
    sink_kind: str
    format: str
    path_expression: str | None
    payload: Any
    payload_symbol: str | None
    dataset_variable: str | None
    dimensions: list[str]
    dtype: str | None
    library_contract: dict[str, Any] | None
    source_span: dict[str, Any]
    provenance: IOProvenance
    serialization_boundary: SerializationBoundary
    dataset_outputs: list[DatasetOutput] = field(default_factory=list)
    certified_payload_range: Any | None = None
    range_status: str | None = None
    range_obligations: list[dict[str, Any]] = field(default_factory=list)
    serialization_cast: dict[str, Any] | None = None


ArtifactOutput = OutputSink


@dataclass
class AuditOutputResult:
    output_id: str
    name: str
    kind: str
    theory: Any | None
    implementation: Any
    formula: Any
    residual: Any | None
    error_components: list[Any]
    error_bound: Any | None
    known_bound: Any | None
    total_bound: Any | None
    dependencies: list[str]
    source_locations: list[dict[str, Any]]
    lean_status: str
    status: str
    error_causes: list[str] = field(default_factory=list)
    slice_hash: str = ""
    value_interval: Any | None = None
    error_interval: Any | None = None
    true_value_enclosure: Any | None = None
    range_status: str | None = None
    range_obligations: list[dict[str, Any]] = field(default_factory=list)
    interval_propagation: Any | None = None
    execution_range: Any | None = None
    range_constraint_status: str | None = None
    end_to_end_claim: Any | None = None
    end_to_end_status: str | None = None
    proof_chain: Any | None = None
    total_error_bound: Any | None = None
    artifact_enclosure: Any | None = None
    remaining_obligations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AuditRootResult:
    root_id: str
    entry_module: str
    entry_symbol: str
    outputs: list[AuditOutputResult]
    dependency_slice: list[str]
    shared_dependencies: list[dict[str, Any]] = field(default_factory=list)
    root_relations: list[dict[str, Any]] = field(default_factory=list)
    status: str = "UNRESOLVED"
    graph_hash: str = ""
    end_to_end_status: str | None = None
    end_to_end_claim_ids: list[str] = field(default_factory=list)


@dataclass
class ProjectAuditResult:
    status: str
    project_graph: ProjectDependencyGraph
    roots: list[AuditRootResult]
    outputs: list[AuditOutputResult]
    modules: list[ModuleNode]
    dependencies: list[dict[str, Any]]
    shared_dependencies: list[dict[str, Any]]
    error_causes: list[dict[str, Any]]
    proofs: list[dict[str, Any]]
    artifacts: list[OutputSink]
    provenance: dict[str, Any]
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    end_to_end_status: str | None = None
    end_to_end_claims: list[dict[str, Any]] = field(default_factory=list)
    end_to_end_coverage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = _serial(self)
        value["project_graph"] = self.project_graph.to_dict()
        return value

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=True) + "\n"

    def get_output(self, name: str) -> AuditOutputResult:
        matches = [output for output in self.outputs if output.name == name or output.output_id == name]
        if len(matches) != 1:
            raise KeyError(f"Expected one output named {name!r}, found {len(matches)}")
        return matches[0]

    def write_json(self, path: str | Path) -> Path:
        target = Path(path); target.write_text(self.to_json(), encoding="utf-8"); return target

    def debug(self) -> Any:
        from .semantic_debugger import debug_project
        return debug_project(self)

    def audit_probability(self, **options: Any) -> Any:
        from .probability import audit_probability
        return audit_probability(**options)

    def create_bundle(self, path: str | Path, *, locale: str = "en-US", debug: Any = None) -> Any:
        from .assurance_release import create_audit_bundle
        return create_audit_bundle(self, path, locale=locale, debug=debug)

    def diff(self, other: Any) -> Any:
        from .assurance_release import audit_diff
        return audit_diff(self, other)

    def explain_unresolved(self) -> Any:
        from .research_provenance import explain_unresolved
        return explain_unresolved(self)

    def explain(self, baseline: Any = None) -> Any:
        from .research_provenance import explain_result
        difference = baseline.diff(self) if baseline is not None and hasattr(baseline, "diff") else None
        return explain_result(self, difference)

    def provenance_graph(self) -> Any:
        return self.provenance.get("research_provenance_graph", {})

    def accept_baseline(self) -> Any:
        from .research_provenance import AcceptedAuditBaseline
        return AcceptedAuditBaseline.from_result(self)

    def test_candidates(self) -> Any:
        from .research_provenance import generate_test_candidates
        return generate_test_candidates(self)

    def sensitivity(self) -> Any:
        from .research_provenance import sensitivity_report
        return sensitivity_report(self)

    def to_latex(self) -> str:
        def esc(value: Any) -> str:
            text = str(value)
            replacements = {"\\": r"\textbackslash{}", "_": r"\_", "%": r"\%", "&": r"\&",
                            "#": r"\#", "{": r"\{", "}": r"\}", "$": r"\$",
                            "^": r"\^{}", "~": r"\~{}"}
            return "".join(replacements.get(character, character) for character in text)
        def human_path(value: Any) -> str:
            raw = str(value); name = Path(raw).name
            return raw if raw.isascii() else (name if name.isascii() else "non-ASCII path (exact path retained in JSON)")
        def display(value: Any) -> str:
            if isinstance(value, float) and math.isfinite(value): return f"{value:.12g}"
            return str(value)
        def local_ir(value: Any) -> Any:
            if isinstance(value, list): return [local_ir(item) for item in value]
            if not isinstance(value, dict): return value
            result = {key: local_ir(item) for key, item in value.items()}
            if result.get("op") in {"FreeVariable", "BoundVariable", "IndexedValue"} and result.get("name"):
                name = str(result["name"]).replace("::", ".").rsplit(".", 1)[-1]
                result["name"] = name.replace("_", r"\_") if name.isascii() else "symbol"
            return result
        def rendered_formula(name: str, expression: Any) -> str:
            if not isinstance(expression, dict): return r"\text{not registered}"
            wrapper = {"outputs": [{"target": {"op": "FreeVariable", "name": name},
                                     "expression": local_ir(expression)}]}
            return render_expression(wrapper, "latex").strip()
        lines = [r"\documentclass{article}", r"\usepackage[T1]{fontenc}",
                 r"\usepackage[margin=0.65in]{geometry}", r"\usepackage{longtable}", r"\usepackage{array}",
                 r"\begin{document}", r"\small", r"\section*{FormulaTracer Project Verification Certificate -- End-to-End}",
                 r"\subsection*{Audit Target}",
                 f"Overall audit: \\texttt{{{esc(self.end_to_end_status or 'END_TO_END_UNRESOLVED')}}}\\\\",
                 f"Project analysis status: \\texttt{{{esc(self.status)}}}\\\\", r"Modules:", r"\begin{itemize}"]
        lines += [f"\\item \\texttt{{{esc(module.name)}}}: \\texttt{{{esc(human_path(module.path))}}}" for module in self.modules]
        lines += [r"\end{itemize}"]
        if self.provenance.get("range_specification") is not None:
            specification = self.provenance["range_specification"]
            lines += [r"\subsection*{Inputs / Constants}", r"\begin{itemize}"]
            for item in specification.get("ranges", []):
                lines += [f"\\item $\\mathtt{{{esc(item.get('name'))}}} \\in "
                          f"[\\mathtt{{{esc(display(item.get('lower')))}}},\\mathtt{{{esc(display(item.get('upper')))}}}]$; "
                          f"status \\texttt{{{esc(item.get('status'))}}}"]
            lines += [r"\end{itemize}"]
        for root in self.roots:
            lines += [f"\\section*{{Root {esc(root.entry_symbol)}}}",
                      f"End-to-end status: \\texttt{{{esc(root.end_to_end_status or 'END_TO_END_UNRESOLVED')}}}"]
            for output in root.outputs:
                claim = output.end_to_end_claim or {}
                lines += [f"\\subsection*{{Output {esc(output.name)}}}", r"\subsubsection*{Theory}",
                          r"\[" + rendered_formula(output.name, claim.get("theory_expression")) + r"\]",
                          r"\subsubsection*{Implementation}", r"\[" + rendered_formula(output.name, output.formula) + r"\]",
                          r"\subsubsection*{Transformations / Approximation}",
                          f"Approximation records: {len(claim.get('approximation_proofs', []))}\\\\"]
                if output.value_interval is not None:
                    value = output.value_interval["interval"]
                    error = output.error_interval["interval"]
                    enclosure = output.true_value_enclosure
                    lines += [r"\subsubsection*{Certified ranges / Value Range}",
                              f"Display interval: $[\\mathtt{{{esc(display(value.get('lower')))}}},\\mathtt{{{esc(display(value.get('upper')))}}}]$\\\\",
                              r"Exact outward-rounded endpoints are retained in the JSON certificate.\\",
                              r"\subsubsection*{Error Components / Total Error}",
                              f"Components: {len(output.error_components)}; completeness: \\texttt{{{esc(claim.get('error_completeness_status'))}}}\\\\",
                              f"Error interval: $[\\mathtt{{{esc(display(error.get('lower')))}}},\\mathtt{{{esc(display(error.get('upper')))}}}]$\\\\",
                              r"\subsubsection*{True-value Enclosure}",
                              f"$[\\mathtt{{{esc(display(enclosure.get('lower')))}}},\\mathtt{{{esc(display(enclosure.get('upper')))}}}]$\\\\",
                              f"Range/enclosure subclaim: \\texttt{{{esc(output.range_status)}}}"]
                matrix = claim.get("verification_matrix", [])
                execution_status = next((item.get("status") for item in matrix if item.get("layer") == "NUMERIC_EXECUTION"), "UNRESOLVED")
                lines += [r"\subsubsection*{Execution Semantics / FFI}",
                          f"Execution status: \\texttt{{{esc(execution_status)}}}; FFI boundaries: {len(claim.get('ffi_boundaries', []))}\\\\",
                          r"\subsubsection*{I/O Artifact}"]
                artifacts = claim.get("artifact", [])
                if artifacts:
                    lines += [r"\begin{itemize}"]
                    lines += [f"\\item {esc(item.get('format'))}: \\texttt{{{esc(human_path(item.get('path')))}}}; "
                              f"payload range \\texttt{{{esc(item.get('status'))}}}; materialization \\texttt{{{esc(item.get('materialization_status'))}}}"
                              for item in artifacts]
                    lines += [r"\end{itemize}"]
                else: lines += [r"None.\\"]
                lines += [r"\newpage", r"\subsubsection*{Lean Verification / Verification Matrix}",
                          r"\begin{longtable}{>{\ttfamily}p{0.28\linewidth}>{\ttfamily}p{0.25\linewidth}p{0.37\linewidth}}",
                          r"Layer & Status & Explanation\\\hline"]
                lines += [f"{esc(item.get('layer'))} & {esc(item.get('status'))} & {esc(item.get('explanation'))}\\\\"
                          for item in matrix]
                lines += [r"\end{longtable}", r"\subsubsection*{Remaining Assumptions / Obligations}",
                          f"Assumptions: {len(claim.get('assumptions', []))}; obligations: {len(claim.get('remaining_obligations', []))}\\\\",
                          r"\subsubsection*{Overall End-to-End Status}",
                          f"\\texttt{{{esc(output.end_to_end_status or 'END_TO_END_UNRESOLVED')}}}\\\\",
                          esc(claim.get("explanation", "End-to-end claim was not constructed."))]
        lines += [r"\section*{Provenance / Hashes}",
                  f"Project graph hash: \\texttt{{{esc(self.provenance.get('project_graph_hash', 'unavailable'))}}}\\\\",
                  f"Coverage: \\texttt{{{esc(json.dumps(self.end_to_end_coverage, sort_keys=True))}}}",
                  r"\end{document}", ""]
        return "\n".join(lines)

    def write_latex(self, path: str | Path) -> Path:
        target = Path(path); target.write_text(self.to_latex(), encoding="utf-8"); return target


class LanguageFrontend(ABC):
    language: str

    @abstractmethod
    def parse(self, path: Path) -> ast.AST:
        raise NotImplementedError


class PythonFrontend(LanguageFrontend):
    language = "python"

    def parse(self, path: Path) -> ast.Module:
        try:
            return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise AuditError(f"PYTHON_FRONTEND_PARSE_FAILED: {path}: {exc}") from exc


class RustFrontend(LanguageFrontend):
    language = "rust"
    frontend_version = "formulatracer-rust-source-v1"

    def parse(self, path: Path) -> Any:
        from .rust_project import parse_rust_source
        return parse_rust_source(path)


class CppFrontend(LanguageFrontend):
    language = "cpp"
    frontend_version = "formulatracer-cpp-common-v1"

    def parse(self, path: Path) -> Any:
        from .cpp_project import parse_cpp_source
        return parse_cpp_source(path)


class DependencyResolver(ABC):
    @abstractmethod
    def resolve(self, entry_source: Path, project_root: Path | None = None) -> ProjectDependencyGraph:
        raise NotImplementedError


@dataclass
class _ModuleInfo:
    node: ModuleNode
    path: Path
    tree: ast.Module
    aliases: dict[str, str] = field(default_factory=dict)
    definitions: dict[str, list[ast.AST]] = field(default_factory=dict)


class PythonDependencyResolver(DependencyResolver):
    """Resolve local imports without importing code or consulting ``sys.path``."""

    def __init__(self, frontend: PythonFrontend | None = None):
        self.frontend = frontend or PythonFrontend()
        self.module_info: dict[str, _ModuleInfo] = {}
        self.root = Path()

    @staticmethod
    def infer_project_root(entry: Path) -> Path:
        entry = entry.resolve()
        for parent in (entry.parent, *entry.parents):
            if any((parent / marker).is_file() for marker in ("pyproject.toml", "setup.cfg", "setup.py")):
                return parent
        top = entry.parent
        while (top / "__init__.py").is_file():
            top = top.parent
        return top

    @staticmethod
    def _module_name(path: Path, root: Path) -> str:
        relative = path.resolve().relative_to(root.resolve()).with_suffix("")
        parts = list(relative.parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def _path_for(self, module: str, graph: ProjectDependencyGraph) -> Path | None:
        relative = Path(*module.split("."))
        candidates = [self.root / relative.with_suffix(".py"), self.root / relative / "__init__.py"]
        found = [path.resolve() for path in candidates if path.is_file()]
        if len(found) > 1:
            graph.diagnostics.append({"code": "AMBIGUOUS_IMPORT", "module": module,
                                      "candidates": [str(path) for path in found]})
            return None
        return found[0] if found else None

    @staticmethod
    def _absolute_from(module: str, is_package: bool, imported: str | None, level: int) -> str:
        if not level:
            return imported or ""
        package = module.split(".") if is_package else module.split(".")[:-1]
        keep = len(package) - (level - 1)
        base = package[:max(0, keep)]
        return ".".join([*base, *([imported] if imported else [])])

    def _load(self, path: Path, graph: ProjectDependencyGraph) -> _ModuleInfo:
        name = self._module_name(path, self.root)
        if name in self.module_info:
            return self.module_info[name]
        text = path.read_text(encoding="utf-8")
        node = ModuleNode(f"module:{name}", name, str(path), is_package=path.name == "__init__.py",
                          source_hash=sha256(text.encode("utf-8")).hexdigest())
        info = _ModuleInfo(node, path, self.frontend.parse(path))
        self.module_info[name] = info; graph.modules.append(node)
        return info

    def resolve(self, entry_source: Path, project_root: Path | None = None) -> ProjectDependencyGraph:
        entry_source = entry_source.resolve()
        self.root = (project_root or self.infer_project_root(entry_source)).resolve()
        self.module_info = {}
        graph = ProjectDependencyGraph()
        queue = [self._load(entry_source, graph)]
        visited: set[str] = set()
        while queue:
            info = queue.pop(0)
            if info.node.name in visited: continue
            visited.add(info.node.name)
            self._index_symbols(info, graph)
            for item in ast.walk(info.tree):
                targets: list[tuple[str, str | None, str | None, bool]] = []
                if isinstance(item, ast.Import):
                    targets += [(alias.name, alias.asname or alias.name.split(".")[0], None, False)
                                for alias in item.names]
                elif isinstance(item, ast.ImportFrom):
                    base = self._absolute_from(info.node.name, info.node.is_package, item.module, item.level)
                    targets += [(base, alias.asname or alias.name, alias.name, info.node.is_package)
                                for alias in item.names if alias.name != "*"]
                elif isinstance(item, ast.Call) and _ast_name(item.func) in {"importlib.import_module", "__import__"}:
                    if item.args and isinstance(item.args[0], ast.Constant) and isinstance(item.args[0].value, str):
                        targets.append((item.args[0].value, None, None, False))
                    else:
                        graph.diagnostics.append({"code": "DYNAMIC_IMPORT_UNRESOLVED",
                                                  "source_span": _span(info.path, item)})
                for module, local, symbol, reexport in targets:
                    candidate_module = f"{module}.{symbol}" if symbol and self._path_for(f"{module}.{symbol}", graph) else module
                    alias_canonical = (module.split(".")[0] if not symbol and local == module.split(".")[0]
                                       else f"{module}.{symbol}" if symbol else module)
                    target_path = self._path_for(candidate_module, graph)
                    if target_path is None:
                        if module and module not in graph.external_modules and not any(
                                diagnostic.get("code") == "AMBIGUOUS_IMPORT" and diagnostic.get("module") == module
                                for diagnostic in graph.diagnostics):
                            graph.external_modules.append(module.split(".")[0])
                        if local:
                            info.aliases[local] = alias_canonical
                        continue
                    target = self._load(target_path, graph)
                    canonical = f"{module}.{symbol}" if symbol else candidate_module
                    if local: info.aliases[local] = alias_canonical
                    edge_cls = ReExportEdge if reexport else ImportEdge
                    graph.edges.append(edge_cls(info.node.module_id, target.node.module_id, alias=local,
                                                canonical_name=canonical, provenance=_span(info.path, item)))
                    if target.node.name not in visited: queue.append(target)
        self._resolve_reexports(graph)
        # Canonicalize consumers of ``from package import reexported_name``.
        for info in self.module_info.values():
            for local, canonical in list(info.aliases.items()):
                package, dot, symbol = canonical.rpartition(".")
                exported = self.module_info.get(package)
                if dot and exported and symbol in exported.aliases:
                    info.aliases[local] = exported.aliases[symbol]
        self._add_semantic_edges(graph)
        self._detect_cycles(graph)
        return graph

    def _index_symbols(self, info: _ModuleInfo, graph: ProjectDependencyGraph) -> None:
        for item in info.tree.body:
            names: list[tuple[str, str]] = []
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [(item.name, "FUNCTION")]
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                names = [(target.id, "CONSTANT" if target.id.isupper() else "VARIABLE")
                         for target in targets if isinstance(target, ast.Name)]
            for name, kind in names:
                info.definitions.setdefault(name, []).append(item)
                symbol_id = f"symbol:{info.node.name}:{name}:{getattr(item, 'lineno', 1)}"
                graph.symbols.append(SymbolNode(symbol_id, info.node.name, name, kind,
                                                f"{info.node.name}.{name}", not name.startswith("_"),
                                                _span(info.path, item)))
                graph.edges.append(DefinitionEdge(info.node.module_id, symbol_id,
                                                  provenance=_span(info.path, item)))

    def _resolve_reexports(self, graph: ProjectDependencyGraph) -> None:
        exports: dict[tuple[str, str], set[str]] = {}
        for edge in graph.edges:
            if edge.kind == "RE_EXPORT" and edge.alias and edge.canonical_name:
                module = edge.source.removeprefix("module:")
                exports.setdefault((module, edge.alias), set()).add(edge.canonical_name)
        for (module, name), targets in exports.items():
            if len(targets) > 1:
                graph.diagnostics.append({"code": "AMBIGUOUS_REEXPORT", "module": module,
                                          "symbol": name, "candidates": sorted(targets)})

    def _add_semantic_edges(self, graph: ProjectDependencyGraph) -> None:
        by_name = {(symbol.module, symbol.name): symbol for symbol in graph.symbols}
        for module, info in self.module_info.items():
            for name, definitions in info.definitions.items():
                owner = by_name.get((module, name))
                if owner is None: continue
                for definition in definitions:
                    body = definition.value if isinstance(definition, (ast.Assign, ast.AnnAssign)) else definition
                    parameters = {arg.arg for arg in definition.args.args} if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)) else set()
                    for node in ast.walk(body):
                        if isinstance(node, ast.Call):
                            local = _ast_name(node.func)
                            head, dot, tail = local.partition(".")
                            canonical_head = info.aliases.get(head, f"{module}.{head}")
                            canonical = f"{canonical_head}.{tail}" if dot else info.aliases.get(local, f"{module}.{local}")
                            target = next((value for value in graph.symbols if value.canonical_name == canonical), None)
                            graph.edges.append(CallEdge(owner.symbol_id,
                                target.symbol_id if target else f"external:{canonical}",
                                alias=local, canonical_name=canonical, provenance=_span(info.path, node)))
                        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in parameters:
                            canonical = info.aliases.get(node.id, f"{module}.{node.id}")
                            target = next((value for value in graph.symbols if value.canonical_name == canonical), None)
                            if target and target.symbol_id != owner.symbol_id:
                                graph.edges.append(ValueDependencyEdge(owner.symbol_id, target.symbol_id,
                                    alias=node.id, canonical_name=canonical, provenance=_span(info.path, node)))

    def _detect_cycles(self, graph: ProjectDependencyGraph) -> None:
        adjacency: dict[str, list[str]] = {}
        for edge in graph.edges:
            if edge.kind in {"IMPORT", "RE_EXPORT"}:
                adjacency.setdefault(edge.source, []).append(edge.target)
        active: list[str] = []; done: set[str] = set(); seen_cycles: set[tuple[str, ...]] = set()
        def visit(node: str) -> None:
            if node in active:
                cycle = active[active.index(node):] + [node]
                key = tuple(cycle)
                if key not in seen_cycles:
                    seen_cycles.add(key); graph.cycles.append([item.removeprefix("module:") for item in cycle])
                return
            if node in done: return
            active.append(node)
            for target in adjacency.get(node, []): visit(target)
            active.pop(); done.add(node)
        for module in adjacency: visit(module)
        if graph.cycles:
            for cycle in graph.cycles:
                graph.diagnostics += [{"code": "IMPORT_CYCLE_DETECTED", "cycle": cycle},
                                      {"code": "CROSS_FILE_SEMANTICS_UNRESOLVED", "cycle": cycle}]


class _ProjectSlice:
    """Small cross-module symbolic evaluator used after dependency resolution."""

    _binary = {ast.Add: "Add", ast.Sub: "Subtract", ast.Mult: "Multiply", ast.Div: "Divide",
               ast.Pow: "Power", ast.MatMult: "TensorContraction", ast.Mod: "Modulo"}
    _reductions = {"numpy.sum": "Add", "np.sum": "Add", "numpy.prod": "Multiply", "np.prod": "Multiply",
                   "numpy.mean": "Mean", "np.mean": "Mean"}
    _numeric = {"numpy.dot", "numpy.matmul", "numpy.einsum", "numpy.where", "numpy.clip",
                "numpy.abs", "numpy.sqrt", "numpy.log", "numpy.exp", "numpy.power",
                "numpy.reshape", "numpy.transpose", "numpy.diff", "numpy.gradient"}
    _approximation = {"numpy.diff", "numpy.gradient", "np.diff", "np.gradient"}

    def __init__(self, resolver: PythonDependencyResolver, graph: ProjectDependencyGraph,
                 ffi_functions: dict[str, Any] | None = None):
        self.resolver, self.graph = resolver, graph
        self.dependencies: set[str] = set()
        self.locations: list[dict[str, Any]] = []
        self.error_causes: set[str] = set()
        self.stack: set[str] = set()
        self.diagnostics: list[dict[str, Any]] = []
        self._source_lines: dict[Path, list[str]] = {}
        self.ffi_functions = dict(ffi_functions or {})
        self.contract_registry = LibraryContractRegistry.coverage_expansion()

    def source_lines(self, path: Path) -> list[str]:
        resolved = path.resolve()
        if resolved not in self._source_lines:
            try: self._source_lines[resolved] = resolved.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError): self._source_lines[resolved] = []
        return self._source_lines[resolved]

    def canonical(self, module: str, local: str) -> str:
        info = self.resolver.module_info[module]
        candidate = info.aliases.get(local, f"{module}.{local}")
        # Resolve package re-exports to the actual definition where it is unique.
        matches = [symbol.canonical_name for symbol in self.graph.symbols
                   if symbol.name == candidate.rsplit(".", 1)[-1] and
                   (symbol.canonical_name == candidate or candidate.startswith(symbol.module + "."))]
        return matches[0] if len(set(matches)) == 1 else candidate

    def definition(self, canonical: str, line: int | None = None) -> tuple[_ModuleInfo, ast.AST] | None:
        module, _, name = canonical.rpartition(".")
        info = self.resolver.module_info.get(module)
        if not info or name not in info.definitions: return None
        definitions = info.definitions[name]
        if line is not None:
            selected = [node for node in definitions if getattr(node, "lineno", 0) == line]
            return (info, selected[-1]) if selected else None
        return info, definitions[-1]

    def _record(self, canonical: str, info: _ModuleInfo, node: ast.AST) -> None:
        self.dependencies.add(canonical)
        span = _span(info.path, node)
        if span not in self.locations: self.locations.append(span)

    def expression_for_definition(self, canonical: str, line: int | None = None) -> dict[str, Any]:
        found = self.definition(canonical, line)
        if found is None: return {"op": "FreeVariable", "name": canonical}
        info, node = found
        self._record(canonical, info, node)
        if canonical in self.stack:
            self.diagnostics.append({"code": "CROSS_FILE_SEMANTICS_UNRESOLVED", "symbol": canonical})
            return {"op": "OpaqueNumericCall", "name": canonical, "args": [],
                    "shape_constraints": [{"kind": "unresolved_recursive_value"}]}
        self.stack.add(canonical)
        try:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                resolved = self.expr(node.value, info.node.name, {}) if node.value else {"op": "Constant", "value": None}
                if resolved.get("op") == "Constant" and node.value is not None:
                    resolved["source_span"] = _span(info.path, node.value)
                return resolved
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return self.function(node, info.node.name, [])
            return {"op": "OpaqueNumericCall", "name": canonical, "args": []}
        finally:
            self.stack.remove(canonical)

    def expr(self, node: ast.AST, module: str, env: dict[str, dict[str, Any]]) -> dict[str, Any]:
        source_span = _span(self.resolver.module_info[module].path, node)
        # Literal locations are carried by the enclosing node's argument spans.
        # Keeping them off the public Constant shape preserves the stable IR API
        # used by cross-language consumers while retaining exact debugger origin.
        if isinstance(node, ast.Constant): return {"op": "Constant", "value": node.value}
        if isinstance(node, ast.Name):
            if node.id in env:
                value = env[node.id]
                if isinstance(value, dict) and "__ast__" in value:
                    if value.get("__canonical__"):
                        self.dependencies.add(str(value["__canonical__"]))
                    if value.get("__span__") and value["__span__"] not in self.locations:
                        self.locations.append(value["__span__"])
                    resolved = self.expr(value["__ast__"], str(value["__module__"]), value["__env__"])
                    # A named constant is a provenance-bearing source symbol;
                    # attach its defining literal span without changing the
                    # shape of anonymous literal nodes in the public IR.
                    if resolved.get("op") == "Constant" and value.get("__canonical__"):
                        resolved["source_span"] = _span(
                            self.resolver.module_info[str(value["__module__"])].path, value["__ast__"])
                    return resolved
                return deepcopy(value)
            canonical = self.canonical(module, node.id)
            if self.definition(canonical): return self.expression_for_definition(canonical)
            self.dependencies.add(canonical)
            return {"op": "FreeVariable", "name": canonical, "local_name": node.id,
                    "canonical_name": canonical, "source_span": source_span}
        if isinstance(node, ast.BinOp):
            result = {"op": self._binary.get(type(node.op), "OpaqueOperator"),
                    "args": [self.expr(node.left, module, env), self.expr(node.right, module, env)],
                    "source_span": source_span,
                    "argument_spans": [_span(self.resolver.module_info[module].path, node.left),
                                       _span(self.resolver.module_info[module].path, node.right)]}
            operator_path = self.resolver.module_info[module].path
            operator_span = _operator_span(operator_path, node, self.source_lines(operator_path))
            if operator_span: result["operator_span"] = operator_span
            return result
        if isinstance(node, ast.UnaryOp):
            return {"op": "Negate" if isinstance(node.op, ast.USub) else "UnaryOperator",
                    "args": [self.expr(node.operand, module, env)], "source_span": source_span}
        if isinstance(node, ast.Compare):
            return {"op": "Compare", "comparison": type(node.ops[0]).__name__,
                    "args": [self.expr(node.left, module, env), self.expr(node.comparators[0], module, env)],
                    "source_span": source_span}
        if isinstance(node, ast.IfExp):
            return {"op": "IfThenElse", "condition": self.expr(node.test, module, env),
                    "then": self.expr(node.body, module, env), "else": self.expr(node.orelse, module, env),
                    "source_span": source_span,
                    "condition_span": _span(self.resolver.module_info[module].path, node.test)}
        if isinstance(node, ast.Subscript):
            indices = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return {"op": "IndexedValue", "base": self.expr(node.value, module, env),
                    "indices": [self.expr(item, module, env) if not isinstance(item, ast.Slice) else
                                {"op": "Slice", "lower": self.expr(item.lower, module, env) if item.lower else None,
                                 "upper": self.expr(item.upper, module, env) if item.upper else None,
                                 "step": self.expr(item.step, module, env) if item.step else None}
                                for item in indices], "source_span": source_span}
        if isinstance(node, (ast.Tuple, ast.List)):
            return {"op": "Tuple", "args": [self.expr(item, module, env) for item in node.elts]}
        if isinstance(node, ast.Attribute):
            name = _ast_name(node)
            canonical = self.resolver.module_info[module].aliases.get(name.split(".")[0], name.split(".")[0])
            suffix = ".".join(name.split(".")[1:])
            return {"op": "FreeVariable", "name": f"{canonical}.{suffix}" if suffix else canonical}
        if isinstance(node, ast.Call): return self.call(node, module, env)
        return {"op": "OpaqueNumericCall", "name": type(node).__name__, "args": [],
                "shape_constraints": [{"kind": "opaque_result_shape", "relation": "shape constrained by source semantics"}]}

    def call(self, node: ast.Call, module: str, env: dict[str, dict[str, Any]]) -> dict[str, Any]:
        local = _ast_name(node.func)
        head, dot, tail = local.partition(".")
        alias = self.resolver.module_info[module].aliases.get(head, head)
        canonical = f"{alias}.{tail}" if dot else self.canonical(module, local)
        source_span = _span(self.resolver.module_info[module].path, node)
        callable_span = _span(self.resolver.module_info[module].path, node.func)
        argument_spans = [_span(self.resolver.module_info[module].path, item) for item in node.args]
        keyword_spans = {item.arg: _span(self.resolver.module_info[module].path, item.value)
                         for item in node.keywords if item.arg}
        semantic_string_consumers = {
            "builtins.eval", "builtins.exec", "eval", "exec", "numexpr.evaluate",
            "sympy.sympify", "sympy.parse_expr", "sympy.parsing.sympy_parser.parse_expr",
        }
        if canonical in semantic_string_consumers or local in semantic_string_consumers:
            role = "LITERAL" if node.args and isinstance(node.args[0], ast.Constant) else "DYNAMIC"
            self.diagnostics.append({
                "code": "SEMANTIC_STRING_UNRESOLVED", "callable": canonical,
                "source_span": source_span, "string_role": role,
                "executed_by_analyzer": False,
            })
            return {"op": "OpaqueNumericCall", "name": canonical, "args": [],
                    "semantic_string": {"role": role, "executed_by_analyzer": False},
                    "shape_constraints": [{"kind": "opaque_result_shape",
                        "relation": "dynamic program text is never executed by static analysis"}],
                    "source_span": source_span}
        if canonical in self.ffi_functions:
            args = [self.expr(arg, module, env) for arg in node.args]
            value = self.ffi_functions[canonical](args)
            ffi_cause = "ffi-error-cause:" + _digest([canonical, module])[:16]
            self.error_causes.add(ffi_cause)
            value.setdefault("language_boundary", {"kind": "FFIBoundary",
                "resolution_status": "RUST_SOURCE_RESOLVED",
                "representation_mapping": "REPRESENTATION_MAPPING_UNRESOLVED"})
            value.setdefault("ffi_error_cause_id", ffi_cause)
            return value
        found = self.definition(canonical)
        if found and isinstance(found[1], (ast.FunctionDef, ast.AsyncFunctionDef)):
            info, function = found
            self._record(canonical, info, function)
            if canonical in self.stack:
                self.diagnostics.append({"code": "RECURSIVE_CALL_UNRESOLVED", "symbol": canonical})
            else:
                self.stack.add(canonical)
                try: return self.function(function, info.node.name, [self.expr(arg, module, env) for arg in node.args])
                finally: self.stack.remove(canonical)
        args = [self.expr(arg, module, env) for arg in node.args]
        if canonical in self._reductions:
            return {"op": "Reduce", "reduction": self._reductions[canonical],
                    "input": args[0] if args else {"op": "MissingInput"},
                    "axes": next((ast.literal_eval(item.value) for item in node.keywords if item.arg == "axis" and
                                  isinstance(item.value, ast.Constant)), None), "api": canonical,
                    "source_span": source_span, "callable_span": callable_span, "argument_spans": argument_spans,
                    "keyword_spans": keyword_spans}
        if canonical in self._numeric:
            metadata: dict[str, Any] = {}
            if canonical in self._approximation:
                cause = "error-cause:" + _digest([module, _span(self.resolver.module_info[module].path, node), canonical])[:16]
                self.error_causes.add(cause)
                metadata["semantic_error_cause_id"] = cause
                metadata["error_role"] = "LOCAL_ERROR"
            return {"op": "FunctionCall", "name": canonical, "args": args, **metadata,
                    "keywords": {item.arg: ast.unparse(item.value) for item in node.keywords if item.arg},
                    "source_span": source_span, "callable_span": callable_span, "argument_spans": argument_spans,
                    "keyword_spans": keyword_spans}
        # Apply reviewed public-reference contracts to project-wide slices.  The
        # contract is evidence about public semantics, not a proof of the
        # library implementation; its provenance remains attached to the IR.
        binding = self.contract_registry.resolve(canonical)
        if binding:
            common = {"api": canonical, "semantic_family": binding.family,
                      "reference_contract": binding.to_dict(), "source_span": source_span, "callable_span": callable_span,
                      "argument_spans": argument_spans, "keyword_spans": keyword_spans}
            if binding.family == "Reduction":
                reduction = {"add": "Add", "multiply": "Multiply", "mean": "Mean",
                             "minimum": "Minimum", "maximum": "Maximum"}.get(
                                 str(binding.bind.get("reducer")), str(binding.bind.get("reducer", "Reduction")).title())
                axis_name = "dim" if binding.package == "xarray" else "axis"
                axis = next((ast.literal_eval(item.value) for item in node.keywords
                             if item.arg == axis_name and isinstance(item.value, ast.Constant)), None)
                constraint = {"kind": "reduction_output_rank", "axis": axis,
                              "relation": "rank(out)=rank(input)-|reduced_axes| unless keepdims",
                              "named_dimensions_preserved": binding.package == "xarray"}
                return {"op": "Reduce", "reduction": reduction,
                        "input": args[0] if args else {"op": "MissingInput"},
                        "dimensions" if binding.package == "xarray" else "axes": axis,
                        "shape_constraints": [constraint], **common}
            family_ops = {"TensorContraction": "TensorContraction", "ShapeTransform": "ShapeTransform",
                          "IndexSelection": "IndexSelection", "Statistics": "Statistics",
                          "Interpolation": "Interpolation", "LinearAlgebraRelation": "LinearAlgebraRelation",
                          "GraphAlgorithm": "GraphAlgorithm", "SpatialGeometry": "SpatialGeometry",
                          "TableMapping": "TableMapping", "Grouping": "Grouping", "Aggregation": "Aggregation",
                          "Alignment": "Alignment", "ParallelExecution": "ExecutionOnly"}
            op = family_ops.get(binding.family, "FunctionCall")
            constraints = []
            if binding.family == "TensorContraction":
                constraints.append({"kind": "matmul_dimension_relation",
                                    "relation": "contracted extents are equal"})
            elif binding.family == "ShapeTransform":
                constraints.append({"kind": "shape_relation",
                                    "relation": "output shape is constrained by the public transform contract",
                                    "named_dimensions_preserved": binding.package == "xarray"})
            value = {"op": op, "name": next(iter(binding.bind.values()), canonical), "args": args,
                     "keywords": {item.arg: ast.unparse(item.value) for item in node.keywords if item.arg}, **common}
            if constraints: value["shape_constraints"] = constraints
            return value
        # Method reductions and xarray transformations preserve their receiver and labels.
        if dot and tail in {"sum", "mean", "where", "sel", "isel", "transpose", "rename", "broadcast"}:
            receiver = self.expr(node.func.value, module, env) if isinstance(node.func, ast.Attribute) else None
            return {"op": "Reduce" if tail in {"sum", "mean"} else "FunctionCall",
                    "name": tail, "input": receiver, "args": args,
                    "alignment_constraints": [{"kind": "xarray_label_alignment",
                                                "dimension_names_preserved": True}]}
        return {"op": "OpaqueNumericCall", "name": canonical, "args": args,
                "source_span": source_span, "callable_span": callable_span,
                "shape_constraints": [{"kind": "opaque_result_shape",
                                       "relation": "shape(result) constrained by external contract"}]}

    def function(self, function: ast.FunctionDef | ast.AsyncFunctionDef, module: str,
                 arguments: list[dict[str, Any]]) -> dict[str, Any]:
        env = {arg.arg: (arguments[index] if index < len(arguments) else
                         {"op": "FreeVariable", "name": f"{module}.{function.name}.{arg.arg}"})
               for index, arg in enumerate(function.args.args)}
        for arg in function.args.args:
            self.dependencies.add(f"{module}.{function.name}.{arg.arg}")
        for statement in function.body:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = {"__ast__": statement.value or ast.Constant(None),
                                          "__module__": module, "__env__": dict(env),
                                          "__canonical__": f"{module}.{function.name}.{target.id}:{statement.lineno}",
                                          "__span__": _span(self.resolver.module_info[module].path, statement)}
                    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                        previous = env.get(target.value.id, {"op": "FreeVariable", "name": target.value.id})
                        env[target.value.id] = {"op": "IndexedStateUpdate", "previous_state": previous,
                                                "indices": ast.unparse(target.slice),
                                                "value": self.expr(statement.value, module, env) if statement.value else None}
            elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
                previous = env.get(statement.target.id)
                snapshot = dict(env)
                synthetic = ast.BinOp(left=ast.Name(statement.target.id, ast.Load()), op=statement.op,
                                      right=statement.value)
                snapshot[statement.target.id] = previous or {"op": "FreeVariable", "name": statement.target.id}
                env[statement.target.id] = {"__ast__": synthetic, "__module__": module, "__env__": snapshot}
            elif isinstance(statement, ast.Return):
                return self.expr(statement.value, module, env) if statement.value else {"op": "Constant", "value": None}
            elif isinstance(statement, ast.If):
                # Preserve the branch relation without pretending general CFG equivalence.
                yes = next((item for item in statement.body if isinstance(item, ast.Return)), None)
                no = next((item for item in statement.orelse if isinstance(item, ast.Return)), None)
                if yes and no:
                    return {"op": "IfThenElse", "condition": self.expr(statement.test, module, env),
                            "then": self.expr(yes.value, module, dict(env)),
                            "else": self.expr(no.value, module, dict(env))}
                # Merge simple branch-local assignments as an exact conditional value.
                # General effects and loops remain represented by the CFG/Error IR path.
                def branch_assignments(statements: list[ast.stmt]) -> tuple[dict[str, dict[str, Any]], set[str]]:
                    local = dict(env); assigned: set[str] = set()
                    for item in statements:
                        if isinstance(item, (ast.Assign, ast.AnnAssign)):
                            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                            for target in targets:
                                if isinstance(target, ast.Name):
                                    local[target.id] = self.expr(item.value, module, local) if item.value else {"op": "Constant", "value": None}
                                    assigned.add(target.id)
                    return local, assigned
                yes_env, yes_names = branch_assignments(statement.body)
                no_env, no_names = branch_assignments(statement.orelse)
                condition = self.expr(statement.test, module, env)
                for name in sorted(yes_names | no_names):
                    before = env.get(name, {"op": "FreeVariable", "name": f"{module}.{function.name}.{name}"})
                    env[name] = {"op": "IfThenElse", "condition": deepcopy(condition),
                                 "then": deepcopy(yes_env.get(name, before)),
                                 "else": deepcopy(no_env.get(name, before)),
                                 "cfg_merge": "simple_branch_assignment"}
        return {"op": "OpaqueNumericCall", "name": f"{module}.{function.name}", "args": arguments,
                "shape_constraints": [{"kind": "missing_return"}]}


class ProjectAnalyzer:
    """Language-neutral orchestration with the Python backend implemented in Phase 9.5."""

    _sink_specs = {
        "numpy.save": ("FILE_OUTPUT", "npy", 1, 0), "np.save": ("FILE_OUTPUT", "npy", 1, 0),
        "numpy.savez": ("FILE_OUTPUT", "npz", 1, 0), "np.savez": ("FILE_OUTPUT", "npz", 1, 0),
        "json.dump": ("STREAM_OUTPUT", "json", 0, 1),
    }
    _method_sinks = {"to_csv": ("FILE_OUTPUT", "csv"), "to_parquet": ("FILE_OUTPUT", "parquet"),
                     "to_netcdf": ("DATASET_OUTPUT", "netcdf")}

    def __init__(self, entry_source: str | Path, *, project_root: str | Path | None = None,
                 frontend: LanguageFrontend | None = None, resolver: DependencyResolver | None = None):
        self.entry_source = Path(entry_source).resolve()
        self.project_root = Path(project_root).resolve() if project_root else None
        if frontend is None:
            frontend = (RustFrontend() if self.entry_source.suffix == ".rs" or self.entry_source.name == "Cargo.toml" else
                        CppFrontend() if self.entry_source.suffix in {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"} or self.entry_source.name == "CMakeLists.txt"
                        else PythonFrontend() if self.entry_source.suffix == ".py" else None)
        if frontend is None:
            raise AuditError(f"UNSUPPORTED_LANGUAGE: {self.entry_source}")
        self.frontend = frontend
        if resolver is not None:
            self.resolver = resolver
        elif isinstance(self.frontend, PythonFrontend):
            self.resolver = PythonDependencyResolver(self.frontend)
        elif isinstance(self.frontend, RustFrontend):
            from .rust_project import RustDependencyResolver
            self.resolver = RustDependencyResolver(self.frontend)
        elif isinstance(self.frontend, CppFrontend):
            from .cpp_project import CppDependencyResolver
            self.resolver = CppDependencyResolver(self.frontend)
        else:
            self.resolver = PythonDependencyResolver()
        self.registry = LibraryContractRegistry.default()

    def analyze(self, targets: Iterable[str | OutputTarget] | str | OutputTarget | None = None) -> ProjectAuditResult:
        if not self.entry_source.is_file(): raise AuditError(f"ENTRY_SOURCE_NOT_FOUND: {self.entry_source}")
        if isinstance(targets, (str, OutputTarget)):
            targets = [targets]
        if isinstance(self.frontend, RustFrontend):
            from .rust_project import RustProjectAnalyzer
            return RustProjectAnalyzer(self.entry_source, project_root=self.project_root,
                                       frontend=self.frontend, resolver=self.resolver).analyze(targets)
        if isinstance(self.frontend, CppFrontend):
            from .cpp_project import CppProjectAnalyzer
            return CppProjectAnalyzer(self.entry_source, project_root=self.project_root,
                                      frontend=self.frontend, resolver=self.resolver).analyze(targets)
        if not isinstance(self.frontend, PythonFrontend): self.frontend.parse(self.entry_source)
        graph = self.resolver.resolve(self.entry_source, self.project_root)
        self._active_graph = graph
        if not isinstance(self.resolver, PythonDependencyResolver):
            raise AuditError("PROJECT_ANALYZER_BACKEND_NOT_IMPLEMENTED")
        self._ffi_functions = self._integrate_local_rust_extensions(graph)
        self._ffi_functions.update(self._integrate_local_cpp_extensions(graph))
        sink_records = self._discover_sinks(graph)
        candidates = self._targets(targets, graph, sink_records)
        roots: list[AuditRootResult] = []
        outputs: list[AuditOutputResult] = []
        diagnostics = list(graph.diagnostics)
        self._slice_diagnostics: list[dict[str, Any]] = []
        for module, function, target_list in candidates:
            root_outputs: list[AuditOutputResult] = []
            for target in target_list:
                try:
                    result = self._analyze_output(module, function, target)
                    root_outputs.append(result); outputs.append(result)
                except (AuditError, ValueError, TypeError) as exc:
                    diagnostics.append({"code": "OUTPUT_ANALYSIS_FAILED", "target": target.name, "message": str(exc)})
                    failed = AuditOutputResult("output:" + _digest([module, function, target.name])[:16], target.name,
                        target.kind, None, {"op": "UnresolvedOutput"}, {"op": "UnresolvedOutput"}, None,
                        [], None, None, None, [], [], "NOT_RUN", "FAILED")
                    root_outputs.append(failed); outputs.append(failed)
            deps = sorted({dependency for output in root_outputs for dependency in output.dependencies})
            root_id = "root:" + _digest([module, function, [item.name for item in root_outputs]])[:16]
            root_status = self._root_status(root_outputs)
            root = AuditRootResult(root_id, module, function or "<module>", root_outputs, deps, status=root_status)
            root.graph_hash = _digest([root_id, deps, [item.slice_hash for item in root_outputs]])
            roots.append(root)
        diagnostics.extend(self._slice_diagnostics)
        artifacts = [item for _, item in sink_records]
        shared, causes = self._relations(roots)
        status = self._project_status(roots, graph)
        source_hashes = {item.name: item.source_hash for item in graph.modules}
        provenance = {"entry_source_hash": sha256(self.entry_source.read_bytes()).hexdigest(),
                      "used_source_hashes": source_hashes, "project_graph_hash": graph.graph_hash,
                      "module_graph_hash": _digest([(edge.source, edge.target) for edge in graph.edges if edge.kind in {"IMPORT", "RE_EXPORT"}]),
                      "root_graph_hashes": {root.root_id: root.graph_hash for root in roots},
                      "output_slice_hashes": {output.output_id: output.slice_hash for output in outputs},
                      "library_contract_registry_hash": _digest(sorted(self.registry.registered_callables())),
                      "lean_source_hashes": self._lean_hashes()}
        return ProjectAuditResult(status, graph, roots, outputs, graph.modules,
                                  [_serial(edge) for edge in graph.edges], shared, causes,
                                  [{"output_id": output.output_id, "lean_status": output.lean_status} for output in outputs],
                                  artifacts, provenance, diagnostics)

    def _integrate_local_rust_extensions(self, graph: ProjectDependencyGraph) -> dict[str, Any]:
        """Attach local maturin/PyO3 source without inspecting unrelated external crates."""
        root = self.project_root or PythonDependencyResolver.infer_project_root(self.entry_source)
        pyproject = root / "pyproject.toml"
        if not pyproject.is_file(): return {}
        try:
            import tomllib
            config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        maturin = config.get("tool", {}).get("maturin", {})
        if not isinstance(maturin, dict): return {}
        module_name = str(maturin.get("module-name") or maturin.get("module_name") or "").strip()
        manifest_value = str(maturin.get("manifest-path") or maturin.get("manifest_path") or "Cargo.toml")
        manifest = (root / manifest_value).resolve()
        if not module_name: return {}
        if not manifest.is_file():
            graph.metadata.setdefault("native_extensions", []).append(_serial(NativeExtension(
                module_name, "PyO3/maturin", str(manifest), None, "BINARY_ONLY")))
            graph.diagnostics.append({"code": "FFI_MAPPING_UNRESOLVED", "module": module_name,
                                      "resolution_status": "BINARY_ONLY",
                                      "manifest": str(manifest)})
            return {}
        from .rust_project import RustDependencyResolver, RustProjectAnalyzer
        rust_resolver = RustDependencyResolver(RustFrontend())
        rust_graph = rust_resolver.resolve(manifest)
        rust_analyzer = RustProjectAnalyzer(manifest, resolver=rust_resolver, frontend=RustFrontend(),
                                            pre_resolved_graph=rust_graph)
        graph.modules.extend(item for item in rust_graph.modules if item.module_id not in {m.module_id for m in graph.modules})
        graph.symbols.extend(item for item in rust_graph.symbols if item.symbol_id not in {s.symbol_id for s in graph.symbols})
        graph.edges.extend(rust_graph.edges)
        graph.external_modules.extend(item for item in rust_graph.external_modules if item not in graph.external_modules)
        graph.diagnostics.extend(rust_graph.diagnostics)
        native = NativeExtension(module_name, "PyO3/maturin", str(manifest), str(manifest.parent),
                                 "LOCAL_NATIVE_SOURCE_RESOLVED")
        ffi_functions: dict[str, Any] = {}
        boundaries = []
        for symbol in rust_graph.symbols:
            if symbol.kind != "FUNCTION" or not rust_resolver.is_python_export(symbol.canonical_name): continue
            export_name = rust_resolver.python_export_name(symbol.canonical_name)
            python_name = f"{module_name}.{export_name}"
            native.exported_symbols.append(python_name)
            source_id = f"external:{python_name}"
            boundary = FFIBoundary("ffi:" + _digest([python_name, symbol.symbol_id])[:16], "python", "rust",
                source_id, symbol.symbol_id, "RUST_SOURCE_RESOLVED", "REPRESENTATION_MAPPING_UNRESOLVED",
                {"pyproject": str(pyproject), "manifest": str(manifest)}, "PyO3/maturin", {},
                [{"code": "FFI_REPRESENTATION_EVIDENCE_REQUIRED",
                  "status": "UNRESOLVED", "boundary": python_name}])
            boundaries.append(boundary)
            graph.edges.append(CrossLanguageCallEdge(source_id, symbol.symbol_id,
                canonical_name=symbol.canonical_name, provenance={"boundary_id": boundary.boundary_id}))
            callback = lambda args, canonical=symbol.canonical_name: rust_analyzer.lower_function(canonical, args)
            ffi_functions[python_name] = callback
            ffi_functions[symbol.canonical_name] = callback
        graph.metadata.setdefault("native_extensions", []).append(_serial(native))
        graph.metadata.setdefault("language_boundaries", []).extend(_serial(item) for item in boundaries)
        return ffi_functions

    def _integrate_local_cpp_extensions(self, graph: ProjectDependencyGraph) -> dict[str, Any]:
        """Resolve explicit local pybind11 exports; never infer binary-only semantics."""
        root = self.project_root or PythonDependencyResolver.infer_project_root(self.entry_source)
        sources = [path for suffix in ("*.cpp", "*.cc", "*.cxx") for path in root.rglob(suffix)
                   if "build" not in {part.lower() for part in path.parts}]
        exports: list[tuple[str, str, Path]] = []
        for source in sources:
            try: text = source.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError): continue
            module_match = re.search(r"\bPYBIND11_MODULE\s*\(\s*([A-Za-z_]\w*)\s*,", text)
            if not module_match: continue
            module_name = module_match.group(1)
            for match in re.finditer(r"\.def\s*\(\s*\"([^\"]+)\"\s*,\s*&\s*([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)", text):
                exports.append((f"{module_name}.{match.group(1)}", match.group(2), source))
        if not exports: return {}
        from .cpp_project import CppDependencyResolver, CppProjectAnalyzer
        ffi_functions: dict[str, Any] = {}; extensions: dict[str, NativeExtension] = {}; boundaries = []
        analyzers: dict[Path, tuple[CppProjectAnalyzer, CppDependencyResolver, ProjectDependencyGraph]] = {}
        for python_name, cpp_name, source in exports:
            if source not in analyzers:
                resolver = CppDependencyResolver(CppFrontend()); cpp_graph = resolver.resolve(source, root)
                analyzers[source] = (CppProjectAnalyzer(source, project_root=root, frontend=CppFrontend(),
                                                        resolver=resolver), resolver, cpp_graph)
                graph.modules.extend(item for item in cpp_graph.modules if item.module_id not in {m.module_id for m in graph.modules})
                graph.symbols.extend(item for item in cpp_graph.symbols if item.symbol_id not in {s.symbol_id for s in graph.symbols})
                graph.edges.extend(cpp_graph.edges); graph.diagnostics.extend(cpp_graph.diagnostics)
            analyzer, resolver, cpp_graph = analyzers[source]
            candidates = [canonical for canonical in resolver.functions if canonical == cpp_name or canonical.endswith(f"::{cpp_name}")]
            if len(candidates) != 1:
                graph.diagnostics.append({"code": "FFI_MAPPING_UNRESOLVED", "python_symbol": python_name,
                                          "cpp_symbol": cpp_name, "candidate_count": len(candidates)})
                continue
            canonical = candidates[0]; symbol = next(item for item in cpp_graph.symbols if item.canonical_name == canonical)
            module_name = python_name.rsplit(".", 1)[0]
            extension = extensions.setdefault(module_name, NativeExtension(module_name, "pybind11", None, str(source.parent),
                                                                            "LOCAL_NATIVE_SOURCE_RESOLVED"))
            extension.exported_symbols.append(python_name)
            boundary = FFIBoundary("ffi:" + _digest([python_name, symbol.symbol_id])[:16], "python", "cpp",
                f"external:{python_name}", symbol.symbol_id, "CPP_SOURCE_RESOLVED",
                "REPRESENTATION_MAPPING_UNRESOLVED", {"source": str(source)}, "pybind11", {},
                [{"code": "FFI_REPRESENTATION_EVIDENCE_REQUIRED", "status": "UNRESOLVED", "boundary": python_name}])
            boundaries.append(boundary); graph.edges.append(CrossLanguageCallEdge(boundary.source_symbol, symbol.symbol_id,
                canonical_name=canonical, provenance={"boundary_id": boundary.boundary_id}))
            def callback(args: list[dict[str, Any]], analyzer: Any = analyzer, canonical: str = canonical) -> dict[str, Any]:
                value = analyzer.lower_function(canonical, args)
                value.setdefault("language_boundary", {"kind": "FFIBoundary", "resolution_status": "CPP_SOURCE_RESOLVED",
                                                        "representation_mapping": "REPRESENTATION_MAPPING_UNRESOLVED"})
                return value
            ffi_functions[python_name] = callback
        graph.metadata.setdefault("native_extensions", []).extend(_serial(item) for item in extensions.values())
        graph.metadata.setdefault("language_boundaries", []).extend(_serial(item) for item in boundaries)
        return ffi_functions

    def _targets(self, requested: Iterable[str | OutputTarget] | None, graph: ProjectDependencyGraph,
                 sinks: list[tuple[tuple[str, str | None], OutputSink]]) -> list[tuple[str, str | None, list[OutputTarget]]]:
        if requested:
            result: list[tuple[str, str | None, list[OutputTarget]]] = []
            for raw in requested:
                target = VariableTarget(raw) if isinstance(raw, str) else raw
                matches = self._target_matches(target)
                if len(matches) != 1:
                    raise AuditError(f"OUTPUT_VARIABLE_AMBIGUOUS: {target.name}: {len(matches)} definitions")
                module, function = matches[0]
                result.append((module, function, [target]))
            return self._merge_roots(result)
        incoming = {edge.target for edge in graph.edges if edge.kind == "CALL" and edge.target.startswith("symbol:")}
        result = []
        entry_module = PythonDependencyResolver._module_name(self.entry_source,
            self.project_root or PythonDependencyResolver.infer_project_root(self.entry_source))
        for module, info in self.resolver.module_info.items():
            for name, definitions in info.definitions.items():
                node = definitions[-1]
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or name.startswith("_"): continue
                returns = [item for item in ast.walk(node) if isinstance(item, ast.Return) and item.value]
                decorated = any(_ast_name(item.func).endswith("theory") for item in node.decorator_list if isinstance(item, ast.Call))
                symbol = next((item for item in graph.symbols if item.module == module and item.name == name), None)
                is_root = decorated or (module == entry_module and bool(returns)) or (symbol and symbol.symbol_id not in incoming and bool(returns))
                if not is_root: continue
                targets: list[OutputTarget] = []
                value = returns[-1].value if returns else None
                if isinstance(value, (ast.Tuple, ast.List)):
                    for index, item in enumerate(value.elts):
                        output_name = item.id if isinstance(item, ast.Name) else f"return_{index}"
                        targets.append(OutputTarget(OutputTargetKind.RETURN_OUTPUT.value, output_name, module, name,
                                                    expression=ast.unparse(item)))
                else:
                    output_name = value.id if isinstance(value, ast.Name) else name
                    targets.append(OutputTarget(OutputTargetKind.RETURN_OUTPUT.value, output_name, module, name))
                result.append((module, name, targets))
            if module == entry_module:
                for name, definitions in info.definitions.items():
                    node = definitions[-1]
                    if (isinstance(node, (ast.Assign, ast.AnnAssign)) and
                            (name in {"result", "output"} or name.endswith("_result"))):
                        result.append((module, None, [OutputTarget(OutputTargetKind.VARIABLE_OUTPUT.value,
                                                                  name, module)]))
        for owner, sink in sinks:
            module, function = owner
            if sink.dataset_outputs:
                sink_targets = [OutputTarget(OutputTargetKind.DATASET_OUTPUT.value, item.name,
                    module, function, expression=item.payload_symbol) for item in sink.dataset_outputs]
            else:
                sink_targets = [OutputTarget(sink.sink_kind, sink.dataset_variable or
                    sink.payload_symbol or sink.sink_id, module, function,
                    expression=sink.payload_symbol)]
            result.append((module, function, sink_targets))
        return self._merge_roots(result)

    @staticmethod
    def _merge_roots(items: list[tuple[str, str | None, list[OutputTarget]]]) -> list[tuple[str, str | None, list[OutputTarget]]]:
        merged: dict[tuple[str, str | None], list[OutputTarget]] = {}
        for module, function, targets in items:
            current = merged.setdefault((module, function), [])
            for target in targets:
                if not any((item.kind, item.name) == (target.kind, target.name) for item in current): current.append(target)
        return [(module, function, targets) for (module, function), targets in merged.items()]

    def _target_matches(self, target: OutputTarget) -> list[tuple[str, str | None]]:
        result: list[tuple[str, str | None]] = []
        for module, info in self.resolver.module_info.items():
            if target.module and target.module != module: continue
            if target.function:
                function_defs = info.definitions.get(target.function, [])
                for function in function_defs:
                    if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if target.kind == OutputTargetKind.EXPRESSION_OUTPUT.value:
                            result.append((module, target.function))
                        elif any(isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and
                                 target.name in self._assigned(node) for node in ast.walk(function)):
                            result.append((module, target.function))
            elif target.name in info.definitions:
                result.append((module, None))
            else:
                for name, definitions in info.definitions.items():
                    function = definitions[-1]
                    if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                            target.name in self._assigned(node) for node in ast.walk(function)
                            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))):
                        result.append((module, name))
        return list(dict.fromkeys(result))

    @staticmethod
    def _assigned(node: ast.AST) -> set[str]:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
        return {target.id for target in targets if isinstance(target, ast.Name)}

    def _analyze_output(self, module: str, function_name: str | None, target: OutputTarget) -> AuditOutputResult:
        info = self.resolver.module_info[module]
        slicer = _ProjectSlice(self.resolver, self.resolver_graph, getattr(self, "_ffi_functions", {}))
        expression: dict[str, Any]
        theory = None
        if function_name:
            function = info.definitions[function_name][-1]
            assert isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            expression, selected = self._function_target_expression(slicer, info, function, target)
            theory = self._theory(function, target.name)
        elif target.kind == OutputTargetKind.EXPRESSION_OUTPUT.value and target.expression:
            expression = slicer.expr(ast.parse(target.expression, mode="eval").body, module, {})
        else:
            expression = slicer.expression_for_definition(f"{module}.{target.name}", target.definition_line)
        implementation = {"schema_version": "1.0", "language": "python", "module": module,
                          "outputs": [{"name": target.name, "expression": expression}],
                          "expression_id": "expression:" + _digest(expression)[:16]}
        theory_ir = comparison = None
        lean_status = "NOT_RUN"
        output_status = "UNRESOLVED"
        if theory is not None and function_name:
            try:
                single = audit_python(info.path, output=target.name, function=function_name,
                                      mode=AuditMode.REPORT_ONLY, verify_lean=True,
                                      library_registry=self.registry)
                theory_ir, comparison, lean_status = single.theory, single.comparison, single.lean["status"]
                output_status = ("FULLY_VERIFIED" if single.lean.get("kernel_verified") else
                                 "VERIFIED_UNDER_ASSUMPTIONS" if comparison and comparison.get("match") else "UNRESOLVED")
            except (AuditError, OSError, ValueError) as exc:
                slicer.diagnostics.append({"code": "PER_OUTPUT_LEAN_AUDIT_UNRESOLVED", "message": str(exc)})
        relation = "EXACT_EQUAL" if comparison and comparison.get("match") else "UNRESOLVED"
        error = build_error_analysis(theory_ir=theory_ir, implementation_ir=implementation, output=target.name,
                                     comparison_relation=relation, comparison=comparison,
                                     kernel_checked=lean_status == "LEAN_KERNEL_VERIFIED")
        total = error.graph_enclosure.output_bound
        total_status = error.graph_enclosure.total_output_status
        error_components = list(error.error_components)
        if slicer.error_causes:
            local_components: dict[str, list[ErrorComponent]] = {}
            def collect(node: Any, path: tuple[Any, ...] = ()) -> None:
                if not isinstance(node, dict): return
                cause = node.get("semantic_error_cause_id") or node.get("ffi_error_cause_id")
                if cause:
                    source = ErrorSource.CAST_ERROR.value if node.get("ffi_error_cause_id") else ErrorSource.DISCRETIZATION_ERROR.value
                    component = ErrorComponent(f"local-{cause}", source,
                        {"op": "OpaqueErrorTerm", "source": cause}, ErrorMetric.ABSOLUTE.value,
                        ErrorBound(BoundStatus.BOUND_UNRESOLVED.value, ErrorMetric.ABSOLUTE.value, None),
                        "UNRESOLVED", {"phase": 9, "error_role": "LOCAL_ERROR", "module": module},
                        str(cause), str(cause))
                    key = "/" + "/".join(str(item) for item in path) if path else "/"
                    local_components.setdefault(key, []).append(component)
                for key, value in node.items():
                    if isinstance(value, dict): collect(value, (*path, key))
                    elif isinstance(value, list):
                        for index, item in enumerate(value):
                            if isinstance(item, dict): collect(item, (*path, key, index))
            collect(expression)
            propagated = propagate_expression_graph(expression, local_components=local_components,
                                                    output=target.name,
                                                    kernel_checked=lean_status == "LEAN_KERNEL_VERIFIED")
            error_components += [item for values in local_components.values() for item in values]
            total = propagated.output_composition.known_bound
            total_status = propagated.output_composition.total_status
        output_id = "output:" + _digest([module, function_name, target.name, expression])[:16]
        dependencies = sorted(slicer.dependencies)
        self._slice_diagnostics.extend(slicer.diagnostics)
        return AuditOutputResult(output_id, target.name, target.kind, theory, expression, expression,
            _serial(error.residual_expression), _serial(error_components), _serial(total),
            _serial(total), {"status": total_status,
                             "bound": _serial(total) if total_status == "TOTAL_ERROR_BOUND_VERIFIED" else None}, dependencies,
            slicer.locations, lean_status,
            "UNRESOLVED" if slicer.diagnostics else output_status,
            sorted(slicer.error_causes), _digest([dependencies, expression]))

    @property
    def resolver_graph(self) -> ProjectDependencyGraph:
        # Set by analyze through the resolver's most recent graph edges/symbols.
        graph = getattr(self, "_active_graph", None)
        if graph is None: raise AuditError("PROJECT_GRAPH_NOT_ACTIVE")
        return graph

    def _function_target_expression(self, slicer: _ProjectSlice, info: _ModuleInfo,
                                    function: ast.FunctionDef | ast.AsyncFunctionDef,
                                    target: OutputTarget) -> tuple[dict[str, Any], ast.AST | None]:
        if target.kind == OutputTargetKind.RETURN_OUTPUT.value:
            returned = [node for node in ast.walk(function) if isinstance(node, ast.Return) and node.value]
            if not returned: raise AuditError("RETURN_OUTPUT_NOT_FOUND")
            returned_value = returned[-1].value
            # Function-environment slicing intentionally handles straight-line
            # assignments.  For a returned loop accumulator, reuse the normal
            # function-scoped Python frontend instead of mistaking its initializer
            # for the final value.
            if isinstance(returned_value, ast.Name) and any(
                    isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)
                    and node.target.id == returned_value.id and
                    any(isinstance(parent, (ast.For, ast.While)) and node in ast.walk(parent)
                        for parent in ast.walk(function))
                    for node in ast.walk(function)):
                single = audit_python(info.path, output=returned_value.id, function=function.name,
                                      mode=AuditMode.REPORT_ONLY, verify_lean=False,
                                      library_registry=self.registry)
                observed = single.implementation.get("outputs", [])
                if observed and observed[0].get("expression", {}).get("op") in {"FoldLeft", "FiniteSum", "FiniteProduct"}:
                    return deepcopy(observed[0]["expression"]), returned[-1]
            env = self._function_env(slicer, info, function, returned[-1].lineno)
            node = returned_value
            if target.expression:
                node = ast.parse(target.expression, mode="eval").body
            return slicer.expr(node, info.node.name, env), returned[-1]
        if target.kind == OutputTargetKind.EXPRESSION_OUTPUT.value and target.expression:
            env = self._function_env(slicer, info, function, 10**9)
            return slicer.expr(ast.parse(target.expression, mode="eval").body, info.node.name, env), None
        definitions = [node for node in ast.walk(function) if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                       and target.name in self._assigned(node)]
        if target.definition_line is not None:
            definitions = [node for node in definitions if getattr(node, "lineno", 0) == target.definition_line]
        if not definitions: raise AuditError(f"OUTPUT_VARIABLE_NOT_FOUND: {target.name}")
        selected = sorted(definitions, key=lambda node: getattr(node, "lineno", 0))[-1]
        env = self._function_env(slicer, info, function, getattr(selected, "lineno", 0))
        return slicer.expr(ast.Name(target.name, ast.Load()), info.node.name, env), selected

    def _function_env(self, slicer: _ProjectSlice, info: _ModuleInfo,
                      function: ast.FunctionDef | ast.AsyncFunctionDef, through_line: int) -> dict[str, dict[str, Any]]:
        env = {arg.arg: {"op": "FreeVariable", "name": f"{info.node.name}.{function.name}.{arg.arg}"}
               for arg in function.args.args}
        slicer.dependencies.update(value["name"] for value in env.values())
        for statement in function.body:
            if getattr(statement, "lineno", 0) > through_line: break
            if isinstance(statement, (ast.Assign, ast.AnnAssign)) and statement.value:
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for node in targets:
                    if isinstance(node, ast.Name):
                        env[node.id] = {"__ast__": statement.value, "__module__": info.node.name,
                                        "__env__": dict(env),
                                        "__canonical__": f"{info.node.name}.{function.name}.{node.id}:{statement.lineno}",
                                        "__span__": _span(info.path, statement)}
            elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
                previous = env.get(statement.target.id, {"op": "FreeVariable", "name": statement.target.id})
                snapshot = dict(env); snapshot[statement.target.id] = previous
                synthetic = ast.BinOp(left=ast.Name(statement.target.id, ast.Load()), op=statement.op,
                                      right=statement.value)
                env[statement.target.id] = {"__ast__": synthetic, "__module__": info.node.name,
                                            "__env__": snapshot,
                                            "__canonical__": f"{info.node.name}.{function.name}.{statement.target.id}:{statement.lineno}",
                                            "__span__": _span(info.path, statement)}
            elif isinstance(statement, ast.If):
                def branch_values(statements: list[ast.stmt]) -> tuple[dict[str, dict[str, Any]], set[str]]:
                    local = dict(env); assigned: set[str] = set()
                    for item in statements:
                        if isinstance(item, (ast.Assign, ast.AnnAssign)) and item.value:
                            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                            for target in targets:
                                if isinstance(target, ast.Name):
                                    local[target.id] = slicer.expr(item.value, info.node.name, local)
                                    assigned.add(target.id)
                    return local, assigned
                yes_env, yes_names = branch_values(statement.body)
                no_env, no_names = branch_values(statement.orelse)
                condition = slicer.expr(statement.test, info.node.name, env)
                for name in sorted(yes_names | no_names):
                    before = env.get(name, {"op": "FreeVariable", "name": f"{info.node.name}.{function.name}.{name}"})
                    env[name] = {"op": "IfThenElse", "condition": deepcopy(condition),
                                 "then": deepcopy(yes_env.get(name, before)),
                                 "else": deepcopy(no_env.get(name, before)),
                                 "cfg_merge": "simple_branch_assignment"}
        return env

    @staticmethod
    def _theory(function: ast.FunctionDef | ast.AsyncFunctionDef, output: str) -> dict[str, Any] | None:
        for decorator in function.decorator_list:
            if isinstance(decorator, ast.Call) and _ast_name(decorator.func).endswith("theory"):
                values = {item.arg: ast.literal_eval(item.value) for item in decorator.keywords
                          if item.arg and isinstance(item.value, ast.Constant)}
                if values.get("output") == output:
                    return {"output": output, "expression": values.get("expression"),
                            "provenance": "USER_REGISTERED_INDEPENDENT_THEORY"}
        return None

    def _discover_sinks(self, graph: ProjectDependencyGraph) -> list[tuple[tuple[str, str | None], OutputSink]]:
        result = []
        for module, info in self.resolver.module_info.items():
            datasets: dict[str, list[DatasetOutput]] = {}
            for node in ast.walk(info.tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and
                                isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str)):
                            datasets.setdefault(target.value.id, []).append(DatasetOutput(
                                str(target.slice.value), _ast_name(node.value) or ast.unparse(node.value), source_span=_span(info.path, node)))
            parents: dict[ast.AST, ast.AST] = {}
            for parent in ast.walk(info.tree):
                for child in ast.iter_child_nodes(parent): parents[child] = parent
            for call in (node for node in ast.walk(info.tree) if isinstance(node, ast.Call)):
                raw = _ast_name(call.func); head, dot, tail = raw.partition(".")
                canonical_head = info.aliases.get(head, head)
                canonical = f"{canonical_head}.{tail}" if dot else raw
                spec = self._sink_specs.get(canonical) or self._sink_specs.get(raw)
                receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
                method = call.func.attr if isinstance(call.func, ast.Attribute) else ""
                if spec:
                    kind, fmt, payload_index, path_index = spec
                    payload_node = call.args[payload_index] if len(call.args) > payload_index else None
                    path_node = call.args[path_index] if len(call.args) > path_index else None
                elif method in self._method_sinks:
                    kind, fmt = self._method_sinks[method]
                    payload_node, path_node = receiver, call.args[0] if call.args else None
                    canonical = canonical if canonical != raw else method
                else: continue
                raw_function = next((parent.name for parent in self._ancestors(call, parents)
                                     if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
                function = raw_function if raw_function in info.definitions else None
                if raw_function and function is None:
                    graph.diagnostics.append({"code": "SINK_OWNER_UNRESOLVED", "module": module,
                                              "function": raw_function, "source_span": _span(info.path, call)})
                payload_symbol = _ast_name(payload_node) if payload_node else None
                contract = self.registry.resolve(canonical)
                contract_dict = contract.to_dict() if contract else None
                boundary_id = "serialization:" + _digest([module, _span(info.path, call)])[:16]
                boundary = SerializationBoundary(boundary_id,
                    {"op": "PayloadReference", "name": payload_symbol or ast.unparse(payload_node) if payload_node else None},
                    canonical, contract_dict)
                dataset_outputs = list(datasets.get(payload_symbol or "", []))
                if fmt == "npz":
                    dataset_outputs = [
                        *[DatasetOutput(_ast_name(item) or f"arr_{index}", _ast_name(item) or ast.unparse(item),
                                       source_span=_span(info.path, item))
                          for index, item in enumerate(call.args[1:])],
                        *[DatasetOutput(item.arg or "unnamed", _ast_name(item.value) or ast.unparse(item.value),
                                       source_span=_span(info.path, item.value))
                          for item in call.keywords],
                    ]
                sink = OutputSink("sink:" + _digest([module, _span(info.path, call), canonical])[:16], kind, fmt,
                    ast.unparse(path_node) if path_node else None, boundary.mathematical_payload, payload_symbol,
                    None, [], None, contract_dict, _span(info.path, call),
                    IOProvenance(module, str(info.path), canonical, _span(info.path, call)), boundary,
                    dataset_outputs)
                result.append(((module, function), sink))
        return result

    @staticmethod
    def _ancestors(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> Iterable[ast.AST]:
        while node in parents:
            node = parents[node]; yield node

    @staticmethod
    def _root_status(outputs: list[AuditOutputResult]) -> str:
        if not outputs or all(item.status == "FAILED" for item in outputs): return "FAILED"
        if any(item.status == "FAILED" for item in outputs): return "PARTIALLY_VERIFIED"
        if all(item.status == "FULLY_VERIFIED" for item in outputs): return "FULLY_VERIFIED"
        if any(item.status == "VERIFIED_UNDER_ASSUMPTIONS" for item in outputs): return "VERIFIED_UNDER_ASSUMPTIONS"
        return "UNRESOLVED"

    def _relations(self, roots: list[AuditRootResult]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        shared: list[dict[str, Any]] = []; causes: list[dict[str, Any]] = []
        for root in roots:
            for index, left_output in enumerate(root.outputs):
                for right_output in root.outputs[index + 1:]:
                    intersection = sorted(set(left_output.dependencies) & set(right_output.dependencies))
                    if intersection:
                        record = {"left_output": left_output.output_id, "right_output": right_output.output_id,
                                  "root": root.root_id, "kind": SharedDependencyKind.SHARED_INTERMEDIATE.value,
                                  "symbols": intersection}
                        shared.append(record); root.shared_dependencies.append(record)
                    for cause in sorted(set(left_output.error_causes) & set(right_output.error_causes)):
                        causes.append({"semantic_cause_id": cause,
                                       "kind": SharedDependencyKind.SHARED_ERROR_CAUSE.value,
                                       "roots": [root.root_id],
                                       "outputs": [left_output.output_id, right_output.output_id]})
        output_symbols = {root.root_id: ({f"{root.entry_module}.{output.name}" for output in root.outputs} |
                          ({f"{root.entry_module}.{root.entry_symbol}"} if root.entry_symbol != "<module>" else set()))
                          for root in roots}
        for index, left in enumerate(roots):
            for right in roots[index + 1:]:
                intersection = set(left.dependency_slice) & set(right.dependency_slice)
                root_dep = bool(output_symbols[left.root_id] & set(right.dependency_slice) or
                                output_symbols[right.root_id] & set(left.dependency_slice))
                if root_dep: kind = SharedDependencyKind.ROOT_DEPENDENCY.value
                elif intersection:
                    kinds = {symbol.canonical_name: symbol.kind for symbol in self.resolver_graph.symbols}
                    if any(kinds.get(item) == "CONSTANT" for item in intersection): kind = SharedDependencyKind.SHARED_CONSTANT.value
                    elif any(kinds.get(item) == "FUNCTION" for item in intersection): kind = SharedDependencyKind.SHARED_FUNCTION.value
                    elif any(item.rsplit(".", 1)[-1] in {"data", "dataset", "source"} for item in intersection): kind = SharedDependencyKind.SHARED_DATA_SOURCE.value
                    else: kind = SharedDependencyKind.SHARED_INTERMEDIATE.value
                elif any(item.get("code") in {"DYNAMIC_IMPORT_UNRESOLVED", "AMBIGUOUS_IMPORT",
                                               "AMBIGUOUS_REEXPORT", "CROSS_FILE_SEMANTICS_UNRESOLVED"}
                         for item in self.resolver_graph.diagnostics):
                    kind = SharedDependencyKind.DEPENDENCE_UNKNOWN.value
                else: kind = SharedDependencyKind.DISCONNECTED.value
                record = {"left_root": left.root_id, "right_root": right.root_id,
                          "kind": kind, "symbols": sorted(intersection)}
                shared.append(record); left.root_relations.append(record); right.root_relations.append(record)
                shared_causes = sorted({cause for output in left.outputs for cause in output.error_causes} &
                                       {cause for output in right.outputs for cause in output.error_causes})
                for cause in shared_causes:
                    value = {"semantic_cause_id": cause, "kind": SharedDependencyKind.SHARED_ERROR_CAUSE.value,
                             "roots": [left.root_id, right.root_id]}
                    causes.append(value); left.shared_dependencies.append(value); right.shared_dependencies.append(value)
                if intersection:
                    left.shared_dependencies.append(record); right.shared_dependencies.append(record)
        return shared, causes

    @staticmethod
    def _project_status(roots: list[AuditRootResult], graph: ProjectDependencyGraph) -> str:
        if not roots or all(root.status == "FAILED" for root in roots): return ProjectStatus.FAILED.value
        if any(root.status == "FAILED" for root in roots): return ProjectStatus.PARTIALLY_VERIFIED.value
        if graph.diagnostics or any(root.status == "UNRESOLVED" for root in roots): return ProjectStatus.UNRESOLVED.value
        if all(root.status == "FULLY_VERIFIED" for root in roots): return ProjectStatus.FULLY_VERIFIED.value
        return ProjectStatus.VERIFIED_UNDER_ASSUMPTIONS.value

    @staticmethod
    def _lean_hashes() -> dict[str, str]:
        lean = Path(__file__).resolve().parents[2] / "lean"
        if not lean.is_dir(): return {}
        return {str(path.relative_to(lean)): sha256(path.read_bytes()).hexdigest() for path in lean.rglob("*.lean")}


class FormulaTracer:
    """Primary object API for project-wide FormulaTracer audits."""

    def __init__(self, entry_source: str | Path, *, project_root: str | Path | None = None,
                 frontend: LanguageFrontend | None = None, resolver: DependencyResolver | None = None):
        self.analyzer = ProjectAnalyzer(entry_source, project_root=project_root,
                                        frontend=frontend, resolver=resolver)

    @classmethod
    def from_tex(cls, tex: str, **options: Any) -> Any:
        """Create the human-facing mathematical object from TeX."""
        from .generation_planning import MathematicalFormula
        return MathematicalFormula.from_tex(tex, **options)

    @classmethod
    def from_expression(cls, expression: dict[str, Any], **options: Any) -> Any:
        """Create the same API from canonical Mathematical IR."""
        from .generation_planning import MathematicalFormula
        return MathematicalFormula.from_expression(expression, **options)

    @classmethod
    def from_source(cls, source: str | Path, **options: Any) -> "FormulaTracer":
        """Explicit source-oriented constructor, symmetrical with TeX input."""
        return cls(source, **options)

    def analyze(self, targets: Iterable[str | OutputTarget] | str | OutputTarget | None = None, *,
                ranges: Any = None, output_ranges: Mapping[str, Any] | None = None,
                observed_results: Mapping[str, Any] | None = None,
                error_specifications: Mapping[str, Any] | None = None,
                model_error_scopes: Mapping[str, str] | None = None,
                input_artifacts: Iterable[Any] = (), configuration: Iterable[Any] = (),
                audit_profile: Any = "RESEARCH") -> ProjectAuditResult:
        result = self.analyzer.analyze(targets)
        if ranges is not None or output_ranges:
            from .interval import analyze_project_ranges
            result = analyze_project_ranges(result, ranges, output_ranges=output_ranges)
        from .end_to_end import build_end_to_end_claims
        result = build_end_to_end_claims(result, observed_results=observed_results,
            error_specifications=error_specifications, model_error_scopes=model_error_scopes)
        from .research_provenance import augment_project_provenance
        return augment_project_provenance(result, entry_source=self.analyzer.entry_source,
            project_root=self.analyzer.project_root, input_artifacts=input_artifacts,
            configuration=configuration, profile=audit_profile)

    def debug(self, targets: Iterable[str | OutputTarget] | str | OutputTarget | None = None,
              **analyze_options: Any) -> Any:
        return self.analyze(targets, **analyze_options).debug()

    def analyze_incremental(self, previous: ProjectAuditResult, *, cache: Any = None,
                            **analyze_options: Any) -> Any:
        from .research_provenance import run_incremental_audit
        return run_incremental_audit(self, previous, cache=cache, analyze_options=analyze_options)

    def synthesize(self, *, theory: Any, language: str, constraints: Any = None,
                   output_path: str | Path | None = None, verify: bool = True) -> Any:
        from .synthesis import synthesize
        return synthesize(theory, language=language, constraints=constraints,
                          output_path=output_path, verify=verify)
