# Physics foundation

FormulaTracer's physics support is a composition layer over the existing
Mathematical IR, Relation Graph, Error/Range engines, unit algebra, provider
contracts, provenance, and Lean bridge. It is not a catalogue of physical laws
and it does not claim that a model describes nature.

The versioned pack at
`registry/scientific_foundations/physics-v1.json` contains three distinct kinds
of entry:

- **Definition** expands a high-level name (for example, divergence) into
  existing derivative, indexed-value, finite-sum, tensor, or integral IR.
- **Theorem** relates existing expressions and carries every regularity,
  domain, shape, orientation, frame, or convergence condition needed before
  the relation can be used.
- **Realization** relates a mathematical object to an algorithm. Approximation,
  discretization, and algorithmic-realization edges never enter an exact
  e-class.

The Rust semantic core validates packs and decides theorem/realization
applicability. Missing facts remain proof obligations. Python, C, and C++
bindings do not make these decisions.

## Assurance boundary

Lean currently kernel-checks the algebraic cancellation obligations used by
curl/divergence identities and the complex-subalgebra multiplication embedding
into quaternions. The registered Gauss, Stokes, Euler–Lagrange, Noether,
Legendre, frame, and transform relations remain conditional theorems; they are
not labelled kernel verified.

Generated implementations are not trusted because FormulaTracer generated
them. Production-capable examples are emitted as source and independently
re-read by the normal Python, Rust, or C++ frontend before a round-trip result
is reported.

## Fail-closed cases

FormulaTracer returns unresolved rather than guessing when any of the following
is missing or inconsistent:

- regularity for mixed partials;
- domain, boundary, or orientation evidence for Gauss/Stokes;
- compatible physical dimensions or frames;
- Euler angle convention metadata or a nonsingular chart;
- unit quaternion/nonzero-normalization evidence;
- transform convention or Laplace region-of-convergence evidence;
- Dask execution backend/tree information needed for a floating reduction
  bound.

Finite differences, finite volumes, quadrature, adaptive ODE solvers, and
floating implementations are kept separate from their continuous mathematical
targets.

## References

The machine-readable reference and license modes are in
`output/physics_foundation/reference-inventory.json` and
`output/physics_foundation/realization-license-audit.json`. No upstream source
or documentation text is retained in this repository.
