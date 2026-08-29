# IEEE-754 and concrete numerical execution

Phase 3 records floating execution semantics without rewriting the exact
Mathematical Expression IR. Every certificate now separates:

- `MATHEMATICAL_EQUIVALENCE`: equality of the extracted and registered
  mathematical expressions;
- `NUMERIC_EXECUTION_EQUIVALENCE`: equality under recorded dtype, grouping,
  rounding, evaluation-order, and FMA contracts;
- `BITWISE_EQUIVALENCE`: identical executable bit patterns. This is
  `NOT_APPLICABLE` when one side is an abstract theory formula.

Consequently, `(a + b) + c` and `a + (b + c)` may be mathematically equivalent
while numerical execution equivalence remains unestablished. NumPy/xarray/Dask
reductions and tensor contractions similarly retain a
`FLOAT_REDUCTION_REORDERING` risk unless their concrete ordering is contracted.

## Recorded execution contract

For binary16, binary32, and binary64 representations, the analysis records
radix, significand precision, exponent width, NaN, positive and negative
infinity, signed zero, and subnormal support. Each reached arithmetic operation
records its source span, evaluation-order category, rounding mode, exceptional
values, overflow/underflow possibility, and FMA status. Actual NaN, infinity,
negative-zero, and binary64-subnormal inputs are noted without embedding the
full input array in the report.

The default rounding contract is `ROUND_TO_NEAREST_TIES_TO_EVEN`; callers may
select another supported mode or `UNKNOWN` with `python-certificate
--rounding-mode`. `UNKNOWN` is fail-closed in `STRICT`, while `REPORT_ONLY`
still emits the certificate. Explicit `fma` is distinguished from an ordinary
multiply followed by add. Backend FMA contraction for library kernels remains
unresolved rather than inferred.

This phase does not claim a platform bit-for-bit replay, emulate every IEEE
exception flag, or prove the hardware implementation. Those require a pinned
runtime/backend contract. The restricted Python executor also remains evidence
only; a declared `float32` dtype does not cause its Python-list interpreter to
masquerade as NumPy float32 execution.

## Lean boundary

`CppAudit.Semantics.FloatingPoint` defines an abstract rounding function and an
error-bound contract. Lean proves that evaluated addition stays within the
contract and that exact rounding recovers mathematical addition. IEEE-754
encoding and hardware behavior are deliberately outside the kernel model.
