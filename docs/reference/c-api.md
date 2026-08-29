# Stable C ABI v1

`include/formulatracer.h` is the language-independent ABI contract.
`FT_ABI_VERSION` is `1`. Opaque handles protect Rust layouts from ABI exposure.

The API creates a context, loads TeX or versioned IR, verifies one formula or a
pair, returns structured JSON/TeX and field projections, evaluates safe
mathematical functions, and frees every owned handle/string. Ordinary input
errors return status/error data; panics are contained at the FFI boundary.

Build with `cargo build --release -p formulatracer-c-api`, then run the
[C-only example](../../examples/c_native/README.md). Python is not involved.
Applications must use `ft_string_free` for returned strings and the matching
`*_free` function for each opaque handle.

Proposed native release layout:

```text
include/formulatracer.h
include/formulatracer.hpp
lib/formulatracer_c_api.{lib,a}
bin/formulatracer_c_api.{dll,so}
bin/formulatracer-native[.exe]
LICENSE
THIRD_PARTY_NOTICES.md
```
