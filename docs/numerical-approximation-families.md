# Numerical approximation families

Phase 6 represents numerical methods by semantic family, independently of a
particular Python API.  The registry is
`registry/approximation_families.yaml` and validates against
`schemas/approximation-family.schema.json`.

## Exact and approximate semantics

`DiscreteDifference`, `FiniteDifference`, `Quadrature`, `Interpolation`, and
`Extrapolation` describe discrete computations.  A library reference contract
may establish those exact semantics.  A separate authorized transformation
connects the discrete computation to `Derivative`, `Integral`, or an
interpolation target through `DISCRETIZATION_OF` or `APPROXIMATION_OF`.

In particular, `numpy.diff` is exactly a discrete difference.  It is not a
derivative unless an allowed finite-difference transformation also identifies
the spacing and scaling.  Likewise, a trapezoidal weighted sum can have exact
discrete semantics while its relationship to an integral remains approximate.

## Registered families

Finite differences include forward, backward, central first derivative, and
central second derivative stencils.  Quadrature includes left/right rectangle,
midpoint, trapezoidal, and Simpson families.  Interpolation includes nearest,
linear/piecewise-linear, and multilinear families.  Axis positions and xarray
dimension names are separate metadata fields.

Every family records expected convergence order, required smoothness, the
convergence parameter and target, and provenance.  These fields have
`CONVERGENCE_PROOF_NOT_YET_ESTABLISHED`; they are not Lean-verified error
bounds.  Historical fixed `error_bound` rule fields are migrated at load time
to `selection_error_estimate` with `UNPROVEN_SELECTION_METADATA`.

## Fail-closed constraints

Finite-difference transformations require explicit spacing.  Central stencils
require an explicitly interior location, and one-sided boundary stencils must
be authorized when used at a boundary.  Quadrature requires a resolved
partition; composite Simpson additionally requires an even interval count.
Interpolation requires a resolved support/query domain relation, and known
extrapolation is classified separately.

Partial-expression transformation accepts a unique match or an explicit
`target_path`.  Multiple matches without a target path are rejected as
`AMBIGUOUS_TRANSFORMATION_MATCH`.

## Proof boundary

`CppAudit.Semantics.NumericalApproximation` defines the canonical discrete
formulas and proves by kernel reduction that generated formulas equal those
definitions.  It does not assert convergence, approximation error, or total
floating-point error.  Those obligations remain for Phase 7.
