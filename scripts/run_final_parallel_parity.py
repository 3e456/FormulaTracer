"""Focused native-ownership gate for parallel execution semantics."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
from cpp_audit.parallel_semantics import analyze_parallel_semantics
from formulatracer.runtime_paths import reset_semantic_runtime_metrics, semantic_runtime_snapshot

ROOT=Path(__file__).resolve().parents[1]

def main()->int:
    reset_semantic_runtime_metrics()
    with tempfile.TemporaryDirectory(prefix="formulatracer-parallel-") as directory:
        reduction=Path(directory)/"reduction.py"; reduction.write_text("import numpy as np\ndef calculate(x):\n    return np.sum(x)\n",encoding="utf-8")
        race=Path(directory)/"race.py"; race.write_text("shared=[]\ndef worker(x):\n    shared.append(x)\n    return x\ndef calculate(pool, xs):\n    return pool.map(worker, xs)\n",encoding="utf-8")
        first=analyze_parallel_semantics(reduction,function="calculate")
        second=analyze_parallel_semantics(race,function="calculate")
    runtime=semantic_runtime_snapshot()
    checks={
        "reduction_not_bitwise_promoted":first.claims["BITWISE_REPRODUCIBLE"]=="NOT_ESTABLISHED",
        "backend_policy_unresolved":first.overall_policy=="UNKNOWN_EXECUTION_POLICY",
        "shared_mutation_detected":second.claims["POTENTIAL_DATA_RACE"]=="DETECTED",
        "native_path_only":runtime["RUST_NATIVE_SEMANTIC_CALLS"]==2 and runtime["PYTHON_REFERENCE_CALLS"]==0 and runtime["PYTHON_SEMANTIC_FALLBACK_COUNT"]==0,
    }
    payload={"schema_version":"1.0","component":"cpp_audit.parallel_semantics","native_operation":"C/PARALLEL_ANALYZE","status":"PASS" if all(checks.values()) else "FAIL","checks":checks,"runtime":runtime}
    destination=ROOT/"output/native_migration/final/parallel-parity.json"; destination.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return 0 if payload["status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())
