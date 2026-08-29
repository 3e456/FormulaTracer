# Typed equality saturation

FormulaTracer uses three separate stores after broad mathematical retrieval:

```text
ExactEqualityEGraph  — proven exact representations of one expression
FactEngine           — type, shape, domain, index, period, convergence facts
RelationGraph        — approximation, discretization, truncation, sampling,
                       transform, and algorithm-realization edges
```

Only `EXACT`, `EXACT_UNDER_ASSUMPTIONS`, `ALGEBRAIC_EQUIVALENCE`, and
`IDENTITY_UNDER_ASSUMPTIONS` rules can union e-classes. A conditional rule is
blocked until every declared precondition, domain/type/shape constraint, and
assumption is present in the fact engine. Conflicting facts reject the union.

`registry/transformations/rewrite_catalog.yaml` is a discovery registry.
`registry/transformations/rewrite_packs.yaml` groups rules by mathematical motif.
Neither file authorizes a rewrite. The selected `TransformationSet` supplies the
allow-list intersected with fingerprint/provider-selected packs.

Versioned declarative entries in `registry/mathematical_knowledge/` use the same
authorization boundary. The exact engine loads only exact relation kinds and
checks declared algebraic structures in addition to ordinary facts. Registry
validation rejects unbound exact-template variables and unbounded reverse
pattern-variable expansion before saturation starts.

Saturation is bounded by iteration, e-node, and rule-application budgets. Budget
exhaustion is a visible non-verification result. The Python reference backend
stores complete Mathematical-IR terms as e-nodes while retaining the standard
`add`, `union`, `extract`, and `ematch` boundary; this permits a future native
`egg` backend without changing audit semantics.

Every exact merge records rule ID, source/target expression IDs, discharged
conditions, relation kind, and evidence. `replay_equality_trace` independently
re-applies each recorded rewrite. Similarity and saturation are still only
candidate mechanisms: final provider adoption also checks typed substitution,
library-contract obligations, shape/domain facts, and independent source audit.

Non-exact provider matches receive `NON_EXACT_RELATION_CANDIDATE`. In particular,
an integral matching the public shape of a quadrature API is not promoted to
`RIGOROUS_EXACT_MATCH`; the plan records `APPROXIMATION_OF` with its error-bound
obligations instead.

The architecture follows the additive e-graph/e-matching/extraction model
described by the [egg project](https://egraphs-good.github.io/egg/egg/tutorials/_01_background/index.html)
and keeps fact deduction separate in the spirit of the
[egglog project](https://github.com/egraphs-good/egglog). FormulaTracer does not
delegate its audit boundary to either project: authorization, condition
discharge, non-exact relation separation, and trace replay remain explicit here.
