# Maintenance policy

FormulaTracer 0.1.x is maintained as a fail-closed scientific auditing library. Maintenance work must preserve the Rust semantic core as the single semantic authority; bindings may only adapt arguments, results, errors, and lifetimes.

## Supported environments

- Python: the CI matrix targets 3.10–3.13. A release may claim this range only while every matrix entry passes; `requires-python` must be narrowed if it does not.
- Rust: MSRV 1.85 and the pinned development toolchain in `rust-toolchain.toml`.
- Operating systems: Windows x86-64 and Linux x86-64 native packages.
- C ABI: version 1. C++ consumers use the thin C ABI wrapper.
- C++/Clang frontend: C++17/C++20 input with LLVM/Clang major 18; FormulaTracer's C++ build uses C++20.
- Lean/mathlib: pinned by `lean-toolchain` and `lake-manifest.json`.

## Change policy

Public APIs are classified in `maintenance/api-policy.json`. Stable names receive a deprecation notice and migration guidance before removal whenever security or correctness does not require immediate removal. Experimental APIs may change during 0.x, but changes must be documented. Internal APIs carry no compatibility promise.

Provider contracts are re-audited after an upstream major release, API removal, default or semantic change, license change, or FormulaTracer contract change. A representative subset runs in ordinary CI; broader checks run manually, on schedule, and before a release.

Dependency updates are grouped monthly. Runtime ranges remain suitable for library users; exact maintainer/test versions live in `requirements/ci.txt`. Cargo and Lean dependencies remain locked for validation.

## Required re-audits

Run release-level validation after changes to the semantic core, C ABI, schemas, runtime dependencies, compiled Rust crates, providers, generated-code templates, native platforms, linkage mode, license metadata, or packaging.

Security reports follow `SECURITY.md`. Never commit private research data, private AuditBundles, local paths, or credentials. A release candidate must pass privacy, license, artifact-content, compatibility, and semantic gates.

## CI and build operations

- Tier 1 (`ci.yml`) checks supported Python imports, focused tests, Rust MSRV/stable, formatting, correctness/suspicious Clippy lints, docs, metadata, API drift, and privacy.
- Tier 2 (`integration.yml`) runs full regression, differentials, native consumers, the operational fixture, and Clang 18 integration.
- Tier 3 (`release-validation.yml`) is manual and non-publishing. It runs release-level semantic/proof checks and creates short-retention verified artifacts.
- The monthly maintenance workflow detects dependency/provider drift without making external network availability a normal pull-request blocker.

`python tools/build_release.py --kind all` is the canonical local artifact command. CI starts from `actions/checkout`, so build/test/package never depend on a developer worktree. Each build cleans `dist/release`, isolates the target-native library, and writes a SHA-256 manifest with source/toolchain/lock provenance. The present claim is **STRUCTURALLY_REPRODUCIBLE**, not bit-for-bit reproducible.

The remote feature branch and a clean sanitized clone are the development source of truth. A dirty secondary worktree must never be used for packaging until every change has known provenance.
