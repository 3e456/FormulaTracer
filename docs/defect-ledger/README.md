# Deferred Defect Ledger

FormulaTracer records defects discovered during Batch development instead of
silently broadening the active Batch. `BLOCKER` and
`CRITICAL_FALSE_ACCEPTANCE` defects are fixed immediately. Other defects remain
visible in `defects.json` until the Final Stabilization / Defect Burn-down.

Allowed severities are `BLOCKER`, `CRITICAL_FALSE_ACCEPTANCE`, `HIGH`, `MEDIUM`,
`LOW`, and `COSMETIC`. Allowed states are `OPEN`, `DEFERRED`, `FIXED`,
`VERIFIED_FIXED`, and `WONT_FIX_WITH_REASON`. Tests must not be removed or
hidden with xfail merely to conceal a ledger item.

The stabilization phase deduplicates findings, clusters them by root-cause
system (frontend, project graph, contracts, comparison, transformation,
error/range, probability, synthesis, debugger, renderer, or FFI), fixes them in
severity order, and permanently adds reproduction tests.
