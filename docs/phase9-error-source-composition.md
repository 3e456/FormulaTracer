# Phase 9: Error Source Composition

Phase 9 propagates Phase 8 local error components through a conservative composition graph. It never assumes sign cancellation, independence, or a sampled value range.

Implemented rules include addition/subtraction, exact scalar multiplication, product bounds with cross terms, quotient bounds under denominator separation, integer-power propagation, Lipschitz function contracts, linear maps, finite sums/means, maximum bounds, and selected norm conversions. Product, quotient, power, function, linear-map, mean, and norm rules fail closed when their range, sensitivity, count, or dimension contracts are missing.

Every composition records source components and bounds, semantic causes, dependency status, the propagation rule, a Lean theorem reference where available, assumptions, and the resulting known bound. A local approximation error remains one semantic cause as it passes through downstream nodes. Shared causes are not treated as independent. Exact cancellation is permitted only for the same cause with exactly opposite coefficients and an explicit cancellation request. RSS is rejected without formally proven independence.

The certificate separates:

- `known_output_bound`: the sum or propagated form of resolved components;
- `total_output_status`: unresolved while rounding, cast, parallel-order, or another unbounded component remains;
- `error_budget`: known-bound tolerance status and the separate total-tolerance status;
- `FINITE_ERROR_ENCLOSURE_INVALIDATED`: graph status used when potential overflow has not been excluded.

`python-certificate` accepts `--error-propagation FILE.json`. Contracts in that file may provide exact component coefficients, value ranges, denominator separation, dimensions, operator norms, or a `FunctionSensitivityContract`. These values are treated as explicit audit contracts, never inferred from runtime samples.
