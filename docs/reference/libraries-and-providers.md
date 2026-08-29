# Scientific libraries and providers

A provider entry means FormulaTracer has a selected API contract or reference
classification. It does **not** mean every API, dtype, backend, device, default,
or upstream version is supported. Contract adoption still validates semantic
parameters and returns unresolved when evidence is insufficient.

The primary harvested registry contains 12 families: Python builtins, NumPy,
SciPy, pandas, xarray, Dask, GeoPandas, Shapely, pyproj, Rasterio, netCDF4, and
igraph. The ecosystem registry also contains selected contracts for JAX,
PyTorch, CuPy, Numba, SymPy, scikit-learn, statsmodels, NetworkX, Polars,
PyArrow, h5py, Zarr, XGBoost, LightGBM, Rust `std`/ndarray/nalgebra/faer/Rayon,
and C++ Eigen/Boost where recorded by current versioned data.

Registry `version` fields describe the reference-harvest scope. They are not a
release-wide compatibility promise. The current public support designation for
external scientific libraries is `REFERENCE_ONLY_VERSION_UNPINNED` until a
version-specific conformance run verifies signature, defaults, axis/dimension,
dtype, missing-value, mutation, laziness/device, and mathematical behavior.

## Current measured registry

- public APIs harvested: 14,864
- contract targets: 9,350
- formalized/classified targets: 9,207
- not applicable: 139
- reference insufficient: 4
- existing formal contracts: 393
- formal contract objects: 2,136

These are inventory/classification figures, not claims that 9,207 APIs have
individual Lean proofs or that entire upstream libraries are supported.

## Representative upstream checks

The release audit rechecked representative high-impact contracts against
official documentation. For example, `numpy.sum` keeps `axis`, accumulator
`dtype`, `out`, `keepdims`, `initial`, and `where`; `xarray.DataArray.sum` uses
named `dim`, missing-value rules, `min_count`, and attribute propagation;
`scipy.linalg.solve` depends on matrix shape, `assume_a`, transposition,
finiteness, dtype, and overwrite behavior. A generic mathematical reduction or
linear solve may be adopted only after these execution conditions are retained.

Official references are recorded in
`output/public_release_audit/provider-upstream-conformance.json`. Provider
references support a contract; they do not prove a concrete upstream binary.
