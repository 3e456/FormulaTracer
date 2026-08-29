# Canonical code synthesis and round-trip verification

FormulaTracer lowers a `TheorySpecification` to a small `AlgorithmIR`, emits
readable canonical Python, Rust, or C++, then sends the source back through the
existing frontend. A generator claim alone is never verification.

```python
theory = TheorySpecification("y", expression_ir, ["x"])
generated = tracer.synthesize(theory=theory, language="python")
assert generated.round_trip.status == "ROUND_TRIP_VERIFIED"
```

Supported emission includes arithmetic, comparisons, `IfThenElse`, elementary
functions, finite reductions/folds/transform-reduce statement forms, and
explicitly authorized basic finite differences. Approximation families not in
`allowed_approximations` are rejected before generation. The pipeline retains
theory, transformed theory, Algorithm IR, expected implementation IR, generated
source, observed implementation IR, and observed Mathematical IR.

Round-trip comparison normalizes only provenance, qualified symbol spelling,
and integral floating literals. It does not silently equate loop bounds,
reduction orders, axes, or approximation families. The first failed stage is
reported as `FIRST_SYNTHESIS_DIVERGENCE`.

`RepairCandidate` is limited to local operator/constant/axis/reduction/family
differences. It does not edit the user's source. A repaired copy must pass a new
frontend analysis, debugger run, Lean/error/range path, and E2E status before it
becomes `REPAIR_VERIFIED`.
