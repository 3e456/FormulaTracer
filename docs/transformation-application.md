# TransformationSet application

Phase 5 connects an authoritative Theory Expression to an independently
extracted Implementation Expression through an explicitly selected,
versioned `TransformationSet`:

```text
Theory → allowed rules → transformed theory → implementation comparison
```

No set means no transformation permission. A rule outside the selected set is
recorded as `RULE_NOT_ALLOWED`, including an exact normalization that would
otherwise happen implicitly. Candidate ranking never overrides authorization
or a hard constraint.

## Application IR

`TransformationApplication` records the rule and source/target expression IDs,
parameters, `EXACT`/`EXACT_UNDER_ASSUMPTIONS`/`APPROXIMATION` kind, assumptions,
hard-constraint checks, discharged and remaining obligations, rule/reference
provenance, authorization, and status. `TransformationTrace` preserves all
steps. `TransformationResult` adds applied/rejected rules, the transformed
theory, formal comparison relation, selection evidence, and a
`ResidualCandidate`.

Supported comparison relations are `EXACT_EQUAL`,
`EQUIVALENT_UNDER_ASSUMPTIONS`, `DISCRETIZATION_OF`, `APPROXIMATION_OF`,
`REFINEMENT_OF`, `PARTIAL_IMPLEMENTATION_OF`, `INCONSISTENT_WITH`, and
`NOT_COMPARABLE`.

Built-in exact applications cover alpha renaming, finite-sum normalization,
neutral-element elimination, and simple additive/multiplicative commutation.
Division-to-multiplication is classified `EXACT_UNDER_ASSUMPTIONS` and exposes
the nonzero-denominator obligation. Existing forward/central first-derivative
rules can now be applied; the transformed stencil must match the implementation
graph. Their error remains `BOUND_NOT_YET_EVALUATED` and
`APPROXIMATION_ERROR_NOT_YET_PROVEN` in this phase.

## Enforcement and selection

Processing order is fixed:

1. selected-set authorization;
2. source-pattern and hard constraints (finite domain, derivative order,
   required observable, and supplied domain/shape/axis/nonzero evidence);
3. feasible-candidate selection using `minimum_cost`, `minimum_error`,
   `frequency_fidelity`, `stability`, or `locality`;
4. template application and expression-graph comparison.

A different finite-difference stencil is inconsistent. Numeric samples are
never proof evidence. Reference contracts may be attached through the rule's
`library_contract` provenance field, ready for gradient/interpolation/integral
families in later phases.

`python-certificate` accepts `--transformation-set`, repeatable
`--transformation-rule` and `--transformation-assumption`, optional JSON
`--transformation-context`, and `--selection-profile`. JSON and LaTeX show the
original theory, every arrow, transformed theory, implementation, relation,
and remaining assumptions/error obligations.

## Lean boundary

Six kernel theorems cover alpha renaming, finite fold/sum identity, additive
and multiplicative neutral elements, and additive and multiplicative
commutation. Approximation error and conditional division soundness are not
promoted to unconditional kernel claims. The latter remains explicitly
verified under assumptions; approximation bounds are Phase 6–7 work.
