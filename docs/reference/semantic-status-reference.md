# Status, Relation, and Evidence Reference

The complete implementation-derived value lists are in
`output/public_function_reference/{status,relation,evidence}-reference.json`.

## Verification statuses

- `EXACT_EQUALITY`: canonical or kernel-backed exact equality.
- `CERTIFIED_WITHIN_ERROR_BOUND`: a certified bound exists and applies.
- `CERTIFIED_INTERVAL_OVERLAP`: certified enclosures overlap; this is not equality.
- `EMPIRICALLY_WITHIN_TOLERANCE`: runtime observation only.
- `OUTSIDE_CERTIFIED_BOUND`: observed result violates the applicable bound.
- `BOUND_NOT_AVAILABLE`: the relation may be known but no certified bound exists.
- `UNRESOLVED`: required type, domain, effect, contract, or proof information is absent.

## Relations

Only `EXACT_EQUALITY` and `EXACT_UNDER_ASSUMPTIONS` are exact. `APPROXIMATION_OF`,
`DISCRETIZATION_OF`, `TRUNCATED_TO`, `SAMPLED_AS`, and
`ALGORITHMICALLY_REALIZED_BY` remain Relation Graph edges and never merge exact
e-classes.

## Evidence

`KERNEL_VERIFIED` is strongest and Lean-specific. `FORMALLY_DERIVED`,
`REFERENCE_CONTRACT`, provider-backed, runtime, structural, and `USER_DECLARED`
evidence each describe a different boundary. Users should resolve missing
assumptions/contracts or inspect opaque nodes rather than treating `UNRESOLVED`
as verified.

