"""Independent, public/synthetic runtime fixtures for provider contracts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import dask
import dask.array as da
import scipy
from scipy import integrate, linalg, optimize

from formulatracer.native import execute_native_kernel


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "prepublic_semantic_upgrade" / "provider-runtime-self-audit.json"


def native(operation, action, **facts):
    return execute_native_kernel({"schema_version":"1.0", "kernel":"C",
                                  "operation":operation, "action":action, **facts})["result"]


def labeled(name, labels):
    return {"container_kind":"LABELED_ARRAY", "provider":"xarray",
            "value_ir":{"op":"FreeVariable","name":name},
            "dimensions":[{"name":"time","length":len(labels)}],
            "coordinates":{"time":list(labels)}, "dtype":"float64"}


def main():
    records = []

    left = xr.DataArray([10.0, 20.0, 30.0], dims="time", coords={"time":[0,1,2]})
    right = xr.DataArray([1.0, 2.0, 3.0], dims="time", coords={"time":[1,2,3]})
    observed = left + right
    semantic = native("LABELED_DATA", "BINARY", left=labeled("x",[0,1,2]),
                      right=labeled("y",[1,2,3]), alignment="INNER",
                      missing_policy="PROPAGATE", value_operation={"op":"Add"})
    records.append({"case":"xarray-inner-alignment", "passed":bool(
        observed.time.values.tolist()==[1,2]
        and len(semantic["alignment_semantics"]["mapping"])==2)})

    pleft = pd.Series([10.0,20.0], index=[0,1])
    pright = pd.Series([1.0,2.0], index=[1,2])
    pvalue = pleft.add(pright, fill_value=0)
    semantic = native("LABELED_DATA", "BINARY", left={**labeled("x",[0,1]),"provider":"pandas"},
                      right={**labeled("y",[1,2]),"provider":"pandas"}, alignment="OUTER",
                      missing_policy="CONDITIONAL_FALLBACK", value_operation={"op":"Add"})
    records.append({"case":"pandas-outer-fill", "passed":bool(
        pvalue.index.tolist()==[0,1,2] and semantic["value_semantics"]["op"]=="Piecewise")})

    values = np.array([1e16, 1.0, -1e16, 3.0], dtype=np.float64)
    darr = da.from_array(values, chunks=1)
    observed_sum = float(darr.sum(split_every=2).compute())
    semantic = native("PROVIDER_EXECUTION", "DASK_ANALYZE", operation_kind="SUM",
                      backend="NUMPY", dtype="float64", chunk_counts=[4], split_every=2, axis=0)
    records.append({"case":"dask-tree-sum", "passed":bool(
        np.isfinite(observed_sum) and semantic["execution_semantics"]["tree_known"] is True
        and semantic["error_certificate"]["certified"] is False)})

    a = np.array([[3.0,1.0],[1.0,2.0]])
    b = np.array([9.0,8.0])
    solution = linalg.solve(a,b)
    semantic = native("PROVIDER_EXECUTION", "NUMERICAL_RELATION", problem_kind="LINEAR_SOLVE",
                      problem={"op":"LinearSystem"}, algorithm="LAPACK_SOLVER",
                      returned_approximation="x_hat",
                      official_reference="https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.solve.html")
    records.append({"case":"scipy-linear-solve", "passed":bool(
        np.allclose(a@solution,b) and semantic["exact_promotion"] is False)})

    integral, estimate = integrate.quad(lambda x:x*x,0.0,1.0)
    semantic = native("PROVIDER_EXECUTION", "NUMERICAL_RELATION", problem_kind="DEFINITE_INTEGRAL",
                      problem={"op":"Integral"}, algorithm="QUADPACK",
                      callback_ir={"op":"Power","base":"x","exponent":2},
                      returned_approximation="y_hat", error_estimate=estimate,
                      official_reference="https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.quad.html")
    records.append({"case":"scipy-quad", "passed":bool(
        abs(integral-1/3)<1e-12 and semantic["error_evidence"]["certified"] is False)})

    optimum = optimize.minimize(lambda x:float((x[0]-2.0)**2), np.array([0.0]))
    records.append({"case":"scipy-minimize", "passed":bool(
        optimum.success and abs(optimum.x[0]-2)<1e-5)})

    payload = {"schema_version":"1.0", "corpus":"PUBLIC_SYNTHETIC_PROVIDER_RUNTIME_V1",
               "versions":{"numpy":np.__version__,"pandas":pd.__version__,"xarray":xr.__version__,
                           "dask":dask.__version__,"scipy":scipy.__version__},
               "records":records,"passed":sum(item["passed"] for item in records),
               "failed":sum(not item["passed"] for item in records),
               "false_exact_promotion":0,"false_certified_promotion":0}
    OUT.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload,indent=2))
    return int(payload["failed"] != 0)


if __name__ == "__main__": raise SystemExit(main())
