from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def callers(module: str) -> list[str]:
    needle = module.rsplit(".", 1)[-1]
    found: set[str] = set()
    for path in (ROOT / "python").rglob("*.py"):
        if path.name == f"{needle}.py":
            continue
        text = path.read_text(encoding="utf-8")
        if f".{needle} import" in text or f"cpp_audit.{needle}" in text:
            found.add(path.relative_to(ROOT).as_posix())
    return sorted(found)


def end_to_end_responsibilities() -> list[dict[str, object]]:
    path = ROOT / "python/cpp_audit/end_to_end.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = []
    semantic = {
        "_component_verified", "_error_completeness", "_assumptions", "_observed_status",
        "_status", "_proof_chain", "build_end_to_end_claims", "_expression_is_integer_exact",
    }
    serialization = {"_serial", "_id"}
    frontend = {"_walk", "_output_root"}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        if node.name in semantic:
            category = "SEMANTIC_DECISION"
        elif node.name in serialization:
            category = "SERIALIZATION"
        elif node.name in frontend:
            category = "FRONTEND_EXTRACTION"
        elif isinstance(node, ast.ClassDef):
            category = "SERIALIZATION"
        else:
            category = "ORCHESTRATION_ONLY"
        result.append({"symbol": node.name, "line": node.lineno, "classification": category})
    return result


def main() -> int:
    # The feature-freeze inventory is regenerated from the current source.  The
    # semantic-ownership snapshot is historical and must not resurrect retired
    # owners after a cutover.
    inventory = load(ROOT / "output/feature_freeze/python-semantic-inventory.json")
    graph = load(ROOT / "output/native_migration/ownership-graph.json")
    runtime = load(ROOT / "output/native_migration/runtime-owner-profile.json")
    calls = {item["owner"]: item["calls"] for item in runtime["owners"]}
    edges = graph["edges"]
    scc = {node["module"]: node["scc"] for node in graph["nodes"]}
    native_equivalents = {
        "cpp_audit.bitvector": ["A/BITVECTOR_EVALUATE", "native bitvector module"],
        "cpp_audit.ieee754": ["A/LEGACY_IEEE754", "A/IEEE754_ANALYZE"],
        "cpp_audit.interval": ["C/LEGACY_INTERVAL", "C/INTERVAL"],
        "cpp_audit.probability": ["C/LEGACY_PROBABILITY", "C/PROBABILITY"],
        "cpp_audit.synthesis": ["D/LEGACY_SYNTHESIS", "D/PLAN_GENERATION"],
        "cpp_audit.logic_semantics": ["A/LOGIC_EVALUATE"],
        "cpp_audit.mathematical_primitives": ["A/PRIMITIVE_REGISTRY"],
        "cpp_audit.numeric_types": ["F/LEGACY_NUMERIC_TYPES", "A/NUMERIC_TYPE_ANALYZE"],
        "cpp_audit.units": ["A/UNIT_ANALYZE"],
        "cpp_audit.expression": ["F/LEGACY_EXPRESSION", "B/CANONICALIZE"],
        "cpp_audit.math_semantics": ["F/LEGACY_MATH_SEMANTICS", "B/MATH_SEMANTICS"],
        "cpp_audit.transformations": ["B/LEGACY_TRANSFORMATIONS", "B/TRANSFORMATION_CATALOG", "B/APPLY_TRANSFORMATION"],
        "cpp_audit.equality_saturation": ["B/LEGACY_EQUALITY", "B/EGRAPH", "B/SATURATE_AND_MATCH"],
        "cpp_audit.approximation_families": ["C/APPROXIMATION_FAMILY"],
        "cpp_audit.approximation_proofs": ["C/APPROXIMATION_PROOF"],
        "cpp_audit.end_to_end": ["F/ASSEMBLE_PROJECT_VERIFICATION"],
        "cpp_audit.interval": ["C/INTERVAL", "C/ANALYZE_RANGE"],
        "cpp_audit.parallel_semantics": ["C/PARALLEL_ANALYZE"],
        "cpp_audit.probability": ["C/PROBABILITY_ANALYZE"],
        "cpp_audit.generation_planning": ["D/PLAN_GENERATION"],
        "cpp_audit.mathematical_knowledge": ["D/LEGACY_KNOWLEDGE", "D/KNOWLEDGE_APPLY"],
        "cpp_audit.synthesis": ["D/SYNTHESIZE"],
        "cpp_audit.core": ["F/VERIFY", "F/AUDIT_BUNDLE"],
    }
    records = []
    for module in inventory["modules"]:
        if module["classification"] != "PYTHON_SEMANTIC_SOURCE_OF_TRUTH":
            continue
        name = module["module"]
        records.append({
            "module": name,
            "path": module["path"],
            "kernel": module["semantic_kernel"],
            "semantic_responsibility": [item["name"] for item in module["symbols"]
                                         if item["classification"] == "PYTHON_SEMANTIC_SOURCE_OF_TRUTH"],
            "symbol_count": module["symbol_count"],
            "runtime_production_calls": calls.get(name, 0),
            "production_callers": callers(name),
            "dependencies": sorted(edge["target"] for edge in edges if edge["source"] == name),
            "dependents": sorted(edge["source"] for edge in edges if edge["target"] == name),
            "scc": scc[name],
            "rust_equivalent_operations": native_equivalents[name],
            "native_parity_status": "PENDING_FINAL_SYMBOL_PARITY",
            "retirement_blocker": "production reachability and focused symbol parity",
        })
    output = {
        "schema_version": "1.0",
        "starting_head": "b0d011f37c99ce7905176f82313a2b7327dff893",
        "owner_count": len(records),
        "symbol_count": sum(item["symbol_count"] for item in records),
        "runtime_calls": sum(item["runtime_production_calls"] for item in records),
        "owners": sorted(records, key=lambda item: (-item["runtime_production_calls"], item["module"])),
        "end_to_end_decomposition": end_to_end_responsibilities(),
        "policy": "Zero runtime calls never suffice for retirement; every symbol requires native parity or proven non-semantic/reference-only isolation.",
    }
    destination = ROOT / "output/native_migration/final/remaining-owner-inventory.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
