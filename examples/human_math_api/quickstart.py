"""TeX-first planning and independent round-trip verification."""

from formulatracer import FormulaTracer


formula = FormulaTracer.from_tex(r"\sum_{i=0}^{N-1} x_i")
plan = formula.plan_generation(search="broad", candidate_budget=100)
print(plan.explain(limit=5))

# Similarity produced the list, but only a rigorously matched candidate is selectable.
generated = formula.generate(language="python", auto_select=True)
print(generated.status)  # SOURCE_GENERATED_UNVERIFIED
print(generated.verify().status)  # INDEPENDENTLY_REAUDITED_VERIFIED
