# Approximation proofs

Phase 7 separates Phase 6 reference convergence metadata from kernel-checked
error and convergence claims.  Proof objects are stored in
`registry/approximation_proofs.yaml` and validated by
`schemas/approximation-proof.schema.json`.

## Proof boundary

The Lean library proves finite error inequalities for forward, backward, and
central first differences, aggregation of local trapezoidal panel errors, a
Lipschitz nearest-neighbor bound, and a linear-interpolation remainder bound.
The common theorem `polynomial_error_bound_implies_convergence` proves that a
nonnegative `C |h|^p` bound with positive natural `p` converges to zero.

These are conditional theorems.  Taylor remainder, derivative-norm, domain,
partition, and local-panel hypotheses are explicit `ApproximationAssumption`
objects.  Supplying such an assumption does not turn it into an unconditional
claim: certificates report `KERNEL_VERIFIED_ERROR_BOUND_UNDER_ASSUMPTIONS`
until every assumption has machine-checked discharge evidence.

The finite-difference Taylor coefficients are checked against factorial
normalization in Lean (`2!⁻¹ = 1/2`, `3!⁻¹ = 1/6`).  The relevant mathlib
dependency is `Mathlib.Analysis.Calculus.Taylor.taylor_mean_remainder_bound`.
Connecting every source program's `ContDiffOn` and iterated-derivative bounds
to the registered Taylor remainder remains an explicit obligation; the
remainder is never inferred from numeric samples.

For composite trapezoidal quadrature, Lean proves that local panel bounds
aggregate to the global `((b-a) M / 12) h²` bound using
`Finset.abs_sum_le_sum_abs` and `b-a = n h`.  Establishing each local panel
bound from a source function's second derivative is still an assumption.

## Error categories

`APPROXIMATION_ERROR` is kept separate from `IEEE754_ROUNDING_ERROR` and
parallel reduction-order effects.  Phase 7 does not compose a total error.

`selection_error_estimate` is rejected as proof provenance.  Formal bounds
must name a Lean theorem and have a source hash.  Reference-only families are
never promoted merely because their expected order matches metadata.

## Coverage

`registry/approximation_proof_coverage.json` lists all twelve Phase 6 families.
Forward/backward/central-first difference, trapezoidal quadrature,
nearest-neighbor, and linear interpolation have kernel-checked conditional
bounds.  Central-second difference, rectangle, midpoint, Simpson, and
multilinear interpolation remain reference-only for Phase 7.
