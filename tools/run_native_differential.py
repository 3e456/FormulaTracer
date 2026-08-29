"""Run migration acceptance differentials against retained Python artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from cpp_audit.native_differential import compare_case
from formulatracer.native import compare_ir


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "native_migration" / "python_rust_differential.json"


def load(relative: str): return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def main() -> None:
    results = []
    theories = load("output/self_audit/theory-corpus.json")["cases"]
    for case in theories:
        results.append(compare_case("positive:" + case["theory_id"], case["expression"], case["expression"]))
    mutations = load("output/self_audit/mutation-results.json")["cases"]
    for case in mutations:
        results.append(compare_case("mutation:" + case["mutation_id"],
                                    case["normalized_original_theory"]["math"],
                                    case["normalized_mutated_observed"]["math"]))
    round_trips = load("output/self_audit/valid-round-trip-results.json")["cases"]
    for case in round_trips:
        results.append(compare_case("roundtrip:" + case["case_id"],
                                    case["normalized_theory"]["math"],
                                    case["normalized_observed"]["math"]))
    sample = theories[0]["expression"]
    start=perf_counter()
    for _ in range(1000): compare_ir(sample,sample)
    native_seconds=perf_counter()-start
    payload = {
        "schema_version":"1.0", "baseline_sha":"8df98ee529f86fa6b8142c3b6a96abe240150419",
        "mode":"MIGRATION_DUAL_ENGINE_ONLY", "cases":len(results),
        "semantic_matches":sum(r.semantic_match for r in results),
        "tex_matches":sum(r.tex_match for r in results),
        "false_acceptance":sum(r.false_acceptance for r in results),
        "mismatches":[r.__dict__ for r in results if not r.semantic_match],
        "tex_mismatches":[r.__dict__ for r in results if not r.tex_match],
        "performance_observation":{"native_c_abi_1000_comparisons_seconds":native_seconds,"release_gate":False},
    }
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({k:payload[k] for k in ("cases","semantic_matches","tex_matches","false_acceptance")},indent=2))


if __name__ == "__main__": main()
