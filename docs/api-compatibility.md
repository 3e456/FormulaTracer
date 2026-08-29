# API and schema compatibility

FormulaTracer is currently version 0.1.0. SemVer permits breaking changes before 1.0, but the project deliberately limits avoidable breakage.

## Stability classes

- **STABLE**: the recommended Python facade listed in `maintenance/api-policy.json`, Stable C ABI v1, the named C++ RAII types, and the small Rust facade (`Formula`, `SemanticObject`, `VerificationResult`, `MathematicalFunction`).
- **EXPERIMENTAL**: other currently public Python and Rust items. They are usable but may evolve during 0.x with release notes.
- **INTERNAL**: helpers not exported through the supported facade. They are not compatibility promises.

The large Rust `pub use` surface remains experimental unless explicitly promoted. This avoids claiming stability while allowing a future non-semantic module-boundary cleanup.

## Deprecation

Stable API removal normally requires a documented replacement, migration note, and at least one subsequent 0.x release carrying the deprecated entry point. A security issue, false acceptance, memory-safety defect, or impossible-to-maintain contract may require immediate fail-closed removal.

## Stable C ABI v1

`FT_ABI_VERSION` is 1. Public structs are opaque. Objects are freed by the matching `ft_*_free` function; strings by `ft_string_free`. Errors are returned as `FT_Status` or through the context error object. Existing v1 symbols and their ownership rules may not change incompatibly. An incompatible layout, ownership, calling-convention, or semantic-contract change requires a new ABI version rather than silently changing v1.

The C++ wrapper is an ergonomic RAII facade over this ABI and is not a semantic implementation.

## Versioned schemas

Every versioned interchange object is read according to its `schema_version`. Supported older versions remain readable or receive an explicit converter. Unknown future versions fail closed; FormulaTracer does not silently downgrade or reinterpret them. Breaking schema changes require a new version and migration notes. The machine policy is `maintenance/schema-policy.json`.

CI compares the current Python/C public surface with the committed public API inventory. New entries must be classified, documented, and tested; removals require explicit compatibility review.
