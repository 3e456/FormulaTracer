# Phase 11: Theory-to-artifact end-to-end enclosure

FormulaTracer creates one `EndToEndVerificationClaim` for each selected output.
The claim composes existing evidence; it does not reinterpret an observed value,
a reference contract, or a Phase 10 interval as a stronger proof.

```python
from formulatracer import FormulaTracer

result = FormulaTracer("model.py").analyze(
    ranges={"x": (1, 2)},
    output_ranges={"y": (5, 8)},
    observed_results={"y": 6.5},
)
output = result.get_output("y")
print(output.end_to_end_status)
print(output.proof_chain)
```

## Claim model

The public IR consists of `EndToEndEnclosure`,
`EndToEndVerificationClaim`, `EndToEndProofChain`, `VerificationLayer`,
`ArtifactEnclosure`, and `EnclosureEvidence`. The claim retains independently
extracted theory and implementation expressions, transformation and
approximation evidence, value/error/true-value enclosures, execution semantics,
FFI and serialization boundaries, artifacts, assumptions, obligations, and the
complete proof chain.

Every proof-chain edge records its rule, status, assumptions, and any Lean
theorem or reference contract. Assumptions are deduplicated without losing their
authority (`PROVEN`, `PROVIDED`, `REFERENCE_CONTRACT`, or `UNRESOLVED`), and
`assumption_dependencies` identifies the layer or theorem that consumes each
assumption.

## Verification layers

The verification matrix reports these layers separately:

- `THEORY`, `IMPLEMENTATION`, and `THEORY_IMPLEMENTATION`
- `TRANSFORMATION` and `APPROXIMATION`
- `RANGE` and `ERROR`
- `NUMERIC_EXECUTION` and `PARALLEL`
- `FFI`, `SERIALIZATION`, and `ARTIFACT`
- `LEAN`

Only critical layers participate in the final promotion rule. All critical
layers must be verified for a fully verified status. A missing rounding model,
unresolved FFI mapping, serialization cast, or unknown critical error source
therefore keeps the result partial or unresolved even if its Phase 10 range is
verified.

Final statuses are `END_TO_END_KERNEL_VERIFIED`,
`END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS`,
`END_TO_END_ENCLOSURE_VERIFIED`,
`END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS`,
`PARTIAL_END_TO_END_VERIFICATION`, `END_TO_END_UNRESOLVED`, and
`END_TO_END_FAILED`.

## Error completeness and execution

The error completeness check compares critical-path components with the
components included in the total bound. It recognizes approximation,
discretization, rounding, cast, overflow, underflow, parallel-order, FFI,
serialization, and input-uncertainty sources. Shared semantic-cause identifiers
are deduplicated before composition. Unknown or omitted sources cannot produce a
complete model. Theory/model uncertainty is explicitly separate and defaults to
`MODEL_ERROR_NOT_IN_SCOPE`, not a silent zero bound.

Mathematical equivalence and concrete numeric execution are distinct. Exact-real
execution may promote an exact chain; floating execution requires appropriate
rounding, cast, overflow, underflow, and parallel-order evidence. A runtime
sample is recorded as `OBSERVED_VALUE_WITHIN_CERTIFIED_RANGE` evidence only. A
sample outside the certified range is `OBSERVED_VALUE_OUTSIDE_CERTIFIED_RANGE`
and fails the claim.

## Artifacts and language boundaries

An `ArtifactEnclosure` keeps the path, format, payload symbol/dataset variable,
stored dtype, payload value/error enclosure, serialization contract,
materialization status, and optional SHA-256 hash. File existence establishes
only `ARTIFACT_MATERIALIZED`. Payload correctness requires a value-preserving
serialization contract; conversions remain explicit Error IR sources.

Python, Rust, C++, and joined Python-to-native routes use the same common result
model. An unresolved representation mapping at an FFI boundary is never skipped.
Claims remain independent across outputs and roots; the project exposes an
aggregate status and coverage counts without turning a verified sibling into a
failure.

## Lean and certificate boundary

`CppAudit.EndToEnd` supplies composition lemmas for exact chains, nested
enclosures, value-plus-error enclosures, finite component bounds, and residual
decomposition. Lean proves the mathematical composition after receiving the
explicit completeness premise. Python's metadata assertion that the enumerated
component list is complete is intentionally not described as kernel-verified.

JSON retains exact outward-rounded endpoints and raw IR. LaTeX uses the
mathematical renderer, a readable path representation, and rounded display
decimals without narrowing the stored enclosure. The certificate distinguishes
overall audit status from verified range/enclosure subclaims and lists every
remaining assumption and obligation.

## Current limits

The implementation composes evidence already produced by the language
frontends and Phase 6--10 analyzers. It does not prove compiler correctness,
hardware IEEE-754 conformance, arbitrary serializer implementations, arbitrary
FFI layouts, probabilistic error models, or completeness of an unenumerated
physical model. Those boundaries remain explicit obligations or reference
contracts.
