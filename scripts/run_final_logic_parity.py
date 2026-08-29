"""Focused native-ownership gate for the retired Python logic owner."""

from __future__ import annotations

import json
from pathlib import Path

from cpp_audit.logic_semantics import analyze_piecewise_domains, canonicalize_logic, evaluate_logic, select
from formulatracer.runtime_paths import reset_semantic_runtime_metrics, semantic_runtime_snapshot


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    reset_semantic_runtime_metrics()
    source = {"op": "IfThenElse", "condition": {"op": "Compare", "comparison": "GreaterThan",
              "args": [{"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 0}]},
              "then": {"op": "Constant", "value": 7}, "else": {"op": "Constant", "value": 9}}
    canonical = canonicalize_logic(source)
    analysis = analyze_piecewise_domains(canonical)
    selected = select({"op": "Constant", "value": True}, source["then"], source["else"])
    visited: list[object] = []

    def evaluator(node: dict[str, object], _environment: dict[str, object]) -> object:
        value = node["value"]
        visited.append(value)
        return value

    evaluated = evaluate_logic(selected, {}, evaluator)
    checks = {
        "canonical_select": canonical.get("op") == "Select",
        "predicate_preserved": canonical.get("condition", {}).get("op") == "Predicate",
        "branch_count": len(analysis.branches) == 2,
        "branch_assumptions_preserved": all(branch.assumptions for branch in analysis.branches),
        "lazy_branch_evaluation": evaluated == 7 and visited == [True, 7],
    }
    runtime = semantic_runtime_snapshot()
    checks["native_path_only"] = (
        runtime["RUST_NATIVE_SEMANTIC_CALLS"] >= 5
        and runtime["PYTHON_REFERENCE_CALLS"] == 0
        and runtime["PYTHON_SEMANTIC_FALLBACK_COUNT"] == 0
    )
    payload = {
        "schema_version": "1.0",
        "component": "cpp_audit.logic_semantics",
        "native_operation": "A/LOGIC",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "runtime": runtime,
    }
    destination = ROOT / "output/native_migration/final/logic-parity.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
