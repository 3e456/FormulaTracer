# Reconstruction closure

FormulaTracer reconstructs generated implementations through one Rust-owned
pipeline:

```text
Theory IR -> typed structural quotient
Generated source -> frontend -> Implementation IR -> Algorithm IR
            -> reconstructed Mathematical IR -> typed structural quotient
            -> typed isomorphism -> Exact E-Graph / Relation Graph
            -> assumptions / obligations / error / range
            -> ReconstructionResult
```

`ReconstructionResult` is the canonical semantic object. Python exposes only a
thin projection. Its statuses distinguish exact reconstruction, equivalence
under assumptions, approximation, discretization, truncation, sampling,
algorithmic realization, composite relation chains, and correctly unresolved
analysis.

## Structural quotient and witnesses

The quotient may remove source spans, internal IDs, alpha-renamed binders,
safe association changes, and fact-gated commutative permutations. It preserves
symbol, binder, index, node, permutation, association, and blocked-ambiguity
witnesses. Structural isomorphism is a comparison aid and never proves equality.
Exact acceptance additionally requires canonical identity or an explicit Exact
E-Graph result.

## Temporaries and loops

Temporary expressions are inlined from their dependency graph only when there
is no mutation, aliasing, side effect, exception sensitivity, evaluation-order
sensitivity, or unknown call effect. Otherwise the result is
`INLINE_RECONSTRUCTION_UNRESOLVED`.

Loops are reconstructed through `Loop -> Fold -> Reduction`. Additive and
multiplicative folds become finite sums or products only when identity,
termination, bounds, update contribution, and side-effect conditions are
established. Bounds, axes, order, and IEEE-754 execution metadata are not
quotiented away.

## Provider and relation projection

A provider projection records provider/version/language, operation, mathematical
target, types and shapes, assumptions, obligations, relation, error model, and
provenance. Retrieval is not reconstruction. A candidate contract is used only
after an implementation has independently established that the provider call is
the observed algorithm.

Non-exact edges remain in the Relation Graph. Sampling followed by FFT
realization, for example, is a two-edge composite chain and is never merged into
an exact e-class. A reconstructed relation does not imply a certified error
bound; absent error evidence remains absent.

## Correctly unresolved policy

Missing generated source, ambiguous binders, unsafe temporary effects,
unsupported mathematics, unproved assumptions, and open obligations produce a
machine-readable blocking stage and reason. Runtime numerical agreement cannot
upgrade these outcomes. False acceptance is less acceptable than an explained
unresolved result.

The fixed external-21 artifacts predate source retention for generated programs.
They retain theory, planning, provider candidates, and algorithm contracts, but
not generated source or independently observed Implementation IR. FormulaTracer
therefore reports those cases as `CORRECTLY_UNRESOLVED`; it does not reconstruct
from provider retrieval alone. The independent self-generated corpus exercises
the new exact, inline, loop/fold, provider, relation, and negative-mutation paths.

Machine-readable evidence is under `output/reconstruction_closure/`.
