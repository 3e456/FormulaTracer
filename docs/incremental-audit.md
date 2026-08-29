# Incremental audit and cache safety

The incremental planner compares source hashes, walks the existing dependency
graph backwards, and identifies affected modules, roots, and outputs. The object
API remains authoritative:

```python
incremental = tracer.analyze_incremental(previous, cache=cache)
```

Cache keys include every used source hash, FormulaTracer version, Mathematical
IR version, library-contract registry hash, and mathematical-knowledge registry
hash. Reuse requires an exact serialized-key match and a canonical value-payload
digest match. Missing, unreadable, key-tampered, value-tampered, stale, or
version-mismatched entries trigger reanalysis and can never promote a result to
verified.

Unknown changed modules fail closed to full-project analysis. CI/watch tooling
can consume the returned affected-output plan, semantic diff, and critical
regression gates without introducing another CI framework.
