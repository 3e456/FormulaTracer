# Parallel numerical semantics

Phase 4 generalizes the Dask execution layer into an explicit parallel audit.
`python-parallel SOURCE --function NAME` reports one of `SEQUENTIAL`,
`PARALLEL_DETERMINISTIC`, `PARALLEL_REORDERABLE`,
`PARALLEL_NONDETERMINISTIC`, `DISTRIBUTED`, `GPU_PARALLEL`, or
`UNKNOWN_EXECUTION_POLICY` for every reached execution boundary.

The pass recognizes Dask task graphs and distributed clients,
`multiprocessing`/executor maps, numerical threading, GPU calls through
CuPy/PyTorch/JAX, and NumPy reductions or contractions whose threaded backend
cannot be pinned from source. It never treats a library name alone as a proof
of deterministic ordering.

Each operation independently records:

- `PARALLEL_MAP_EQUIVALENT`, conditional on worker purity;
- `PARALLEL_REDUCTION_EQUIVALENT_OVER_EXACT_DOMAIN`, conditional on the exact
  operator laws;
- `PARALLEL_REDUCTION_ORDER_DIFFERS`;
- `BITWISE_REPRODUCIBLE`;
- `NUMERICALLY_REPRODUCIBLE_WITHIN_TOLERANCE`;
- `POTENTIAL_DATA_RACE`; and
- `CROSS_ITERATION_DEPENDENCY`.

Shared subscript/attribute mutation, global/nonlocal state, and mutating worker
methods are conservative race/dependency findings and fail closed in the
execution certificate. An unpinned BLAS thread count or scheduler remains
`UNKNOWN_EXECUTION_POLICY`, but does not invalidate the separately proved
mathematical formula. Floating reduction tolerance is not invented: the report
states `REQUIRES_TOLERANCE_CONTRACT` until a later error-bound phase supplies it.

Lean proves the pure-map identity and exposes exact reduction equality only
under an explicit contract. Scheduler behavior, races, hardware threads, and
distributed delivery are outside the kernel boundary.
