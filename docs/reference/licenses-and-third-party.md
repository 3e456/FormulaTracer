# Licensing and third-party components

FormulaTracer is Apache-2.0. It is permissive, permits research and commercial
use, modification, and redistribution, and includes an express patent grant.
The canonical terms are in `LICENSE`; this page is not legal advice.

Dependencies are classified as runtime, build, proof, development/test,
optional provider, validation-only, reference-only, vendored/copied, or compiled
into a distributed binary. Optional/reference-only providers are not
FormulaTracer runtime dependencies merely because a contract mentions them.

The Python runtime directly requires PyYAML and jsonschema, with tomli required
conditionally on Python versions earlier than 3.11. Native Rust binaries compile
the Cargo dependency closure listed in the artifact audit. LLVM/Clang is an
optional C++ frontend build/link dependency; Lean/mathlib is a proof-build
dependency. No third-party source tree is intentionally vendored.

Every wheel, sdist, DLL/SO/static library, and native CLI must be audited as an
artifact. If an LLVM-linked artifact is distributed, its Apache-2.0 WITH LLVM-
exception obligations must be included. Generated-code licensing depends on
user content, templates, and upstream provenance; generation does not
automatically license all output under Apache-2.0.

See `THIRD_PARTY_NOTICES.md`, `docs/dependency-license-audit.md`, and
`output/public_docs/distribution-license-audit.json`.
