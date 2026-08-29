# Public-release readiness

Revision and executable evidence are recorded in
`output/public_release_audit/final-public-release-assessment.json`. This report
describes the decision boundary rather than claiming publication.

## Product and environment

FormulaTracer reconstructs mathematics from scientific code and integrates
relation analysis, assumptions, proof obligations, error/range evidence,
provider contracts, provenance, and localization. Theory comparison is an
optional later step. FormulaTracer 0.1.0 requires Python 3.10+ for the Python
distribution; native development uses Rust 1.85+ (edition 2021), C ABI v1,
C++20 builds, LLVM/Clang major 18, and Lean/mathlib 4.19.0.

Python wheels are intended to bundle the native semantic core. Rust, C, and
C++ consumers can use the core without Python through the native Rust API or C
ABI v1. The C++ wrapper is thin RAII. The native CLI currently processes
semantic documents; complete Rust-source audit orchestration is not advertised.

## Providers and evidence

Provider contracts cover selected APIs. External provider version ranges remain
publicly unpinned until version-specific upstream conformance is complete.
Representative high-impact contracts were checked against official NumPy,
SciPy, xarray, and PyTorch references. Four recorded SciPy APIs remain correctly
reference-insufficient; they are not promoted to supported.

Formal, reference-backed, empirical, runtime, structural, and unresolved
evidence remain separate. Only Lean-returned evidence is kernel-verified.

## Packaging, licensing, privacy, and security

Apache-2.0 remains the recommended project license. Runtime, compiled Rust,
build, proof, optional-provider, validation-only, and reference-only categories
are separated. Every concrete wheel/sdist/native artifact must contain the
project license and required notices and must be re-audited when linkage changes.

Public examples are synthetic. The repository and public artifacts must not
contain private research source, formulas, datasets, paths, credentials, or
outputs. Vulnerabilities use GitHub Private vulnerability reporting; ordinary
bugs and questions use Issues and Discussions.

## Decision

`PUBLIC_RELEASE_READY` is computed, not assumed. It is true only after the full
Python/Rust/C/C++/Lean regression, standalone examples, Windows/Linux clean
wheel installs, sdist inspection, link/example checks, license artifact audit,
privacy scan, and semantic-ownership gates are recorded as passing. See the
machine assessment for the current value and any blockers.
