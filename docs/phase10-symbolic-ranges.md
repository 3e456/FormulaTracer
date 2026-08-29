# Phase 10: Symbolic ranges and true-value enclosures

FormulaTracer performs range analysis after every language frontend has produced the common Mathematical Expression IR. Python, Rust, and C++ therefore share one interval engine and one result model.

```python
from formulatracer import FormulaTracer

result = FormulaTracer("model.py").analyze(
    ranges={
        "x": (0.0, 1.0),
        "temperature": {"lower": 250.0, "upper": 330.0,
                        "dimensions": ["time", "lat", "lon"]},
    },
    output_ranges={"weighted_score": (0.0, 1000.0)},
)
output = result.get_output("weighted_score")
```

The three range objects are intentionally distinct:

- `value_interval` encloses the extracted implementation expression.
- `error_interval` encloses only verified Error IR components.
- `true_value_enclosure` is the Minkowski sum of the first two and is total only when every error component is bounded by acceptable evidence.

Observed samples have status `NUMERICALLY_OBSERVED_ONLY` and are never proof. Missing denominator bounds, function domains, loop invariants, cast semantics, FFI representation mappings, or error bounds remain explicit `IntervalObligation` records.

The engine simplifies exact symbolic identities such as `x - x` before interval evaluation. Independent symbols with identical input ranges retain distinct identities. Numeric floating endpoints are rounded outward; symbolic endpoints remain Expression IR and carry assumptions. Named tensor dimensions and shape/cardinality evidence remain attached to `InputRange`.

Implemented rules cover addition, subtraction, multiplication, division away from zero, integer powers, negation, absolute value, min/max, exp/log/sqrt/sin/cos, branch pruning and path refinement, finite reductions, means, and componentwise dot/matmul bounds. General loop invariants, general real powers, per-index tensor ranges, full affine arithmetic, and automatic operator-norm inference remain future work.

Mathematical real ranges and execution ranges are separate. Known float32/float64 overflow invalidates a finite execution enclosure, and possible subnormal values create an obligation. Unknown casts, FFI conversions, and serializer dtype changes are fail-closed.

Lean module `CppAudit.Interval` supplies reusable general theorems for add, subtract, negate, scale, multiply, absolute value, finite sums, square bounds, positive-denominator division, and value-plus-error enclosure. Runtime observations and Python/Rust/C++ types are outside the kernel claim.
