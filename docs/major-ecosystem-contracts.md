# Major ecosystem contract expansion

The ecosystem harvester classifies selected public APIs from major Python,
Rust, and C++ scientific ecosystems. It reuses common Mathematical IR families
instead of creating one Lean theorem per spelling. For example NumPy-compatible
JAX/CuPy reductions, PyTorch tensor reductions, Rust ndarray reductions, and
Eigen reductions share `Reduction(Add)` where their reference conditions allow.

Execution metadata remains distinct: JAX is immutable JIT/device execution,
PyTorch retains tensor/autograd/device boundaries, CuPy is GPU execution, Rayon
is parallel/reorderable, and Eigen retains native vectorization metadata.

Every harvested seed deterministically receives one of
`FORMAL_SEMANTIC_CONTRACT`, `REFERENCE_ONLY_CONTRACT`, `NOT_APPLICABLE`, or
`REFERENCE_INSUFFICIENT`. Versions are `UNVERIFIED` unless pinned by caller
provenance. The report separately counts existing-family reuse and semantic
families needing further reference-contract work.

Included ecosystems are JAX, PyTorch, CuPy, Numba, SymPy, scikit-learn,
statsmodels, NetworkX, Polars, PyArrow, h5py, zarr, XGBoost, LightGBM, Dask-ML,
Rust std/ndarray/nalgebra/faer/Rayon, and C++ std/Eigen/selected Boost numeric
APIs. This is a prioritized semantic seed coverage, not a claim that every API
or library implementation is verified.

`diff_library_versions` compares harvested public records and emits additions,
removals, signature changes, deprecations, reference changes, possible semantic
changes, or unchanged entries. Only impacted contracts require re-review.
