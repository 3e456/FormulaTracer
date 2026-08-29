# FormulaTracer Large-Scale Self-Generation Assurance

## Technical summary

FormulaTracer generated a deterministic corpus of **336 theories across 28 families**, lowered the supported subset to **468 ephemeral source cases**, and independently re-extracted every case through the production frontend. The observed results were **192 exact round trips**, **264 equivalents under explicit reference/execution assumptions**, **12 fail-closed unresolved cases**, and **0 semantic divergences among capability-supported known-good cases**.

The adversarial release gate passes: **252/252 validated semantic-changing mutations were detected**, including 12 two-fault compositions, and **no mutated implementation was accepted as theory-equivalent**. All **120/120** alpha-renaming metamorphic variants were accepted. Therefore:

```text
CRITICAL_SELF_AUDIT_FALSE_ACCEPTANCE_OPEN = 0
```

One critical contract-projection defect was found and fixed during the run: PyTorch `dim` and `keepdim` were previously dropped by the generic reduction lowering. The fix is locked by a regression test and recorded in the versioned defect ledger.

## The observed pipeline agrees across supported ecosystems

The denominator for round-trip rates is the 468 sources actually generated and independently analyzed. Theory-only and reference-only capability entries are not counted as successful generation.

| Result | Cases | Share |
|---|---:|---:|
| Exact round trip | 192 | 41.03% |
| Equivalent under assumptions | 264 | 56.41% |
| Numeric execution difference only | 504 cross-library pairs | separately classified |
| Round trip unresolved | 12 | 2.56% |
| Semantic divergence | 0 | 0.00% |
| Frontend failure | 0 | 0.00% |

The 504 NumPy/JAX/PyTorch/CuPy backend pairs all produced equivalent canonical Mathematical IR. Their device, JIT, autograd, GPU, and reduction-order differences remain execution metadata and are not promoted to mathematical identity claims. For the scalar arithmetic subset, all 12 Python/Rust/C++ groups produced the same canonical mathematics.

| Backend | Generated | Exact | Under assumptions | Unresolved |
|---|---:|---:|---:|---:|
| Python explicit | 36 | 36 | 0 | 0 |
| Python loop | 24 | 12 | 0 | 12 |
| NumPy | 120 | 120 | 0 | 0 |
| JAX | 96 | 0 | 96 | 0 |
| PyTorch | 72 | 0 | 72 | 0 |
| CuPy | 96 | 0 | 96 | 0 |
| Rust explicit | 12 | 12 | 0 | 0 |
| C++ explicit | 12 | 12 | 0 | 0 |

The capability inventory covers 19 requested backends. Backends without a real lowering—Rust ndarray/Rayon/nalgebra/faer, C++ std/Eigen/Boost, and SymPy-specific families—remain `REFERENCE_ONLY` or `UNSUPPORTED`; they are not represented as generated successes.

## Adversarial changes fail closed

Mutation bases were restricted to cases that had already completed exact or assumption-qualified round trips. Each mutation retained its base theory, original observed IR, source hash, changed line, mutation family, and expected semantic impact.

| Assurance set | Cases | Accepted correctly | Rejected/detected correctly | False result |
|---|---:|---:|---:|---:|
| Semantic mutations | 252 | n/a | 252 | 0 false acceptances |
| Metamorphic alpha-renames | 120 | 120 | n/a | 0 false rejections |
| Two-fault compositions | 12 | n/a | 12 | 0 false acceptances |

Covered mutations include arithmetic operator changes, sum/mean/product substitutions, tensor operand swaps, comparison widening, approximation parameter changes, and dtype-narrowing composition. The generator's expected IR was never used as observed evidence; mutated sources were parsed again by the production frontend.

## Debugger localization is useful but not source-span complete

The semantic comparator identified the correct semantic node for **156 of 240** single-mutation cases (**65.00%**); 84 were explicitly unresolved. Exact source-span credit is **0/240** because Mathematical IR currently does not retain a per-operator source span after normalization. The harness deliberately does not infer a span from the known mutation location and then present that inference as debugger evidence.

This is not a false-acceptance issue—the semantic mutations were still rejected—but it is the clearest stabilization target before claiming source-level self-localization accuracy.

## Scope, definitions, and evidence boundaries

- `EXACT_ROUND_TRIP` means the independently observed canonical Mathematical IR equals the original theory under the core mapping.
- `EQUIVALENT_UNDER_ASSUMPTIONS` means the mathematics agrees while the library mapping is reference-contract evidence or execution assumptions remain.
- `ROUND_TRIP_UNRESOLVED` is fail-closed and contributes no acceptance evidence.
- `SELF_GENERATED_GROUND_TRUTH` identifies theory/mutation ownership; it is not kernel proof.
- Generated source is ephemeral. The repository retains recipes, theory IDs, deterministic seed `20260827`, generator version `large-self-audit-v1`, hashes, results, and regression fixtures only.

The corpus has 12 parameterized cases per family: four variations at each of `SIMPLE`, `MODERATE`, and `COMPLEX`. The full theory inventory includes arithmetic, reductions, map/filter/fold families, tensor transforms, approximation, probability/statistics, graph, and spatial theories. A source is generated only when a backend's capability is explicit.

## Methodology prevents generator self-confirmation

For each supported case, the audit path is:

```text
Original Theory
→ backend recipe
→ ephemeral source
→ production Python/Rust/C++ frontend
→ LibraryContract resolution
→ observed Mathematical IR
→ canonical projection
→ independent comparison
```

Cross-library comparisons use only independently observed canonical IR. Cross-language cases use the existing synthesis frontend round trip, then apply the same library-independent projection. Mutation validity is tied to a semantics-changing recipe and confirmed by an observed IR difference; no unresolved base case enters the false-acceptance denominator.

The earlier six control-flow synthesis gaps were re-executed. They remain **6 `STILL_UNRESOLVED`** and **0 false acceptances**; the harness does not relabel normalization/frontend gaps as true semantic divergence without independent proof.

## Approximation and probability claims remain bounded

Four representative approximation mappings—`numpy.diff`, `numpy.gradient`, `xarray.DataArray.diff`, and `xarray.DataArray.interp`—were recognized. Their exact discrete semantics and candidate approximation families are retained, while theorem binding remains `CONVERGENCE_PROOF_NOT_YET_ESTABLISHED`; Error IR and range enclosure correctly require additional assumptions and input ranges.

The probability audit covered one known uniform distribution and one user-defined uniform distribution with a sample-mean/Monte-Carlo target. Results were one `PROBABILITY_AUDIT_REFERENCE_CONTRACT` and one `PROBABILITY_AUDIT_EMPIRICALLY_SUPPORTED`. PRNG internals remain explicitly out of proof scope.

## Limitations and robustness

- Python loop finite-sum normalization remains unresolved in 12 cases and is not counted as acceptance.
- Library-specific Rust and C++ scientific backends are capability records, not generated implementations, until real lowering rules exist.
- Exact debugger source spans cannot be measured from current normalized IR.
- Peak memory was not measured because enabling allocation tracing materially distorts this short run; wall time and per-family/backend time are retained.
- GPU kernels, JIT/compiler correctness, PRNG internals, and library implementation correctness remain outside the proof boundary.

The full run completed in **3.34 seconds** at approximately **140 analyzed cases/second** on this host. These numbers are diagnostic, not a benchmark guarantee.

## Final regression preserved the previous assurance boundary

The complete Python regression finished with **410 passed and 36 subtests passed**. The focused control-flow, library-contract, harvester, shape/dimension, Rust, and C++ selection finished with **97 passed**. `lake build` completed successfully, and the Lean source scan found **0 `sorry` / `admit` / `axiom` occurrences**. All 15 self-audit JSON artifacts parsed and the summary passed its Draft 2020-12 schema; `git diff --check` passed.

The final private research-scale read-only revalidation covered **20+ projects and 170+ source files**. Detailed corpus metrics and findings remain private. The public aggregate records that no critical false acceptance was observed and no research data content was read or modified.

## Recommended next steps

1. Carry per-operator source spans through Mathematical IR normalization and rerun debugger localization.
2. Formalize Python loop finite-sum normalization before promoting that backend capability from assumption-qualified to supported.
3. Add real Rust ndarray/Rayon/nalgebra and C++ Eigen/std lowerings one family at a time; keep the current reference-only status until each round trip exists.
4. Move to the final Release Candidate audit while retaining `CRITICAL_SELF_AUDIT_FALSE_ACCEPTANCE_OPEN = 0` as a hard release gate.

## Further questions

The main open assurance question is whether source-span propagation can be added without perturbing normalized expression identity. A second is which library-specific Rust or C++ backend provides the highest real-research coverage gain for the next bounded lowering increment.
