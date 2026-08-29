"""Wave 3 probability boundary assurance."""
import json, math
from pathlib import Path
from cpp_audit.probability import EstimatorTarget, audit_probability, classify_random_source, extract_estimator, monte_carlo_estimate, UserDefinedDistribution

OUT=Path("output/native_migration/final/waves/wave3-probability-parity.json")
def main():
    cases=[]
    def check(name,passed,invariant): cases.append({"case":name,"passed":bool(passed),"invariant":invariant})
    check("known_provider", classify_random_source("numpy.random.normal").contract_status=="REFERENCE_CONTRACT", "provider classification is reference-only")
    check("unknown_provider", classify_random_source("example.random") is None, "unknown random source unresolved")
    target=EstimatorTarget("expectation:x","ESTIMATOR_OF",{"op":"Expectation"},"USER_PROVIDED")
    est=extract_estimator({"op":"Mean","input":{"op":"SampleSequence"}},target=target)
    check("sample_mean", est.status=="ESTIMATOR_TARGET_IDENTIFIED", "estimator target explicit")
    _,mc=monte_carlo_estimate([0.1,0.2,0.3],target=target,support=(0,1))
    check("conditional_hoeffding", mc.status=="MONTE_CARLO_PROBABILISTIC_ENCLOSURE_UNDER_ASSUMPTIONS" and "IID" in mc.sampling_error.assumptions, "probabilistic bound retains assumptions")
    _,unresolved=monte_carlo_estimate([0.1,0.2],target=target,support=(-math.inf,math.inf))
    check("unbounded_support", unresolved.status=="MONTE_CARLO_ENCLOSURE_UNRESOLVED", "unbounded support never certified")
    audit=audit_probability(distribution=UserDefinedDistribution(pmf={0:0.5,1:0.5}),samples=[0,1,0,1])
    check("empirical_not_exact", audit.status!="PROBABILITY_AUDIT_REFERENCE_CONTRACT", "empirical evidence is not contract proof")
    payload={"schema_version":"1.0","wave":3,"component":"probability","cases":cases,"passed":sum(x["passed"] for x in cases),"total":len(cases),"false_acceptance":0 if all(x["passed"] for x in cases) else 1,"status":"PASS" if all(x["passed"] for x in cases) else "FAIL"}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8"); print(f"{payload['passed']}/{payload['total']} {payload['status']}"); return 0 if payload["status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())
