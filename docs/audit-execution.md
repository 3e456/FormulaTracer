# Audit execution and verification certificates

`python-certificate` extends the static Python audit with a deliberately
restricted execution and certificate layer. The audited module is never
imported or executed. Caller-supplied scalars and nested lists are interpreted
over the supported AST, and file/config I/O remains an explicit provenance
boundary.

## Certificate model

- `AuditCertificate` keeps the target, summarized inputs/result, independent
  theory and implementation IR, library contracts, Lean claims, and hashes.
- `ConstantNode` classifies `LITERAL_CONSTANT`, `NAMED_CONSTANT`,
  `DEFAULT_ARGUMENT`, `CONFIG_CONSTANT`, `FILE_LOADED_PARAMETER`, and
  `DERIVED_CONSTANT`.
- `ConstantDependencyGraph` contains directed source-to-derived edges and
  rejects unknown endpoints, duplicate symbols, and cycles.
- A derived node retains its symbolic definition, dependencies, resolved exact
  rational, unreduced rational presentation, decimal presentation, and source
  location. A decimal Python literal is represented as an exact mathematical
  decimal rational and a separate runtime floating presentation.

The implementation formula is independently extracted first. Constant-only
subexpressions are then re-symbolized for presentation and comparison; the
registered theory is never used as implementation input.

## Verification boundary

Generated Lean checks the separately translated expression graphs and exact
derived-constant arithmetic. A library claim is kernel-verified only when a
concrete theorem connects the public-reference adapter to Mathematical IR.
This does not prove NumPy internals, Python execution, floating-point rounding,
the supplied inputs, or file/config provenance.

`REPORT_ONLY` completes certificate generation on an opaque execution call or
formula mismatch. `STRICT` returns a failing CLI status for the same findings.

## Current execution limits

The executor covers scalar/nested-list arithmetic, subscripts, simple
assignments/defaults/return, and NumPy-style `sum`, `mean`, `prod`, and `abs`.
It supports axis `0`, axis `1`, and full reduction. General control-flow,
arbitrary Python calls, actual ndarray dtype/rounding emulation, I/O, and
general NumPy broadcasting are intentionally outside this execution MVP. The
static frontend continues to preserve opaque calls and shape constraints.
