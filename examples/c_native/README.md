# C-only consumer

Build the Rust C ABI library first, then configure this consumer. Python is not
used. A packaged native release has the same `include/`, `lib/`, and `bin/`
layout described in `docs/reference/c-api.md`.

```console
cargo build --release -p formulatracer-c-api
cmake -S examples/c_native -B build/c-native -DFORMULATRACER_ROOT=/path/to/FormulaTracer
cmake --build build/c-native
```

Ensure the native library directory is on `PATH` (Windows) or the platform
dynamic-library search path (Linux) before running the executable.
