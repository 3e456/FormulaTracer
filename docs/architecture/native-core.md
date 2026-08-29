# Native semantic core architecture

Status: implemented production architecture. Migration baseline: `8df98ee529f86fa6b8142c3b6a96abe240150419`.

## Decision

FormulaTracer has one semantic implementation. Rust owns Mathematical and
Implementation IR semantics, canonicalization, facts and constraints, exact
equality, non-exact relations, typed matching, data-driven knowledge/provider
packs, approximation/error/range, provenance, cache integrity, debugger
localization, mathematical functions, TeX rendering, and certificate semantics.

The stable, versioned C ABI is the external binary boundary. Python, C++, Rust,
and future bindings perform conversion, lifetime management, error mapping, and
ergonomic adaptation only:

```text
                         formulatracer-core (Rust) ─ proof obligations ─ Lean 4
                            /              \
                   native Rust API     Stable C ABI v1
                                             │
                                     ┌───────┼────────┐
                                     C    C++ RAII   Python

C++ Clang frontend ─ versioned Implementation IR ─────┘
                         ↑
              versioned IR / pack schemas
```

`NO_SEMANTIC_REIMPLEMENTATION_IN_LANGUAGE_BINDINGS` is a release invariant.
Opaque handles prevent Rust layout, arenas, e-nodes, or union-find internals
from becoming ABI promises. Portable interchange uses versioned JSON schemas.

Stable C ABI v1 is the language-neutral interop contract. C calls it directly;
C++ wraps it with RAII; Python uses a thin ergonomic C-ABI wrapper. PyO3 may be
evaluated only as a binding optimization and may not create another semantic
path. Native Rust users call the same `formulatracer-core` directly, so they do
not need to round-trip through C. Cross-language conformance compares
Mathematical IR, status, assumptions, relation, error/range, evidence, and TeX.

The core implementation language is independent of generated research-code
targets. FormulaTracer continues to generate and re-audit Python, Rust, and C++
research implementations.

## Structured result boundary

All major operations return a structured semantic result object. The canonical
`VerificationResult` owns status, theory and implementation objects, relation,
assumptions, error/range, evidence, provenance, and debugger information. TeX,
JSON, Markdown, CLI text, and localized explanations are derived presentation
or serialization views; none is the canonical result itself.

ABI v1 represents results and nested theory/implementation values with opaque
handles. Rust and Python expose typed object facades, while C++ owns the same
handles through RAII. Compatibility projections such as the serialized `tex`
field may exist during migration, but the core recomputes presentation from the
semantic implementation object and bindings may not interpret it semantically.

## Migration completion and safety

The staged migration used Python as a reference engine until every component
satisfied Rust completeness, semantic differential, mutation, real-world,
critical-defect, and facade gates. Production cutover is now complete. Retained
Python reference code is validation-only and unreachable from production.
Incomplete or unsupported native paths still return `NATIVE_COMPONENT_INCOMPLETE`
or `UNRESOLVED`; they never silently assert success or approximate equality.

The versioned `execute_kernel` dispatch is the shared native boundary for
semantic Kernels A--F. C ABI v1 exposes it as `ft_kernel_execute_json`; the
Python facade only serializes the request and owns the returned string. The
production canonical-equality, canonical-TeX, generalization,
anti-unification, and algebraic-domain paths now use
this boundary. Their former Python implementations remain private migration
oracles used only by differential validation. All production surfaces have now
passed the retirement gate; Python remains frontend, thin binding,
presentation, orchestration, reference, or validation code only.

Runtime evidence distinguishes `PYTHON_REFERENCE` from `PYTHON_FALLBACK`. A
workflow may have zero fallback while remaining Python-owned because it enters
a retained semantic implementation directly. The migration observer records
both paths by Kernel; completion requires both Python counts to reach zero.

Non-exact relations (`APPROXIMATION_OF`, `DISCRETIZATION_OF`, `TRUNCATED_TO`,
`SAMPLED_AS`, `ALGORITHMICALLY_REALIZED_BY`) are stored in a relation graph and
never merge exact e-classes. Only Lean may label evidence `KERNEL_VERIFIED`.

## Language boundaries

- Rust: semantic source of truth and natural public API.
- C: stable ABI v1, status/error objects, opaque ownership, explicit free calls.
- C++: Clang 18 frontend remains language-specific; public API is thin RAII.
- Python: primary user facade and language frontend; retained semantic oracles
  are isolated to differential validation.
- Lean: independent proof kernel, unchanged and outside the native trust claim.

## Priority and performance

The KPI order is semantic identity across languages, prevention of duplicated
logic, zero false acceptance, preserved Lean boundary, distribution,
maintainability, then speed. Rust migration does not require a speedup. A slower
but semantically correct and maintainable component is
`CORRECT_BUT_PERFORMANCE_REGRESSION`, not a migration failure. Optimization may
not complicate the semantic design or weaken determinism. Full audit is a final
operation; normal work should use fail-closed incremental analysis.

## Packaging

Windows x86-64 and Linux x86-64 native wheels are v1 targets. Users of those
wheels must not need Rust, Cargo, Clang, CMake, or Lean. macOS remains
`OUT_OF_SCOPE_FOR_V1`. Source builds document developer toolchains separately.
