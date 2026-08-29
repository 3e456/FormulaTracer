# Third-party notices

FormulaTracer itself is licensed under Apache License 2.0; the complete text is
in [`LICENSE`](LICENSE). This notice is an engineering dependency inventory and
does not alter any upstream license.

This inventory distinguishes imported/linked software from libraries known only
as providers, documentation references, or ephemeral validation targets.
Reference-only knowledge does not mean code is copied or redistributed.

## Runtime

The Python package declares PyYAML and jsonschema, plus the MIT-licensed tomli
compatibility parser only on Python versions earlier than 3.11. The observed
jsonschema dependency chain includes attrs, jsonschema-specifications,
referencing, and rpds-py. Package managers install these; their source is not
vendored here.

## Rust components compiled into native artifacts

Native DLL/SO/static-library and CLI artifacts compile the Cargo.lock closure,
including serde/serde_json, sha2 and its digest/crypto support crates,
thiserror, and proc-macro/build support crates. The exact versions and official
license metadata must be regenerated for each release artifact. These crates
are not vendored in the tracked source, but compiled code is redistributed in
native binaries and therefore is not classified as reference-only.

## Build, development, and proof

The optional native frontend builds against LLVM/Clang 18. Lean artifacts use
Lean 4.19.0 and mathlib 4.19.0. Their source trees are not vendored here.
setuptools and wheel build Python artifacts; CMake and a C/C++ build tool build
native consumers/frontends; pytest is development/test-only. If an LLVM-linked
binary is distributed, Apache-2.0 WITH LLVM-exception notices and applicable
license text must accompany that concrete artifact.

## Optional/reference-only providers

NumPy, SciPy, pandas, xarray, Dask, Numba, JAX, PyTorch, CuPy, SymPy,
scikit-learn, statsmodels, Eigen, Boost, egg, and egglog appear in semantic
registries. They are not runtime requirements or distributed with this source
package by that fact alone.

## Validation-only material

External validation uses ephemeral checkouts. Only URL, revision, declared
license, hashes, and semantic/result metadata remain; retained source count is
zero in the recorded external-corpus result.

The [machine-readable inventory](output/release_candidate/dependency-license-inventory.json)
records observed versions, all seven usage categories, import/link,
distribution, copying, and notice/text assessments. This is an engineering
inventory, not legal advice; each release artifact still requires a final check.

FormulaTracer-generated code is not automatically Apache-2.0 in every case.
Licensing follows the provenance of user input, selected templates, copied
material, and external provider requirements.
