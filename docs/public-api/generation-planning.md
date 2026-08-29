# Ranked generation planning

Provider discovery intentionally favors recall:

```text
whole expression + every subexpression
→ loose mathematical features and motifs
→ ranked top-K retrieval
→ top-K typed unification
→ selected rewrite packs
→ budgeted typed equality saturation
→ e-matching + typed substitution
→ rigorous adoption status
```

Default budgets are 100 retrieval candidates, 20 detailed unifications, five
full verifications, eight saturation iterations, 200 e-nodes, and 500 rule
applications per candidate. `search="broad"`
or `candidate_budget=` can expand retrieval. There is no similarity cutoff.

High-weight signals include reduction/integral structure, characteristic kernels,
bound/free-index topology, factorials, shifted evaluations, and complex
exponentials. Variable names and TeX spelling are intentionally weak signals.
The best-scoring subexpression path is retained, so an FFT-like subgraph within a
larger research expression can be proposed independently.

## Equality and relation boundaries

The registry is broad, but expression fingerprints and provider hints select
rewrite packs before saturation. Every registered rule records relation
kind, preconditions, domain/type/shape constraints, assumptions, evidence, and
inverse. Registry membership does not authorize use: `TransformationSet` remains
the authorization boundary. Conditional identities enter an e-class only after
the fact engine discharges every precondition and constraint.

Exact mathematical reassociation is kept distinct from floating-point execution
order. Approximation, discretization, truncation, sampling, and algorithmic
realization are relation-graph edges and never merge e-classes. Exhausted
saturation records `SATURATION_BUDGET_EXHAUSTED`; exhausted
candidate ranking records `PROVIDER_RETRIEVAL_MISS`.

## Selection and generation

`plan.select()` accepts only exact statuses, including `MATCH_WITH_EXACT_EGRAPH`.
`NON_EXACT_RELATION_CANDIDATE` is inspectable but cannot be selected as an exact
implementation. `plan.explain()` shows retrieval reasons
and rigorous status separately. One-shot `generate(auto_select=True)` uses the
same selection boundary and returns `SOURCE_GENERATED_UNVERIFIED`. Calling
`verify()` re-runs the normal language frontend and compares the observed IR.
