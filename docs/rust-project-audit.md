# Rust / Cargo / cross-language project audit

Phase 9.6 adds a static Rust frontend to the language-neutral project graph and
Mathematical Expression IR. `FormulaTracer("src/main.rs").analyze()` and a
`Cargo.toml` entry both resolve Cargo packages, crate roots, local modules,
workspace members, local path dependencies, `use` aliases, and public
re-exports. Registry and git crates remain external contract boundaries: the
resolver does not crawl their source trees.

The source frontend recognizes functions and methods, constants/statics,
structs/enums, ordinary numeric expressions, `if`/`match`, `Option`/`Result`
propagation, mutable assignments, indexing, iterator chains, built-in macros,
unsafe blocks, and configuration attributes. Iterator `map`, `filter`, `fold`,
`reduce`, `sum`, and `product` lower to language-neutral operators. Unknown
calls and macros remain `OpaqueNumericCall`/opaque graph nodes with provenance
and constraints; they never disappear from a report.

Reviewed seed contracts cover `std` iterators and scalar elementary methods,
`ndarray`, `nalgebra`, `faer`, and Rayon. A contract key includes crate identity
and public symbol, so an API with a similar name in another crate cannot inherit
the contract accidentally. Rayon reductions retain reorderable execution and
floating-point order warnings separately from their mathematical finite sum.

For a maturin/PyO3 project, the Python resolver reads `[tool.maturin]`, resolves
the local Cargo crate, identifies `#[pyfunction]` exports, adds a
`CrossLanguageCallEdge`, and inlines the Rust mathematical body into the Python
slice. The FFI boundary records source and representation-mapping status. A
resolved Rust body does not prove dtype/layout/conversion equivalence, so the
representation mapping remains a separate obligation and error source.

```console
cpp-audit project-analyze examples/rust_project_audit/Cargo.toml \
  --json-output build/rust-project-audit.json \
  --latex-output build/rust-project-audit.tex

cpp-audit project-analyze examples/cross_language_audit/analysis.py \
  --json-output build/cross-language-audit.json
```

Audit identity uses source, Cargo.toml, Cargo.lock, graph, output-slice, and
contract-registry hashes. Cargo/rustc versions are recorded when available and
otherwise explicitly marked `UNAVAILABLE`. The static source/Cargo model is the
authoritative input; compiler-internal HIR/MIR identifiers are not persisted.

Current exclusions include complete macro expansion, build-script execution,
borrow-checker proofs, trait solving, arbitrary MIR semantics, binary-only FFI
reconstruction, and claims of bitwise equality for reordered floating-point
parallel reductions. These produce diagnostics or unresolved obligations.
