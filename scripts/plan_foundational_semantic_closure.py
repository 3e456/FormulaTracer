"""Freeze the dependency-ordered closure waves from the current owner graph."""

from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/native_migration/final/waves"
WAVES = [
    ("wave1-foundation", ["cpp_audit.core", "cpp_audit.expression", "cpp_audit.numeric_types", "cpp_audit.math_semantics"]),
    ("wave2-equivalence", ["cpp_audit.transformations", "cpp_audit.mathematical_knowledge", "cpp_audit.equality_saturation"]),
    ("wave3-numerical", ["cpp_audit.ieee754", "cpp_audit.interval", "cpp_audit.probability"]),
    ("wave4-synthesis", ["cpp_audit.synthesis"]),
]

def read(path: Path): return json.loads(path.read_text(encoding="utf-8"))

def main() -> int:
    graph=read(ROOT/"output/native_migration/ownership-graph.json")
    owners=read(ROOT/"output/native_migration/final/remaining-owner-inventory.json")
    symbols=read(ROOT/"output/native_migration/final/remaining-symbol-inventory.json")["symbols"]
    by_owner={item["module"]:item for item in owners["owners"]}
    edges=[edge for edge in graph["edges"] if edge["source"] in by_owner and edge["target"] in by_owner]
    scc={node["module"]:node["scc"] for node in graph["nodes"] if node["module"] in by_owner}
    OUT.mkdir(parents=True,exist_ok=True)
    summary=[]
    for index,(name,modules) in enumerate(WAVES,1):
        records=[item for item in symbols if item["module"] in modules]
        semantic=[item for item in records if item["classification"]=="PRODUCTION_REACHABLE_SEMANTIC"]
        payload={
            "schema_version":"1.0","wave":index,"name":name,"status":"PLANNED",
            "owners_before":[module for module in modules if module in by_owner],
            "semantic_symbols_before":len(semantic),"symbols_before":len(records),
            "symbols_migrated":[],"symbols_reclassified":[],"symbols_remaining":[item["symbol"] for item in semantic],
            "rust_parity":"PENDING","false_acceptance":0,
            "reachability":{"production_semantic":len(semantic),"dynamic_unresolved":sum(item["production_reachability_unresolved"] for item in records)},
            "dependency_edges":[edge for edge in edges if edge["source"] in modules or edge["target"] in modules],
            "sccs":{module:scc[module] for module in modules if module in scc},
            "order_rationale":"Each remaining owner is a singleton SCC. Dependencies are migrated before consumers; frontend extraction may remain Python while all semantic decisions move native.",
        }
        (OUT/f"{name}.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        summary.append({"wave":index,"name":name,"owners":payload["owners_before"],"semantic_symbols":len(semantic)})
    (OUT/"dependency-order.json").write_text(json.dumps({"schema_version":"1.0","starting_head":"0a30535e6645389ef2ab5c444b4caea05aca348a","scc_count":len(set(scc.values())),"cycles":[],"edges":edges,"waves":summary},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return 0

if __name__=="__main__": raise SystemExit(main())
