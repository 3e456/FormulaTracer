# Architecture

The human YAML and C++ source are independent inputs. YAML becomes a Human
Algorithm IR; C++ is parsed by Clang and immediately lowered to stable
Implementation IR. Both lower into a bipartite Canonical Semantic Graph whose
value nodes and operation nodes are joined by role-labelled edges. LaTeX, DOT,
reports and Lean are generated from that graph.

The portable Python extractor is deliberately limited to the weighted-sum
golden subset. It is not a replacement for Clang and is excluded from the
complete-verification CLI. `verify-ir` accepts only `clang-libtooling`
provenance with the recorded compilation database and exact compile command.
IDs are content-derived, output ordering is deterministic, and all artifacts
carry schema/standard versions plus source, specification, and registry hashes.

Reduction order is semantic data. `accumulate`/`inner_product` use left-to-right
folds; `reduce` permits reordering and therefore cannot satisfy an ordered spec
without an additional algebraic/numeric contract.

Python execution representation is a separate semantic layer. Mathematical
Expression IR keeps abstract `Integer`, `Real`, and `Complex` domains;
`NumericExecutionType`, `NumericCast`, and `PromotionRule` record Python,
NumPy, xarray, or Dask execution details alongside it. Unresolved dtype
transitions are diagnostics and cannot strengthen a mathematical claim.

The IEEE-754 layer then classifies mathematical, numerical-execution, and
bitwise equivalence independently. It retains operation grouping, rounding,
special values, reduction order, and FMA assumptions; its Lean component uses
an abstract rounding/error contract instead of claiming a hardware model.

Parallel execution is another orthogonal layer. Scheduler and device policy,
map purity, reduction reordering, reproducibility, races, and cross-iteration
dependencies are retained without changing the Mathematical IR. Exact-domain
map/reduction claims and floating/bitwise execution claims have distinct
statuses.

Transformation application is permissioned rather than a global rewrite pass.
Only rules in the selected, versioned `TransformationSet` may connect theory to
implementation. Hard constraints are checked before selection objectives, and
the trace retains intermediate IDs, obligations, provenance, comparison
relation, and an unevaluated residual candidate.

Before Mathematical Expression IR lowering, Rich Implementation IR now carries
an explicit dependency graph. Resolved Clang AST relationships become stable,
role-labelled edges (`VALUE_DEPENDS_ON`, `INDEX_DEPENDS_ON`,
`CONDITION_DEPENDS_ON`, `LOOP_BOUND_DEPENDS_ON`, and related definition,
memory, control, recurrence, and result edges). Every edge records its source
and target node, source span, `RESOLVED` confidence, and `clang_ast`
derivation. The validator checks endpoints, output identity, operation arity,
loop facts, stores, conditions, and restricted cycles before output slicing.

Expression extraction walks this graph backwards from Store, Return, or a
registered output-producing algorithm call. Dead computations are excluded;
unresolved edges and unknown effects in the reached slice fail closed. Pattern
recognition over the resulting slice currently produces Map, IfThenElse,
FoldLeft, and TransformReduce. The old weighted-sum `analysis` facts remain for
legacy verifier diagnostics but are not the expression extractor's primary
path.

Implementation IR and Canonical Graph have separate interpreters. Differential
tests compare both with the actual C++ executable and independent Human
reference. This runtime evidence is reported separately from Lean refinement.
