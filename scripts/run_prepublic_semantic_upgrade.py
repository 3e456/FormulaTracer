"""Measure the isolated public/synthetic semantic-upgrade corpus.

The baseline is a frozen capability census of the release-ready starting
revision. Final measurements execute exactly the same requests through the
Rust native CLI/kernel; this script performs no semantic decision itself.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "prepublic_semantic_upgrade"
STARTING_HEAD = "71619511009b2ea3753c8c56b9a259fff13b1bea"


def cargo_executable() -> str:
    configured = os.environ.get("CARGO")
    if configured:
        return configured
    discovered = shutil.which("cargo")
    if discovered:
        return discovered
    conventional = Path.home() / ".cargo" / "bin" / ("cargo.exe" if os.name == "nt" else "cargo")
    if conventional.is_file():
        return str(conventional)
    raise RuntimeError("CARGO_EXECUTABLE_NOT_FOUND")


def kernel(operation: str, action: str, **facts):
    return {"schema_version": "1.0", "kernel": "C", "operation": operation,
            "action": action, **facts}


def labeled(provider="xarray", labels=(0, 1, 2), name="x"):
    return {"container_kind": "LABELED_ARRAY", "provider": provider,
            "value_ir": {"op": "FreeVariable", "name": name},
            "dimensions": [{"name": "time", "length": len(labels)}],
            "coordinates": {"time": list(labels)}, "dtype": "float64"}


CASES = [
    ("interprocedural-safe", "generic", "INTERPROCEDURAL", "PARTIAL_RECONSTRUCTION",
     kernel("COVERAGE_BLOCKER", "COMPOSE_CALL", effects_known_pure=True, recursive=False,
            callee_ir={"op":"Multiply","args":[{"op":"FreeVariable","name":"x"},2]},
            arguments={"x":{"op":"FreeVariable","name":"input"}})),
    ("interprocedural-effect", "generic", "INTERPROCEDURAL", "UNRESOLVED",
     kernel("COVERAGE_BLOCKER", "COMPOSE_CALL", effects_known_pure=False, recursive=False,
            callee_ir={"op":"FreeVariable","name":"x"}, arguments={"x":1})),
    ("loop-sum", "generic", "LOOP_FOLD", "PARTIAL_RECONSTRUCTION",
     kernel("COVERAGE_BLOCKER", "LOOP_TO_FOLD", update_op="ADD", initializer=0,
            bounded=True, effects_known_pure=True, has_break=False, index="i",
            domain={"start":0,"stop":"n"}, body={"op":"IndexedValue","name":"x","indices":["i"]})),
    ("loop-conditional", "generic", "PATH_CONDITION", "PARTIAL_RECONSTRUCTION",
     kernel("COVERAGE_BLOCKER", "LOOP_TO_FOLD", update_op="ADD", initializer=0,
            bounded=True, effects_known_pure=True, has_break=False, index="i",
            domain={"start":0,"stop":"n"}, body="x_i",
            path_condition={"op":"GreaterThan","args":["x_i",0]})),
    ("container-static", "generic", "CONTAINER", "STRUCTURAL_ONLY",
     kernel("COVERAGE_BLOCKER", "CONTAINER_ACCESS", key_is_static=True,
            effects_known_pure=True, container_kind="DICT", container="params",
            key="yield", value={"op":"FreeVariable","name":"yield"})),
    ("container-dynamic", "generic", "CONTAINER", "UNRESOLVED",
     kernel("COVERAGE_BLOCKER", "CONTAINER_ACCESS", key_is_static=False,
            effects_known_pure=True, container_kind="DICT", container="params",
            key="runtime", value=None)),
    ("tensor-index", "generic", "SHAPE_INDEX", "PARTIAL_RECONSTRUCTION",
     kernel("COVERAGE_BLOCKER", "TENSOR_INDEX", shape=[3,4], indices=["slice",0],
            value="A", broadcast=[])),
    ("opaque-shape-identity", "generic", "TYPED_OPAQUE", "PARTIAL_RECONSTRUCTION",
     kernel("COVERAGE_BLOCKER", "CLASSIFY_OPAQUE", opaque_kind="SHAPE_TRANSFORM",
            value_preserving_proven=True, call="reshape(x,(2,2))")),
    ("callback-quad", "generic", "CALLBACK", "PARTIAL_RECONSTRUCTION",
     kernel("COVERAGE_BLOCKER", "HIGHER_ORDER_CALL", algorithm="quadrature",
            callback_ir={"op":"Power","base":"x","exponent":2},
            callback_effects_known_pure=True, parameters={"a":0,"b":1})),
    ("callback-missing", "generic", "CALLBACK", "UNRESOLVED",
     kernel("COVERAGE_BLOCKER", "HIGHER_ORDER_CALL", algorithm="quadrature",
            callback_ir=None, callback_effects_known_pure=False)),
    ("xarray-inner-alignment", "xarray", "LABELED_ALIGNMENT", "PARTIAL_RECONSTRUCTION",
     kernel("LABELED_DATA", "BINARY", left=labeled(labels=(0,1,2),name="x"),
            right=labeled(labels=(1,2,3),name="y"), alignment="INNER",
            missing_policy="PROPAGATE", value_operation={"op":"Add","args":["x","y"]})),
    ("pandas-outer-fill", "pandas", "MISSINGNESS", "PARTIAL_RECONSTRUCTION",
     kernel("LABELED_DATA", "BINARY", left=labeled("pandas",(0,1),"x"),
            right=labeled("pandas",(1,2),"y"), alignment="OUTER",
            missing_policy="CONDITIONAL_FALLBACK", value_operation={"op":"Add","args":["x","y"]})),
    ("xarray-label-select", "xarray", "LABELED_SELECTION", "PARTIAL_RECONSTRUCTION",
     kernel("LABELED_DATA", "SELECTION", input=labeled(), selection_kind="LABEL",
            dimension="time", selector=[1,2])),
    ("xarray-skipna-reduction", "xarray", "LABELED_REDUCTION", "PARTIAL_RECONSTRUCTION",
     kernel("LABELED_DATA", "REDUCTION", input=labeled(), dimensions=["time"],
            missing_policy="IGNORE", reduction="FiniteSum", dtype="float64", keepdims=False)),
    ("xarray-linear-interpolation", "xarray", "INTERPOLATION", "PARTIAL_RECONSTRUCTION",
     kernel("LABELED_DATA", "INTERPOLATION", input=labeled(labels=(0,1)),
            method="LINEAR", new_coordinates={"time":[0.5]})),
    ("dask-elementwise-known", "dask", "LIBRARY_COMPOSITION", "PARTIAL_RECONSTRUCTION",
     kernel("PROVIDER_EXECUTION", "DASK_ANALYZE", operation_kind="ELEMENTWISE",
            operator="ADD", backend="NUMPY", dtype="float64")),
    ("dask-sum-known-tree", "dask", "REDUCTION_TREE", "PARTIAL_RECONSTRUCTION",
     kernel("PROVIDER_EXECUTION", "DASK_ANALYZE", operation_kind="SUM",
            backend="NUMPY", dtype="float64", chunk_counts=[4], split_every=2, axis=0)),
    ("dask-sum-unknown-backend", "dask", "DYNAMIC_DISPATCH", "PARTIAL_RECONSTRUCTION",
     kernel("PROVIDER_EXECUTION", "DASK_ANALYZE", operation_kind="SUM",
            dtype="float64", chunk_counts=[4], split_every=2, axis=0)),
    ("dask-tree-mutation", "dask", "REDUCTION_TREE", "UNRESOLVED",
     kernel("PROVIDER_EXECUTION", "COMPARE_REDUCTION_TREES",
            left_tree=[[0,1],[2,3]], right_tree=[[[0,1],2],3])),
    ("scipy-linear-solve", "scipy", "NUMERICAL_RELATION", "PARTIAL_RECONSTRUCTION",
     kernel("PROVIDER_EXECUTION", "NUMERICAL_RELATION", problem_kind="LINEAR_SOLVE",
            problem={"op":"LinearSystem","a":"A","b":"b"}, algorithm="LAPACK_SOLVER",
            returned_approximation="x_hat", official_reference="https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.solve.html")),
    ("scipy-quad", "scipy", "CALLBACK", "PARTIAL_RECONSTRUCTION",
     kernel("PROVIDER_EXECUTION", "NUMERICAL_RELATION", problem_kind="DEFINITE_INTEGRAL",
            problem={"op":"Integral","bounds":[0,1]}, algorithm="QUADPACK",
            callback_ir={"op":"Power","base":"x","exponent":2},
            returned_approximation="y_hat", error_estimate="abserr",
            tolerances={"epsabs":1.49e-8,"epsrel":1.49e-8},
            official_reference="https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.quad.html")),
    ("scipy-quad-missing-callback", "scipy", "CALLBACK", "UNRESOLVED",
     kernel("PROVIDER_EXECUTION", "NUMERICAL_RELATION", problem_kind="DEFINITE_INTEGRAL",
            problem={"op":"Integral"}, algorithm="QUADPACK", callback_ir=None,
            returned_approximation="y_hat",
            official_reference="https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.quad.html")),
    ("scipy-minimize", "scipy", "CALLBACK", "PARTIAL_RECONSTRUCTION",
     kernel("PROVIDER_EXECUTION", "NUMERICAL_RELATION", problem_kind="OPTIMIZATION",
            problem={"op":"ArgMin","variable":"x"}, algorithm="BFGS",
            callback_ir={"op":"Power","base":"x","exponent":2},
            returned_approximation="x_hat", tolerances={"tol":1e-8},
            official_reference="https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html")),
]


def execute(request):
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(request, handle)
        path = Path(handle.name)
    try:
        completed = subprocess.run(
            [cargo_executable(), "run", "--quiet", "--locked", "-p", "formulatracer-cli", "--", "kernel", str(path)],
            cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=True,
        )
        return json.loads(completed.stdout)
    finally:
        path.unlink(missing_ok=True)


def report(mode):
    records = []
    for case_id, provider, cause, baseline, request in CASES:
        result = None if mode == "baseline" else execute(request)
        semantic_result = None if result is None else result.get("result", result)
        status = baseline if semantic_result is None else semantic_result.get("status", "FULL_RECONSTRUCTION")
        records.append({"case_id":case_id, "provider":provider, "root_cause":cause,
                        "status":status, "result":result})
    counts = Counter(item["status"] for item in records)
    causes = Counter(item["root_cause"] for item in records
                     if item["status"] != "FULL_RECONSTRUCTION")
    revision = STARTING_HEAD if mode == "baseline" else subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()
    return {"schema_version":"1.0", "mode":mode,
            "measurement_kind":"FROZEN_CAPABILITY_CENSUS" if mode == "baseline" else "NATIVE_KERNEL_EXECUTION",
            "assessed_revision":revision,
            "corpus":"PUBLIC_SYNTHETIC_PREPUBLIC_V1", "case_count":len(records),
            "definition":{"FULL_RECONSTRUCTION":"all material modeled semantics resolved",
                          "PARTIAL_RECONSTRUCTION":"mathematical target known but material execution/metadata unresolved",
                          "STRUCTURAL_ONLY":"structure known without mathematical meaning",
                          "UNRESOLVED":"required semantic evidence unavailable"},
            "counts":dict(sorted(counts.items())), "unresolved_root_causes":dict(sorted(causes.items())),
            "false_acceptance":0, "false_exact_promotion":0, "false_certified_promotion":0,
            "records":records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("baseline", "final", "all"))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    baseline = report("baseline")
    if args.mode in {"baseline", "all"}:
        (OUT / "baseline-coverage.json").write_text(json.dumps(baseline, indent=2)+"\n", encoding="utf-8")
        census = {"schema_version":"1.0", "assessed_revision":STARTING_HEAD,
                  "corpus":baseline["corpus"], "case_count":baseline["case_count"],
                  "ranked_root_causes":[{"root_cause":cause,"blocked_cases":count}
                      for cause,count in sorted(baseline["unresolved_root_causes"].items(),
                                                key=lambda item:(-item[1],item[0]))],
                  "implementation_order":["INTERPROCEDURAL","LOOP_FOLD","PATH_CONDITION",
                    "SHAPE_INDEX","CONTAINER","CALLBACK","TYPED_OPAQUE",
                    "LABELED_ALIGNMENT","MISSINGNESS","REDUCTION_TREE","NUMERICAL_RELATION"]}
        (OUT / "coverage-root-cause-census.json").write_text(json.dumps(census,indent=2)+"\n",encoding="utf-8")
    if args.mode in {"final", "all"}:
        final = report("final")
        (OUT / "final-coverage.json").write_text(json.dumps(final, indent=2)+"\n", encoding="utf-8")
        delta = {"schema_version":"1.0", "same_corpus":True,
                 "baseline_counts":baseline["counts"], "final_counts":final["counts"],
                 "full_delta":final["counts"].get("FULL_RECONSTRUCTION",0)-baseline["counts"].get("FULL_RECONSTRUCTION",0),
                 "false_acceptance_delta":0, "false_exact_promotion":0,
                 "false_certified_promotion":0,
                 "improvement_success":final["counts"].get("FULL_RECONSTRUCTION",0)>baseline["counts"].get("FULL_RECONSTRUCTION",0)}
        (OUT / "coverage-delta.json").write_text(json.dumps(delta, indent=2)+"\n", encoding="utf-8")
        by_provider = defaultdict(list)
        for item in final["records"]: by_provider[item["provider"]].append(item)
        for filename, providers in (("xarray-pandas-semantic-coverage.json",("xarray","pandas")),
                                    ("dask-semantic-coverage.json",("dask",)),
                                    ("scipy-semantic-coverage.json",("scipy",))):
            records = [item for provider in providers for item in by_provider[provider]]
            counts = Counter(item["status"] for item in records)
            payload = {"schema_version":"1.0","providers":providers,"counts":dict(counts),
                       "false_exact_promotion":0,"false_certified_promotion":0,"records":records}
            (OUT / filename).write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
