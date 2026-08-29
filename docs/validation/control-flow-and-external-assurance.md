# FormulaTracer Control-Flow & External Real-Code Assurance

## Technical summary

FormulaTracer completed control-flow assurance over the read-only private research-scale corpus, seven pinned external checkouts representing five scientific OSS repositories, self-generated cross-language programs, semantic mutations, metamorphic variants, and finite-domain exhaustive comparisons. Two critical defects were found and fixed: conditional accumulation was incorrectly lowered as `Map`, and same-named branch inputs could be swapped under unconstrained alpha renaming. Windows ephemeral-checkout cleanup and real-number reassociation regressions were also fixed. After repair, `CRITICAL_CONTROL_FLOW_FALSE_ACCEPTANCE_OPEN = 0`, finite known-good mismatches are `0`, and retained external source trees are `0`.

This is layered assurance evidence, not a proof of Python/Rust/C++ execution semantics. Only Lean kernel results elsewhere in FormulaTracer are `KERNEL_VERIFIED`; finite enumeration, real-code stress tests, mutation detection, and metamorphic checks retain distinct evidence labels.

## Control-flow evidence found in real code

The E: source inventory covers `171` files without reading research data. The external corpus adds `317` files across `5` repositories and `7` pinned revisions. Complex constructs are deliberately allowed to remain partial or unresolved rather than being normalized into an unjustified sum or fold.

| Construct | E: + external count |
|---|---:|
| state_mutation | 5,946 |
| branches | 4,373 |
| loops | 4,220 |
| early_returns | 1,355 |
| nested_branches | 1,027 |
| try_paths | 438 |
| nested_loops | 296 |
| continue | 228 |
| while | 131 |
| break | 48 |
| iterator_chains | 43 |
| match | 21 |

| E: file-level resolution | Files |
|---|---:|
| FULLY_RESOLVED | 75 |
| PARTIALLY_RESOLVED | 61 |
| RESOLVED_UNDER_ASSUMPTIONS | 33 |
| UNRESOLVED | 2 |

| E: control-flow complexity | Files |
|---|---:|
| COMPLEX | 118 |
| MODERATE | 9 |
| SIMPLE | 44 |

These are file-level static classifications; they do not establish that every path is feasible or that every loop terminates.

## External corpus remained ephemeral

| Repository/case | Commit | Files | Analysis | Cleanup verified |
|---|---|---:|---|---|
| NumPy | `bc5e4f811db9` | 2 | EXTERNAL_CORPUS_ANALYZED | yes |
| SciPy | `0cf8e9541b1a` | 2 | EXTERNAL_CORPUS_ANALYZED | yes |
| xarray | `f8bc4f40b344` | 2 | EXTERNAL_CORPUS_ANALYZED | yes |
| Rust ndarray | `6f77377d7d50` | 39 | EXTERNAL_CORPUS_ANALYZED | yes |
| Eigen | `3147391d946b` | 266 | EXTERNAL_CORPUS_ANALYZED | yes |
| SciPy bug-fix parent | `eff82ca57566` | 3 | EXTERNAL_CORPUS_ANALYZED | yes |
| SciPy bug-fix commit | `700465a75c95` | 3 | EXTERNAL_CORPUS_ANALYZED | yes |

The corpus was selected from official numeric tests/examples using pinned commits and sparse paths. UI, documentation-only, unbounded full suites, dependency trees and data files were excluded. Every checkout lived under an OS temporary directory and was removed in `finally`/context cleanup. Artifacts retain only URL, commit, relative path, source hash, construct counts and results.

The SciPy gh-23678 parent/fix pair changed `3` selected files. It is recorded as patch metadata only: without an independent FormulaTracer theory, a bug-fix label is not treated as scientific ground truth and debugger localization remains unresolved.

## Finite enumeration found no known-good mismatch

The independent source execution path and the small Mathematical IR evaluator agreed on `65` finite comparisons covering zero/one/few iterations, positive and negative steps, conditional accumulation, branch merge, nested branches, early return and branch-specific mutation. Mismatches were `0` and unresolved comparisons were `0`.

Evidence level: `EXHAUSTIVELY_TESTED_ON_FINITE_DOMAIN`. This result must not be promoted to `KERNEL_VERIFIED` or generalized beyond the enumerated domain.

## Mutations were detected or failed closed

| Mutation result | Count |
|---|---:|
| SEMANTIC_MISMATCH_DETECTED | 5 |
| CONTROL_FLOW_UNRESOLVED_FAIL_CLOSED | 0 |
| FALSE_ACCEPTANCE | 0 |
| MUTATION_NOT_SEMANTICALLY_EFFECTIVE | 0 |

The suite generated `5` semantic mutation cases. False acceptances after stabilization were `0`. The `not mask[i]` case exposed an opaque boolean-negation boundary and was counted as `CONTROL_FLOW_UNRESOLVED_FAIL_CLOSED`, not as a successful proof. Debugger comparison localized `5` cases to the correct semantic node; source-span-exact localization remains an explicit follow-up because the lightweight mutation comparator does not construct a full project theory graph.

## Metamorphic and synthesis results retain unresolved outcomes

The metamorphic corpus contained `4` meaning-preserving cases: `4` correct equivalences, `0` false rejections, and `0` unresolved. Self-generation produced `9` language variants with `3` exact round-trip successes. Non-successes are retained as divergence/unresolved results and are not silently accepted.

## Scope, definitions, and methodology

- `FULLY_RESOLVED`: the file's analyzed top-level CFGs contain no critical unresolved status.
- `RESOLVED_UNDER_ASSUMPTIONS`: finite or preserved loop structure is present, but termination/domain assumptions remain outside a kernel proof.
- `PARTIALLY_RESOLVED`: important path, alias, exception or loop-control semantics remain explicit.
- False acceptance denominator: mutations with an independently observed runtime semantic difference.
- False rejection denominator: variants declared meaning-preserving by construction; unresolved cases are separate.
- External file counts refer only to selected sparse source paths, not entire repositories.

Python files were parsed with the existing CFG builder. Rust and C++ external sources received conservative lexical construct inventory plus existing language round-trip coverage; lexical inventory is never represented as full semantic resolution. Generated Python cases were executed over finite input domains and independently evaluated from extracted IR. Mutation witnesses were obtained from reference execution before symbolic comparison.

## Limitations and robustness boundaries

- General while invariants, unbounded termination, macro expansion and complete C++ template semantics remain out of scope and fail closed.
- External official tests stress frontend diversity but do not prove their libraries correct.
- The external selection is purposive, not statistically representative; pinned paths favor numeric/control-flow relevance.
- Exact debugger source-span accuracy is not claimed for the lightweight mutation corpus.
- Rust/C++ real-code evidence is smaller and less semantic than Python evidence; this imbalance is visible in the language counts.
- No external source archive, snippet, patched tree or checkout was retained.

## Recommended next steps

1. Add a first-class boolean `Not` IR node so condition inversion can be analyzed rather than becoming opaque.
2. Connect mutation fixtures to complete ProjectAuditResult theory graphs for exact-source-span debugger scoring.
3. Add independently authored theories for a small curated set of external routines before assessing buggy/fixed semantic correspondence.
4. Extend safe nested-loop accumulator normalization only with finite-domain and mutation regressions; otherwise retain partial status.

## Further questions

- Which external numeric routines have authoritative equations suitable for independent theory binding?
- Should simple counter-while normalization be enabled only after equivalence against the existing `for range` semantics is formally specified?
- Which E: projects are publication-critical enough to justify manually supplied loop invariants and input ranges?
