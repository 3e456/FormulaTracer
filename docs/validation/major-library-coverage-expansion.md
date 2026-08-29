# Major Library Coverage Expansion and Self-Audit Readiness

## Technical summary

FormulaTracer now deterministically classifies 277 observed-or-targeted APIs across the private research-scale corpus corpus and the major Python/Rust/C++ ecosystem seed: 24 have kernel-verified family mappings and 253 remain explicitly reference-contract evidence. Direct library-call resolution on the unchanged private research-scale corpus source corpus increased from 91.16% to 100.00%. This is a reference-resolution result, not proof that the library implementations are formally verified.

The same read-only private research-scale corpus reanalysis reduced entry-level `UNKNOWN_LIBRARY` from 101 to 99, `SHAPE_UNRESOLVED` from 101 to 100, and Mathematical-IR `Other` nodes from 3,239 to 3,227. The smaller entry-level change is expected: most remaining opaque nodes are custom/dynamic calls or unsupported syntax rather than missing registrations for observed numeric packages.

A thin `LibraryBackend`/`LibraryLoweringRule`/`LibraryCapability` API now supports capability queries and verified frontend round trips. Actual source generation and FormulaTracer re-analysis produced 12 exact normalized round trips across seven requested theory families and NumPy/JAX/PyTorch/CuPy/Python-loop backends. Rust and C++ ecosystem capabilities are catalogued, but their new library-specific generators correctly report `BACKEND_CAPABILITY_UNAVAILABLE`.

One critical false acceptance was found during revalidation: `numpy.nanmean(axis=0)` and `axis=1` were not localized as different because the semantic debugger ignored public keyword parameters. The comparator now checks axis/dimension/dtype/method keyword changes; the fixed private research-scale corpus mutation run detects 7/7 evaluated mutations. `CRITICAL_LIBRARY_FALSE_ACCEPTANCE_OPEN = 0`.

## Measured coverage improved without a proof-boundary promotion

| Metric | Before | After | Interpretation |
|---|---:|---:|---|
| Library contract resolution | 91.16% | 100.00% | All 2,806 observed numeric-prefix calls now have a reviewed reference or formal family mapping |
| Mathematical IR extraction | 91.35% | 91.35% | Library registration alone does not solve theory, general CFG, or unsupported syntax |
| `UNKNOWN_LIBRARY` entries | 101 | 99 | Two entries lost opaque library boundaries; remaining cases are mostly non-library/custom opaque calls |
| `SHAPE_UNRESOLVED` entries | 101 | 100 | One shape obligation became contract-constrained; unknown shape remains fail-closed |
| Mathematical IR `Other` nodes | 3,239 | 3,227 | Twelve nodes moved to meaningful contract-backed IR |
| Partial or unresolved outputs | 983 | 983 | No theory/input-range evidence was invented |
| Critical library false acceptances | 0 baseline gate | 0 final gate | One newly exposed defect was fixed and replayed |

The original 3,239 `Other` nodes can be meaningfully decomposed without forcing non-mathematical operations into equations:

| Category | Nodes |
|---|---:|
| Non-mathematical values/containers | 1,503 |
| Reference-only/opaque operations | 1,144 |
| Indexing | 211 |
| Control flow | 141 |
| Elementwise | 80 |
| I/O and serialization | 49 |
| Still unknown | 111 |

This gives a 96.57% meaningful reclassification rate for the former `Other` population. `NON_MATHEMATICAL`, `REFERENCE_ONLY`, and `IO_SERIALIZATION` are deliberate terminal categories, not failed attempts to fabricate a mathematical family.

## Scope and measurement definitions

The before/after denominator is the same read-only private research-scale corpus inventory: 20+ projects, 170+ source files, 40k+ LOC, 700+ audit roots, and 900+ outputs. FormulaTracer read source and environment metadata only. Detailed corpus records are not distributed.

`UNKNOWN_LIBRARY` is an entry-level unresolved-cause flag derived from opaque numeric IR. The gap artifact therefore reports both the 101 affected entries and the individual opaque public/custom call names found in their output graphs. It must not be interpreted as exactly 101 unique public APIs. `SHAPE_UNRESOLVED` is also entry-level; 100 of the original 101 cases overlapped with `UNKNOWN_LIBRARY`, while one was independently shape-constrained.

The existing public-reference registry remains the large-scale baseline: 9,207 formalized public APIs, 139 `NOT_APPLICABLE`, four `REFERENCE_INSUFFICIENT`, and zero review-pending candidates in its 9,350-target phase. This batch adds a focused 101-contract major-ecosystem seed and classifies 277 observed-or-targeted APIs for self-audit readiness; it does not replace the existing harvester corpus.

## Method and contract architecture

Resolution continues to use official public reference evidence before source inspection. Contracts lower public calls into shared semantic families—Reduction, TensorContraction, ShapeTransform, selection, statistics, graph, spatial, table, and execution boundaries—while keeping dtype, device, parallel order, JIT, autograd, and mutability in execution metadata.

The added private research-scale corpus gap contracts cover NumPy input/output boundaries, contiguous conversion, scalar casts, segmented `minimum.reduceat`, xarray dataset/data-array input boundaries, pandas tabular input boundaries, and rasterio dataset/rasterization boundaries. I/O calls are registered as representation/serialization boundaries; they are not promoted to mathematical theorems.

Shape relations are attached only when public semantics determine them. The classified catalog contains 87 shape-aware APIs and 87 explicit constraints, including reduction rank, contracted-dimension equality, reshape element-count conservation, transpose permutations, broadcast compatibility, and index selection. Three xarray APIs explicitly retain named-dimension preservation. Missing evidence continues to yield `SHAPE_UNRESOLVED`.

Proof evidence is one of `KERNEL_VERIFIED`, `KERNEL_VERIFIED_UNDER_ASSUMPTIONS`, `REFERENCE_CONTRACT`, `FORMALLY_DERIVED`, `EMPIRICALLY_VALIDATED`, or `UNRESOLVED`. Official documentation alone never produces a claim that the installed native/library implementation is formally verified. Version provenance retains `UNVERIFIED` when an installed or version-pinned value is unavailable.

## Self-generation and cross-library results

The backend API exposes deterministic `supports(family)` and `lower(family)` queries. Supported lowering emits source; unsupported lowering returns `BACKEND_CAPABILITY_UNAVAILABLE` without substitute code.

| Backend | Implemented generation | Actual round trip | Execution distinction |
|---|---|---|---|
| Python loop | Elementwise, FilteredSum, FiniteSum, Piecewise | 3 verified; iterator FiniteSum remains a frontend limitation | Sequential Python |
| NumPy | Elementwise, FiniteSum, Dot, MatrixMultiply, Piecewise, Reduction | 6 verified | CPU array execution |
| JAX | FiniteSum | Verified | JIT/device metadata retained |
| PyTorch | FiniteSum | Verified | tensor/device/autograd metadata retained |
| CuPy | FiniteSum | Verified | GPU and reduction-order metadata retained |
| Rust loop/iterator/ndarray/Rayon | capability catalog only | unavailable | language/library frontend generator pending |
| C++ loop/std/Eigen | capability catalog only | unavailable | native execution metadata retained |

Every success follows `Theory → backend source → actual FormulaTracer frontend → reference contract → observed IR → normalized comparison`. Generator-expected IR alone is not accepted. The previous six non-successes are now deterministically classified as five `NORMALIZATION_GAP` cases and one `FRONTEND_LIMITATION`; none is silently accepted.

## Limitations and robustness checks

Six targeted mutations—sum/mean, axis change, operand swap, transpose removal, dtype narrowing, and where-branch swap—were detected by normalized theory comparison. The private research-scale corpus suite separately evaluated seven in-slice mutations after the comparator repair and detected all seven. Control-flow semantics remain protected by the existing conditional accumulation, branch identity, break/continue, and loop-carried-state regression suites.

The 100% library-call resolution metric includes reference-only and I/O-boundary contracts. It is intentionally separate from kernel-verified mappings, Mathematical-IR extraction, and end-to-end proof status. Remaining opaque calls include user-defined dynamic access, parser artifacts, path/UI helpers, and unsupported cross-language expressions; formalizing them as scientific-library mathematics would be incorrect.

No external checkout was needed for this batch. `external source retained = 0`.

## Readiness decision and next steps

The Python multi-library self-audit can proceed for the implemented seven-family smoke matrix. The next bounded work should add real Rust and C++ library lowerings behind the same backend interface, then replay the exact round-trip matrix. Shape work should focus on the 100 remaining entry-level cases where receiver types or axes are genuinely recoverable, without guessing dimensions.

The release gate is satisfied:

```text
CRITICAL_LIBRARY_FALSE_ACCEPTANCE_OPEN = 0
external source retained = 0
private research-scale corpus corpus modified = false
research data content read = false
```

## Open questions

- Which remaining custom opaque calls should receive user-authored contracts versus local-source inlining?
- Which Rust ndarray/Rayon and C++ std/Eigen lowering families should be implemented first for the next cross-language matrix?
- Can receiver/type propagation recover more xarray dimension names without relying on runtime data?
