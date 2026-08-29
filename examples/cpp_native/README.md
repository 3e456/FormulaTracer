# C++-only consumer

This example uses the header-only RAII wrapper over stable C ABI v1. The wrapper
only manages ownership, errors, and ergonomics; all semantics remain in Rust.

```console
cargo build --release -p formulatracer-c-api
cmake -S examples/cpp_native -B build/cpp-native -DFORMULATRACER_ROOT=/path/to/FormulaTracer
cmake --build build/cpp-native
```

Python is not required. This verifies semantic documents; C++ source auditing
additionally needs the separate Clang 18 frontend to produce Implementation IR.
