"""Focused native synthesis semantic/adversarial gate."""
import json
from pathlib import Path
from formulatracer.native import NativeContext

OUT=Path("output/native_migration/final/waves/wave4-synthesis-parity.json")
ADV=Path("output/native_migration/final/waves/wave4-adversarial.json")
def native(action,**payload):
    with NativeContext() as c:return c.execute_kernel({"schema_version":"1.0","kernel":"D","operation":"LEGACY_SYNTHESIS","action":action,**payload})["result"]
def decide(expression,language="python",provider=None,**extra):
    constraints={"language":language,"numeric_domain":"real","allowed_approximations":extra.pop("allowed",[])}
    constraints.update(extra.pop("constraints",{}));return native("DECIDE",expression=expression,language=language,constraints=constraints,assumptions=extra.pop("assumptions",[]),provider=provider,**extra)
def main():
    cases=[]
    def check(name,condition,kind):cases.append({"case":name,"passed":bool(condition),"kind":kind})
    exact=decide({"op":"Add","args":[{"op":"FreeVariable","name":"x"},{"op":"Constant","value":1}]})
    check("positive_exact",exact["status"]=="SAFE_TO_GENERATE_EXACT","positive")
    normalized=native("ROUND_TRIP",expected={"op":"FreeVariable","name":"a::x"},actual={"op":"FreeVariable","name":"x","source_span":{"line":1}})
    check("formatting_invariant",normalized["status"]=="ROUND_TRIP_VERIFIED","metamorphic")
    provider={"language":"python","supported_domain":"complex","dtype":"float64","shape":[2,3],"axis":1,"normalization_convention":"forward","sign_convention":"negative","truncation_parameter":8}
    checks=[
      ("wrong_provider_domain",decide({"op":"Add"},provider=provider)),
      ("wrong_dtype",decide({"op":"Add"},provider=provider,dtype="float32")),
      ("wrong_shape",decide({"op":"Add"},provider=provider,shape=[3,2])),
      ("wrong_axis",decide({"op":"Add"},provider=provider,axis=0)),
      ("wrong_fourier_normalization",decide({"op":"FunctionCall"},provider=provider,normalization_convention="inverse")),
      ("wrong_sign_convention",decide({"op":"FunctionCall"},provider=provider,sign_convention="positive")),
      ("wrong_truncation",decide({"op":"FiniteSum"},provider=provider,truncation_parameter=16)),
      ("provider_language",decide({"op":"Add"},language="rust",provider=provider)),
      ("missing_assumption",decide({"op":"Divide","required_assumptions":["x != 0"]})),
      ("open_obligation",decide({"op":"Add","proof_obligations":[{"statement":"shape compatible","status":"OPEN"}]})),
      ("approximation_not_exact",decide({"op":"DiscreteDifference","relation":"APPROXIMATION_OF"})),
      ("unauthorized_family",decide({"op":"DiscreteDifference","family_id":"central_difference"})),
      ("unsupported_language",decide({"op":"Add"},language="fortran")),]
    for name,result in checks:check(name,not result["safe_to_generate_exact"],"negative")
    payload={"schema_version":"1.0","wave":4,"owner":"cpp_audit.synthesis","native_operation":"D/LEGACY_SYNTHESIS","cases":cases,"positive":sum(x["kind"]=="positive" and x["passed"] for x in cases),"negative":sum(x["kind"]=="negative" and x["passed"] for x in cases),"metamorphic":sum(x["kind"]=="metamorphic" and x["passed"] for x in cases),"total":len(cases),"passed":sum(x["passed"] for x in cases),"false_acceptance":sum(x["kind"]=="negative" and not x["passed"] for x in cases),"open_obligation_promoted_to_safe":0 if next(x for x in cases if x["case"]=="open_obligation")["passed"] else 1,"status":"PASS" if all(x["passed"] for x in cases) else "FAIL"}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8");ADV.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8");print(f"{payload['passed']}/{payload['total']} {payload['status']}");return 0 if payload["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
