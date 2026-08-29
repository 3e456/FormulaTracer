"""Static Cargo/Rust project frontend for the common FormulaTracer audit model.

The frontend intentionally uses stable source and Cargo manifest information as
the audit identity. Cargo/rustc machine-readable output is optional provenance;
no rustc-internal HIR/MIR node identifier is persisted.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from typing import Any, Iterable

from .core import AuditError
from .error_ir import build_error_analysis
from .project import (ArtifactOutput, AuditOutputResult, AuditRootResult, CallEdge,
                      DefinitionEdge, DependencyEdge, DependencyResolver, ImportEdge,
                      IOProvenance, ModuleNode, OutputSink, OutputTarget, OutputTargetKind,
                      ProjectAuditResult, ProjectDependencyGraph, ProjectStatus, ReExportEdge,
                      RustFrontend, SerializationBoundary, SymbolNode, ValueDependencyEdge,
                      VariableTarget, _digest, _serial)
from .rust_contracts import RustLibraryContractRegistry


class CargoDependencyKind(str, Enum):
    LOCAL_MODULE = "LOCAL_MODULE"
    LOCAL_PATH_CRATE = "LOCAL_PATH_CRATE"
    WORKSPACE_CRATE = "WORKSPACE_CRATE"
    REGISTRY_CRATE = "REGISTRY_CRATE"
    GIT_CRATE = "GIT_CRATE"
    EXTERNAL_BINARY_DEPENDENCY = "EXTERNAL_BINARY_DEPENDENCY"


class FFIResolutionStatus(str, Enum):
    REFERENCE_CONTRACT_RESOLVED = "REFERENCE_CONTRACT_RESOLVED"
    FFI_MAPPING_RESOLVED = "FFI_MAPPING_RESOLVED"
    RUST_SOURCE_RESOLVED = "RUST_SOURCE_RESOLVED"
    LOCAL_NATIVE_SOURCE_RESOLVED = "LOCAL_NATIVE_SOURCE_RESOLVED"
    FFI_MAPPING_UNRESOLVED = "FFI_MAPPING_UNRESOLVED"
    BINARY_ONLY = "BINARY_ONLY"
    EXTERNAL_SOURCE_NOT_INSPECTED = "EXTERNAL_SOURCE_NOT_INSPECTED"


@dataclass
class CargoDependency:
    name: str
    kind: str
    version: str | None = None
    path: str | None = None
    git: str | None = None
    features: list[str] = field(default_factory=list)
    optional: bool = False


@dataclass
class CargoCrate:
    crate_id: str
    name: str
    crate_type: str
    root_source: str
    package: str


@dataclass
class CargoPackage:
    name: str
    version: str
    manifest_path: str
    crates: list[CargoCrate]
    dependencies: list[CargoDependency]
    features: dict[str, Any]
    build_script: str | None = None
    proc_macro: bool = False


@dataclass
class CargoWorkspace:
    root: str
    manifest_path: str
    cargo_toml_hash: str
    cargo_lock_hash: str | None
    members: list[str]
    packages: list[CargoPackage]
    selected_features: list[str] = field(default_factory=list)
    target_configuration: str = "HOST_DEFAULT_UNRESOLVED"


@dataclass
class RustItem:
    kind: str
    name: str
    signature: str
    body: str | None
    public: bool
    mutable: bool
    attributes: list[str]
    begin_line: int
    end_line: int
    owner: str | None = None


@dataclass
class RustUse:
    path: str
    alias: str | None
    public: bool
    begin_line: int


@dataclass
class RustModuleDecl:
    name: str
    public: bool
    begin_line: int
    inline: bool = False


@dataclass
class RustSource:
    path: Path
    text: str
    items: list[RustItem]
    uses: list[RustUse]
    modules: list[RustModuleDecl]
    macros: list[dict[str, Any]]
    unsafe_blocks: list[dict[str, Any]]
    cfg_attributes: list[str]


@dataclass
class RustModuleInfo:
    node: ModuleNode
    source: RustSource
    crate_name: str
    aliases: dict[str, str] = field(default_factory=dict)
    symbols: dict[str, RustItem] = field(default_factory=dict)


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
        if char in {'"', "'"}:
            # Lifetimes are not character literals; only quote when a closing quote is nearby.
            if char == "'" and (index + 2 >= len(text) or text.find("'", index + 1, index + 6) < 0):
                continue
            quote = char; continue
        if char == opening: depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0: return index
    return -1


def _attributes_before(text: str, offset: int) -> list[str]:
    prefix = text[:offset].splitlines()
    result = []
    for value in reversed(prefix):
        stripped = value.strip()
        if stripped.startswith("#[") and stripped.endswith("]"):
            result.append(stripped)
        elif not stripped or stripped.startswith("///") or stripped.startswith("//!"):
            continue
        else: break
    return list(reversed(result))


def _expand_use(value: str) -> list[tuple[str, str | None]]:
    value = value.strip()
    if "{" not in value:
        path, marker, alias = value.partition(" as ")
        return [(path.strip(), alias.strip() if marker else None)]
    prefix, rest = value.split("{", 1); content = rest.rsplit("}", 1)[0]
    result = []
    for part in _split_top_level(content, ","):
        part = part.strip()
        if part == "self": result.append((prefix.rstrip(":"), None))
        else: result.extend(_expand_use(prefix + part))
    return result


def _split_top_level(text: str, delimiter: str) -> list[str]:
    result: list[str] = []; start = 0; depths = {"(": 0, "[": 0, "{": 0}; pairs = {")": "(", "]": "[", "}": "{"}
    quote: str | None = None; escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == quote: quote = None
            continue
        if char in {'"', "'"}: quote = char; continue
        if char in depths: depths[char] += 1
        elif char in pairs: depths[pairs[char]] = max(0, depths[pairs[char]] - 1)
        elif char == delimiter and not any(depths.values()):
            result.append(text[start:index]); start = index + 1
    result.append(text[start:]); return result


def parse_rust_source(path: Path) -> RustSource:
    path = path.resolve()
    try: text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc: raise AuditError(f"RUST_FRONTEND_PARSE_FAILED: {path}: {exc}") from exc
    items: list[RustItem] = []
    impl_ranges: list[tuple[int, int, str]] = []
    for match in re.finditer(r"\bimpl(?:\s*<[^>{}]*>)?\s+([A-Za-z_]\w*)(?:\s+for\s+[A-Za-z_]\w*)?[^{}]*\{", text):
        end = _matching(text, text.find("{", match.start()))
        if end >= 0: impl_ranges.append((match.start(), end, match.group(1)))
    function_pattern = re.compile(r"(?m)(?P<prefix>^[ \t]*(?:(?:pub(?:\([^)]*\))?|unsafe|async|const|extern\s+\"[^\"]+\")\s+)*)fn\s+(?P<name>[A-Za-z_]\w*)\s*(?P<generics><[^>{}]*>)?\s*\(")
    for match in function_pattern.finditer(text):
        open_paren = text.find("(", match.start()); close_paren = _matching(text, open_paren, "(", ")")
        if close_paren < 0: continue
        open_brace = text.find("{", close_paren)
        semicolon = text.find(";", close_paren, open_brace if open_brace >= 0 else len(text))
        if semicolon >= 0 and (open_brace < 0 or semicolon < open_brace): continue
        if open_brace < 0: continue
        close_brace = _matching(text, open_brace)
        if close_brace < 0: continue
        owner = next((name for start, end, name in impl_ranges if start < match.start() < end), None)
        prefix = match.group("prefix") or ""
        items.append(RustItem("FUNCTION", match.group("name"), text[match.start():open_brace].strip(),
            text[open_brace + 1:close_brace], "pub" in prefix, False, _attributes_before(text, match.start()),
            _line(text, match.start()), _line(text, close_brace), owner))
    item_pattern = re.compile(r"(?m)^[ \t]*(?P<pub>pub(?:\([^)]*\))?\s+)?(?P<kind>const|static|struct|enum)\s+(?P<mut>mut\s+)?(?P<name>[A-Za-z_]\w*)")
    for match in item_pattern.finditer(text):
        kind = match.group("kind").upper(); line_end = text.find("\n", match.end())
        snippet = text[match.start():(line_end if line_end >= 0 else len(text))].strip()
        body = snippet.split("=", 1)[1].rsplit(";", 1)[0].strip() if "=" in snippet and kind in {"CONST", "STATIC"} else None
        items.append(RustItem(kind, match.group("name"), snippet, body, bool(match.group("pub")),
                              bool(match.group("mut")), _attributes_before(text, match.start()),
                              _line(text, match.start()), _line(text, line_end if line_end >= 0 else len(text))))
    uses = []
    for match in re.finditer(r"(?m)^[ \t]*(?P<pub>pub\s+)?use\s+(?P<value>[^;]+);", text):
        uses.extend(RustUse(path_value, alias, bool(match.group("pub")), _line(text, match.start()))
                    for path_value, alias in _expand_use(match.group("value")))
    modules = [RustModuleDecl(match.group("name"), bool(match.group("pub")), _line(text, match.start()),
                              match.group("end") == "{")
               for match in re.finditer(r"(?m)^[ \t]*(?P<pub>pub\s+)?mod\s+(?P<name>[A-Za-z_]\w*)\s*(?P<end>[;{])", text)]
    builtins = {"vec", "format", "println", "eprintln", "matches", "assert", "assert_eq", "dbg", "include_str", "include_bytes"}
    declared = set(re.findall(r"macro_rules!\s*([A-Za-z_]\w*)", text))
    macros = []
    for match in re.finditer(r"\b([A-Za-z_]\w*)!\s*[({\[]", text):
        name = match.group(1)
        kind = "BUILTIN_OR_COMMON" if name in builtins else "USER_MACRO" if name in declared else "PROCEDURAL_OR_EXTERNAL"
        macros.append({"name": name, "kind": kind, "begin_line": _line(text, match.start()),
                       "status": "SOURCE_SEMANTICS_KNOWN" if kind == "BUILTIN_OR_COMMON" else "MACRO_EXPANSION_UNRESOLVED"})
    unsafe_blocks = [{"code": "UNSAFE_BLOCK", "begin_line": _line(text, match.start()),
                      "proof_obligation": "UNSAFE_MEMORY_ASSUMPTION"}
                     for match in re.finditer(r"\bunsafe\s*\{", text)]
    for item in items:
        if item.kind == "FUNCTION" and "unsafe" in item.signature.split("fn", 1)[0]:
            unsafe_blocks.append({"code": "UNSAFE_OPERATION", "symbol": item.name,
                                  "begin_line": item.begin_line, "proof_obligation": "UNSAFE_MEMORY_ASSUMPTION"})
    cfg = re.findall(r"#\[(?:cfg|cfg_attr)\([^\]]+\)\]", text)
    return RustSource(path, text, items, uses, modules, macros, unsafe_blocks, cfg)


class RustDependencyResolver(DependencyResolver):
    """Cargo-aware resolver that follows only workspace/local path Rust source."""

    def __init__(self, frontend: RustFrontend | None = None):
        self.frontend = frontend or RustFrontend()
        self.workspace: CargoWorkspace | None = None
        self.module_info: dict[str, RustModuleInfo] = {}
        self.symbol_items: dict[str, tuple[RustModuleInfo, RustItem]] = {}
        self.root = Path()
        self._python_exports: dict[str, str] = {}

    @staticmethod
    def find_manifest(entry: Path) -> Path:
        entry = entry.resolve()
        if entry.name == "Cargo.toml": return entry
        for parent in (entry.parent, *entry.parents):
            manifest = parent / "Cargo.toml"
            if manifest.is_file(): return manifest
        raise AuditError(f"CARGO_MANIFEST_NOT_FOUND: {entry}")

    @staticmethod
    def _load_toml(path: Path) -> dict[str, Any]:
        try: return tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc: raise AuditError(f"CARGO_MANIFEST_INVALID: {path}: {exc}") from exc

    def _dependency(self, name: str, value: Any, manifest_dir: Path,
                    workspace_names: set[str]) -> CargoDependency:
        if isinstance(value, str):
            return CargoDependency(name, CargoDependencyKind.REGISTRY_CRATE.value, version=value)
        value = value if isinstance(value, dict) else {}
        if value.get("path"):
            path = (manifest_dir / str(value["path"])).resolve()
            kind = CargoDependencyKind.WORKSPACE_CRATE.value if name in workspace_names else CargoDependencyKind.LOCAL_PATH_CRATE.value
            return CargoDependency(name, kind, str(value.get("version")) if value.get("version") else None,
                                   str(path), features=list(value.get("features") or []), optional=bool(value.get("optional")))
        if value.get("git"):
            return CargoDependency(name, CargoDependencyKind.GIT_CRATE.value,
                                   str(value.get("version")) if value.get("version") else None,
                                   git=str(value["git"]), features=list(value.get("features") or []),
                                   optional=bool(value.get("optional")))
        if value.get("workspace"):
            return CargoDependency(name, CargoDependencyKind.WORKSPACE_CRATE.value,
                                   features=list(value.get("features") or []), optional=bool(value.get("optional")))
        return CargoDependency(name, CargoDependencyKind.REGISTRY_CRATE.value,
                               str(value.get("version")) if value.get("version") else None,
                               features=list(value.get("features") or []), optional=bool(value.get("optional")))

    def _package(self, manifest: Path, workspace_names: set[str]) -> CargoPackage | None:
        data = self._load_toml(manifest); package = data.get("package")
        if not isinstance(package, dict): return None
        name = str(package.get("name") or manifest.parent.name); version = str(package.get("version") or "UNVERIFIED")
        crates: list[CargoCrate] = []
        lib = data.get("lib") if isinstance(data.get("lib"), dict) else {}
        lib_path = manifest.parent / str(lib.get("path", "src/lib.rs"))
        if lib_path.is_file(): crates.append(CargoCrate(f"crate:{name}:lib", name.replace("-", "_"), "LIB", str(lib_path.resolve()), name))
        main = manifest.parent / "src/main.rs"
        if main.is_file(): crates.append(CargoCrate(f"crate:{name}:bin", name.replace("-", "_"), "BIN", str(main.resolve()), name))
        for index, binary in enumerate(data.get("bin") or []):
            if not isinstance(binary, dict): continue
            path = manifest.parent / str(binary.get("path", f"src/bin/{binary.get('name', index)}.rs"))
            if path.is_file(): crates.append(CargoCrate(f"crate:{name}:bin:{index}", str(binary.get("name") or name).replace("-", "_"), "BIN", str(path.resolve()), name))
        dependency_sections = [data.get("dependencies") or {}, data.get("dev-dependencies") or {}, data.get("build-dependencies") or {}]
        dependencies = [self._dependency(dep_name, value, manifest.parent, workspace_names)
                        for section in dependency_sections for dep_name, value in section.items()]
        build = package.get("build", "build.rs")
        build_path = manifest.parent / str(build) if build is not False else None
        return CargoPackage(name, version, str(manifest.resolve()), crates, dependencies,
                            dict(data.get("features") or {}), str(build_path.resolve()) if build_path and build_path.is_file() else None,
                            bool(lib.get("proc-macro")))

    def discover_workspace(self, entry: Path) -> CargoWorkspace:
        manifest = self.find_manifest(entry); data = self._load_toml(manifest)
        workspace_root = manifest.parent
        workspace = data.get("workspace") if isinstance(data.get("workspace"), dict) else {}
        member_patterns = list(workspace.get("members") or [])
        manifests: list[Path] = [manifest] if isinstance(data.get("package"), dict) else []
        for pattern in member_patterns:
            for candidate in workspace_root.glob(str(pattern)):
                child = candidate / "Cargo.toml" if candidate.is_dir() else candidate
                if child.is_file() and child.resolve() not in {item.resolve() for item in manifests}: manifests.append(child.resolve())
        names = set()
        for item in manifests:
            package = self._load_toml(item).get("package") or {}
            if package.get("name"): names.add(str(package["name"]))
        packages = [package for item in manifests if (package := self._package(item, names)) is not None]
        # Follow local path dependencies only; registry/git sources stay external.
        queue = [Path(dep.path) / "Cargo.toml" for package in packages for dep in package.dependencies if dep.path]
        known = {Path(package.manifest_path).resolve() for package in packages}
        while queue:
            child = queue.pop(0).resolve()
            if child in known or not child.is_file(): continue
            known.add(child); package = self._package(child, names)
            if package:
                packages.append(package)
                queue.extend(Path(dep.path) / "Cargo.toml" for dep in package.dependencies if dep.path)
        lock = workspace_root / "Cargo.lock"
        return CargoWorkspace(str(workspace_root.resolve()), str(manifest.resolve()), sha256(manifest.read_bytes()).hexdigest(),
            sha256(lock.read_bytes()).hexdigest() if lock.is_file() else None,
            [str(item.resolve()) for item in manifests], packages,
            list(workspace.get("default-members") or []), "HOST_DEFAULT_UNRESOLVED")

    @staticmethod
    def _module_name(crate: str, path: Path, crate_root: Path) -> str:
        if path.resolve() == crate_root.resolve(): return crate
        src = crate_root.parent; relative = path.resolve().relative_to(src.resolve()).with_suffix("")
        parts = list(relative.parts)
        if parts and parts[-1] == "mod": parts.pop()
        return "::".join([crate, *parts])

    @staticmethod
    def _module_path(info: RustModuleInfo, name: str) -> list[Path]:
        directory = info.source.path.parent
        if info.source.path.name not in {"main.rs", "lib.rs", "mod.rs"}:
            directory = directory / info.source.path.stem
        return [directory / f"{name}.rs", directory / name / "mod.rs"]

    def _canonical_use(self, info: RustModuleInfo, path: str) -> str:
        path = path.strip().lstrip("::")
        if path.startswith("crate::"): return f"{info.crate_name}::{path[7:]}"
        if path.startswith("self::"): return f"{info.node.name}::{path[6:]}"
        if path.startswith("super::"):
            module = info.node.name.split("::")[:-1]
            while path.startswith("super::"):
                if len(module) > 1: module.pop()
                path = path[7:]
            return "::".join([*module, path])
        head = path.split("::", 1)[0]
        if any(name == head or name.startswith(f"{info.crate_name}::{head}") for name in self.module_info):
            return f"{info.crate_name}::{path}"
        return path

    def _source_span(self, info: RustModuleInfo, line: int, end_line: int | None = None) -> dict[str, Any]:
        return {"file": str(info.source.path), "begin_line": line, "begin_column": 1,
                "end_line": end_line or line, "end_column": 1}

    def resolve(self, entry_source: Path, project_root: Path | None = None) -> ProjectDependencyGraph:
        entry_source = entry_source.resolve(); self.workspace = self.discover_workspace(entry_source)
        self.root = Path(self.workspace.root); self.module_info = {}; self.symbol_items = {}; self._python_exports = {}
        graph = ProjectDependencyGraph(metadata={"cargo_workspace": _serial(self.workspace),
            "dependency_kinds": [item.value for item in CargoDependencyKind]})
        roots: list[tuple[CargoPackage, CargoCrate]] = []
        if entry_source.name == "Cargo.toml":
            roots = [(package, crate) for package in self.workspace.packages for crate in package.crates]
        else:
            containing = [package for package in self.workspace.packages
                          if entry_source.is_relative_to(Path(package.manifest_path).parent)]
            exact = [(package, crate) for package in containing for crate in package.crates
                     if Path(crate.root_source).resolve() == entry_source]
            roots = exact or [(package, next((crate for crate in package.crates if crate.crate_type == "LIB"), package.crates[0]))
                              for package in containing if package.crates]
        if not roots:
            roots = [(package, crate) for package in self.workspace.packages for crate in package.crates]
        selected_packages = {package.name for package, _ in roots}; changed = True
        while changed:
            changed = False
            for package in self.workspace.packages:
                if package.name not in selected_packages: continue
                for dependency in package.dependencies:
                    candidate = next((value for value in self.workspace.packages if value.name == dependency.name), None)
                    if candidate and candidate.name not in selected_packages and dependency.kind in {
                            CargoDependencyKind.LOCAL_PATH_CRATE.value, CargoDependencyKind.WORKSPACE_CRATE.value}:
                        selected_packages.add(candidate.name); changed = True
        for package in self.workspace.packages:
            if package.name in selected_packages and not any(known.name == package.name for known, _ in roots):
                roots.extend((package, crate) for crate in package.crates)
        queue: list[tuple[CargoPackage, CargoCrate, Path]] = [(package, crate, Path(crate.root_source)) for package, crate in roots]
        visited_paths: set[Path] = set()
        crate_roots = {crate.name: Path(crate.root_source) for package in self.workspace.packages for crate in package.crates}
        while queue:
            package, crate, path = queue.pop(0); path = path.resolve()
            if path in visited_paths: continue
            visited_paths.add(path)
            if not path.is_file():
                graph.diagnostics.append({"code": "RUST_MODULE_UNRESOLVED", "path": str(path)}); continue
            source = self.frontend.parse(path); name = self._module_name(crate.name, path, Path(crate.root_source))
            node = ModuleNode(f"module:{name}", name, str(path), language="rust",
                              source_hash=sha256(source.text.encode()).hexdigest())
            info = RustModuleInfo(node, source, crate.name); self.module_info[name] = info; graph.modules.append(node)
            for declaration in source.modules:
                if declaration.inline:
                    graph.diagnostics.append({"code": "INLINE_MODULE_SOURCE_LOWERING_UNRESOLVED", "module": f"{name}::{declaration.name}",
                                              "source_span": self._source_span(info, declaration.begin_line)})
                    continue
                candidates = [candidate.resolve() for candidate in self._module_path(info, declaration.name) if candidate.is_file()]
                if len(candidates) != 1:
                    graph.diagnostics.append({"code": "RUST_MODULE_AMBIGUOUS" if len(candidates) > 1 else "RUST_MODULE_UNRESOLVED",
                                              "module": declaration.name, "candidates": [str(item) for item in candidates],
                                              "source_span": self._source_span(info, declaration.begin_line)})
                    continue
                target_name = self._module_name(crate.name, candidates[0], Path(crate.root_source))
                graph.edges.append(ImportEdge(node.module_id, f"module:{target_name}", canonical_name=target_name,
                    provenance={**self._source_span(info, declaration.begin_line), "dependency_kind": CargoDependencyKind.LOCAL_MODULE.value}))
                queue.append((package, crate, candidates[0]))
            self._index_symbols(info, graph)
        # Local path/workspace crates are source-resolved; all other crates remain external.
        local_names = {package.name for package in self.workspace.packages}
        for package in self.workspace.packages:
            source_module = next((item.node.module_id for item in self.module_info.values() if item.crate_name == package.name.replace("-", "_")), f"crate:{package.name}")
            for dependency in package.dependencies:
                if dependency.kind in {CargoDependencyKind.LOCAL_PATH_CRATE.value, CargoDependencyKind.WORKSPACE_CRATE.value} and dependency.name in local_names:
                    target = next((item.node.module_id for item in self.module_info.values() if item.crate_name == dependency.name.replace("-", "_")), f"crate:{dependency.name}")
                    graph.edges.append(DependencyEdge(source_module, target, "CARGO_DEPENDENCY", canonical_name=dependency.name,
                                                      provenance={"dependency_kind": dependency.kind, "manifest": package.manifest_path}))
                else:
                    if dependency.name not in graph.external_modules: graph.external_modules.append(dependency.name)
                    graph.edges.append(DependencyEdge(source_module, f"external-crate:{dependency.name}", "CARGO_DEPENDENCY",
                        canonical_name=dependency.name, provenance={"dependency_kind": dependency.kind, "version": dependency.version,
                                                                   "source_inspected": False}))
            if package.build_script:
                graph.diagnostics.append({"code": "BUILD_SCRIPT_PRESENT", "package": package.name, "path": package.build_script})
                graph.diagnostics.append({"code": "BUILD_GENERATED_SOURCE_UNRESOLVED", "package": package.name})
            if package.proc_macro:
                graph.diagnostics.append({"code": "PROC_MACRO_SEMANTICS_UNRESOLVED", "package": package.name})
        self._resolve_uses(graph)
        self._semantic_edges(graph)
        self._diagnostics(graph)
        self._detect_cycles(graph)
        return graph

    def _index_symbols(self, info: RustModuleInfo, graph: ProjectDependencyGraph) -> None:
        for item in info.source.items:
            canonical = f"{info.node.name}::{item.owner}::{item.name}" if item.owner else f"{info.node.name}::{item.name}"
            symbol_id = f"symbol:{canonical}:{item.begin_line}"
            kind = "METHOD" if item.owner and item.kind == "FUNCTION" else item.kind
            symbol = SymbolNode(symbol_id, info.node.name, item.name, kind, canonical, item.public,
                                self._source_span(info, item.begin_line, item.end_line), "rust")
            graph.symbols.append(symbol); info.symbols[item.name] = item; self.symbol_items[canonical] = (info, item)
            graph.edges.append(DefinitionEdge(info.node.module_id, symbol_id,
                provenance=self._source_span(info, item.begin_line, item.end_line)))
            if item.kind == "FUNCTION" and any("pyfunction" in attribute for attribute in item.attributes):
                export_name = item.name
                for attribute in item.attributes:
                    match = re.search(r"name\s*=\s*\"([^\"]+)\"", attribute)
                    if match: export_name = match.group(1)
                self._python_exports[canonical] = export_name

    def _resolve_uses(self, graph: ProjectDependencyGraph) -> None:
        for info in self.module_info.values():
            for use in info.source.uses:
                canonical = self._canonical_use(info, use.path)
                alias = use.alias or use.path.rsplit("::", 1)[-1]
                info.aliases[alias] = canonical
                target_symbol = next((symbol for symbol in graph.symbols if symbol.canonical_name == canonical), None)
                target_module = next((module for module in graph.modules
                                      if canonical == module.name or canonical.startswith(module.name + "::")), None)
                target = target_symbol.symbol_id if target_symbol else target_module.module_id if target_module else f"external:{canonical}"
                edge_cls = ReExportEdge if use.public else ImportEdge
                graph.edges.append(edge_cls(info.node.module_id, target, alias=alias, canonical_name=canonical,
                                            provenance=self._source_span(info, use.begin_line)))
        # Consumers of a crate-root re-export resolve to the actual canonical symbol.
        root_exports = {alias: canonical for info in self.module_info.values()
                        if "::" not in info.node.name for alias, canonical in info.aliases.items()}
        for info in self.module_info.values():
            for alias, canonical in list(info.aliases.items()):
                crate, _, name = canonical.rpartition("::")
                if crate and "::" not in crate and name in root_exports:
                    info.aliases[alias] = root_exports[name]

    def canonical_reference(self, info: RustModuleInfo, name: str) -> str:
        name = name.strip()
        if name in info.aliases: return info.aliases[name]
        if "::" in name:
            return self._canonical_use(info, name)
        local = f"{info.node.name}::{name}"
        if local in self.symbol_items: return local
        root = f"{info.crate_name}::{name}"
        root_info = self.module_info.get(info.crate_name)
        if root_info and name in root_info.aliases: return root_info.aliases[name]
        return root

    def _semantic_edges(self, graph: ProjectDependencyGraph) -> None:
        symbols = {symbol.canonical_name: symbol for symbol in graph.symbols}
        keywords = {"if", "while", "for", "loop", "match", "return", "Some", "Ok", "Err", "None"}
        for canonical, (info, item) in self.symbol_items.items():
            if not item.body: continue
            owner = symbols.get(canonical)
            if owner is None: continue
            for match in re.finditer(r"(?<![.!])\b([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*\(", item.body):
                name = match.group(1)
                if name in keywords: continue
                target_name = self.canonical_reference(info, name)
                target = symbols.get(target_name)
                graph.edges.append(CallEdge(owner.symbol_id, target.symbol_id if target else f"external:{target_name}",
                    alias=name, canonical_name=target_name,
                    provenance={"file": str(info.source.path), "begin_line": item.begin_line + _line(item.body, match.start()) - 1}))
            for name in set(re.findall(r"\b[A-Z][A-Z0-9_]+\b", item.body)):
                target_name = self.canonical_reference(info, name); target = symbols.get(target_name)
                if target:
                    graph.edges.append(ValueDependencyEdge(owner.symbol_id, target.symbol_id, alias=name,
                        canonical_name=target_name, provenance=self._source_span(info, item.begin_line)))

    def _diagnostics(self, graph: ProjectDependencyGraph) -> None:
        for info in self.module_info.values():
            for macro in info.source.macros:
                if macro["status"] == "MACRO_EXPANSION_UNRESOLVED":
                    code = "PROC_MACRO_SEMANTICS_UNRESOLVED" if macro["kind"] == "PROCEDURAL_OR_EXTERNAL" else "MACRO_EXPANSION_UNRESOLVED"
                    graph.diagnostics.append({"code": code, "macro": macro["name"],
                                              "source_span": self._source_span(info, macro["begin_line"])})
            for unsafe in info.source.unsafe_blocks:
                graph.diagnostics.append({**unsafe, "code": "UNSAFE_PROOF_OBLIGATION",
                                          "unsafe_construct": unsafe["code"], "status": "UNRESOLVED",
                                          "source_span": self._source_span(info, unsafe["begin_line"])})
            for cfg in info.source.cfg_attributes:
                graph.diagnostics.append({"code": "RUST_CFG_CONFIGURATION_RECORDED", "configuration": cfg,
                                          "status": "CONFIGURATION_VARIANTS_NOT_MERGED", "file": str(info.source.path)})
            if "?" in info.source.text:
                graph.diagnostics.append({"code": "RUST_RESULT_PATH_UNRESOLVED", "file": str(info.source.path)})
            if re.search(r"\b(if\s+let|Some\s*\(|None\b)", info.source.text):
                graph.diagnostics.append({"code": "RUST_OPTION_PATH_UNRESOLVED", "file": str(info.source.path)})

    def _detect_cycles(self, graph: ProjectDependencyGraph) -> None:
        adjacency: dict[str, list[str]] = {}
        for edge in graph.edges:
            if edge.kind in {"IMPORT", "RE_EXPORT"} and edge.target.startswith("module:"):
                adjacency.setdefault(edge.source, []).append(edge.target)
            elif edge.kind == "CALL" and edge.source.startswith("symbol:") and edge.target.startswith("symbol:"):
                adjacency.setdefault(edge.source, []).append(edge.target)
        active: list[str] = []; done: set[str] = set(); cycles: set[tuple[str, ...]] = set()
        def visit(node: str) -> None:
            if node in active:
                cycles.add(tuple(active[active.index(node):] + [node])); return
            if node in done: return
            active.append(node)
            for target in adjacency.get(node, []): visit(target)
            active.pop(); done.add(node)
        for node in adjacency: visit(node)
        for cycle in sorted(cycles):
            value = [item.removeprefix("module:").removeprefix("symbol:") for item in cycle]
            graph.cycles.append(value)
            module_cycle = all(item.startswith("module:") for item in cycle)
            graph.diagnostics.append({"code": "RUST_MODULE_CYCLE_DETECTED" if module_cycle else
                                      "RUST_CALL_CYCLE_DETECTED", "cycle": value})
            if module_cycle:
                graph.diagnostics.append({"code": "CROSS_FILE_SEMANTICS_UNRESOLVED", "cycle": value})

    def is_python_export(self, canonical: str) -> bool:
        return canonical in self._python_exports

    def python_export_name(self, canonical: str) -> str:
        return self._python_exports[canonical]


class _RustLowerer:
    """Backward symbolic evaluator for the supported Rust numeric subset."""

    def __init__(self, resolver: RustDependencyResolver, graph: ProjectDependencyGraph):
        self.resolver, self.graph = resolver, graph
        self.contracts = RustLibraryContractRegistry()
        self.dependencies: set[str] = set()
        self.locations: list[dict[str, Any]] = []
        self.library_contracts: list[dict[str, Any]] = []
        self.execution_operations: list[dict[str, Any]] = []
        self.diagnostics: list[dict[str, Any]] = []
        self.stack: set[str] = set()

    @staticmethod
    def _params(item: RustItem) -> list[str]:
        match = re.search(r"\((.*)\)", item.signature, re.S)
        if not match: return []
        result = []
        for value in _split_top_level(match.group(1), ","):
            name = value.split(":", 1)[0].strip().removeprefix("mut ").strip()
            if name and name not in {"self", "&self", "&mut self"}: result.append(name)
        return result

    @staticmethod
    def _normalize_simple(expression: str) -> str:
        value = expression.strip()
        value = re.sub(r"\bas\s+(?:f32|f64|i\d+|u\d+|usize|isize)\b", "", value)
        value = re.sub(r"(?<=\d)_(?=\d)", "", value)
        value = re.sub(r"(\d+(?:\.\d+)?)(?:f32|f64|i\d+|u\d+|usize|isize)\b", r"\1", value)
        value = value.replace("::", ".").replace("&&", " and ").replace("||", " or ")
        value = re.sub(r"\btrue\b", "True", value); value = re.sub(r"\bfalse\b", "False", value)
        value = re.sub(r"(?<![\w)])&(?:mut\s+)?", "", value)
        value = re.sub(r"(?<![\w)])\*([A-Za-z_]\w*)", r"\1", value)
        return value

    def _python_expr(self, node: ast.AST, info: RustModuleInfo,
                     env: dict[str, Any]) -> dict[str, Any]:
        if isinstance(node, ast.Constant): return {"op": "Constant", "value": node.value}
        if isinstance(node, ast.Name):
            if node.id in env:
                value = env[node.id]
                if isinstance(value, str): return self.expr(value, info, env)
                return json.loads(json.dumps(value, default=str))
            canonical = self.resolver.canonical_reference(info, node.id)
            if canonical in self.resolver.symbol_items:
                definition_info, item = self.resolver.symbol_items[canonical]
                if item.kind in {"CONST", "STATIC"} and item.body is not None:
                    self._record(canonical, definition_info, item)
                    return self.expr(item.body, definition_info, {})
            self.dependencies.add(canonical)
            return {"op": "FreeVariable", "name": canonical, "local_name": node.id,
                    "canonical_name": canonical}
        if isinstance(node, ast.BinOp):
            operations = {ast.Add: "Add", ast.Sub: "Subtract", ast.Mult: "Multiply", ast.Div: "Divide",
                          ast.Mod: "Modulo", ast.Pow: "Power", ast.MatMult: "TensorContraction"}
            return {"op": operations.get(type(node.op), "OpaqueOperator"),
                    "args": [self._python_expr(node.left, info, env), self._python_expr(node.right, info, env)]}
        if isinstance(node, ast.UnaryOp):
            return {"op": "Negate" if isinstance(node.op, ast.USub) else "Not" if isinstance(node.op, ast.Not) else "UnaryOperator",
                    "args": [self._python_expr(node.operand, info, env)]}
        if isinstance(node, ast.Compare):
            return {"op": "Compare", "comparison": type(node.ops[0]).__name__,
                    "args": [self._python_expr(node.left, info, env), self._python_expr(node.comparators[0], info, env)]}
        if isinstance(node, ast.BoolOp):
            return {"op": "BooleanAnd" if isinstance(node.op, ast.And) else "BooleanOr",
                    "args": [self._python_expr(value, info, env) for value in node.values]}
        if isinstance(node, ast.Subscript):
            return {"op": "IndexedValue", "base": self._python_expr(node.value, info, env),
                    "indices": [self._python_expr(node.slice, info, env)],
                    "shape_constraints": [{"kind": "index_within_extent"}]}
        if isinstance(node, (ast.Tuple, ast.List)):
            return {"op": "Tuple", "args": [self._python_expr(value, info, env) for value in node.elts]}
        if isinstance(node, ast.Attribute):
            name = ast.unparse(node).replace(".", "::")
            return {"op": "FreeVariable", "name": self.resolver.canonical_reference(info, name)}
        if isinstance(node, ast.Call):
            return self._call_ast(node, info, env)
        return self.opaque(type(node).__name__, [], info)

    def _call_ast(self, node: ast.Call, info: RustModuleInfo, env: dict[str, Any]) -> dict[str, Any]:
        name = ast.unparse(node.func).replace(".", "::")
        args = [self._python_expr(value, info, env) for value in node.args]
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"powi", "powf", "pow"}:
            return {"op": "Power", "args": [self._python_expr(node.func.value, info, env), *args],
                    "api": f"rust::{node.func.attr}"}
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"sqrt", "abs", "exp", "ln"}:
            return {"op": "FunctionCall", "name": {"ln": "log"}.get(node.func.attr, node.func.attr),
                    "args": [self._python_expr(node.func.value, info, env), *args], "api": f"rust::{node.func.attr}"}
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"sum", "mean", "mapv", "dot", "shape", "sum_axis", "mean_axis", "slice"}:
            method = node.func.attr; receiver = self._python_expr(node.func.value, info, env)
            crate = "ndarray" if any(package.name == "ndarray" for package in (self.resolver.workspace.packages if self.resolver.workspace else [])) or "ndarray" in self.graph.external_modules else ""
            contract = self.contracts.resolve(crate, f"ArrayBase::{method}") if crate else None
            if contract:
                self.library_contracts.append(contract.to_dict())
                operation = contract.mathematical_operation
                if operation in {"FiniteSum", "Mean"}:
                    return {"op": "Reduce", "reduction": "Add" if operation == "FiniteSum" else "Mean",
                            "input": receiver, "args": args, "api": f"ndarray::ArrayBase::{method}",
                            "shape_constraints": [{"kind": "ndarray_axis_extent"}]}
                return {"op": operation, "args": [receiver, *args], "api": f"ndarray::ArrayBase::{method}",
                        "shape_constraints": [{"kind": "ndarray_shape_contract"}]}
            return self.opaque(f"RustMethod::{method}", [receiver, *args], info,
                               {"status": "UNKNOWN_CRATE_API_NOT_GUESSED"})
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"norm", "norm_l2"}:
            receiver = self._python_expr(node.func.value, info, env); method = node.func.attr
            available = set(self.graph.external_modules)
            crate = "nalgebra" if "nalgebra" in available else "faer" if "faer" in available else ""
            symbol = "Matrix::norm" if crate == "nalgebra" else "Mat::norm_l2"
            contract = self.contracts.resolve(crate, symbol) if crate else None
            if contract:
                self.library_contracts.append(contract.to_dict())
                return {"op": "Norm", "args": [receiver, *args], "api": f"{crate}::{symbol}"}
            return self.opaque(f"RustMethod::{method}", [receiver, *args], info,
                               {"status": "UNKNOWN_CRATE_API_NOT_GUESSED"})
        canonical = self.resolver.canonical_reference(info, name)
        if canonical in self.resolver.symbol_items:
            return self.function(canonical, args)
        crate = name.split("::", 1)[0]
        return self.opaque(canonical, args, info,
                           {"kind": "external_crate", "crate": crate,
                            "resolution_status": "EXTERNAL_SOURCE_NOT_INSPECTED"})

    def opaque(self, name: str, args: list[dict[str, Any]], info: RustModuleInfo,
               provenance: dict[str, Any] | None = None) -> dict[str, Any]:
        self.diagnostics.append({"code": "OPAQUE_RUST_CALL", "callable": name,
                                 "module": info.node.name})
        return {"op": "OpaqueNumericCall", "name": name, "args": args, "language": "rust",
                "shape_constraints": [{"kind": "opaque_result_shape",
                                       "relation": "shape(result) constrained by Rust public contract"}],
                "provenance": provenance or {}}

    def _record(self, canonical: str, info: RustModuleInfo, item: RustItem) -> None:
        self.dependencies.add(canonical)
        span = {"file": str(info.source.path), "begin_line": item.begin_line, "begin_column": 1,
                "end_line": item.end_line, "end_column": 1}
        if span not in self.locations: self.locations.append(span)

    @staticmethod
    def _closure(value: str) -> tuple[list[str], str] | None:
        value = value.strip()
        match = re.match(r"(?:move\s+)?\|([^|]*)\|\s*(.*)", value, re.S)
        if not match: return None
        return [item.strip() for item in match.group(1).split(",") if item.strip()], match.group(2).strip()

    @staticmethod
    def _chain(expression: str) -> tuple[str, list[tuple[str, str]]] | None:
        match = re.search(r"\.(iter|iter_mut|into_iter|par_iter|par_iter_mut|into_par_iter)\s*\(", expression)
        if not match: return None
        base = expression[:match.start()].strip(); steps: list[tuple[str, str]] = []
        position = match.start()
        while position < len(expression):
            method = re.match(r"\.([A-Za-z_]\w*)\s*\(", expression[position:])
            if not method: break
            name = method.group(1); open_paren = position + method.end() - 1
            close = _matching(expression, open_paren, "(", ")")
            if close < 0: return None
            steps.append((name, expression[open_paren + 1:close])); position = close + 1
            while position < len(expression) and expression[position].isspace(): position += 1
        return base, steps

    def _iterator(self, expression: str, info: RustModuleInfo, env: dict[str, Any]) -> dict[str, Any] | None:
        chain = self._chain(expression)
        if not chain: return None
        base, steps = chain; current = self.expr(base, info, env); bound = "item"; parallel = False
        for method, argument in steps:
            if method in {"iter", "iter_mut", "into_iter", "par_iter", "par_iter_mut", "into_par_iter"}:
                parallel = parallel or method.startswith("par_") or "_par_" in method
                current = {"op": "Iterator", "kind": method, "input": current}
                if parallel:
                    self.execution_operations.append({"operation": method, "policy": "PARALLEL_REORDERABLE",
                                                      "backend": "rayon", "reduction_order": "UNSPECIFIED"})
            elif method in {"map", "filter"}:
                closure = self._closure(argument)
                if not closure:
                    self.diagnostics.append({"code": "RUST_CLOSURE_UNRESOLVED", "expression": argument});
                    return self.opaque(f"Iterator::{method}", [current], info)
                names, body = closure; bound = names[-1] if names else "item"
                local = dict(env); local[bound] = {"op": "BoundVariable", "name": bound}
                lowered = self.expr(body, info, local)
                current = ({"op": "Map", "bound_index": bound, "iterable": current, "body": lowered}
                           if method == "map" else {"op": "Filter", "bound_index": bound,
                                                    "iterable": current, "predicate": lowered})
            elif method == "zip":
                current = {"op": "Zip", "args": [current, self.expr(argument, info, env)],
                           "shape_constraints": [{"kind": "zip_equal_or_shortest_extent"}]}
            elif method == "enumerate":
                current = {"op": "Enumerate", "iterable": current, "bound_index": bound}
            elif method in {"sum", "product"}:
                op = "FiniteSum" if method == "sum" else "FiniteProduct"
                contract = self.contracts.resolve("rayon" if parallel else "std",
                    f"ParallelIterator::{method}" if parallel else f"Iterator::{method}")
                if contract: self.library_contracts.append(contract.to_dict())
                current = {"op": op, "iterable": current, "bound_index": bound,
                           "body": current.get("body", {"op": "BoundVariable", "name": bound}),
                           "reduction_order": "unspecified_parallel" if parallel else "left_to_right",
                           "execution_policy": "PARALLEL_REORDERABLE" if parallel else "SEQUENTIAL"}
                if parallel:
                    self.execution_operations.append({"operation": method, "policy": "PARALLEL_REORDERABLE",
                        "reduction_order": "UNSPECIFIED", "floating_point_order_difference": True})
            elif method in {"fold", "reduce"}:
                parts = _split_top_level(argument, ","); initial = self.expr(parts[0], info, env) if parts else None
                closure = self._closure(",".join(parts[1:])) if len(parts) > 1 else None
                current = {"op": "FoldLeft" if method == "fold" else "TransformReduce", "iterable": current,
                           "initial_value": initial, "operation": self.expr(closure[1], info,
                                {**env, **{name: {"op": "BoundVariable", "name": name} for name in closure[0]}}) if closure else None,
                           "reduction_order": "unspecified_parallel" if parallel else "left_to_right"}
            elif method == "collect": current = {"op": "Collect", "input": current}
            else:
                # ndarray/nalgebra/faer method candidates use crate-specific contracts only when provenance is known.
                current = {"op": "OpaqueNumericCall", "name": f"RustMethod::{method}", "args": [current],
                           "shape_constraints": [{"kind": "method_result_shape_constraint"}]}
                self.diagnostics.append({"code": "UNKNOWN_RUST_METHOD", "method": method})
        return current

    def expr(self, expression: str, info: RustModuleInfo, env: dict[str, Any]) -> dict[str, Any]:
        expression = expression.strip().rstrip(";")
        if expression.endswith("?"):
            self.diagnostics.append({"code": "RUST_RESULT_PATH_UNRESOLVED", "expression": expression})
            return {"op": "TryPropagation", "value": self.expr(expression[:-1], info, env),
                    "error_path": {"op": "OpaqueControlPath", "status": "RUST_RESULT_PATH_UNRESOLVED"}}
        iterator = self._iterator(expression, info, env)
        if iterator is not None: return iterator
        if expression.startswith("if "):
            match = re.match(r"if\s+(.+?)\s*\{", expression, re.S)
            if match:
                open_brace = expression.find("{", match.start()); close = _matching(expression, open_brace)
                if close >= 0:
                    rest = expression[close + 1:].strip(); else_value = None
                    if rest.startswith("else"):
                        else_open = rest.find("{"); else_close = _matching(rest, else_open) if else_open >= 0 else -1
                        if else_close >= 0: else_value = rest[else_open + 1:else_close]
                    return {"op": "IfThenElse", "condition": self.expr(match.group(1), info, env),
                            "then": self.expr(expression[open_brace + 1:close], info, dict(env)),
                            "else": self.expr(else_value, info, dict(env)) if else_value is not None else
                                    {"op": "OpaqueControlPath", "status": "RUST_OPTION_PATH_UNRESOLVED"}}
        if expression.startswith("match "):
            open_brace = expression.find("{"); close = _matching(expression, open_brace) if open_brace >= 0 else -1
            if close >= 0:
                subject = expression[6:open_brace].strip(); arms = []
                for arm in _split_top_level(expression[open_brace + 1:close], ","):
                    if "=>" not in arm: continue
                    pattern, value = arm.split("=>", 1); arms.append({"pattern": pattern.strip(), "value": self.expr(value, info, dict(env))})
                if any(arm["pattern"].startswith(("Some", "None")) for arm in arms):
                    self.diagnostics.append({"code": "RUST_OPTION_PATH_UNRESOLVED", "expression": expression})
                if any(arm["pattern"].startswith(("Ok", "Err")) for arm in arms):
                    self.diagnostics.append({"code": "RUST_RESULT_PATH_UNRESOLVED", "expression": expression})
                return {"op": "Match", "input": self.expr(subject, info, env), "arms": arms,
                        "all_paths_preserved": True}
        macro = re.match(r"([A-Za-z_]\w*)!\s*", expression)
        if macro:
            if macro.group(1) == "vec":
                open_bracket = expression.find("["); close_bracket = _matching(expression, open_bracket, "[", "]") if open_bracket >= 0 else -1
                if close_bracket >= 0:
                    return {"op": "Collection", "kind": "Vec",
                            "args": [self.expr(value, info, env) for value in _split_top_level(expression[open_bracket + 1:close_bracket], ",") if value.strip()]}
            return {"op": "OpaqueMacroExpansion", "name": macro.group(1),
                    "status": "MACRO_EXPANSION_UNRESOLVED"}
        try:
            parsed = ast.parse(self._normalize_simple(expression), mode="eval")
            return self._python_expr(parsed.body, info, env)
        except SyntaxError:
            return self.opaque("RustExpression", [], info, {"source": expression})

    @staticmethod
    def _statements(body: str) -> list[str]:
        return [item.strip() for item in _split_top_level(body, ";") if item.strip()]

    def function(self, canonical: str, arguments: list[dict[str, Any]], target: str | None = None,
                 definition_line: int | None = None) -> dict[str, Any]:
        if canonical not in self.resolver.symbol_items:
            info = next(iter(self.resolver.module_info.values()))
            return self.opaque(canonical, arguments, info)
        info, item = self.resolver.symbol_items[canonical]; self._record(canonical, info, item)
        if canonical in self.stack: return self.opaque(canonical, arguments, info, {"status": "RECURSION_UNRESOLVED"})
        self.stack.add(canonical)
        try:
            env: dict[str, Any] = {}
            for index, name in enumerate(self._params(item)):
                env[name] = arguments[index] if index < len(arguments) else {"op": "FreeVariable", "name": f"{canonical}::{name}"}
                self.dependencies.add(f"{canonical}::{name}")
            selected: dict[str, tuple[str | dict[str, Any], int]] = {}
            returned: str | None = None
            control_effects: list[dict[str, Any]] = []
            for offset, statement in enumerate(self._statements(item.body or "")):
                line = item.begin_line + (item.body or "").count("\n", 0, (item.body or "").find(statement))
                let = re.match(r"let\s+(?P<mut>mut\s+)?(?P<name>[A-Za-z_]\w*)(?:\s*:\s*[^=]+)?\s*=\s*(?P<value>.*)", statement, re.S)
                if let:
                    selected[let.group("name")] = (let.group("value").strip(), line); env[let.group("name")] = let.group("value").strip(); continue
                aug = re.match(r"([A-Za-z_]\w*)\s*([+\-*/%])=\s*(.*)", statement, re.S)
                if aug:
                    name, operator, value = aug.groups(); previous = env.get(name, {"op": "FreeVariable", "name": name})
                    operation = {"+": "Add", "-": "Subtract", "*": "Multiply", "/": "Divide", "%": "Modulo"}[operator]
                    env[name] = {"op": operation, "args": [self.expr(previous, info, env) if isinstance(previous, str) else previous,
                                                            self.expr(value, info, env)], "mutation": "final_reaching_definition"}
                    selected[name] = (env[name], line); continue
                indexed = re.match(r"([A-Za-z_]\w*)\s*\[([^]]+)\]\s*=\s*(.*)", statement, re.S)
                if indexed:
                    name, index_value, value = indexed.groups()
                    env[name] = {"op": "IndexedStateUpdate", "previous_state": env.get(name, {"op": "FreeVariable", "name": name}),
                                 "indices": [self.expr(index_value, info, env)], "value": self.expr(value, info, env),
                                 "mutation": "indexed_assignment"}; selected[name] = (env[name], line); continue
                push = re.match(r"([A-Za-z_]\w*)\.push\s*\((.*)\)", statement, re.S)
                if push:
                    name, value = push.groups(); env[name] = {"op": "SequenceAppend", "previous_state": env.get(name),
                                                              "value": self.expr(value, info, env), "mutation": "push"}
                    selected[name] = (env[name], line); continue
                if statement.startswith("return "): returned = statement[7:].strip(); break
                if statement.startswith(("for ", "while ", "loop ")):
                    self.diagnostics.append({"code": "RUST_LOOP_SEMANTICS_CONSERVATIVE", "statement": statement[:40]})
                    kind = "For" if statement.startswith("for ") else "While" if statement.startswith("while ") else "Loop"
                    control_effects.append({"op": kind, "body": {"op": "OpaqueControlPath",
                        "status": "RUST_LOOP_SEMANTICS_CONSERVATIVE", "source": statement}})
                    returned = None
                    continue
                returned = statement
            if target:
                matches = [(value, line) for name, (value, line) in selected.items() if name == target and
                           (definition_line is None or line == definition_line)]
                if not matches: raise AuditError(f"RUST_VARIABLE_TARGET_NOT_FOUND: {target}")
                value, line = matches[-1]; self.dependencies.add(f"{canonical}::{target}:{line}")
                return self.expr(value, info, env) if isinstance(value, str) else value
            if returned is None:
                return {"op": "OpaqueNumericCall", "name": canonical, "args": arguments,
                        "shape_constraints": [{"kind": "unit_or_unresolved_return"}]}
            result = self.expr(returned, info, env)
            if control_effects:
                result = {"op": "ControlFlowSequence", "effects": control_effects, "result": result,
                          "all_loop_effects_preserved": True}
            return result
        finally:
            self.stack.remove(canonical)


class RustProjectAnalyzer:
    """Lower a statically discovered Cargo project into common audit objects."""

    def __init__(self, entry_source: str | Path, *, project_root: str | Path | None = None,
                 frontend: RustFrontend | None = None, resolver: DependencyResolver | None = None,
                 pre_resolved_graph: ProjectDependencyGraph | None = None):
        self.entry_source = Path(entry_source).resolve()
        self.project_root = Path(project_root).resolve() if project_root else None
        self.frontend = frontend or RustFrontend()
        self.resolver = resolver if isinstance(resolver, RustDependencyResolver) else RustDependencyResolver(self.frontend)
        self.graph = pre_resolved_graph
        self.contracts = RustLibraryContractRegistry()

    @staticmethod
    def _return_text(item: RustItem) -> str | None:
        statements = _RustLowerer._statements(item.body or "")
        for statement in statements:
            if statement.startswith("return "): return statement[7:].strip()
        if (item.body or "").rstrip().endswith(";"): return None
        if statements:
            tail = statements[-1]
            if not re.match(r"(?:let\b|for\b|while\b|loop\b|[A-Za-z_]\w*\s*[+\-*/%]?=)", tail): return tail
        return None

    def _auto_roots(self) -> list[tuple[str, RustItem, list[OutputTarget]]]:
        incoming = {edge.target for edge in self.graph.edges if edge.kind == "CALL"}
        roots = []
        for canonical, (info, item) in self.resolver.symbol_items.items():
            if item.kind != "FUNCTION": continue
            symbol = next((symbol for symbol in self.graph.symbols if symbol.canonical_name == canonical), None)
            python_export = self.resolver.is_python_export(canonical)
            is_root = item.name == "main" or python_export or (item.public and symbol and symbol.symbol_id not in incoming)
            returned = self._return_text(item)
            if not is_root or returned is None: continue
            targets = []
            tuple_values = _split_top_level(returned[1:-1], ",") if returned.startswith("(") and returned.endswith(")") else []
            if len(tuple_values) > 1:
                for index, value in enumerate(tuple_values):
                    name = value.strip() if re.fullmatch(r"[A-Za-z_]\w*", value.strip()) else f"return_{index}"
                    targets.append(OutputTarget(OutputTargetKind.RETURN_OUTPUT.value, name, info.node.name, canonical,
                                                expression=value.strip()))
            else:
                name = returned if re.fullmatch(r"[A-Za-z_]\w*", returned) else item.name
                targets.append(OutputTarget(OutputTargetKind.RETURN_OUTPUT.value, name, info.node.name, canonical))
            roots.append((canonical, item, targets))
        return roots

    def _explicit_roots(self, targets: Iterable[str | OutputTarget]) -> list[tuple[str, RustItem, list[OutputTarget]]]:
        grouped: dict[str, tuple[RustItem, list[OutputTarget]]] = {}
        for raw in targets:
            target = VariableTarget(raw) if isinstance(raw, str) else raw
            matches: list[tuple[str, RustItem]] = []
            for canonical, (info, item) in self.resolver.symbol_items.items():
                if item.kind != "FUNCTION": continue
                if target.module and target.module != info.node.name: continue
                if target.function and target.function not in {item.name, canonical}: continue
                definitions = [match for match in re.finditer(rf"\blet\s+(?:mut\s+)?{re.escape(target.name)}(?:\s*:[^=]+)?\s*=|\b{re.escape(target.name)}\s*[+\-*/%]?=", item.body or "")]
                if definitions: matches.append((canonical, item))
            if len(matches) != 1:
                raise AuditError(f"OUTPUT_VARIABLE_AMBIGUOUS: {target.name}: {len(matches)} Rust definitions")
            canonical, item = matches[0]; grouped.setdefault(canonical, (item, []))[1].append(target)
        return [(canonical, item, values) for canonical, (item, values) in grouped.items()]

    def _sink_roots(self) -> tuple[list[tuple[str, RustItem, list[OutputTarget]]], list[OutputSink]]:
        roots = []; artifacts = []
        for canonical, (info, item) in self.resolver.symbol_items.items():
            if item.kind != "FUNCTION" or not item.body: continue
            for match in re.finditer(r"(?m)(?:std::fs::write|fs::write)\s*\(([^,]+),\s*(.+)\)\s*;?\s*$", item.body):
                path_value, payload_expression = match.groups()
                payload_match = re.match(r"([A-Za-z_]\w*)", payload_expression.strip())
                if not payload_match: continue
                payload = payload_match.group(1); span = {"file": str(info.source.path),
                    "begin_line": item.begin_line + _line(item.body, match.start()) - 1, "begin_column": 1,
                    "end_line": item.begin_line + _line(item.body, match.end()) - 1, "end_column": 1}
                boundary = SerializationBoundary("serialization:" + _digest([canonical, span])[:16],
                    {"op": "PayloadReference", "name": payload}, "std::fs::write", None)
                artifact = ArtifactOutput("sink:" + _digest([canonical, span])[:16], "FILE_OUTPUT", "bytes",
                    path_value.strip(), boundary.mathematical_payload, payload, None, [], None, None, span,
                    IOProvenance(info.node.name, str(info.source.path), "std::fs::write", span), boundary)
                artifacts.append(artifact)
                roots.append((canonical, item, [OutputTarget(OutputTargetKind.FILE_OUTPUT.value, payload,
                                                              info.node.name, canonical)]))
        return roots, artifacts

    @staticmethod
    def _merge_roots(items: list[tuple[str, RustItem, list[OutputTarget]]]) -> list[tuple[str, RustItem, list[OutputTarget]]]:
        merged: dict[str, tuple[RustItem, list[OutputTarget]]] = {}
        for canonical, item, targets in items:
            values = merged.setdefault(canonical, (item, []))[1]
            for target in targets:
                if not any((known.kind, known.name) == (target.kind, target.name) for known in values): values.append(target)
        return [(canonical, item, targets) for canonical, (item, targets) in merged.items()]

    def lower_function(self, canonical: str, arguments: list[dict[str, Any]]) -> dict[str, Any]:
        if self.graph is None: self.graph = self.resolver.resolve(self.entry_source, self.project_root)
        return _RustLowerer(self.resolver, self.graph).function(canonical, arguments)

    def _output(self, canonical: str, item: RustItem, target: OutputTarget) -> AuditOutputResult:
        info, _ = self.resolver.symbol_items[canonical]; lowerer = _RustLowerer(self.resolver, self.graph)
        arguments = [{"op": "FreeVariable", "name": f"{canonical}::{name}"} for name in lowerer._params(item)]
        if target.kind == OutputTargetKind.RETURN_OUTPUT.value:
            if target.expression:
                env = {name: arguments[index] for index, name in enumerate(lowerer._params(item))}
                # Recreate final bindings before selecting a tuple component.
                for statement in lowerer._statements(item.body or ""):
                    match = re.match(r"let\s+(?:mut\s+)?([A-Za-z_]\w*)(?:\s*:\s*[^=]+)?\s*=\s*(.*)", statement, re.S)
                    if match: env[match.group(1)] = match.group(2)
                expression = lowerer.expr(target.expression, info, env)
            else: expression = lowerer.function(canonical, arguments)
        else:
            expression = lowerer.function(canonical, arguments, target.name, target.definition_line)
        parallel = bool(lowerer.execution_operations)
        implementation = {"schema_version": "1.0", "language": "rust", "module": info.node.name,
            "symbol": canonical, "mathematical_ir": expression,
            "outputs": [{"name": target.name, "expression": expression}],
            "library_contracts": lowerer.library_contracts,
            "execution_ir": {"operations": lowerer.execution_operations,
                             "overall_policy": "PARALLEL_REORDERABLE" if parallel else "SEQUENTIAL"},
            "mutation_ir": [value for value in _walk_dicts(expression) if value.get("mutation")],
            "proof_obligations": [diagnostic for diagnostic in self.graph.diagnostics
                                  if diagnostic.get("proof_obligation")],
            "expression_id": "expression:" + _digest(expression)[:16]}
        error = build_error_analysis(theory_ir=None, implementation_ir=implementation, output=target.name,
            comparison_relation="UNRESOLVED", parallel_semantics=({"overall_policy": "PARALLEL_REORDERABLE",
                "claims": {"PARALLEL_REDUCTION_ORDER_DIFFERS": "POSSIBLE"}} if parallel else None),
            library_contracts=lowerer.library_contracts)
        error_causes = sorted({component.semantic_cause_id for component in error.error_components})
        dependencies = sorted(lowerer.dependencies)
        output_id = "output:" + _digest([canonical, target.name, expression])[:16]
        return AuditOutputResult(output_id, target.name, target.kind, None, implementation, expression,
            _serial(error.residual_expression), _serial(error.error_components),
            _serial(error.graph_enclosure.output_bound), _serial(error.graph_enclosure.known_output_bound),
            {"status": error.graph_enclosure.total_output_status,
             "bound": _serial(error.graph_enclosure.output_bound) if error.graph_enclosure.total_output_status == "TOTAL_ERROR_BOUND_VERIFIED" else None},
            dependencies, lowerer.locations, "NOT_RUN", "UNRESOLVED", error_causes,
            _digest([dependencies, expression]))

    def analyze(self, targets: Iterable[str | OutputTarget] | None = None) -> ProjectAuditResult:
        self.graph = self.graph or self.resolver.resolve(self.entry_source, self.project_root)
        sink_roots, artifacts = self._sink_roots()
        candidates = self._explicit_roots(targets) if targets else self._merge_roots([*self._auto_roots(), *sink_roots])
        roots: list[AuditRootResult] = []; outputs: list[AuditOutputResult] = []
        diagnostics = list(self.graph.diagnostics)
        for canonical, item, output_targets in candidates:
            root_outputs = []
            for target in output_targets:
                try: root_outputs.append(self._output(canonical, item, target))
                except (AuditError, ValueError, TypeError) as exc:
                    diagnostics.append({"code": "RUST_OUTPUT_ANALYSIS_FAILED", "symbol": canonical,
                                        "target": target.name, "message": str(exc)})
                    root_outputs.append(AuditOutputResult("output:" + _digest([canonical, target.name])[:16],
                        target.name, target.kind, None, {"status": "UNRESOLVED"}, {"op": "UnresolvedOutput"},
                        None, [], None, None, None, [], [], "NOT_RUN", "FAILED"))
            outputs.extend(root_outputs); dependencies = sorted({value for output in root_outputs for value in output.dependencies})
            info, _ = self.resolver.symbol_items[canonical]; root_id = "root:" + _digest([canonical, [item.name for item in root_outputs]])[:16]
            status = "FAILED" if all(output.status == "FAILED" for output in root_outputs) else "PARTIALLY_VERIFIED" if any(output.status == "FAILED" for output in root_outputs) else "UNRESOLVED"
            roots.append(AuditRootResult(root_id, info.node.name, canonical, root_outputs, dependencies,
                                         status=status, graph_hash=_digest([root_id, dependencies])))
        shared = self._relations(roots)
        workspace = self.resolver.workspace
        source_hashes = {module.name: module.source_hash for module in self.graph.modules}
        provenance = {"entry_source_hash": sha256(self.entry_source.read_bytes()).hexdigest(),
            "used_source_hashes": source_hashes, "rust_source_hashes": source_hashes,
            "project_graph_hash": self.graph.graph_hash,
            "module_graph_hash": _digest([(edge.source, edge.target) for edge in self.graph.edges if edge.kind in {"IMPORT", "RE_EXPORT"}]),
            "root_graph_hashes": {root.root_id: root.graph_hash for root in roots},
            "output_slice_hashes": {output.output_id: output.slice_hash for output in outputs},
            "cargo_toml_hash": workspace.cargo_toml_hash if workspace else None,
            "cargo_lock_hash": workspace.cargo_lock_hash if workspace else None,
            "cargo_packages": [{"name": package.name, "version": package.version} for package in (workspace.packages if workspace else [])],
            "cargo_features": workspace.selected_features if workspace else [],
            "cargo_configuration": workspace.target_configuration if workspace else None,
            "rust_frontend_version": self.frontend.frontend_version,
            "backend_toolchain": self._toolchain(), "backend_is_proof_authority": False,
            "rust_library_contract_registry_hash": self.contracts.registry_hash,
            "library_contract_registry_hash": self.contracts.registry_hash,
            "lean_source_hashes": self._lean_hashes()}
        project_status = ProjectStatus.FAILED.value if not roots else ProjectStatus.PARTIALLY_VERIFIED.value if any(root.status == "FAILED" for root in roots) else ProjectStatus.UNRESOLVED.value
        causes = [{"semantic_cause_id": cause, "outputs": [output.output_id for output in outputs if cause in output.error_causes]}
                  for cause in sorted({cause for output in outputs for cause in output.error_causes})]
        return ProjectAuditResult(project_status, self.graph, roots, outputs, self.graph.modules,
            [_serial(edge) for edge in self.graph.edges], shared, causes,
            [{"output_id": output.output_id, "lean_status": output.lean_status} for output in outputs],
            artifacts, provenance, diagnostics)

    def _relations(self, roots: list[AuditRootResult]) -> list[dict[str, Any]]:
        result = []
        kinds = {symbol.canonical_name: symbol.kind for symbol in self.graph.symbols}
        for index, left in enumerate(roots):
            for right in roots[index + 1:]:
                common = sorted(set(left.dependency_slice) & set(right.dependency_slice))
                kind = ("SHARED_CONSTANT" if any(kinds.get(value) in {"CONST", "STATIC"} for value in common) else
                        "SHARED_FUNCTION" if any(kinds.get(value) in {"FUNCTION", "METHOD"} for value in common) else
                        "SHARED_INTERMEDIATE" if common else
                        "DEPENDENCE_UNKNOWN" if self.graph.diagnostics else "DISCONNECTED")
                value = {"left_root": left.root_id, "right_root": right.root_id, "kind": kind, "symbols": common}
                result.append(value); left.root_relations.append(value); right.root_relations.append(value)
        return result

    @staticmethod
    def _toolchain() -> dict[str, Any]:
        result = {}
        for command in ("cargo", "rustc"):
            executable = shutil.which(command)
            if not executable:
                result[command] = {"status": "UNAVAILABLE"}; continue
            try:
                process = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5, check=False)
                result[command] = {"status": "RECORDED", "path": executable, "version": process.stdout.strip(),
                                   "returncode": process.returncode}
            except (OSError, subprocess.TimeoutExpired) as exc:
                result[command] = {"status": "UNAVAILABLE", "error": str(exc)}
        return result

    @staticmethod
    def _lean_hashes() -> dict[str, str]:
        lean = Path(__file__).resolve().parents[2] / "lean"
        return {str(path.relative_to(lean)): sha256(path.read_bytes()).hexdigest() for path in lean.rglob("*.lean")} if lean.is_dir() else {}


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values(): yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value: yield from _walk_dicts(item)
