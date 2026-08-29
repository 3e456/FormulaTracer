# User-defined semantics

User declarations are a redundant input path into FormulaTracer's existing
Mathematical IR and evidence model. They do not form a second semantic engine.

```python
import cpp_audit as audit

@audit.theory(output="y", expression="y = x * scale")
def proprietary_transform(x, scale):
    return vendor_kernel(x, scale)
```

The declaration is recorded as `USER_DECLARED`. If code reconstruction is
available, FormulaTracer compares it independently and reports `MATCH`,
`MISMATCH`, or `NOT_EVALUABLE`. A match does not by itself establish
`IMPLEMENTATION_VERIFIED`, `REFERENCE_VERIFIED`, or `LEAN_KERNEL_VERIFIED`.

For callbacks, value semantics, shape/dtype/units/frame metadata, and effects are
separate. Missing fields remain unknown; especially, user-declared purity is not
silently treated as an implementation-derived effect proof.
