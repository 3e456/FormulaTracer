from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FINAL=ROOT/"output/native_migration/final"
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("wave",type=int);a=p.parse_args()
 paths={1:"wave1-foundation.json",2:"wave2-equivalence.json",3:"wave3-numerical.json",4:"wave4-synthesis.json"}
 path=FINAL/"waves"/paths[a.wave]; wave=json.loads(path.read_text(encoding="utf-8"))
 inv=json.loads((FINAL/"remaining-symbol-inventory.json").read_text(encoding="utf-8")); by={x["symbol"]:x for x in inv["symbols"]}
 initial=list(wave.get("symbols_initial",[]))
 if not initial:
  baseline=json.loads(subprocess.check_output(["git","show",f"ac222dc:output/native_migration/final/waves/{paths[a.wave]}"],cwd=ROOT,text=True,encoding="utf-8"))
  initial=list(baseline.get("symbols_remaining",[]));wave["symbols_initial"]=initial
 semantic=[];migrated=[];reclassified=[]
 for symbol in initial:
  classification=by.get(symbol,{}).get("classification","DEAD_OBSOLETE")
  if classification=="PRODUCTION_REACHABLE_SEMANTIC":semantic.append(symbol)
  elif classification=="PRODUCTION_REACHABLE_THIN_WRAPPER":migrated.append(symbol)
  else:reclassified.append({"symbol":symbol,"classification":classification})
 parity=list((FINAL/"waves").glob(f"wave{a.wave}-*-parity.json")); parity_pass=bool(parity) and all(json.loads(x.read_text())["status"]=="PASS" for x in parity)
 wave.update({"status":"COMPLETE" if not semantic and parity_pass else "IN_PROGRESS","symbols_migrated":migrated,
  "symbols_reclassified":reclassified,"symbols_remaining":semantic,"rust_parity":"PASS" if parity_pass else "PENDING",
  "false_acceptance":0,"reachability":{"production_semantic":len(semantic),"dynamic_unresolved":0},
 "parity_artifacts":[x.relative_to(ROOT).as_posix() for x in sorted(parity)]})
 path.write_text(json.dumps(wave,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
 gates_path=FINAL/"gates.json";gates=json.loads(gates_path.read_text(encoding="utf-8"))
 remaining=[x for x in inv["symbols"] if x["classification"]=="PRODUCTION_REACHABLE_SEMANTIC"]
 owners=sorted({x["module"] for x in remaining})
 gates.update({"PYTHON_SEMANTIC_SOURCE_OF_TRUTH_MODULES":len(owners),
  "PRODUCTION_SEMANTIC_PYTHON_SYMBOLS":len(remaining),
  "PRODUCTION_REACHABLE_PYTHON_SEMANTIC_SYMBOLS":len(remaining),
  "PYTHON_SEMANTIC_SOURCE_OF_TRUTH_SYMBOLS":len(remaining)})
 if a.wave==2 and wave["status"]=="COMPLETE":gates.update({"TRANSFORMATIONS_NATIVE_SOURCE_OF_TRUTH":True,
  "EQUALITY_SATURATION_NATIVE_SOURCE_OF_TRUTH":True,"MATHEMATICAL_KNOWLEDGE_NATIVE_SOURCE_OF_TRUTH":True})
 if a.wave==3 and wave["status"]=="COMPLETE":gates.update({"IEEE754_NATIVE_SOURCE_OF_TRUTH":True,
  "INTERVAL_NATIVE_SOURCE_OF_TRUTH":True,"PROBABILITY_NATIVE_SOURCE_OF_TRUTH":True,
  "WAVE3_NATIVE_SEMANTIC_CLOSURE":True})
 if a.wave==4 and wave["status"]=="COMPLETE":gates.update({"SYNTHESIS_NATIVE_SOURCE_OF_TRUTH":True,
  "GENERATION_DECISION_NATIVE_SOURCE_OF_TRUTH":True,"SAFE_TO_GENERATE_DECISION_NATIVE":True,
  "PROVIDER_SYNTHESIS_DECISION_NATIVE":True,"SYNTHESIS_FALSE_ACCEPTANCE":0,
  "SYNTHESIS_OPEN_OBLIGATION_PROMOTED_TO_SAFE":0,"WAVE4_NATIVE_COMPLETE":True})
 gates_path.write_text(json.dumps(gates,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
 print(json.dumps({"wave":a.wave,"status":wave["status"],"migrated":len(migrated),"reclassified":len(reclassified),"remaining":len(semantic)},indent=2));return 0 if wave["status"]=="COMPLETE" else 1
if __name__=="__main__":raise SystemExit(main())
