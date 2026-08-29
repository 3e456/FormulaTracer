# Mathematical Knowledge Registry

FormulaTracer stores reusable mathematical semantics in versioned YAML under
`registry/mathematical_knowledge/`.  Each entry declares both expressions, its
relation kind, direction, preconditions, domain/type/shape constraints,
algebraic structure, cost, retrieval motifs, provider hints, and evidence.

Exact e-class union is limited to `EXACT`, `EXACT_UNDER_ASSUMPTIONS`,
`DEFINITIONAL`, and `IDENTITY`. Approximation, discretization, truncation,
sampling, transformation, and algorithm-realization entries remain relation
knowledge and cannot establish exact equality.

Registry validation rejects missing reference evidence, disabled directions,
unbound variables in exact replacement templates, and an unbounded reverse
rewrite whose source is a bare pattern variable. The latter prevents rules such
as `x + 0 <-> x` from expanding every AST field; the reducing direction is
sufficient because a successful e-graph union is symmetric.

Candidate selection is high-recall and motif/provider-hint driven. Selection is
not proof: selected exact rules still require explicit authorization and fact
discharge, while non-exact relations never enter the exact e-graph.

The current foundation covers algebra, exp/log, trigonometric and hyperbolic
identities, combinatorics, sums, calculus, series, Fourier, linear algebra,
probability, logic/piecewise, sets/maps, complex values, polynomials,
equation/solver relations, units, and fixed/unbounded bit semantics.

`run_knowledge_assurance()` instantiates every entry, checks the intended
positive result, removes required conditions, applies a semantic mutation, and
reports e-graph growth and all false-acceptance gates. Positive misses are
reported separately from false acceptance.
