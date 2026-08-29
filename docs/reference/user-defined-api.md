# User-defined Semantics Reference

The Python audit frontend exposes the compatibility decorator
`cpp_audit.theory(output=..., expression=...)`. It attaches theory metadata and
does not change function execution. The implementation formula is still
reconstructed independently from Python AST.

```python
from cpp_audit import theory

@theory(output="y", expression="y = sum(i=0..n-1, x[i])")
def custom_sum(x):
    total = 0.0
    for value in x:
        total += value
    return total
```

Native `USER_DECLARATION` comparison reports `MATCH`, `MISMATCH`, or
`NOT_EVALUABLE`. Its evidence is always `USER_DECLARED`, `auto_verified=false`.
Unknown callback effects remain `UNKNOWN_EFFECT`; declaring the value formula
does not prove purity, termination, units, frames, shape, dtype, or domain.

Use declarations to supply redundant intent/evidence, never to replace
code-derived reconstruction. A mismatch is a reportable audit finding.

