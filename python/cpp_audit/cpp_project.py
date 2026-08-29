"""C++/Clang adapter for the language-neutral FormulaTracer project API.

The existing LibTooling Implementation IR remains the authoritative complete
frontend.  A deliberately conservative source recognizer supplies project
discovery and partial Mathematical IR when that toolchain is unavailable; its
output is never promoted to complete verification.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterable

from .core import AuditError
from .error_ir import build_error_analysis
from .expression import extract_expression
from .pipeline import run_frontend, validate_clang_ir
from .project import (ArtifactOutput, AuditOutputResult, AuditRootResult, CallEdge,
                      CppFrontend, DefinitionEdge, DependencyEdge, DependencyResolver,
                      IOProvenance, ImportEdge, IncludeEdge, ModuleNode, OutputSink,
                      OutputTarget, OutputTargetKind, ProjectAuditResult,
                      ProjectDependencyGraph, ProjectStatus, RuntimeEvidence,
                      SerializationBoundary, SymbolNode, ValueDependencyEdge,
                      VariableTarget, _digest, _serial)


CPP_SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx"}
CPP_HEADER_SUFFIXES = {".h", ".hh", ".hpp", ".hxx"}


@dataclass
class CppCompileCommand:
    source: str
    directory: str
    command: str
    command_hash: str


@dataclass
class CppCompilationEnvironment:
    project_root: str
    cmake_lists: str | None
    compilation_database: str | None
    compilation_database_hash: str | None
    compile_commands: list[CppCompileCommand]
    frontend_path: str | None
    frontend_status: str
    clang_version: str | None
    discovery_status: str


@dataclass
class CppInclude:
    name: str
    system: bool
    begin_line: int


@dataclass
class CppConstant:
    name: str
    type_name: str
    expression: str
    begin_line: int
    constexpr: bool


@dataclass
class CppFunction:
    name: str
    canonical_name: str
    return_type: str
    parameters: list[dict[str, str]]
    body: str
    begin_line: int
    end_line: int
    namespace: str = ""


@dataclass
class CppSource:
    path: Path
    text: str
    includes: list[CppInclude]
    constants: list[CppConstant]
    functions: list[CppFunction]
    macros: list[dict[str, Any]]


@dataclass
class _CppModuleInfo:
    node: ModuleNode
    source: CppSource
    symbols: dict[str, CppFunction | CppConstant] = field(default_factory=dict)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _matching(text: str, start: int, opening: str = "{", closing: str = "}") -> int:
    depth = 0; quote: str | None = None; escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == quote: quote = None
            continue
        if char in {'"', "'"}: quote = char; continue
        if text.startswith("//", index):
            end = text.find("\n", index); index = len(text) if end < 0 else end
        if char == opening: depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0: return index
    return -1


def _split_top_level(text: str, delimiter: str = ",") -> list[str]:
    result: list[str] = []; start = 0; levels = {"(": 0, "[": 0, "{": 0, "<": 0}
    pairs = {")": "(", "]": "[", "}": "{", ">": "<"}; quote: str | None = None; escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == quote: quote = None
            continue
        if char in {'"', "'"}: quote = char; continue
        if char in levels: levels[char] += 1
        elif char in pairs and levels[pairs[char]]: levels[pairs[char]] -= 1
        elif char == delimiter and not any(levels.values()): result.append(text[start:index]); start = index + 1
    result.append(text[start:]); return result


def _namespace_at(text: str, offset: int) -> str:
    namespaces: list[tuple[int, int, str]] = []
    for match in re.finditer(r"\bnamespace\s+([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*\{", text):
        opening = text.find("{", match.start()); closing = _matching(text, opening)
        if closing > offset > opening: namespaces.append((opening, closing, match.group(1)))
    return "::".join(item[2] for item in sorted(namespaces) if item[0] < offset < item[1])


def parse_cpp_source(path: Path) -> CppSource:
    path = path.resolve()
    try: text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc: raise AuditError(f"CPP_FRONTEND_PARSE_FAILED: {path}: {exc}") from exc
    includes = [CppInclude(match.group(2), match.group(1) == "<", _line(text, match.start()))
                for match in re.finditer(r"(?m)^\s*#\s*include\s*([<\"])([^>\"]+)[>\"]", text)]
    macros = []
    for match in re.finditer(r"(?m)^\s*#\s*define\s+([A-Za-z_]\w*)(?:\([^\n]*\))?\s+(.+)$", text):
        value = match.group(2).strip(); numeric = bool(re.fullmatch(r"[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?[fFlL]?", value))
        macros.append({"name": match.group(1), "value": value, "begin_line": _line(text, match.start()),
                       "status": "PREPROCESSOR_NUMERIC_LITERAL_RECORDED" if numeric else "CPP_MACRO_SEMANTICS_UNRESOLVED"})
    functions: list[CppFunction] = []
    pattern = re.compile(r"^[ \t]*(?P<prefix>(?:template[ \t]*<[^{};]+>[ \t]*)?(?:inline[ \t]+|static[ \t]+|constexpr[ \t]+|virtual[ \t]+)*)"
        r"(?P<return>[A-Za-z_][\w:<>,*& \t]*?)[ \t]+(?P<name>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)[ \t]*"
        r"\((?P<params>[^{};]*)\)[ \t]*(?:const[ \t]*)?(?:noexcept[ \t]*)?\{", re.M)
    for match in pattern.finditer(text):
        if match.group("return").strip().split()[-1] in {"if", "for", "while", "switch", "catch"}: continue
        opening = text.find("{", match.start()); closing = _matching(text, opening)
        if closing < 0: continue
        params = []
        for part in _split_top_level(match.group("params")):
            clean = part.split("=", 1)[0].strip()
            param = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^]]*\])?$", clean)
            if param: params.append({"name": param.group(1), "type": clean[:param.start(1)].strip()})
        namespace = _namespace_at(text, match.start()); raw_name = match.group("name")
        canonical = raw_name if "::" in raw_name else f"{namespace}::{raw_name}" if namespace else raw_name
        functions.append(CppFunction(raw_name.split("::")[-1], canonical, match.group("return").strip(), params,
            text[opening + 1:closing], _line(text, match.start()), _line(text, closing), namespace))
    occupied = [(function.begin_line, function.end_line) for function in functions]
    constants = []
    constant_pattern = re.compile(r"(?m)^\s*(?:(?P<constexpr>constexpr)\s+|(?:inline\s+)?(?:static\s+)?const\s+)"
        r"(?P<type>[A-Za-z_]\w*(?:::\w+)*(?:\s*[*&])?)\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>[^;]+);")
    for match in constant_pattern.finditer(text):
        line = _line(text, match.start())
        if any(begin <= line <= end for begin, end in occupied): continue
        constants.append(CppConstant(match.group("name"), match.group("type"), match.group("value").strip(), line,
                                     bool(match.group("constexpr"))))
    return CppSource(path, text, includes, constants, functions, macros)


class CppEnvironmentResolver:
    """Discover only recorded compilation environments; never invent flags."""

    def __init__(self, entry: str | Path, project_root: str | Path | None = None):
        self.entry = Path(entry).resolve(); self.explicit_root = Path(project_root).resolve() if project_root else None

    def project_root(self) -> Path:
        if self.explicit_root: return self.explicit_root
        start = self.entry.parent if self.entry.is_file() else self.entry
        for parent in (start, *start.parents):
            if (parent / "CMakeLists.txt").is_file(): return parent
        return start

    def _databases(self, root: Path) -> list[Path]:
        candidates = []
        for direct in (root / "compile_commands.json", root / "build/compile_commands.json"):
            if direct.is_file(): candidates.append(direct)
        build = root / "build"
        if build.is_dir(): candidates.extend(path for path in build.rglob("compile_commands.json") if path not in candidates)
        return candidates

    @staticmethod
    def _version(frontend: Path | None) -> str | None:
        for executable in ([frontend] if frontend else []) + [Path(value) for value in [shutil.which("clang++"), shutil.which("clang-cl")] if value]:
            try:
                process = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=5, check=False)
                if process.returncode == 0: return process.stdout.splitlines()[0]
            except (OSError, subprocess.TimeoutExpired): pass
        return None

    @staticmethod
    def _frontend_available(frontend: Path | None) -> bool:
        if not frontend: return False
        try:
            subprocess.run([str(frontend), "--help"], capture_output=True, text=True, timeout=5, check=False)
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False

    def resolve(self) -> CppCompilationEnvironment:
        root = self.project_root(); databases = self._databases(root); selected = None; commands: list[CppCompileCommand] = []
        for database in databases:
            try: records = json.loads(database.read_text(encoding="utf-8"))
            except (OSError, ValueError): continue
            if not isinstance(records, list): continue
            values = []
            for record in records:
                command = str(record.get("command") or " ".join(record.get("arguments") or []))
                source = str(record.get("file") or "")
                values.append(CppCompileCommand(source, str(record.get("directory") or ""), command,
                                                sha256(command.encode()).hexdigest()))
            if self.entry.name == "CMakeLists.txt" or any(Path(item.source).name == self.entry.name for item in values):
                selected, commands = database, values; break
        frontend = None
        if selected:
            directory = selected.parent
            for name in ("cpp-audit-clang.exe", "cpp-audit-clang"):
                candidate = directory / name
                if candidate.is_file(): frontend = candidate; break
        version = self._version(frontend)
        frontend_status = "AVAILABLE" if self._frontend_available(frontend) else "CPP_FRONTEND_ENVIRONMENT_UNAVAILABLE"
        status = "COMPILATION_ENVIRONMENT_RESOLVED" if selected else "CPP_COMPILATION_DATABASE_UNRESOLVED"
        return CppCompilationEnvironment(str(root), str(root / "CMakeLists.txt") if (root / "CMakeLists.txt").is_file() else None,
            str(selected) if selected else None, sha256(selected.read_bytes()).hexdigest() if selected else None,
            commands, str(frontend) if frontend else None, frontend_status, version, status)


class CppDependencyResolver(DependencyResolver):
    """Build translation-unit/header/include and resolved local-call graphs."""

    def __init__(self, frontend: CppFrontend | None = None):
        self.frontend = frontend or CppFrontend(); self.environment: CppCompilationEnvironment | None = None
        self.module_info: dict[str, _CppModuleInfo] = {}; self.functions: dict[str, tuple[_CppModuleInfo, CppFunction]] = {}
        self.constants: dict[str, tuple[_CppModuleInfo, CppConstant]] = {}; self.root = Path()

    def _local_sources(self, entry: Path) -> list[Path]:
        root = self.root; result: list[Path] = []
        if entry.suffix in CPP_SOURCE_SUFFIXES | CPP_HEADER_SUFFIXES: result.append(entry)
        for command in self.environment.compile_commands if self.environment else []:
            candidate = Path(command.source)
            if not candidate.is_file():
                pieces = candidate.as_posix().split("/")
                for index in range(len(pieces)):
                    possible = root.joinpath(*pieces[index:])
                    if possible.is_file(): candidate = possible; break
            if candidate.is_file() and candidate.suffix in CPP_SOURCE_SUFFIXES and candidate.resolve() not in result:
                result.append(candidate.resolve())
        if not result and entry.name == "CMakeLists.txt":
            result.extend(path for path in root.rglob("*.cpp") if "build" not in path.parts)
        return result

    def _module_name(self, path: Path) -> str:
        try: return path.relative_to(self.root).with_suffix("").as_posix().replace("/", "::")
        except ValueError: return path.stem

    def resolve(self, entry_source: Path, project_root: Path | None = None) -> ProjectDependencyGraph:
        entry = Path(entry_source).resolve(); env_resolver = CppEnvironmentResolver(entry, project_root)
        self.environment = env_resolver.resolve(); self.root = Path(self.environment.project_root)
        self.module_info = {}; self.functions = {}; self.constants = {}
        graph = ProjectDependencyGraph(metadata={"cpp_compilation_environment": _serial(self.environment),
            "translation_units": [], "headers": [], "system_headers": []})
        include_roots: list[Path] = [self.root]
        for command in self.environment.compile_commands:
            for raw in re.findall(r"(?:^|\s)-I\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))", command.command):
                value = next((item for item in raw if item), ""); candidate = Path(value)
                if not candidate.is_absolute():
                    local = Path(command.directory) / candidate
                    if local.is_dir(): include_roots.append(local.resolve())
                if candidate.is_dir(): include_roots.append(candidate.resolve())
                pieces = candidate.as_posix().split("/")
                for index in range(len(pieces)):
                    local = self.root.joinpath(*pieces[index:])
                    if local.is_dir(): include_roots.append(local.resolve()); break
        include_roots = list(dict.fromkeys(include_roots))
        queue = self._local_sources(entry); visited: set[Path] = set()
        while queue:
            path = queue.pop(0).resolve()
            if path in visited or not path.is_file(): continue
            visited.add(path); source = self.frontend.parse(path); name = self._module_name(path)
            node = ModuleNode(f"module:{name}", name, str(path), language="cpp", is_package=path.suffix in CPP_HEADER_SUFFIXES,
                              source_hash=sha256(path.read_bytes()).hexdigest())
            info = _CppModuleInfo(node, source); self.module_info[name] = info; graph.modules.append(node)
            graph.metadata["headers" if path.suffix in CPP_HEADER_SUFFIXES else "translation_units"].append(str(path))
            for include in source.includes:
                if include.system:
                    if include.name not in graph.metadata["system_headers"]: graph.metadata["system_headers"].append(include.name)
                    graph.edges.append(IncludeEdge(node.module_id, f"system-header:{include.name}", canonical_name=include.name,
                        provenance={"file": str(path), "begin_line": include.begin_line, "system": True}))
                    continue
                candidates = [candidate.resolve() for candidate in (path.parent / include.name, *(root / include.name for root in include_roots))
                              if candidate.is_file()]
                candidates = list(dict.fromkeys(candidates))
                if len(candidates) != 1:
                    graph.diagnostics.append({"code": "CPP_INCLUDE_AMBIGUOUS" if candidates else "CPP_INCLUDE_UNRESOLVED",
                        "include": include.name, "source": str(path), "candidates": [str(item) for item in candidates]})
                    continue
                target = candidates[0]; target_name = self._module_name(target)
                graph.edges.append(IncludeEdge(node.module_id, f"module:{target_name}", canonical_name=target_name,
                    provenance={"file": str(path), "begin_line": include.begin_line, "system": False}))
                queue.append(target)
            for function in source.functions:
                canonical = function.canonical_name
                if canonical in self.functions:
                    canonical = f"{name}::{canonical}"
                    function.canonical_name = canonical
                self.functions[canonical] = (info, function); info.symbols[canonical] = function
                symbol = SymbolNode("symbol:" + _digest([canonical, str(path), function.begin_line])[:20], name, function.name,
                    "FUNCTION", canonical, True, {"file": str(path), "begin_line": function.begin_line, "begin_column": 1,
                    "end_line": function.end_line, "end_column": 1}, "cpp")
                graph.symbols.append(symbol); graph.edges.append(DefinitionEdge(node.module_id, symbol.symbol_id,
                    provenance=symbol.source_span))
            for constant in source.constants:
                canonical = f"{constant.name}" if "::" in constant.name else f"{name}::{constant.name}"
                self.constants[canonical] = (info, constant); info.symbols[canonical] = constant
                symbol = SymbolNode("symbol:" + _digest([canonical, str(path), constant.begin_line])[:20], name, constant.name,
                    "CONST", canonical, True, {"file": str(path), "begin_line": constant.begin_line, "begin_column": 1,
                    "end_line": constant.begin_line, "end_column": 1}, "cpp")
                graph.symbols.append(symbol); graph.edges.append(DefinitionEdge(node.module_id, symbol.symbol_id,
                    provenance=symbol.source_span))
        symbols = {symbol.canonical_name: symbol for symbol in graph.symbols}
        by_short: dict[str, list[SymbolNode]] = {}
        for symbol in graph.symbols: by_short.setdefault(symbol.name, []).append(symbol)
        for canonical, (info, function) in self.functions.items():
            owner = symbols.get(canonical)
            if not owner: continue
            for match in re.finditer(r"(?<![.:>])\b([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*\(", function.body):
                name = match.group(1)
                if name in {"if", "for", "while", "switch", "return", "sizeof", "static_cast"}: continue
                candidates = [symbols[name]] if name in symbols else by_short.get(name.split("::")[-1], [])
                if len(candidates) == 1: target, resolved = candidates[0].symbol_id, candidates[0].canonical_name
                else:
                    target, resolved = f"external:{name}", name
                    if len(candidates) > 1: graph.diagnostics.append({"code": "CPP_OVERLOAD_AMBIGUOUS", "call": name,
                        "function": canonical, "candidate_count": len(candidates)})
                graph.edges.append(CallEdge(owner.symbol_id, target, alias=name, canonical_name=resolved,
                    provenance={"file": str(info.source.path), "begin_line": function.begin_line + _line(function.body, match.start()) - 1,
                                "resolution": "CLANG_REQUIRED" if target.startswith("external:") else "PORTABLE_UNIQUE"}))
            for short, candidates in by_short.items():
                if len(candidates) == 1 and re.search(rf"\b{re.escape(short)}\b", function.body) and candidates[0].kind == "CONST":
                    graph.edges.append(ValueDependencyEdge(owner.symbol_id, candidates[0].symbol_id, alias=short,
                        canonical_name=candidates[0].canonical_name, provenance={"file": str(info.source.path), "begin_line": function.begin_line}))
        if self.environment.discovery_status != "COMPILATION_ENVIRONMENT_RESOLVED":
            graph.diagnostics.append({"code": "CPP_COMPILATION_DATABASE_UNRESOLVED", "project_root": str(self.root),
                                      "complete_verification": False})
        if self.environment.frontend_status != "AVAILABLE":
            graph.diagnostics.append({"code": "CPP_FRONTEND_ENVIRONMENT_UNAVAILABLE", "frontend": self.environment.frontend_path,
                                      "portable_recognizer_is_complete_verification": False})
        for info in self.module_info.values():
            for macro in info.source.macros:
                if macro["status"] == "CPP_MACRO_SEMANTICS_UNRESOLVED": graph.diagnostics.append({"code": macro["status"],
                    "macro": macro["name"], "source": str(info.source.path), "begin_line": macro["begin_line"]})
        return graph

    def command_for(self, path: Path) -> CppCompileCommand | None:
        return next((item for item in (self.environment.compile_commands if self.environment else [])
                     if Path(item.source).name == path.name), None)


class _CppLowerer:
    def __init__(self, resolver: CppDependencyResolver, graph: ProjectDependencyGraph):
        self.resolver = resolver; self.graph = graph; self.dependencies: set[str] = set(); self.locations: list[dict[str, Any]] = []
        self.contracts: list[dict[str, Any]] = []; self.execution: list[dict[str, Any]] = []

    def _free(self, canonical: str, name: str) -> dict[str, Any]:
        return {"op": "FreeVariable", "name": f"{canonical}::{name}"}

    def _constant(self, name: str, info: _CppModuleInfo, stack: set[str] | None = None) -> dict[str, Any] | None:
        matches = [(canonical, value) for canonical, value in self.resolver.constants.items() if canonical == name or canonical.endswith(f"::{name}")]
        if len(matches) != 1: return None
        canonical, (owner, constant) = matches[0]; self.dependencies.add(canonical); stack = set(stack or ())
        if canonical in stack: return {"op": "OpaqueNumericCall", "name": canonical, "args": [], "status": "CONSTANT_CYCLE"}
        stack.add(canonical); return self.expr(constant.expression, owner, {}, stack)

    @staticmethod
    def _normalize(value: str) -> str:
        value = re.sub(r"\bstatic_cast\s*<[^>]+>\s*\(([^()]*)\)", r"(\1)", value)
        value = value.replace("true", "True").replace("false", "False").replace("&&", " and ").replace("||", " or ")
        value = re.sub(r"(?<![=!<>])!(?!=)", " not ", value)
        value = re.sub(r"(?<=\d)[fFlL]\b", "", value)
        value = value.replace("std::", "std_").replace("::", "_")
        return value

    def _python_expr(self, node: ast.AST, info: _CppModuleInfo, env: dict[str, Any], stack: set[str]) -> dict[str, Any]:
        if isinstance(node, ast.Constant): return {"op": "Constant", "value": node.value}
        if isinstance(node, ast.Name):
            if node.id in env:
                value = env[node.id]; return self.expr(value, info, env, stack) if isinstance(value, str) else value
            constant = self._constant(node.id, info, stack)
            return constant or {"op": "FreeVariable", "name": node.id}
        if isinstance(node, ast.BinOp):
            operation = {ast.Add: "Add", ast.Sub: "Subtract", ast.Mult: "Multiply", ast.Div: "Divide", ast.Mod: "Modulo", ast.Pow: "Power"}.get(type(node.op), "OpaqueBinary")
            return {"op": operation, "args": [self._python_expr(node.left, info, env, stack), self._python_expr(node.right, info, env, stack)]}
        if isinstance(node, ast.UnaryOp): return {"op": "Negate" if isinstance(node.op, ast.USub) else "LogicalNot",
                                                   "arg": self._python_expr(node.operand, info, env, stack)}
        if isinstance(node, ast.Compare): return {"op": "Compare", "operator": type(node.ops[0]).__name__,
            "args": [self._python_expr(node.left, info, env, stack), self._python_expr(node.comparators[0], info, env, stack)]}
        if isinstance(node, ast.Subscript):
            indices = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
            return {"op": "IndexedValue", "name": ast.unparse(node.value),
                    "indices": [self._python_expr(index, info, env, stack) for index in indices]}
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func).replace("std_", "std::")
            operation = {"std::sqrt": "Sqrt", "std::abs": "Abs", "sqrt": "Sqrt", "abs": "Abs", "pow": "Power", "std::pow": "Power"}.get(name)
            args = [self._python_expr(arg, info, env, stack) for arg in node.args]
            if operation: return {"op": operation, "args": args, "library_contract": {"language": "cpp", "library": "std", "public_symbol": name}}
            matches = [(canonical, item) for canonical, item in self.resolver.functions.items() if canonical == name or canonical.endswith(f"::{name}")]
            if len(matches) == 1: return self.function(matches[0][0], args)
            return {"op": "OpaqueNumericCall", "name": name, "args": args, "shape_constraints": [{"kind": "return_type_constraint"}]}
        raise ValueError(type(node).__name__)

    def expr(self, value: str, info: _CppModuleInfo, env: dict[str, Any], stack: set[str] | None = None) -> dict[str, Any]:
        value = value.strip().rstrip(";"); stack = set(stack or ())
        conditional = re.match(r"(.+?)\?(.+?):(.+)", value, re.S)
        if conditional: return {"op": "IfThenElse", "condition": self.expr(conditional.group(1), info, env, stack),
            "then": self.expr(conditional.group(2), info, env, stack), "else": self.expr(conditional.group(3), info, env, stack)}
        try: return self._python_expr(ast.parse(self._normalize(value), mode="eval").body, info, env, stack)
        except (SyntaxError, ValueError): return {"op": "OpaqueNumericCall", "name": "CppExpression", "args": [],
            "source": value, "shape_constraints": [{"kind": "cpp_expression_type_constraint"}]}

    @staticmethod
    def _transform_reduce(canonical: str, order: str) -> dict[str, Any]:
        index = {"op": "BoundVariable", "name": "i"}
        return {"op": "TransformReduce", "bound_index": "i",
            "index_domain": {"lower": {"op": "Constant", "value": 0}, "upper_exclusive": {"op": "FreeVariable", "name": f"{canonical}::inputs"}},
            "initial_value": {"op": "Constant", "value": 0.0}, "transform": {"op": "Multiply", "args": [
                {"op": "IndexedValue", "name": "quantity", "indices": [{"op": "FreeVariable", "name": "r"}, index]},
                {"op": "IndexedValue", "name": "factor", "indices": [index]}]}, "reduction": "Add", "reduction_order": order}

    def function(self, canonical: str, args: list[dict[str, Any]] | None = None, target: str | None = None) -> dict[str, Any]:
        info, function = self.resolver.functions[canonical]; body = function.body
        self.locations.append({"file": str(info.source.path), "begin_line": function.begin_line, "end_line": function.end_line})
        for param in function.parameters: self.dependencies.add(f"{canonical}::{param['name']}")
        env = {param["name"]: (args[index] if args and index < len(args) else self._free(canonical, param["name"]))
               for index, param in enumerate(function.parameters)}
        if "std::inner_product" in body or re.search(r"\bstd::accumulate\s*\(", body):
            symbol = "std::inner_product" if "std::inner_product" in body else "std::accumulate"
            self.contracts.append({"language": "cpp", "library": "std", "version": "cpp20", "public_symbol": symbol,
                "semantic_family": "ORDERED_REDUCTION", "official_reference": f"https://en.cppreference.com/w/cpp/algorithm/{symbol.split('::')[-1]}"})
            reduction = self._transform_reduce(canonical, "left_to_right")
            assigned = re.search(r"(?:auto|float|double|long\s+double)\s+([A-Za-z_]\w*)\s*=\s*std::(?:inner_product|accumulate)", body)
            returned = list(re.finditer(r"\breturn\s+([^;]+);", body))
            if assigned and returned: return self.expr(returned[-1].group(1), info, {assigned.group(1): reduction})
            return reduction
        if re.search(r"\bstd::reduce\s*\(", body):
            self.contracts.append({"language": "cpp", "library": "std", "version": "cpp20", "public_symbol": "std::reduce",
                "semantic_family": "REORDERABLE_REDUCTION", "official_reference": "https://en.cppreference.com/w/cpp/algorithm/reduce"})
            self.execution.append({"operation": "std::reduce", "policy": "PARALLEL_REORDERABLE", "reduction_order": "UNSPECIFIED",
                                   "floating_point_order_difference": True})
            return self._transform_reduce(canonical, "reorderable")
        accumulation = re.search(r"\b([A-Za-z_]\w*)\s*\+=\s*[^;]*\*[^;]*;", body)
        if accumulation:
            reduction = self._transform_reduce(canonical, "left_to_right")
            returned = list(re.finditer(r"\breturn\s+([^;]+);", body))
            if returned: return self.expr(returned[-1].group(1), info, {accumulation.group(1): reduction})
            return reduction
        selected: dict[str, str | dict[str, Any]] = {}
        for match in re.finditer(r"(?:^|;)\s*(?:const\s+)?(?:auto|float|double|long\s+double|int|long|size_t)\s+([A-Za-z_]\w*)\s*=\s*([^;]+)", body):
            selected[match.group(1)] = match.group(2).strip(); env[match.group(1)] = match.group(2).strip()
        for match in re.finditer(r"(?:^|;)\s*([A-Za-z_]\w*)\s*([+\-*/%])=\s*([^;]+)", body):
            name, operator, rhs = match.groups(); op = {"+": "Add", "-": "Subtract", "*": "Multiply", "/": "Divide", "%": "Modulo"}[operator]
            previous = env.get(name, self._free(canonical, name)); value = {"op": op, "args": [self.expr(previous, info, env) if isinstance(previous, str) else previous, self.expr(rhs, info, env)], "mutation": "final_reaching_definition"}
            selected[name] = value; env[name] = value
        if target:
            if target not in selected: raise AuditError(f"CPP_VARIABLE_TARGET_NOT_FOUND: {target}")
            value = selected[target]; self.dependencies.add(f"{canonical}::{target}")
            return self.expr(value, info, env) if isinstance(value, str) else value
        returned = list(re.finditer(r"\breturn\s+([^;]+);", body))
        if returned: return self.expr(returned[-1].group(1), info, env)
        assignments = list(re.finditer(r"\b([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*)|\s*\[([^]]+)\])\s*=\s*([^;]+);", body))
        if assignments: return self.expr(assignments[-1].group(4), info, env)
        return {"op": "OpaqueNumericCall", "name": canonical, "args": list(env.values()), "shape_constraints": [{"kind": "cpp_return_type_constraint", "type": function.return_type}]}


class CppProjectAnalyzer:
    def __init__(self, entry_source: str | Path, *, project_root: str | Path | None = None,
                 frontend: CppFrontend | None = None, resolver: DependencyResolver | None = None):
        self.entry_source = Path(entry_source).resolve(); self.project_root = Path(project_root).resolve() if project_root else None
        self.frontend = frontend or CppFrontend()
        self.resolver = resolver if isinstance(resolver, CppDependencyResolver) else CppDependencyResolver(self.frontend)
        self.graph: ProjectDependencyGraph | None = None

    def lower_function(self, canonical: str, arguments: list[dict[str, Any]]) -> dict[str, Any]:
        if self.graph is None: self.graph = self.resolver.resolve(self.entry_source, self.project_root)
        return _CppLowerer(self.resolver, self.graph).function(canonical, arguments)

    def _auto_roots(self) -> list[tuple[str, CppFunction, list[OutputTarget]]]:
        incoming = {edge.target for edge in self.graph.edges if edge.kind == "CALL" and edge.target.startswith("symbol:")}
        roots = []
        for canonical, (info, function) in self.resolver.functions.items():
            if (self.entry_source.name != "CMakeLists.txt" and
                    info.source.path.resolve() != self.entry_source.resolve()):
                continue
            symbol = next((item for item in self.graph.symbols if item.canonical_name == canonical), None)
            if self.entry_source.name == "CMakeLists.txt" and symbol and symbol.symbol_id in incoming: continue
            targets = []
            assignments = list(re.finditer(r"\b([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*)|\s*\[([^]]+)\])\s*=\s*([^;]+);", function.body))
            for match in assignments:
                name = match.group(2) or match.group(1)
                targets.append(OutputTarget(OutputTargetKind.RETURN_OUTPUT.value, name, info.node.name, canonical,
                                            expression=match.group(4).strip()))
            if function.name != "main" and re.search(r"\breturn\s+[^;]+;", function.body):
                targets.append(OutputTarget(OutputTargetKind.RETURN_OUTPUT.value, function.name, info.node.name, canonical))
            if targets: roots.append((canonical, function, targets))
        return roots

    def _explicit_roots(self, targets: Iterable[str | OutputTarget]) -> list[tuple[str, CppFunction, list[OutputTarget]]]:
        grouped: dict[str, tuple[CppFunction, list[OutputTarget]]] = {}
        for raw in targets:
            target = VariableTarget(raw) if isinstance(raw, str) else raw; matches = []
            for canonical, (info, function) in self.resolver.functions.items():
                if target.module and target.module != info.node.name: continue
                if target.function and target.function not in {function.name, canonical}: continue
                if re.search(rf"\b{re.escape(target.name)}\s*(?:[+\-*/%]?=|\{{|\()", function.body): matches.append((canonical, function))
            if len(matches) != 1: raise AuditError(f"OUTPUT_VARIABLE_AMBIGUOUS: {target.name}: {len(matches)} C++ definitions")
            canonical, function = matches[0]; grouped.setdefault(canonical, (function, []))[1].append(target)
        return [(canonical, function, values) for canonical, (function, values) in grouped.items()]

    def _sinks(self) -> tuple[list[tuple[str, CppFunction, list[OutputTarget]]], list[OutputSink]]:
        roots = []; artifacts = []
        for canonical, (info, function) in self.resolver.functions.items():
            if (self.entry_source.name != "CMakeLists.txt" and
                    info.source.path.resolve() != self.entry_source.resolve()):
                continue
            streams = {match.group(1): match.group(2) for match in re.finditer(r"std::ofstream\s+([A-Za-z_]\w*)\s*\(\s*([^,)]+)", function.body)}
            for match in re.finditer(r"([A-Za-z_]\w*)\s*<<\s*([A-Za-z_]\w*)", function.body):
                stream, payload = match.groups()
                if stream not in streams: continue
                span = {"file": str(info.source.path), "begin_line": function.begin_line + _line(function.body, match.start()) - 1,
                        "begin_column": 1, "end_line": function.begin_line + _line(function.body, match.end()) - 1, "end_column": 1}
                boundary = SerializationBoundary("serialization:" + _digest([canonical, span])[:16], {"op": "PayloadReference", "name": payload}, "std::ofstream::operator<<",
                    {"language": "cpp", "library": "std", "public_symbol": "std::basic_ostream::operator<<"})
                artifact = ArtifactOutput("sink:" + _digest([canonical, span])[:16], "FILE_OUTPUT", "text", streams[stream],
                    boundary.mathematical_payload, payload, None, [], None, None, span,
                    IOProvenance(info.node.name, str(info.source.path), "std::ofstream::operator<<", span), boundary)
                artifacts.append(artifact); roots.append((canonical, function, [OutputTarget(OutputTargetKind.FILE_OUTPUT.value, payload, info.node.name, canonical)]))
        return roots, artifacts

    def _native_ir(self, canonical: str, function: CppFunction) -> tuple[dict[str, Any] | None, RuntimeEvidence | None]:
        info, _ = self.resolver.functions[canonical]; environment = self.resolver.environment
        if not environment or not environment.compilation_database:
            evidence = RuntimeEvidence(
                "runtime:" + _digest([canonical, "COMPILATION_DATABASE_UNAVAILABLE"])[:16],
                "CLANG_IMPLEMENTATION_IR", "UNAVAILABLE", {},
                {"diagnostic": "COMPILATION_DATABASE_UNAVAILABLE"},
                {"translation_unit": str(info.source.path)}, False)
            return None, evidence
        frontend = Path(environment.frontend_path) if environment.frontend_path else None
        if frontend and environment.frontend_status == "AVAILABLE":
            try:
                with tempfile.TemporaryDirectory() as temporary:
                    ir = run_frontend(frontend, Path(environment.compilation_database).parent, info.source.path, function.name,
                                      Path(temporary) / "implementation-ir.json")
                valid = not validate_clang_ir(ir)
                evidence = RuntimeEvidence("runtime:" + _digest([canonical, ir.get("source_hash")])[:16], "CLANG_IMPLEMENTATION_IR",
                    "VALIDATED" if valid else "FAILED", ir.get("producer", {}), {"validation_diagnostics": validate_clang_ir(ir)},
                    {"translation_unit": str(info.source.path)}, False)
                return ir if valid else None, evidence
            except (AuditError, OSError, ValueError) as exc:
                return None, RuntimeEvidence("runtime:" + _digest([canonical, str(exc)])[:16], "CLANG_IMPLEMENTATION_IR", "UNAVAILABLE", {}, {"error": str(exc)}, {}, False)
        # Existing native artifacts may be attached as evidence only when their exact source hash matches.
        root = Path(environment.project_root); source_hash = sha256(info.source.path.read_bytes()).hexdigest()
        for candidate in (root / "build").rglob("*.ir.json") if (root / "build").is_dir() else []:
            try: ir = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError): continue
            if ir.get("source_hash") == source_hash and ir.get("function") == function.name:
                diagnostics = validate_clang_ir(ir)
                evidence = RuntimeEvidence("runtime:" + _digest([str(candidate), source_hash])[:16], "CACHED_CLANG_IMPLEMENTATION_IR",
                    "VALIDATED" if not diagnostics else "LEGACY_SCHEMA_RECORDED", ir.get("producer", {}),
                    {"validation_diagnostics": diagnostics}, {"artifact": str(candidate), "source_hash": source_hash}, False)
                return ir if not diagnostics else None, evidence
        return None, None

    def _output(self, canonical: str, function: CppFunction, target: OutputTarget) -> tuple[AuditOutputResult, RuntimeEvidence | None]:
        info, _ = self.resolver.functions[canonical]; lowerer = _CppLowerer(self.resolver, self.graph)
        ir, runtime = self._native_ir(canonical, function); expression = None; extraction = None
        if ir:
            extraction = extract_expression(ir)
            if extraction.get("status") == "EXPRESSION_EXTRACTED" and extraction.get("outputs"):
                value = extraction["outputs"][0]; expression = value.get("expression", value)
        if expression is None:
            reduction_body = ("std::inner_product" in function.body or "std::accumulate" in function.body or
                              "std::reduce" in function.body or
                              bool(re.search(r"\b(?:acc|total|sum)\s*\+=\s*[^;]*\*[^;]*;", function.body)))
            if target.expression and not reduction_body: expression = lowerer.expr(target.expression, info, {})
            else: expression = lowerer.function(canonical, target=target.name if target.kind != OutputTargetKind.RETURN_OUTPUT.value else None)
        parallel = bool(lowerer.execution) or expression.get("reduction_order") == "reorderable"
        type_names = [function.return_type, *(item["type"] for item in function.parameters)]
        execution_types = sorted({name for value in type_names for name in ("long double", "double", "float") if name in value})
        implementation = {"schema_version": "1.0", "language": "cpp", "module": info.node.name, "symbol": canonical,
            "mathematical_ir": expression, "outputs": [{"name": target.name, "expression": expression}],
            "clang_implementation_ir": ir, "clang_expression_extraction": extraction,
            "frontend_authority": "CLANG_LIBTOOLING" if ir else "PORTABLE_RECOGNIZER_PARTIAL",
            "library_contracts": lowerer.contracts,
            "execution_ir": {"operations": lowerer.execution, "overall_policy": "PARALLEL_REORDERABLE" if parallel else "SEQUENTIAL"},
            "numeric_execution": {"cpp_types": execution_types, "mathematical_domain": "Real",
                "ieee754_equivalence": "NOT_CLAIMED", "floating_point_exact_real_equivalence": False},
            "alias_semantics": {"status": "CLANG_RESOLVED" if ir else "UNRESOLVED", "complete_verification": bool(ir)},
            "expression_id": "expression:" + _digest(expression)[:16]}
        error = build_error_analysis(theory_ir=None, implementation_ir=implementation, output=target.name,
            comparison_relation="UNRESOLVED", parallel_semantics=({"overall_policy": "PARALLEL_REORDERABLE",
                "claims": {"PARALLEL_REDUCTION_ORDER_DIFFERS": "POSSIBLE"}} if parallel else None),
            library_contracts=lowerer.contracts)
        causes = sorted({component.semantic_cause_id for component in error.error_components})
        output = AuditOutputResult("output:" + _digest([canonical, target.name, expression])[:16], target.name, target.kind,
            None, implementation, expression, _serial(error.residual_expression), _serial(error.error_components),
            _serial(error.graph_enclosure.output_bound), _serial(error.graph_enclosure.known_output_bound),
            {"status": error.graph_enclosure.total_output_status, "bound": None}, sorted(lowerer.dependencies), lowerer.locations,
            "NOT_RUN", "UNRESOLVED", causes, _digest([sorted(lowerer.dependencies), expression]))
        return output, runtime

    def analyze(self, targets: Iterable[str | OutputTarget] | None = None) -> ProjectAuditResult:
        self.graph = self.resolver.resolve(self.entry_source, self.project_root)
        sink_roots, artifacts = self._sinks(); candidates = self._explicit_roots(targets) if targets else self._auto_roots() + sink_roots
        merged: dict[str, tuple[CppFunction, list[OutputTarget]]] = {}
        for canonical, function, values in candidates:
            current = merged.setdefault(canonical, (function, []))[1]
            for value in values:
                if not any((item.kind, item.name) == (value.kind, value.name) for item in current): current.append(value)
        roots = []; outputs = []; runtime_evidence = []; diagnostics = list(self.graph.diagnostics)
        for canonical, (function, output_targets) in merged.items():
            root_outputs = []
            for target in output_targets:
                try:
                    output, runtime = self._output(canonical, function, target); root_outputs.append(output)
                    if runtime and runtime.evidence_id not in {item.evidence_id for item in runtime_evidence}: runtime_evidence.append(runtime)
                except (AuditError, ValueError, TypeError) as exc:
                    diagnostics.append({"code": "CPP_OUTPUT_ANALYSIS_FAILED", "symbol": canonical, "target": target.name, "message": str(exc)})
            outputs.extend(root_outputs); dependencies = sorted({value for output in root_outputs for value in output.dependencies})
            info, _ = self.resolver.functions[canonical]; root_id = "root:" + _digest([canonical, [item.name for item in root_outputs]])[:16]
            roots.append(AuditRootResult(root_id, info.node.name, canonical, root_outputs, dependencies,
                status="UNRESOLVED" if root_outputs else "FAILED", graph_hash=_digest([root_id, dependencies])))
        shared = []; kinds = {symbol.canonical_name: symbol.kind for symbol in self.graph.symbols}
        dependence_unknown = any(item.get("code") in {"CPP_INCLUDE_UNRESOLVED", "CPP_INCLUDE_AMBIGUOUS",
            "CPP_OVERLOAD_AMBIGUOUS", "UNRESOLVED_ALIAS_CLASS"} for item in self.graph.diagnostics)
        for index, left in enumerate(roots):
            for right in roots[index + 1:]:
                common = sorted(set(left.dependency_slice) & set(right.dependency_slice))
                kind = "SHARED_CONSTANT" if any(kinds.get(value) == "CONST" for value in common) else "SHARED_FUNCTION" if common else "DEPENDENCE_UNKNOWN" if dependence_unknown else "DISCONNECTED"
                relation = {"left_root": left.root_id, "right_root": right.root_id, "kind": kind, "symbols": common}
                shared.append(relation); left.root_relations.append(relation); right.root_relations.append(relation)
        source_hashes = {module.name: module.source_hash for module in self.graph.modules}; environment = self.resolver.environment
        provenance = {"entry_source_hash": sha256(self.entry_source.read_bytes()).hexdigest(), "used_source_hashes": source_hashes,
            "cpp_translation_unit_hashes": {name: value for name, value in source_hashes.items() if not self.resolver.module_info[name].node.is_package},
            "project_graph_hash": self.graph.graph_hash, "module_graph_hash": _digest([(edge.source, edge.target) for edge in self.graph.edges if edge.kind == "INCLUDE"]),
            "root_graph_hashes": {root.root_id: root.graph_hash for root in roots}, "output_slice_hashes": {output.output_id: output.slice_hash for output in outputs},
            "cmake_lists_hash": sha256(Path(environment.cmake_lists).read_bytes()).hexdigest() if environment and environment.cmake_lists else None,
            "compile_commands_hash": environment.compilation_database_hash if environment else None,
            "compile_command_hashes": {item.source: item.command_hash for item in (environment.compile_commands if environment else [])},
            "clang_version": environment.clang_version if environment else None, "cpp_frontend_version": self.frontend.frontend_version,
            "frontend_environment_status": environment.frontend_status if environment else "CPP_FRONTEND_ENVIRONMENT_UNAVAILABLE",
            "runtime_evidence": [_serial(item) for item in runtime_evidence], "runtime_evidence_is_lean_proof": False,
            "library_contract_registry_hash": _digest(["cpp-std-registry", "cpp20"]), "lean_source_hashes": self._lean_hashes()}
        causes = [{"semantic_cause_id": cause, "outputs": [output.output_id for output in outputs if cause in output.error_causes]}
                  for cause in sorted({cause for output in outputs for cause in output.error_causes})]
        status = ProjectStatus.UNRESOLVED.value if roots else ProjectStatus.FAILED.value
        return ProjectAuditResult(status, self.graph, roots, outputs, self.graph.modules, [_serial(edge) for edge in self.graph.edges],
            shared, causes, [{"output_id": output.output_id, "lean_status": output.lean_status} for output in outputs], artifacts, provenance, diagnostics)

    @staticmethod
    def _lean_hashes() -> dict[str, str]:
        lean = Path(__file__).resolve().parents[2] / "lean"
        return {str(path.relative_to(lean)): sha256(path.read_bytes()).hexdigest() for path in lean.rglob("*.lean")} if lean.is_dir() else {}
