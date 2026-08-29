from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; FINAL=ROOT/"output/native_migration/final"; OUT=FINAL/"waves/wave4-inventory.json"
def main()->int:
    data=json.loads((FINAL/"remaining-symbol-inventory.json").read_text(encoding="utf-8"))
    symbols=[x for x in data["symbols"] if x.get("module")=="cpp_audit.synthesis" and x.get("classification")=="PRODUCTION_REACHABLE_SEMANTIC"]
    rows=[]
    for item in symbols:
        name=item["symbol"]; short=name.rsplit(".",1)[-1]
        responsibility={"_normalize":"canonical semantic comparison boundary","verify_round_trip":"independent frontend reconstruction verdict","propose_repair":"repair eligibility and semantic replacement decision","verify_repair":"post-repair semantic acceptance"}.get(short,"identity or source emission support")
        rows.append({"module":"cpp_audit.synthesis","symbol":name,"semantic_responsibility":responsibility,
          "production_caller":item.get("production_reachability_path",[]),"input":"Theory/Implementation IR, constraints, provider contract, or debugger finding","output":"GenerationDecision, round-trip/repair verdict, or formatted artifact","provider_dependency":"explicit ProviderContract only","relation_dependency":"existing exact/non-exact relation taxonomy","assumptions":"explicit only","proof_obligations":"open obligations forbid SAFE_TO_GENERATE_EXACT","rust_equivalent":"D/LEGACY_SYNTHESIS","runtime_reachability":"PRODUCTION_REACHABLE","scc":0,"final_classification":"PENDING"})
    payload={"schema_version":"1.0","wave":4,"status":"IN_PROGRESS","owners":["cpp_audit.synthesis"],"semantic_symbols":len(rows),"symbols":rows,"dependency_edges":[{"source":"cpp_audit.synthesis","target":"cpp_audit.generation_planning"}],"sccs":[["cpp_audit.synthesis"]],"order_rationale":"GenerationDecision and semantic verification precede language-specific source formatting."}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8");print(json.dumps({"symbols":len(rows)},indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
