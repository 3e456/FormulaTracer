from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import date
import json
from pathlib import Path


FRONTENDS = {
    "python_audit", "python_cfg", "project", "cpp_project", "rust_project",
    "clang_frontend", "rust_frontend", "reference_harvester", "public_api_inventory",
    "dependency", "pipeline", "math_surface",
}
PRESENTATION = {"__main__", "cli", "render", "audit_execution", "localization"}
VALIDATION = {
    "assurance_release", "release_candidate", "release_candidate_v2", "self_audit",
    "control_flow_assurance", "knowledge_assurance", "real_world_validation",
    "execution_sandbox", "library_coverage", "native_differential", "reconstruction_artifacts",
}
REFERENCE = {"contracts", "reference_registry", "library_contracts", "ecosystem_contracts", "major_ecosystem",
             "rust_contracts", "mathematical_primitives"}
THIN = {"native", "math", "runtime_paths", "structural", "algebraic_domains", "logic_semantics", "units", "core", "expression", "numeric_types", "math_semantics",
        "approximation_families",
        "approximation_proofs",
        "parallel_semantics",
        "error_composition", "error_ir", "research_provenance", "semantic_debugger", "end_to_end",
        "generation_planning", "bitvector", "mathematical_knowledge"}

KERNELS = {
    "A": {"algebraic_domains", "bitvector", "ieee754", "logic_semantics", "mathematical_primitives", "numeric_types", "units"},
    "B": {"expression", "math_semantics", "math_surface", "transformations", "equality_saturation"},
    "C": {"approximation_families", "approximation_proofs", "end_to_end", "error_composition", "error_ir", "interval", "parallel_semantics", "probability"},
    "D": {"generation_planning", "mathematical_knowledge", "synthesis"},
    "E": {"research_provenance", "semantic_debugger"},
    "F": {"core"},
}


def category(path: Path) -> str:
    stem = path.stem
    if stem in THIN or path.parts[-2:] == ("formulatracer", "__init__.py"):
        return "THIN_BINDING"
    if stem in FRONTENDS:
        return "LANGUAGE_FRONTEND"
    if stem in PRESENTATION:
        return "PRESENTATION_ONLY"
    if stem in VALIDATION or "assurance" in stem:
        return "VALIDATION_ONLY"
    if stem in REFERENCE or "registry" in stem:
        return "REFERENCE_ONLY"
    if stem == "__init__":
        return "PUBLIC_FACADE"
    return "PYTHON_SEMANTIC_SOURCE_OF_TRUTH"


def kernel_for(path: Path) -> str | None:
    return next((kernel for kernel, stems in KERNELS.items() if path.stem in stems), None)


def symbol_category(path: Path, name: str, module_category: str) -> str:
    if path.stem == "algebraic_domains" and name == "_reference_structure_closure":
        return "VALIDATION_ONLY"
    if path.stem == "bitvector":
        if name.startswith("_reference_") or name == "run_exhaustive_bit_assurance":
            return "VALIDATION_ONLY"
        return "THIN_BINDING"
    if path.stem == "math_surface":
        if name in {"canonical_equal", "to_tex", "typed_unify", "instantiate",
                    "generalize", "anti_unify"}:
            return "THIN_BINDING"
        if name in {"_reference_canonical_equal", "_reference_to_tex",
                    "_reference_typed_unify", "_reference_instantiate",
                    "_reference_generalize", "_reference_anti_unify"}:
            return "VALIDATION_ONLY"
        if name in {"parse_tex", "MathSurfaceAST", "CanonicalSymbolRegistry", "MathBuilder"}:
            return "LANGUAGE_FRONTEND"
    if path.stem == "error_composition":
        if name.startswith("_reference_"):
            return "VALIDATION_ONLY"
        if name in {"compose_error_components", "evaluate_error_budget",
                    "propagate_expression_graph"}:
            return "THIN_BINDING"
    if path.stem == "error_ir":
        if name == "_reference_build_error_analysis":
            return "VALIDATION_ONLY"
        if name == "build_error_analysis":
            return "THIN_BINDING"
    if path.stem == "research_provenance":
        if name.startswith("_reference_"):
            return "VALIDATION_ONLY"
        if name in {"resolve_configuration", "compare_dataset_schemas", "build_data_lineage",
                    "augment_project_provenance", "_execute_native_kernel"}:
            return "THIN_BINDING"
    if path.stem == "semantic_debugger":
        if name.startswith("_reference_"):
            return "VALIDATION_ONLY"
        if name in {"debug_project", "_execute_native_kernel", "AuditDebugResult.create_reproducer"}:
            return "THIN_BINDING"
    if path.stem == "end_to_end":
        if name == "_reference_build_end_to_end_claims":
            return "VALIDATION_ONLY"
        if name in {"build_end_to_end_claims", "_execute_native_kernel"}:
            return "THIN_BINDING"
    if path.stem == "approximation_proofs":
        if name == "_discharge":
            return "REFERENCE_ONLY"
        if name in {"resolve_approximation_proof", "_native"}:
            return "THIN_BINDING"
    if path.stem == "parallel_semantics":
        if name in {"_function_effects", "_aggregate_policy"}:
            return "REFERENCE_ONLY"
        if name in {"analyze_parallel_semantics", "_native"}:
            return "THIN_BINDING"
        if name in {"_span", "_function_features"}:
            return "LANGUAGE_FRONTEND"
    if path.stem == "core":
        if name in {"audit", "normalize", "_native"}: return "THIN_BINDING"
        if name == "_semantic_diagnostics": return "REFERENCE_ONLY"
        if name in {"_digest", "_stable_id"} or name.startswith("render") or name == "json_text": return "PRESENTATION_ONLY"
        if name in {"extract_ir", "_line_of", "_diag"}: return "LANGUAGE_FRONTEND"
        if name in {"load_spec", "load_registry", "registry_hash"}: return "REFERENCE_ONLY"
    if path.stem == "expression":
        if name in {"_native_expression", "normalize_exact", "compare_exact", "select_transformation"}:
            return "THIN_BINDING"
        if name in {"_rename_bound", "_normalize_node", "Candidate"}:
            return "REFERENCE_ONLY"
        if name in {"_stable_id", "_render_node", "render_expression", "expression_report"}:
            return "PRESENTATION_ONLY"
        if name in {"load_transformation_rule", "load_transformation_set"}:
            return "REFERENCE_ONLY"
        return "LANGUAGE_FRONTEND"
    if path.stem == "numeric_types":
        if name in {"_native_numeric", "_type_from_dict", "execution_type", "infer_value_type", "_Analyzer.promote"}:
            return "THIN_BINDING"
        if name in {"_promoted_dtype"}:
            return "REFERENCE_ONLY"
        if name.endswith(".to_dict"):
            return "PRESENTATION_ONLY"
        return "LANGUAGE_FRONTEND"
    if path.stem == "math_semantics":
        if name in {"_native_math", "_function_from", "_relation_from", "_process_from"} or "." in name or name in {
            "localize_mathematical_node", "function_properties", "propagate_properties", "range_condition_status",
            "series_evaluation_candidates", "analyze_convergence", "integral_transform", "inverse_mapping",
            "convolution", "discrete_transform_layers"}:
            return "THIN_BINDING"
        return "PRESENTATION_ONLY"
    if path.stem == "mathematical_knowledge":
        if name in {"_native_knowledge", "apply_knowledge_once"} or "." in name:
            return "THIN_BINDING"
        return "REFERENCE_ONLY"
    if path.stem == "generation_planning":
        if name == "_reference_plan_generation":
            return "VALIDATION_ONLY"
        if name == "plan_generation":
            return "THIN_BINDING"
    return module_category


def symbols(tree: ast.Module) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            result.append({"name": node.name, "kind": kind, "line": node.lineno})
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        result.append({"name": f"{node.name}.{child.name}", "kind": "method", "line": child.lineno})
    return result


def build(root: Path) -> dict[str, object]:
    records = []
    for path in sorted((root / "python").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path), type_comments=True)
            parse_status = "PARSED"
            found = symbols(tree)
        except (OSError, UnicodeError, SyntaxError) as exc:
            parse_status = f"ERROR:{type(exc).__name__}"
            found = []
        module_category = category(path)
        for item in found:
            item["classification"] = symbol_category(path, str(item["name"]), module_category)
        records.append({
            "module": relative.removeprefix("python/").removesuffix(".py").replace("/", "."),
            "path": relative,
            "classification": module_category,
            "semantic_kernel": kernel_for(path),
            "semantic_source_of_truth": "python" if module_category == "PYTHON_SEMANTIC_SOURCE_OF_TRUTH" else None,
            "parse_status": parse_status,
            "symbols": found,
            "symbol_count": len(found),
        })
    counts = Counter(record["classification"] for record in records)
    return {
        "schema_version": "1.0",
        "generated": str(date.today()),
        "policy": "Every Python module and top-level semantic symbol is classified; retirement requires a passed native differential gate.",
        "categories": [
            "NATIVE_SOURCE_OF_TRUTH", "THIN_BINDING", "PUBLIC_FACADE", "LANGUAGE_FRONTEND", "PRESENTATION_ONLY",
            "VALIDATION_ONLY", "REFERENCE_ONLY", "RETIRED_SEMANTIC_IMPLEMENTATION", "PYTHON_SEMANTIC_SOURCE_OF_TRUTH",
        ],
        "summary": dict(sorted(counts.items())),
        "python_semantic_source_of_truth_modules": counts.get("PYTHON_SEMANTIC_SOURCE_OF_TRUTH", 0),
        "modules": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("output/feature_freeze/python-semantic-inventory.json"))
    args = parser.parse_args()
    payload = build(args.root.resolve())
    destination = args.output if args.output.is_absolute() else args.root / args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
