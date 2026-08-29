# FormulaTracer mathematical API quickstart

FormulaTracer accepts TeX, canonical Mathematical IR, or source without making
those inputs equivalent trust claims.

```python
from formulatracer import FormulaTracer

formula = FormulaTracer.from_tex(r"\frac{x}{a}+\frac{y}{a}")
print(formula.to_tex())
print(formula.inspect())

formula.assume("a != 0")
plan = formula.plan_generation(search="broad")
print(plan.explain(language="en", limit=5))

generated = formula.generate(auto_select=True)
assert generated.status == "SOURCE_GENERATED_UNVERIFIED"
generated.verify()
```

`from_source(path)` returns the project-audit object. `from_tex(...)` and
`from_expression(...)` return a `MathematicalFormula`. The object deliberately
uses progressive disclosure: `explain()` is human-facing, while `inspect()`
exposes canonical IR, features, and declared assumptions.

Convenience constructors include `taylor`, `maclaurin`, `fourier`, `laplace`,
`inverse_fourier`, and `inverse_laplace`. These create semantic objects; they do
not by themselves prove convergence, a region of convergence, or an inverse law.

## Verification boundary

The lifecycle is:

```text
TeX → MathSurfaceAST → notation resolution → canonical IR
    → broad retrieval → typed unification → authorized exact equality saturation
    → e-matching → relation-aware provider decision
    → instantiate/recompare → candidate selection → source
    → independent frontend re-analysis → verification status
```

Candidate score and provider metadata are never proof evidence. Unsupported or
ambiguous notation and missing domain/convergence conditions fail closed.
