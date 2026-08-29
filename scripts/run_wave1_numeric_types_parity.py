from __future__ import annotations
import json
from pathlib import Path
from cpp_audit.numeric_types import (_native_numeric, _promoted_dtype, execution_type,
                                     infer_value_type)

ROOT=Path(__file__).resolve().parents[1]
def main()->int:
    cases=[]
    for name in ["bool","int16","uint32","float64","complex128","python.int","mystery"]:
        value=execution_type(name)
        cases.append({"case":f"execution-{name}","match":value.dtype==("unknown" if name=="mystery" else name)})
    for left_name,right_name in [("python.int","python.float"),("int16","uint16"),("float32","int16"),("complex64","float32")]:
        left,right=execution_type(left_name),execution_type(right_name)
        reference=_promoted_dtype(left,right)
        native=_native_numeric("PROMOTE",left=left.to_dict(),right=right.to_dict())
        cases.append({"case":f"promotion-{left_name}-{right_name}","match":native["status"]=="RESOLVED" and (native["type"]["dtype"],native["rule"])==(reference[0],reference[1])})
    cases.append({"case":"unknown-fail-closed","match":_native_numeric("PROMOTE",left=execution_type("unknown").to_dict(),right=execution_type("int8").to_dict())["status"]=="UNRESOLVED"})
    cases.append({"case":"runtime-complex","match":infer_value_type([1,2+3j]).dtype=="python.complex"})
    payload={"schema_version":"1.0","owner":"cpp_audit.numeric_types","native_operation":"F/LEGACY_NUMERIC_TYPES","cases":cases,"passed":sum(c["match"] for c in cases),"total":len(cases),"false_acceptance":0 if all(c["match"] for c in cases) else 1,"status":"PASS" if all(c["match"] for c in cases) else "FAIL"}
    destination=ROOT/"output/native_migration/final/waves/wave1-numeric-types-parity.json";destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8");print(json.dumps(payload,indent=2));return 0 if payload["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
