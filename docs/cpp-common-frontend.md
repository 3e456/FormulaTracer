# C++ common FormulaTracer frontend

Phase 9.7 connects the existing Clang LibTooling pipeline to the same
`FormulaTracer(...).analyze()` object model used by Python and Rust.

```python
from formulatracer import FormulaTracer, VariableTarget

project = FormulaTracer("src/model.cpp").analyze()
intermediate = FormulaTracer("src/model.cpp").analyze(
    [VariableTarget("weighted_score", function="calculate")]
)
```

`CMakeLists.txt` is also an accepted discovery entry. The environment resolver
searches, in order, for a project-root compilation database, the conventional
`build/compile_commands.json`, and other existing CMake build trees. It records
the database and command hashes, source hashes, CMake hash, frontend version,
and Clang version. It never synthesizes compiler flags.

The dependency resolver creates C++ translation-unit and header modules,
distinguishes system and project-local includes, and records local definitions,
calls, constants, and value dependencies. Canonical names retain namespaces;
otherwise identical symbols from distinct translation units receive distinct
module-qualified identities. Multi-root, multi-output assignments, explicit
variable targets, and narrowly recognized `std::ofstream` sinks use the common
root/output/sink model.

## Authority boundary

The native LibTooling Implementation IR remains the authority for complete
frontend verification. It is invoked internally when a usable executable and
real compilation database are available. Cached native IR is accepted only
when its source hash and function identity match and its current schema and
provenance validations pass.

When Clang is unavailable, a portable recognizer can preserve project structure
and partially lower arithmetic, constants, explicit weighted reductions,
`std::accumulate`, `std::inner_product`, `std::reduce`, `std::sqrt`, `std::abs`,
and `std::pow`. Such output is marked `PORTABLE_RECOGNIZER_PARTIAL`, the project
remains unresolved, aliases remain unresolved, and it cannot become complete
verification or Lean evidence.

`std::accumulate` and `std::inner_product` retain left-to-right order.
`std::reduce` retains reorderable execution and a floating-point order error
component. C++ `float`, `double`, and `long double` are execution metadata; the
certificate does not identify them with exact mathematical Real semantics.

## Cross-language boundaries

Explicit local pybind11 `PYBIND11_MODULE`/`.def` mappings can join Python calls
to local C++ symbols. The common graph retains a `CrossLanguageCallEdge`, native
extension identity, source mapping, and FFI representation obligation. Existing
Python error components continue through the C++ expression, while conversion
error is a separate component. The generic boundary model can also represent
Rust-to-C++ and C++-to-Rust edges; automatic resolution of those ABI systems is
outside this phase.

## Known limits

Complete CMake interpretation, compiler flag inference, arbitrary templates,
preprocessor expansion, overload resolution without Clang, complete alias and
mutation analysis, generic stream classification, arbitrary serialization
libraries, and binary-only extension reconstruction remain fail-closed. Runtime
and differential evidence is recorded separately with `proof_authority=false`
and is never promoted to a Lean kernel proof.
