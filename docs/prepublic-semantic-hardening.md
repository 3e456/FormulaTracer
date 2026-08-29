# Isolated pre-public semantic hardening

This work is intentionally isolated from the known-good release branch. It
adds no publication step and uses only the checked-in public/synthetic corpus.

## Coverage order

FormulaTracer first measures structural causes that block full reconstruction:

1. interprocedural substitution with an explicit effect summary;
2. loop-to-fold recognition, including path-condition indicators;
3. tensor shape/index facts and transparent static container access;
4. higher-order callback reconstruction;
5. typed opaque classification that separates value, shape, control, effect,
   and external uncertainty.

Provider-specific semantics are then composed on those primitives:

- xarray and pandas use the provider-neutral labeled array/table layer;
- Dask combines graph/chunk semantics with an explicit backend contract;
- SciPy keeps mathematical problem, numerical method, and returned
  approximation as separate objects.

## Guarantee boundary

An upstream reference guarantee and a FormulaTracer-derived guarantee are
different evidence authorities. Dask documentation establishes parameters and
the chunk/combine/aggregate structure; it does not thereby certify a concrete
roundoff bound. A missing backend, reduction tree, callback, dynamic key, or
effect summary remains partial or unresolved.

Interpolation, solver output, optimization candidates, and quadrature results
are never promoted to exact equality merely because the provider is known.
Library-returned error estimates are retained as estimates unless independent
certificate evidence exists.

## Reproduction

```text
python scripts/run_prepublic_semantic_upgrade.py all
python tools/prepublic_release_hardening.py
cargo test --workspace --locked
```

The before/after corpus and provider reports are in
`output/prepublic_semantic_upgrade/`. The SBOM is an SPDX 2.3 inventory of
locked Rust and CI Python build inputs; it is not a claim that reference-only
scientific providers are distributed with FormulaTracer.
