# Semantic debugger and failure-region search

Detailed source-to-IR localization levels, `OriginSet`, mutation-ground-truth
metrics, safe minimal reproducers, and the false-localization policy are in
[`debugger-provenance.md`](debugger-provenance.md). Exact spans are reported only
when recorded operator/argument provenance supports them.

`ProjectAuditResult.debug()` compares the independently registered theory with
the extracted Mathematical IR. It removes matching semantic children and
returns the cause-side minimal mismatch, rather than sorting mismatches by
source line or reporting every downstream symptom.

```python
result = FormulaTracer("model.py").analyze(ranges={"x": (-10, 10)})
debug = result.debug()
search = debug.search_counterexamples(max_depth=6)
```

Each finding retains expected/actual semantics, a recorded source span, affected
outputs and artifacts, invalidated proof/range/error claims, a localized
subgraph, confidence, and a dependency trace. Source selection uses only IR
source correspondence, output-slice locations, and `ProjectDependencyGraph`
definition spans. It never searches source text.

The taxonomy distinguishes mathematical mismatches from dtype, reduction-order,
FFI, serialization, range, and error-bound failures. An unresolved FFI boundary
is a blocking point; localization does not guess across it. Runtime mismatches
remain `POSSIBLE_ROOT_CAUSE` evidence and cannot become a proven root cause.

Failure-region search uses symbolic interval evaluation, widest-interval
subdivision, and branch-preserving interval unions. A residual interval that
excludes zero is a `FAILURE_REGION_PROVEN`. Midpoint evaluations may produce a
`CounterexampleCandidate`, but its evidence level is always
`NUMERICALLY_CHECKED`; it is not a formal proof. General SMT solving, nonlinear
constraint solving, and exhaustive failure-region computation remain outside
this phase.
