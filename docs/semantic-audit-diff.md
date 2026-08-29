# Semantic audit diff and accepted baselines

`result.accept_baseline()` creates an immutable snapshot. `baseline.diff(next)`
compares semantic fields rather than source text and classifies Theory,
Implementation, constants, parameters, dependencies/providers/contracts,
approximation/transformation, error/range/assumptions, input/output schemas,
artifacts, and proof status.

```text
Theory                 unchanged
Implementation         changed
Library provider       NumPy -> Rust
Error bound            improved
Artifact schema        unchanged
```

The diff reports hashes for changed sections and does not infer mathematical
validity from similarity or an accepted historical result.
