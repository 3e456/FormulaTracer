from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "output/native_migration/final"
OWNERS = {"cpp_audit.ieee754", "cpp_audit.interval", "cpp_audit.probability"}
RUST = {
    "cpp_audit.ieee754": "A/LEGACY_IEEE754",
    "cpp_audit.interval": "C/LEGACY_INTERVAL",
    "cpp_audit.probability": "C/LEGACY_PROBABILITY",
}


def responsibility(symbol: str) -> str:
    short = symbol.rsplit(".", 1)[-1]
    if "ieee754" in symbol:
        return "classify IEEE-754 execution contract separately from exact mathematics"
    if "probability" in symbol:
        return "classify probability, estimator, sampling, or statistical evidence without proof promotion"
    if short.startswith("interval_") or short in {"singleton", "unresolved_interval", "_result", "_contains_zero"}:
        return "construct sound interval enclosure with explicit unresolved/domain behavior"
    if "IntervalEngine" in symbol or short == "analyze_project_ranges":
        return "propagate interval enclosures over Mathematical IR and record obligations/evidence"
    return "interval typed object, specification resolution, provenance, or serialization support"


def main() -> int:
    inventory = json.loads((FINAL / "remaining-symbol-inventory.json").read_text(encoding="utf-8"))
    graph = json.loads((ROOT / "output/native_migration/ownership-graph.json").read_text(encoding="utf-8"))
    scc = {node["module"]: node["scc"] for node in graph["nodes"]}
    dependencies = {owner: sorted(edge["target"] for edge in graph["edges"] if edge["source"] == owner)
                    for owner in OWNERS}
    records = []
    for item in inventory["symbols"]:
        if item["module"] not in OWNERS or item["classification"] != "PRODUCTION_REACHABLE_SEMANTIC":
            continue
        symbol = item["symbol"]
        records.append({
            "module": item["module"], "symbol": symbol, "operation": symbol.rsplit(".", 1)[-1],
            "semantic_responsibility": responsibility(symbol),
            "input": "typed Python facade objects / Mathematical IR / frontend observations",
            "output": "structured semantic result or fail-closed unresolved status",
            "assumptions": "explicit only; unknown dependence/domain/rounding never promoted",
            "failure_mode": "UNRESOLVED or explicit invalid/constraint status",
            "runtime_reachability": "PRODUCTION_REACHABLE",
            "rust_equivalent": RUST[item["module"]], "migration_status": "PENDING",
            "dependencies": dependencies[item["module"]], "scc": scc[item["module"]],
        })
    counts = {owner: sum(record["module"] == owner for record in records) for owner in sorted(OWNERS)}
    payload = {"schema_version": "1.0", "wave": 3, "status": "IN_PROGRESS",
               "migration_order": ["cpp_audit.ieee754", "cpp_audit.interval", "cpp_audit.probability"],
               "order_rationale": "All owners are singleton SCCs; IEEE execution facts feed interval evidence boundaries, while probability consumes neither as exact proof.",
               "counts": counts, "total": len(records), "symbols": records}
    path = FINAL / "waves/wave3-inventory.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"counts": counts, "total": len(records)}, indent=2))
    return 0 if len(records) == 60 else 1


if __name__ == "__main__":
    raise SystemExit(main())
