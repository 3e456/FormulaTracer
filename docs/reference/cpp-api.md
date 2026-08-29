# C++ API

`include/formulatracer.hpp` is a thin C++20 RAII wrapper over stable C ABI v1.
It exposes `Context`, `Formula`, `Result`, `SemanticObject`, and
`MathematicalFunction`. It owns handles, frees strings, maps errors, and adds
ergonomics; it does not implement semantics.

The [C++-only example](../../examples/cpp_native/README.md) uses the wrapper
without Python. Auditing C++17/C++20 source is a separate pipeline: Clang 18
produces versioned Implementation IR and the Rust core audits that IR. The
FormulaTracer C++ components themselves build as C++20.
