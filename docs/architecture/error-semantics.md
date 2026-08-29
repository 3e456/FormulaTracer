# Error semantics

FormulaTracer's Error IR and propagation decisions are owned by
`formulatracer-core`. Python retains typed dataclasses and private reference
oracles for differential validation; production calls cross stable C ABI v1.

## Error IR

An analysis preserves residual expression, metric, error components, semantic
cause IDs, dependency state, bound expression, assumptions, evidence,
provenance, proof obligations, composition trace and graph enclosure. Absolute,
relative, mixed, componentwise and norm metrics are never collapsed into a
single untyped number.

Bound status distinguishes exact zero, kernel-verified, verified under
assumptions, reference-contract, symbolic, interval, empirical-only,
unevaluated, unresolved and invalid bounds.

## Dependency and RSS

The dependency states are `DEPENDENCE_UNKNOWN`, `SHARED_ERROR_CAUSE`,
`INDEPENDENT_COMPONENTS` and `INDEPENDENCE_PROVEN`. Repeated semantic cause IDs
become shared causes. Unknown dependency never becomes independence.

RSS is available only when `independence_proven=true`; otherwise the request is
rejected with `RSS_REQUIRES_PROVEN_INDEPENDENCE`. An accepted RSS result remains
a statistical relation under the explicit `INPUTS_INDEPENDENT` assumption; it
is not a worst-case absolute certificate.

## Propagation

- Add/subtract uses the triangle inequality. Sign does not imply cancellation.
- Exact cancellation requires an identical semantic cause and explicit
  authorization.
- Product bounds retain the cross term and require nominal magnitude bounds.
- Quotient bounds require a positive denominator lower bound greater than the
  denominator error. Possible zero crossing stays unresolved.
- Power propagation is limited to integer exponents with an input range.
- Function propagation requires a metric-compatible Lipschitz/sensitivity
  contract. A derivative alone is not a certified global bound.
- Linear-map, reduction and norm conversion rules retain their norm/count
  conditions.

## Proof obligations and certification

Missing ranges, denominator separation, sensitivity, dimensions, provider
proofs and numerical execution bounds are explicit `UNRESOLVED` obligations.
Removing an obligation or weakening a dependency cannot strengthen a result.
Numeric agreement and tolerance checks are runtime evidence only; they never
promote a symbolic or first-order estimate to a certified enclosure.

Each contribution retains source, origin, semantic cause, parent dependencies,
rule, assumptions, evidence and propagation trace. These fields form the
interface to the later native provenance/debugger migration.

The authoritative rule inventory is
`output/native_migration/error/semantic-rule-inventory.json`.
