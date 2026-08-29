"""Focused native parity and mutation gate for the legacy core slice."""
from __future__ import annotations
import json,tempfile
from pathlib import Path
from cpp_audit.core import audit,extract_ir,normalize
from formulatracer.runtime_paths import reset_semantic_runtime_metrics,semantic_runtime_snapshot
ROOT=Path(__file__).resolve().parents[1];SPEC=ROOT/"examples/weighted_sum/algorithm.yaml";SOURCE=ROOT/"examples/weighted_sum/weighted_sum_loop.cpp";REGISTRY=ROOT/"registry/std"
def main()->int:
 reset_semantic_runtime_metrics(); positive=audit(SPEC,SOURCE,registry_root=REGISTRY); direct=normalize(extract_ir(SOURCE,registry_root=REGISTRY))
 with tempfile.TemporaryDirectory(prefix="formulatracer-core-") as directory:
  path=Path(directory)/"mutated.cpp";path.write_text(SOURCE.read_text(encoding="utf-8").replace("factor[i]","factor[r]"),encoding="utf-8");negative=audit(SPEC,path,registry_root=REGISTRY)
 runtime=semantic_runtime_snapshot();checks={"positive":positive.status=="PASS","canonical_graph":positive.semantic_graph==direct,"negative_mutation":negative.status=="FAILED" and any(item.code=="FACTOR_INDEX_MISMATCH" for item in negative.diagnostics),"native_path_only":runtime["RUST_NATIVE_SEMANTIC_CALLS"]==3 and runtime["PYTHON_SEMANTIC_FALLBACK_COUNT"]==0}
 payload={"schema_version":"1.0","component":"cpp_audit.core","native_operation":"F/LEGACY_CORE","status":"PASS" if all(checks.values()) else "FAIL","checks":checks,"runtime":runtime};destination=ROOT/"output/native_migration/final/waves/wave1-core-parity.json";destination.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");return 0 if payload["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
