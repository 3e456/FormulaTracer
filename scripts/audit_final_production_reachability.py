"""Conservative symbol-level reachability for the final native ownership gate."""

from __future__ import annotations

import ast
from collections import defaultdict, deque
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "python"
FINAL = ROOT / "output/native_migration/final"
BASELINE_OWNER_MODULES = {
    "cpp_audit.approximation_families", "cpp_audit.approximation_proofs", "cpp_audit.core",
    "cpp_audit.equality_saturation", "cpp_audit.expression", "cpp_audit.ieee754",
    "cpp_audit.interval", "cpp_audit.logic_semantics", "cpp_audit.math_semantics",
    "cpp_audit.mathematical_knowledge", "cpp_audit.mathematical_primitives",
    "cpp_audit.numeric_types", "cpp_audit.parallel_semantics", "cpp_audit.probability",
    "cpp_audit.synthesis", "cpp_audit.transformations", "cpp_audit.units",
}
RETIRED_RUST_OPERATIONS = {
    "cpp_audit.core": ["F/LEGACY_CORE"],
    "cpp_audit.expression": ["F/LEGACY_EXPRESSION", "B/CANONICALIZE"],
    "cpp_audit.numeric_types": ["F/LEGACY_NUMERIC_TYPES"],
    "cpp_audit.math_semantics": ["F/LEGACY_MATH_SEMANTICS"],
    "cpp_audit.mathematical_knowledge": ["D/LEGACY_KNOWLEDGE"],
    "cpp_audit.transformations": ["B/LEGACY_TRANSFORMATIONS"],
    "cpp_audit.equality_saturation": ["B/LEGACY_EQUALITY", "B/EGRAPH"],
    "cpp_audit.ieee754": ["A/LEGACY_IEEE754"],
    "cpp_audit.interval": ["C/LEGACY_INTERVAL"],
    "cpp_audit.probability": ["C/LEGACY_PROBABILITY"],
    "cpp_audit.synthesis": ["D/LEGACY_SYNTHESIS", "D/PLAN_GENERATION"],
    "cpp_audit.approximation_families": ["C/APPROXIMATION_FAMILY"],
    "cpp_audit.approximation_proofs": ["C/APPROXIMATION_PROOF"],
    "cpp_audit.parallel_semantics": ["C/PARALLEL_ANALYZE"],
    "cpp_audit.logic_semantics": ["A/LOGIC"],
    "cpp_audit.mathematical_primitives": ["A/PRIMITIVE_REGISTRY"],
    "cpp_audit.units": ["A/UNITS"],
}


def module_name(path: Path) -> str:
    return path.relative_to(PYTHON).as_posix().removesuffix(".py").replace("/", ".")


def symbol_name(module: str, parents: list[str], name: str) -> str:
    return ".".join([module, *parents, name])


class DefinitionCollector(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.parents: list[str] = []
        self.symbols: dict[str, ast.AST] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        name = symbol_name(self.module, self.parents, node.name)
        self.symbols[name] = node
        self.parents.append(node.name)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(child)
        self.parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.symbols[symbol_name(self.module, self.parents, node.name)] = node

    visit_AsyncFunctionDef = visit_FunctionDef


def imports(tree: ast.Module, module: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    package = module.rsplit(".", 1)[0] if "." in module else module
    for node in tree.body:
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                prefix = ".".join(parts[: max(0, len(parts) - node.level + 1)])
                base = ".".join(filter(None, (prefix, base)))
            for item in node.names:
                if item.name != "*":
                    aliases[item.asname or item.name] = ".".join(filter(None, (base, item.name)))
    return aliases


def public_exports(tree: ast.Module) -> set[str] | None:
    """Return a statically declared ``__all__`` without executing the module.

    Both public facades build ``__all__`` from literal lists followed by ``+=``.
    If a future facade makes the declaration dynamic, returning ``None`` keeps
    the reachability audit conservative instead of guessing an API boundary.
    """
    exports: list[str] | None = None

    def strings(node: ast.AST) -> list[str] | None:
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values: list[str] = []
            for item in node.elts:
                if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                    return None
                values.append(item.value)
            return values
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = strings(node.left), strings(node.right)
            return None if left is None or right is None else left + right
        return None

    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            exports = strings(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "__all__" and isinstance(node.op, ast.Add):
            addition = strings(node.value)
            if exports is None or addition is None:
                return None
            exports.extend(addition)
    return set(exports) if exports is not None else None


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted(node.value)
        return f"{left}.{node.attr}" if left else None
    return None


def resolve_call(raw: str, *, module: str, owner: str, aliases: dict[str, str],
                 symbols: set[str]) -> str | None:
    parts = raw.split(".")
    if parts[0] in {"self", "cls"}:
        owner_parts = owner.split(".")
        if len(owner_parts) > len(module.split(".")) + 1:
            candidate = ".".join([*owner_parts[:-1], *parts[1:]])
            return candidate if candidate in symbols else None
    if parts[0] in aliases:
        candidate = ".".join([aliases[parts[0]], *parts[1:]])
        if candidate in symbols:
            return candidate
        # Calling a class imported as a symbol is represented by its definition.
        return aliases[parts[0]] if aliases[parts[0]] in symbols and len(parts) == 1 else None
    local_prefix = owner.rsplit(".", 1)[0]
    for candidate in (f"{local_prefix}.{raw}", f"{module}.{raw}"):
        if candidate in symbols:
            return candidate
    return None


def semantic_effect(node: ast.AST) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if isinstance(node, ast.ClassDef):
        return False, ["schema/type declaration"]
    for child in ast.walk(node):
        if isinstance(child, (ast.Return, ast.Assign, ast.AnnAssign)):
            text = ast.unparse(child) if hasattr(ast, "unparse") else ""
            for marker in ("status", "relation", "assumption", "evidence", "bound", "range",
                           "provider", "proof", "canonical", "equivalent", "unify"):
                if marker in text.lower():
                    reasons.append(f"writes/returns {marker}-bearing value")
                    break
        if isinstance(child, ast.Raise):
            reasons.append("enforces fail-closed condition")
    return bool(reasons), sorted(set(reasons))


def provisional_classification(name: str, node: ast.AST, reachable: bool,
                               validation_reachable: bool) -> tuple[str, str]:
    short = name.rsplit(".", 1)[-1]
    module = ".".join(name.split(".")[:2])
    source = ast.unparse(node) if hasattr(ast, "unparse") else ""
    if short.startswith("_reference_"):
        return "REFERENCE_ORACLE", "explicit retained differential oracle"
    if short in {"to_dict", "to_json", "to_latex", "write_json", "json_text", "descriptor", "metrics"} or short.startswith("render"):
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "serialization or presentation projection"
    if isinstance(node, ast.ClassDef):
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "type/schema declaration has no call-time semantic decision"
    if "NativeContext" in source or "execute_native_kernel" in source or "execute_kernel" in source:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "arguments are projected to the native kernel"
    if short.startswith("load_") or module.endswith(("approximation_families", "approximation_proofs")) and "load" in short:
        return "REFERENCE_ORACLE", "versioned registry/reference material loader"
    if module == "cpp_audit.mathematical_primitives":
        return "REFERENCE_ORACLE", "primitive catalog is versioned reference data, not an interpretation engine"
    if module == "cpp_audit.logic_semantics":
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", (
            "logic construction, canonicalization, domain analysis, and truth-table decisions are delegated to A/LOGIC"
        )
    if module == "cpp_audit.units":
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", (
            "dimension algebra and exact affine conversion are delegated to A/UNITS"
        )
    if module == "cpp_audit.approximation_families" and short in {
        "approximation_metadata", "classify_library_call", "_native"
    }:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", (
            "approximation-family selection and interpolation/extrapolation decisions are delegated to C/APPROXIMATION_FAMILY"
        )
    if module == "cpp_audit.approximation_proofs" and short in {"resolve_approximation_proof", "_native"}:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "proof resolution and assumption discharge are delegated to C/APPROXIMATION_PROOF"
    if module == "cpp_audit.approximation_proofs" and short == "_discharge":
        return "REFERENCE_ORACLE", "retained frozen differential oracle; unreachable from production"
    if module == "cpp_audit.parallel_semantics" and short in {"analyze_parallel_semantics", "_native"}:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "parallel policy, race, ordering, and reproducibility decisions are delegated to C/PARALLEL_ANALYZE"
    if module == "cpp_audit.parallel_semantics" and short in {"_function_effects", "_aggregate_policy"}:
        return "REFERENCE_ORACLE", "retained unreachable differential oracle"
    if module == "cpp_audit.parallel_semantics" and short == "_function_features":
        return "LANGUAGE_FRONTEND", "serializes Python AST facts without deciding parallel semantics"
    if module == "cpp_audit.core" and short in {"audit", "normalize", "_native"}:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "legacy status, diagnostics, assumptions, and canonical graph are delegated to F/LEGACY_CORE"
    if module == "cpp_audit.core" and short == "_semantic_diagnostics":
        return "REFERENCE_ORACLE", "retained unreachable differential oracle"
    if module == "cpp_audit.core" and (short in {"_digest", "_stable_id", "json_text"} or short.startswith("render")):
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "identity or presentation projection"
    if module == "cpp_audit.approximation_proofs" and short in {"_source_hash", "approximation_proof_coverage"}:
        return "REFERENCE_ORACLE", "reference provenance or validation coverage accounting"
    if module == "cpp_audit.probability" and short in {
        "validate_distribution", "validate_empirical_distribution", "validate_independence", "validate_clt"
    }:
        return "VALIDATION_ONLY", "empirical validation produces runtime evidence, never proof authority"
    if module == "cpp_audit.probability" and short in {"_numeric_function", "_target_cdf"}:
        return "VALIDATION_ONLY", "safe bounded numerical validation helper; its output has no proof authority"
    if module == "cpp_audit.probability" and short in {"_native_probability", "classify_random_source", "extract_estimator", "monte_carlo_estimate", "audit_probability"}:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "provider, estimator, probabilistic enclosure, and audit-status decisions are delegated to C/LEGACY_PROBABILITY"
    if module == "cpp_audit.probability" and short in {"_id", "_serial", "ProbabilityAuditResult.write_latex"}:
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "stable serialization or presentation only"
    if module == "cpp_audit.probability":
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "typed probability result carrier or declarative enum"
    if module == "cpp_audit.synthesis" and short in {
        "_render", "_source", "_reduction_source", "_name", "_serial", "synthesize", "synthesize_cross_language"
    }:
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "language-specific code generation adapter; final adoption is native"
    if module == "cpp_audit.synthesis" and short in {"_native_synthesis", "_normalize", "verify_round_trip", "propose_repair", "verify_repair"}:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "generation safety, canonical round-trip, and repair decisions are delegated to D/LEGACY_SYNTHESIS"
    if module == "cpp_audit.synthesis" and short in {"write", "_id"}:
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "file emission or stable presentation identity only"
    if module == "cpp_audit.synthesis":
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "typed synthesis result carrier or source-formatting adapter"
    if module == "cpp_audit.expression" and (short.startswith("_render") or short in {"expression_report"}):
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "human rendering only"
    if module == "cpp_audit.expression" and short in {"_native_expression", "normalize_exact", "compare_exact", "select_transformation"}:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "exact expression and transformation-selection decisions are delegated to F/LEGACY_EXPRESSION"
    if module == "cpp_audit.expression" and short in {"_rename_bound", "_normalize_node", "Candidate"}:
        return "REFERENCE_ORACLE", "retained unreachable differential oracle or its data carrier"
    if module == "cpp_audit.expression" and short in {"load_transformation_rule", "load_transformation_set"}:
        return "REFERENCE_ORACLE", "versioned transformation data loading without applicability decisions"
    if module == "cpp_audit.expression" and short in {"_stable_id", "render_expression"}:
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "stable serialization or human rendering only"
    if module == "cpp_audit.expression" and (
        short in {"extract_expression", "expression_from_file", "_source_correspondence", "_expression_correspondence", "_constant", "_variable", "_substitute_free"}
        or "_GraphExpressionBuilder." in name
    ):
        return "LANGUAGE_FRONTEND", "Implementation IR to Mathematical IR extraction without final verification decision"
    if module == "cpp_audit.numeric_types" and short in {"_native_numeric", "_type_from_dict", "execution_type", "infer_value_type", "promote"}:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "dtype and promotion decisions are delegated to F/LEGACY_NUMERIC_TYPES"
    if module == "cpp_audit.numeric_types" and short == "_promoted_dtype":
        return "REFERENCE_ORACLE", "retained unreachable differential oracle"
    if module == "cpp_audit.numeric_types" and short.endswith("to_dict"):
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "structured object serialization only"
    if module == "cpp_audit.numeric_types":
        return "LANGUAGE_FRONTEND", "Python AST and runtime-value facts are serialized for F/LEGACY_NUMERIC_TYPES"
    if module == "cpp_audit.math_semantics" and (short in {"_native_math", "_function_from", "_relation_from", "_process_from",
        "localize_mathematical_node", "function_properties", "propagate_properties", "range_condition_status",
        "series_evaluation_candidates", "analyze_convergence", "integral_transform", "inverse_mapping", "convolution",
        "discrete_transform_layers", "merged", "usable_for_verification", "partial", "partial_symmetric", "tail", "term", "process", "solve"}):
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "mathematical properties, processes, convergence, transforms, and truncation decisions are delegated to F/LEGACY_MATH_SEMANTICS"
    if module == "cpp_audit.math_semantics":
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "typed semantic result carrier or versioned declaration data"
    if module == "cpp_audit.mathematical_knowledge" and (short in {"_native_knowledge", "apply_knowledge_once", "is_exact", "all_conditions", "descriptor", "register", "entries", "select", "metrics", "validate"}):
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "knowledge validation, selection, directionality, and application are delegated to D/LEGACY_KNOWLEDGE"
    if module == "cpp_audit.mathematical_knowledge":
        return "REFERENCE_ORACLE", "versioned knowledge data loading or typed data carrier"
    if module == "cpp_audit.transformations" and short in {
        "_native_transform", "_rewrite_state", "bounded_rewrite_search", "_find_pattern_matches",
        "_replace_path", "_pattern_matches", "_template", "_apply_exact_rule", "_hard_constraints",
        "_application", "_rewrite_once", "apply_transformation_set"
    }:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "transformation authorization, matching, constraints, application, and final relation/status decisions are delegated to B/LEGACY_TRANSFORMATIONS and existing native kernels"
    if module == "cpp_audit.transformations" and short in {"load_rewrite_catalog", "_load_rules"}:
        return "REFERENCE_ORACLE", "versioned transformation rule data loading without semantic authorization"
    if module == "cpp_audit.transformations" and short in {"_mentions_bound", "_apply_exact_node", "_rename_bound", "_contains_op", "_contains_derivative_order", "_obligations"}:
        return "REFERENCE_ORACLE", "retained unreachable Python differential oracle; production uses B/LEGACY_TRANSFORMATIONS"
    if module == "cpp_audit.transformations":
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "typed result carrier, stable identifier, or expression-envelope orchestration only"
    if module == "cpp_audit.equality_saturation" and short in {
        "_native_equality", "_fact_payload", "_restore_facts", "assert_fact", "knows", "missing_for", "merge",
        "add", "union", "add_equivalent", "equivalent", "extract", "ematch", "select_rewrite_packs",
        "__init__", "run", "replay_equality_trace", "saturate_and_match"
    }:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "fact authorization, relation separation, rule selection, exact merge validation, extraction, and saturation status delegate to B/LEGACY_EQUALITY, B/EGRAPH, and existing native matching kernels"
    if module == "cpp_audit.equality_saturation" and short in {"load_rewrite_packs"}:
        return "REFERENCE_ORACLE", "versioned rewrite-pack data loading only"
    if module == "cpp_audit.equality_saturation":
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "typed e-graph result carrier, deterministic storage mechanics, provenance collection, or stable serialization"
    if module == "cpp_audit.ieee754" and short in {"_native_ieee754", "analyze_ieee754"}:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "IEEE-754 status, equivalence, rounding, and special-value decisions are delegated to A/LEGACY_IEEE754"
    if module == "cpp_audit.interval" and short in {
        "_native_interval", "_interval_payload", "_interval_from_native", "unresolved_interval", "singleton",
        "interval_add", "interval_neg", "interval_sub", "interval_mul", "_contains_zero", "interval_div",
        "interval_abs", "interval_power", "interval_hull", "simplify_expression", "_result",
        "InputRange.interval", "Interval.__post_init__", "Interval.resolved", "Interval.singleton",
        "IntervalEngine._elementary", "IntervalEngine._condition", "IntervalEngine._refine", "_constraint_status"
    }:
        return "PRODUCTION_REACHABLE_THIN_WRAPPER", "interval construction, arithmetic, domain, branch, refinement, and constraint decisions are delegated to C/LEGACY_INTERVAL"
    if module == "cpp_audit.interval" and short in {"_number", "_same", "_bound", "_expr", "_down", "_up", "_numeric_binary", "_endpoint"}:
        return "REFERENCE_ORACLE", "retained unreachable differential helper; production interval decisions use C/LEGACY_INTERVAL"
    if module == "cpp_audit.interval" and short in {"_id", "_serial", "_set_dimensions", "IntervalEngine.obligation", "IntervalEngine.record"}:
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "stable identity, structured projection, or evidence collection only"
    if module == "cpp_audit.interval" and short in {"RangeSpecification.from_value", "RangeSpecification.resolve", "RangeSpecification.constraint", "_input_range", "_output_constraint", "IntervalEngine._resolve_name", "IntervalEngine._indexed", "IntervalEngine._count", "IntervalEngine._reduced_dimensions"}:
        return "LANGUAGE_FRONTEND", "range declarations and Mathematical IR metadata resolution without enclosure authority"
    if module == "cpp_audit.interval" and short in {"InputRange.count", "IntervalEngine.__init__", "IntervalEngine.evaluate", "_error_interval", "_execution_checks", "analyze_project_ranges"}:
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "walks Mathematical IR, invokes native interval/error contracts, and assembles structured evidence"
    if module == "cpp_audit.interval":
        return "ORCHESTRATION_SERIALIZATION_PRESENTATION", "typed interval/result carrier or declarative enum"
    frontend_helpers = {
        "cpp_audit.ieee754": {"_span", "_selected_function", "_expression_shape", "_root_expression", "_special_values"},
        "cpp_audit.numeric_types": {"_span", "_shape", "_flatten", "_literal_shape"},
        "cpp_audit.parallel_semantics": {"_span", "_function_effects"},
    }
    if short in frontend_helpers.get(module, set()) or (
        module == "cpp_audit.core" and short in {"extract_ir", "_line_of", "_diag"}
    ):
        return "LANGUAGE_FRONTEND", "source AST/execution metadata extraction"
    if module == "cpp_audit.core" and short in {"load_spec", "load_registry", "registry_hash"}:
        return "REFERENCE_ORACLE", "legacy specification/registry loading"
    effect, reasons = semantic_effect(node)
    if reachable and effect:
        return "PRODUCTION_REACHABLE_SEMANTIC", "; ".join(reasons)
    if validation_reachable and not reachable:
        return "REFERENCE_ORACLE", "reachable only from validation/reference roots"
    if reachable:
        return "PRODUCTION_REACHABLE_SEMANTIC", (
            "production-reachable executable helper does not satisfy the strict native-call thin-wrapper criterion"
        )
    return "DEAD_OBSOLETE", "not reachable from production or validation roots; conservative deletion review required"


def main() -> int:
    current = json.loads((FINAL / "remaining-owner-inventory.json").read_text(encoding="utf-8"))
    current_owner_modules = {item["module"] for item in current["owners"]}
    owner_modules = BASELINE_OWNER_MODULES
    rust_operations = {item["module"]: item["rust_equivalent_operations"] for item in current["owners"]}
    rust_operations.update(RETIRED_RUST_OPERATIONS)
    trees: dict[str, ast.Module] = {}
    paths: dict[str, Path] = {}
    definitions: dict[str, ast.AST] = {}
    aliases_by_module: dict[str, dict[str, str]] = {}
    for path in sorted(PYTHON.rglob("*.py")):
        module = module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        trees[module], paths[module] = tree, path
        collector = DefinitionCollector(module); collector.visit(tree)
        definitions.update(collector.symbols)
        aliases_by_module[module] = imports(tree, module)
    symbol_set = set(definitions)
    edges: dict[str, set[str]] = defaultdict(set)
    dynamic: dict[str, list[str]] = defaultdict(list)
    for name, node in definitions.items():
        if isinstance(node, ast.ClassDef):
            prefix = name + "."
            # Exporting/constructing a class conservatively exposes every
            # method, including validation hooks and dunder operators.
            edges[name].update(candidate for candidate in symbol_set if candidate.startswith(prefix))
    for owner, node in definitions.items():
        module = next(candidate for candidate in trees if owner == candidate or owner.startswith(candidate + "."))
        for call in (child for child in ast.walk(node) if isinstance(child, ast.Call)):
            raw = dotted(call.func)
            if raw:
                target = resolve_call(raw, module=module, owner=owner,
                                      aliases=aliases_by_module[module], symbols=symbol_set)
                if target:
                    edges[owner].add(target)
                if raw in {"eval", "exec", "globals", "locals"}:
                    dynamic[owner].append(raw)
                elif raw in {"getattr", "setattr"}:
                    # A literal attribute name is statically auditable. Only a
                    # computed name prevents a complete reachability decision.
                    if len(call.args) < 2 or not (
                        isinstance(call.args[1], ast.Constant)
                        and isinstance(call.args[1].value, str)
                    ):
                        dynamic[owner].append(raw)

    # Public facade re-exports and every public method/function in explicit
    # facade/CLI modules are production roots. Validation modules are separate.
    production_roots: set[str] = set()
    validation_roots: set[str] = set()
    for module, tree in trees.items():
        module_defs = {name for name in definitions if name.startswith(module + ".")}
        if module in {"cpp_audit.__init__", "formulatracer.__init__"}:
            exports = public_exports(tree)
            aliases = aliases_by_module[module]
            if exports is None:
                # Unknown/dynamic __all__: retain the conservative fallback.
                production_roots.update(target for target in aliases.values() if target in definitions)
            else:
                production_roots.update(
                    aliases[name] for name in exports
                    if name in aliases and aliases[name] in definitions
                )
        if module in {"cpp_audit.cli", "cpp_audit.__main__", "formulatracer.__main__"}:
            production_roots.update(name for name in module_defs if not name.rsplit(".", 1)[-1].startswith("_"))
        if module.startswith("formulatracer") and module != "formulatracer.native":
            production_roots.update(name for name in module_defs if not name.rsplit(".", 1)[-1].startswith("_"))
        if any(marker in module for marker in ("assurance", "validation", "release_candidate", "self_audit", "native_differential")):
            validation_roots.update(module_defs)

    def closure(roots: set[str]) -> tuple[set[str], dict[str, str | None]]:
        reached = set(roots); parent: dict[str, str | None] = {root: None for root in roots}
        queue = deque(roots)
        while queue:
            source = queue.popleft()
            for target in edges.get(source, ()):
                if target not in reached:
                    reached.add(target); parent[target] = source; queue.append(target)
        return reached, parent

    production, parents = closure(production_roots)
    validation, _ = closure(validation_roots)
    e_runtime = json.loads((ROOT / "<PRIVATE_AUDIT_OUTPUT>/runtime-semantic-paths.json").read_text(encoding="utf-8"))
    external_runtime = json.loads((ROOT / "output/reconstruction/runtime-semantic-paths.json").read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for name, node in sorted(definitions.items()):
        module = next((candidate for candidate in owner_modules if name.startswith(candidate + ".")), None)
        if not module:
            continue
        path: list[str] = []
        cursor: str | None = name
        while cursor is not None and cursor in parents:
            path.append(cursor); cursor = parents[cursor]
        path.reverse()
        classification, reason = provisional_classification(
            name, node, name in production, name in validation)
        records.append({
            "symbol": name, "module": module, "line": getattr(node, "lineno", None),
            "kind": "class" if isinstance(node, ast.ClassDef) else "function",
            "classification": classification, "classification_reason": reason,
            "semantic_responsibility": semantic_effect(node)[1],
            "statically_reachable_from_production": name in production,
            "production_reachability_path": path,
            "statically_reachable_from_validation_only": name in validation and name not in production,
            "production_reachability_unresolved": bool(dynamic.get(name)),
            "dynamic_dispatch_markers": sorted(set(dynamic.get(name, []))),
            "runtime_called_in_private_corpus": int(e_runtime.get("calls_by_owner", {}).get(module, 0)) > 0,
            "runtime_called_in_external21": int(external_runtime.get("calls_by_owner", {}).get(module, 0)) > 0,
            "runtime_called_in_tests": None,
            "runtime_called_in_holdout": None,
            "rust_equivalent": rust_operations[module],
        })
    counts: dict[str, int] = defaultdict(int)
    for item in records:
        counts[item["classification"]] += 1
    introduced_symbols = {
        "cpp_audit.approximation_families._native",
        "cpp_audit.approximation_proofs._native",
        "cpp_audit.parallel_semantics._function_features", "cpp_audit.parallel_semantics._native",
        "cpp_audit.core._native",
        "cpp_audit.expression._native_expression",
        "cpp_audit.numeric_types._native_numeric", "cpp_audit.numeric_types._type_from_dict",
        "cpp_audit.math_semantics._native_math", "cpp_audit.math_semantics._function_from",
        "cpp_audit.math_semantics._relation_from", "cpp_audit.math_semantics._process_from",
        "cpp_audit.mathematical_knowledge._native_knowledge",
        "cpp_audit.logic_semantics._native", "cpp_audit.units._fraction",
        "cpp_audit.units._unit", "cpp_audit.units._native", "cpp_audit.units._result_fraction",
    }
    baseline_records = [item for item in records if item["symbol"] not in introduced_symbols]
    baseline_counts: dict[str, int] = defaultdict(int)
    for item in baseline_records:
        baseline_counts[item["classification"]] += 1
    symbol_payload = {
        "schema_version": "1.0", "starting_head": "b0d011f37c99ce7905176f82313a2b7327dff893",
        "definition": "Production semantic owner means production-public reachable Python code that decides or changes mathematical/audit meaning.",
        "symbol_count": len(records), "baseline_symbol_count": len(baseline_records),
        "remaining_owner_symbol_count": sum(
            item["classification"] == "PRODUCTION_REACHABLE_SEMANTIC"
            or item["production_reachability_unresolved"] for item in records),
        "introduced_binding_symbols": sorted(introduced_symbols),
        "classification_counts": dict(sorted(counts.items())),
        "baseline_classification_counts": dict(sorted(baseline_counts.items())),
        "symbols": records,
        "warning": "This is an initial conservative static classification. PRODUCTION_REACHABILITY_UNRESOLVED and provisional thin helpers require manual/behavioral review before retirement.",
    }
    FINAL.mkdir(parents=True, exist_ok=True)
    (FINAL / "remaining-symbol-inventory.json").write_text(
        json.dumps(symbol_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    records_by_symbol = {item["symbol"]: item for item in records}
    entrypoints = []
    for root in sorted(production_roots):
        reached, _ = closure({root})
        semantic = sorted(name for name in reached
            if records_by_symbol.get(name, {}).get("classification") == "PRODUCTION_REACHABLE_SEMANTIC")
        unresolved = sorted(name for name in reached
            if records_by_symbol.get(name, {}).get("production_reachability_unresolved"))
        entrypoints.append({
            "entrypoint": root,
            "reachable_python_semantic_symbols": semantic,
            "reachable_python_semantic_symbol_count": len(semantic),
            "reachability_unresolved_symbols": unresolved,
            "reachable_rust_operations": sorted({operation for name in reached
                for operation in records_by_symbol.get(name, {}).get("rust_equivalent", [])}),
            "status": "REVIEW_REQUIRED" if semantic or unresolved else "NO_PYTHON_SEMANTIC_OWNER_REACHABLE",
        })
    reachability = {
        "schema_version": "1.0", "production_entrypoint_count": len(production_roots),
        "production_reachable_symbols": len(production),
        "remaining_owner_symbols_reachable": sum(
            item["statically_reachable_from_production"]
            and (item["classification"] == "PRODUCTION_REACHABLE_SEMANTIC"
                 or item["production_reachability_unresolved"])
            for item in records),
        "reviewed_former_owner_symbols_reachable": sum(
            item["statically_reachable_from_production"] and item["module"] in current_owner_modules
            for item in records),
        "production_reachable_python_semantic_symbols": sum(item["classification"] == "PRODUCTION_REACHABLE_SEMANTIC" for item in records),
        "production_reachability_unresolved": sum(item["production_reachability_unresolved"] for item in records),
        "entrypoints": entrypoints,
    }
    (FINAL / "production-reachability.json").write_text(
        json.dumps(reachability, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (FINAL / "public-entrypoint-reachability.json").write_text(
        json.dumps({"schema_version":"1.0","entrypoints":entrypoints}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        by_module[item["module"]].append(item)
    reviewed_owners = current["owners"]
    for owner in reviewed_owners:
        symbols = by_module[owner["module"]]
        owner["symbols"] = [item["symbol"] for item in symbols]
        owner["symbol_classification_counts"] = {
            classification: sum(item["classification"] == classification for item in symbols)
            for classification in sorted({item["classification"] for item in symbols})
        }
        owner["production_reachability"] = {
            "reachable_symbols": sum(item["statically_reachable_from_production"] for item in symbols),
            "semantic_symbols": sum(item["classification"] == "PRODUCTION_REACHABLE_SEMANTIC" for item in symbols),
            "unresolved_symbols": sum(item["production_reachability_unresolved"] for item in symbols),
        }
        semantic_remaining = owner["production_reachability"]["semantic_symbols"]
        unresolved_remaining = owner["production_reachability"]["unresolved_symbols"]
        owner["final_classification"] = (
            "PRODUCTION_SEMANTIC_OWNER_REMAINS" if semantic_remaining or unresolved_remaining
            else "RETIRED_AS_THIN_FRONTEND_PRESENTATION_REFERENCE_OR_VALIDATION")
        owner["remaining_blocker"] = (
            "Behavioral review/native cutover required for reachable semantic or unresolved symbols."
            if semantic_remaining or unresolved_remaining else None)
    remaining_owners = [owner for owner in reviewed_owners
                        if owner["production_reachability"]["semantic_symbols"]
                        or owner["production_reachability"]["unresolved_symbols"]]
    current["reviewed_former_owner_count"] = len(reviewed_owners)
    current["reviewed_former_owner_symbol_count"] = sum(len(owner["symbols"]) for owner in reviewed_owners)
    current["reviewed_former_owners"] = reviewed_owners
    current["owner_count"] = len(remaining_owners)
    current["symbol_count"] = sum(len(owner["symbols"]) for owner in remaining_owners)
    current["owners"] = remaining_owners
    current["symbol_level_classification"] = True
    current["production_reachable_python_semantic_symbols"] = reachability[
        "production_reachable_python_semantic_symbols"]
    current["production_reachability_unresolved"] = reachability[
        "production_reachability_unresolved"]
    (FINAL / "remaining-owner-inventory.json").write_text(
        json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    checks = {
        "owner_count_matches_records": current["owner_count"] == len(current["owners"]),
        "owner_symbol_count_matches_records": current["symbol_count"] == sum(
            owner["production_reachability"]["semantic_symbols"]
            + owner["production_reachability"]["unresolved_symbols"]
            for owner in reviewed_owners),
        "classification_total_matches_records": sum(counts.values()) == len(records),
        "symbols_are_unique": len({item["symbol"] for item in records}) == len(records),
        "all_owner_modules_have_symbols": all(by_module[item["module"]] for item in current["owners"]),
        "all_symbols_have_exactly_one_classification": all(bool(item["classification"]) for item in records),
        "production_dynamic_reachability_resolved": reachability["production_reachability_unresolved"] == 0,
    }
    consistency = {
        "schema_version": "1.0",
        "starting_head": "b0d011f37c99ce7905176f82313a2b7327dff893",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "owner_count": current["owner_count"],
        "owner_symbol_count": current["symbol_count"],
        "baseline_symbol_count": len(baseline_records),
        "introduced_binding_symbol_count": len(introduced_symbols),
        "classification_counts": dict(sorted(counts.items())),
        "production_entrypoint_count": len(production_roots),
        "production_reachable_python_semantic_symbols": reachability[
            "production_reachable_python_semantic_symbols"],
        "production_reachability_unresolved": reachability[
            "production_reachability_unresolved"],
    }
    (FINAL / "inventory-consistency.json").write_text(
        json.dumps(consistency, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
