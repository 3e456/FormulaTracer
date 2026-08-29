# Phase 8: Residual / Error IR

FormulaTracer now keeps mathematical discrepancy and numerical execution error as separate evidence.
`ResidualExpression` is derived only from the independently extracted implementation and theory IR. Runtime samples are never promoted to proof evidence.

The certificate records:

- the scalar or componentwise residual, including shape and named xarray dimensions;
- an explicit error metric and tolerance policy;
- approximation/discretization bounds imported by reference from Phase 7 proofs;
- unresolved rounding, cast, overflow, underflow, and parallel-order components;
- library reference-only semantics as proof obligations, never as an invented numeric epsilon;
- a graph enclosure and a no-cancellation triangle-inequality composition policy.

An exact symbolic equivalence yields `EXACT_ZERO_RESIDUAL` and an `EXACT_ZERO_BOUND` for the mathematical residual. This does not erase unresolved execution effects. Thus a verified approximation bound with unresolved floating-point effects is reported as `PARTIAL_ERROR_BOUND_VERIFIED` / `TOTAL_ERROR_BOUND_UNRESOLVED`.

The `python-certificate` command accepts `--error-specification FILE.json`. Relative error requires `reference_nonzero: true`; mixed absolute-relative error requires both tolerances. The generated LaTeX certificate contains a dedicated residual and error analysis section.
