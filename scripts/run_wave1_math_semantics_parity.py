from __future__ import annotations
import json
from pathlib import Path
from dataclasses import asdict
from cpp_audit.math_semantics import (EvidenceStatus, FourierSeries, InfiniteProcess, Sequence,
    TaylorSeries, TruncationRequirement, TruncationRequirementSolver, analyze_convergence,
    function_properties, integral_transform, inverse_mapping, propagate_properties,
    range_condition_status, series_evaluation_candidates, discrete_transform_layers)
ROOT=Path(__file__).resolve().parents[1]
def main()->int:
    checks=[]
    add=lambda name,ok:checks.append({"case":name,"match":bool(ok)})
    add("log-domain",function_properties("log").domain.constraints==("x > 0",))
    add("unknown-unresolved",function_properties("mystery").evidence["contract"]==EvidenceStatus.UNRESOLVED)
    add("square-range",propagate_properties({"op":"Power","args":[{"op":"FreeVariable","name":"x"},{"op":"Constant","value":2}]}).certified_range.lower==0)
    add("range-branch",range_condition_status({"op":"Compare","comparison":"LessThan","args":[{"op":"FunctionCall","name":"abs","args":[{"op":"FreeVariable","name":"x"}]},{"op":"Constant","value":0}]})=="THEN_BRANCH_PROVABLY_UNREACHABLE")
    geometric=InfiniteProcess("InfiniteSeries",Sequence("n",{"op":"BoundVariable","name":"n","family_id":"geometric","ratio":{"op":"FreeVariable","name":"r"}}))
    unresolved=analyze_convergence(geometric);certified=analyze_convergence(geometric,["abs(r) < 1"])
    add("unknown-assumption-fail-closed",unresolved.status=="CONVERGENCE_UNRESOLVED")
    add("geometric-certified",certified.status=="CONVERGENCE_CERTIFIED")
    add("truncation",TruncationRequirementSolver().solve(certified,TruncationRequirement(1e-6),parameters={"r":.5}).status=="TRUNCATION_CERTIFIED")
    add("taylor",TaylorSeries("exp").process().kind=="InfiniteSeries")
    add("fourier",FourierSeries("f").process().kind=="BilateralInfiniteSeries")
    add("candidates",len(series_evaluation_candidates(geometric))==2)
    laplace=integral_transform("laplace",{"op":"FreeVariable","name":"f"});add("laplace",laplace["status"]=="TRANSFORM_CONTRACT_RESOLVED")
    add("inverse-fail-closed",inverse_mapping(laplace).evidence==EvidenceStatus.UNRESOLVED)
    add("inverse-certified",inverse_mapping(laplace,assumptions=laplace["region_of_convergence"]).evidence==EvidenceStatus.CONTRACT_VERIFIED)
    add("fft-relation",discrete_transform_layers("fft")["algorithm"]["exact_relation"]=="COMPUTES_DFT")
    payload={"schema_version":"1.0","owner":"cpp_audit.math_semantics","native_operation":"F/LEGACY_MATH_SEMANTICS","cases":checks,"passed":sum(c["match"] for c in checks),"total":len(checks),"false_acceptance":0 if all(c["match"] for c in checks) else 1,"status":"PASS" if all(c["match"] for c in checks) else "FAIL"}
    out=ROOT/"output/native_migration/final/waves/wave1-math-semantics-parity.json";out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8");print(json.dumps(payload,indent=2));return 0 if payload["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
