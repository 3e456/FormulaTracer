# ADR 0001: Single native semantic core with stable C ABI

- Status: accepted for staged migration
- Date: 2026-08-27

## Context

The validated Python implementation is large and must not be independently
re-created for every consumer language. Language-specific semantic engines
would drift and increase false-acceptance risk.

## Decision

Rust is the semantic source of truth, C ABI v1 is the stable binary boundary,
C++ retains the Clang frontend and gains only a thin RAII wrapper, Python
remains the primary facade, and Lean remains the independent proof layer.
Knowledge, provider, and domain rules remain versioned data interpreted by the
core. Binding code may not implement semantic decisions.

The native Rust API calls `formulatracer-core` directly. C uses ABI v1; C++ and
Python are thin ABI wrappers. These paths must be semantically conformant. This
does not restrict the independent Python/Rust/C++ target-language choices for
generated research code.

Major operations return one structured semantic object. TeX, JSON, Markdown,
CLI text, and localized explanation are renderings of that object, never an
alternative result or semantic execution path.

## Alternatives

- All Python: preserves today’s behavior but does not provide one native core.
- All C++: couples semantic ownership to the Clang adapter and has a harder safe
  ownership boundary.
- Multiple reimplementations: rejected because equivalence cannot be maintained.
- Rust ABI directly: rejected because Rust layout and ABI are not stable public
  contracts.

## Consequences

Migration is differential and component-by-component. Python code is retained
until explicit retirement gates pass. Opaque C handles and schemas add some
conversion overhead, accepted in exchange for safety and compatibility.
Performance is observed but is not an acceptance KPI.
