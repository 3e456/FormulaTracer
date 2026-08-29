# Python API

For complete signatures, argument tables, return values, exceptions, ownership,
and runnable examples, see the [class and function usage guide](api-usage-guide.md)
([日本語](api-usage-guide.ja.md)).

The supported package name is `formulatracer`. `cpp_audit` and the `cpp-audit`
command are compatibility names, not the preferred public spelling.

## Primary facade

`FormulaTracer` creates audits from projects, source, or TeX. `analyze()` returns
project audit objects. `from_tex()` returns a mathematical formula facade;
`plan_generation()` retrieves candidates and `generate()` emits source only
after a rigorous selection. Generated source starts unverified and must be
re-analyzed.

```python
from formulatracer import FormulaTracer

audit = FormulaTracer("examples/python_audit/weighted_sum.py").analyze()
print(audit.status)
```

Constructor details vary by source/project mode; use `formulatracer --help` and
the tested examples for exact arguments.

## Native result wrappers

`NativeResult` exposes status, theory, implementation, relation, assumptions,
diagnostics, error, range, evidence, provenance, debugger information, and
serialization. `to_tex()`, `to_json()`, and explanations are derived from the
structured result. `NativeMathematicalFunction` supports safe evaluation and
substitution; unsupported operations fail closed and no `eval()` is used.

## Reconstruction

`reconstruct(request)` delegates to the native kernel and returns a structured
`ReconstructionResult`. Exact, assumption-qualified, approximation,
discretization, truncation, sampling, algorithmic-realization, composite, and
unresolved outcomes are not collapsed.

## Errors

Unavailable native libraries raise `NativeUnavailableError`; malformed or
unsupported native requests raise `NativeCallError`. `REPORT_ONLY` preserves
unknown numeric calls and completes an audit. Strict workflows stop before an
unsupported claim can be promoted.

The complete symbol inventory is generated at
`output/public_docs/public-api-inventory.json`; not every compatibility export
is a recommended top-level API.
