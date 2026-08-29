from __future__ import annotations
import json
from pathlib import Path
from cpp_audit.mathematical_knowledge import (MathematicalKnowledgeEntry,MathematicalKnowledgeRegistry,apply_knowledge_once)
ROOT=Path(__file__).resolve().parents[1]
def pv(n):return {"op":"PatternVariable","name":n}
def main()->int:
 exact=MathematicalKnowledgeEntry("add_zero","add zero","algebra",{"op":"Add","args":[pv("x"),{"op":"Constant","value":0}]},pv("x"),"EXACT",evidence_kind="FORMALLY_DERIVED")
 approx=MathematicalKnowledgeEntry("approx","approx","numerical",pv("x"),{"op":"Approx","args":[pv("x")]},"APPROXIMATION",evidence_kind="FORMALLY_DERIVED")
 registry=MathematicalKnowledgeRegistry([exact,approx]);checks=[];add=lambda n,v:checks.append({"case":n,"match":bool(v)})
 add("exact-classification",exact.is_exact and not approx.is_exact);add("exact-filter",[x.knowledge_id for x in registry.entries(exact_only=True)]==["add_zero"])
 add("metrics",registry.metrics()["exact_entries"]==1);add("validation",registry.validate()==[])
 result=apply_knowledge_once({"op":"Multiply","args":[{"op":"Add","args":[{"op":"FreeVariable","name":"a"},{"op":"Constant","value":0}]},{"op":"FreeVariable","name":"b"}]},exact)
 add("subgraph-application",len(result)==1 and result[0]["args"][0]["name"]=="a")
 conditional=MathematicalKnowledgeEntry("unsafe","unsafe","algebra",pv("x"),pv("x"),"EXACT_UNDER_ASSUMPTIONS",evidence_kind="FORMALLY_DERIVED")
 add("condition-required",any(x.startswith("CONDITIONAL_KNOWLEDGE_WITHOUT_CONDITION") for x in MathematicalKnowledgeRegistry([conditional]).validate()))
 unbound=MathematicalKnowledgeEntry("unbound","unbound","algebra",pv("x"),{"op":"Add","args":[pv("x"),pv("y")]},"EXACT",evidence_kind="FORMALLY_DERIVED")
 add("unbound-rejected",any("UNBOUND_FORWARD_VARIABLE" in x for x in MathematicalKnowledgeRegistry([unbound]).validate()))
 payload={"schema_version":"1.0","owner":"cpp_audit.mathematical_knowledge","native_operation":"D/LEGACY_KNOWLEDGE","cases":checks,"passed":sum(x["match"] for x in checks),"total":len(checks),"false_acceptance":0 if all(x["match"] for x in checks) else 1,"status":"PASS" if all(x["match"] for x in checks) else "FAIL"}
 out=ROOT/"output/native_migration/final/waves/wave2-knowledge-parity.json";out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8");print(json.dumps(payload,indent=2));return 0 if payload["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
