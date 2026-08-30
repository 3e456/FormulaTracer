# FormulaTracer

[English](README.md) | [日本語](README.ja.md)

**From scientific code to auditable mathematics.**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](pyproject.toml)
[![Rust 1.85+](https://img.shields.io/badge/Rust-1.85%2B-orange)](Cargo.toml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-green)](LICENSE)

FormulaTracer is an experimental, fail-closed semantic auditor for scientific
software. It reconstructs mathematical meaning from code, then keeps exact and
non-exact relations, assumptions, proof obligations, numerical evidence,
provider contracts, provenance, and source localization in one structured
workflow. A separately declared theory is optional.

When FormulaTracer cannot justify an interpretation, it reports `UNRESOLVED`
instead of guessing. Structural similarity is not proof, numerical similarity
is not a certified bound, and provider retrieval is not verification.

Public references: [Python functions](docs/reference/public-functions.md) ·
[Rust](docs/reference/rust-api-reference.md) · [C ABI](docs/reference/c-api-reference.md) ·
[C++](docs/reference/cpp-api-reference.md) · [result/status/evidence](docs/reference/result-model-reference.md) ·
[providers](docs/reference/provider-api.md) · [physics](docs/reference/physics-api.md) ·
[user-defined semantics](docs/reference/user-defined-api.md)

## Why FormulaTracer?

A formula alone does not say whether the implementation is exact or approximate,
which assumptions it needs, where it came from, or which source span caused a
divergence. FormulaTracer connects those questions through one Rust-owned
semantic model and returns a structured `VerificationResult` or
`ReconstructionResult`; TeX, JSON, and explanations are derived views.

Typical uses include scientific implementation review, model-change review,
pre-publication checks, reproducibility work, and inherited-code assessment.

## Install

Python 3.10 or newer is required. Published supported wheels are intended to
include the native core, so end users do not need Rust, Cargo, or CMake.

```console
python -m pip install formulatracer
```

This repository is currently version `0.1.0`; package publication is not part
of this readiness work. Source developers need Rust 1.85+, and the optional
C++ frontend requires LLVM/Clang major 18 and a C++20 build toolchain.

## Quick start: audit code without a theory

Clone the repository, install it, then run the synthetic example:

```console
python -m pip install -e .
formulatracer python-audit examples/python_audit/weighted_sum.py --function calculate_weighted_score --output weighted_score --mode REPORT_ONLY --report output/python-audit/report.md --json-output output/python-audit/audit.json --no-lean
```

The report contains the independently reconstructed implementation expression,
numeric backward slice, assumptions, provider contracts, provenance, and any
unresolved boundary. No theory annotation is required.

An optional stronger comparison can be added when a theory is available:

```python
from formulatracer import FormulaTracer

formula = FormulaTracer.from_tex(r"\sum_{i=0}^{N-1} x_i")
plan = formula.plan_generation(language="python", search="broad")
print(plan.explain(limit=5))
generated = formula.generate(language="python", auto_select=True)
result = generated.verify()
print(result.status)
print(result.independent_audit)
```

Candidate similarity only starts an investigation. Selection still requires
typed unification, constraints, authorized transformations, and independent
re-analysis.

## Core workflow

```text
Scientific source -> Implementation IR -> Mathematical reconstruction
  -> Exact/relational analysis -> Assumptions and obligations
  -> Error/range and provider evidence -> Provenance and localization
  -> Structured result -> AuditBundle / TeX / JSON / explanation
```

Main Python entry points are `FormulaTracer.from_source`, `FormulaTracer.analyze`,
`FormulaTracer.from_tex`, `plan_generation`, `reconstruct`, and the native
structured-result wrappers. See the [Python API](docs/reference/python-api.md)
instead of relying on internal `cpp_audit` modules.

## Supported languages

| Language | Implementation role | Audit input | Code generation | End-user Python required? |
|---|---|---|---|---|
| Python | Public facade and frontend | Yes | Yes | Yes for Python API/CLI |
| Rust 2021 | Semantic core and native CLI | Yes, via current project frontend | Yes | No for native semantic-document API |
| C | Stable ABI v1 | Limited C/C++ frontend path | No | No |
| C++17/20 | Clang 18 audited input | Yes | Yes | No for C ABI/C++ wrapper |
| Lean 4.19 | Independent proof layer | No | Proof obligations only | No |

The FormulaTracer C++ components build as C++20. The native CLI currently
operates on semantic documents (`canonicalize`, `tex`, `compare`); it is not a
complete Rust-source audit CLI. See [language support](docs/reference/supported-languages.md).

## Scientific libraries and providers

Provider contracts cover selected public APIs, not an entire upstream library.
Most external library entries are currently
`REFERENCE_ONLY_VERSION_UNPINNED`; therefore this release does **not** promise a
broad NumPy/SciPy/xarray version range. Axis, dtype, missing-value, named-
dimension, device, laziness, mutation, and default semantics remain explicit
contract conditions. See the [provider matrix](docs/reference/libraries-and-providers.md).

## User-defined semantics: a redundant evidence path

`@cpp_audit.theory(output=..., expression=...)` supplies a user declaration to
the same Mathematical IR, relation, evidence, and provenance pipeline used by
automatic reconstruction. It is useful for private callbacks, future libraries,
hardware kernels, and source that is unavailable to the auditor. It is not a
second evaluator and a declaration alone never becomes implementation-,
reference-, or Lean-verified evidence.

When implementation-derived mathematics is available, FormulaTracer reports
`MATCH`, `MISMATCH`, or `NOT_EVALUABLE` between the two independent paths.
Callback value semantics and effects are separate: an expression may be retained
while purity remains `UNKNOWN_EFFECT`. See [user-defined semantics](docs/concepts/user-defined-semantics.md).

## Physics foundation

The versioned physics foundation defines multivariable/vector calculus,
geometric integral relations, dimensions and frames, SO(3)/quaternion
representations, Fourier/Laplace relations, numerical realizations, and selected
SciPy callback boundaries. Support levels are reported separately as `DEFINED`,
`THEOREM_REGISTERED`, `LEAN_KERNEL_VERIFIED`, `REALIZATION_AVAILABLE`,
`CONDITIONAL`, or `PARTIAL`.

FormulaTracer audits mathematical and implementation relations. It does **not**
prove that a physical law is empirically true. General Noether, Gauss/Stokes,
SE(3), finite-volume error, and AD claims remain conditional unless their listed
obligations are discharged. See the [physics support boundary](docs/physics-foundation.md).

## Platform status

| Platform | Source/tests | Native package | Status |
|---|---|---|---|
| Windows x86-64 | Locally tested | Wheel build and clean-install tested | Tested |
| Linux x86-64 | Debian GNU/Linux 12 (bookworm), Python 3.11.2 | Wheel/sdist build, clean install, native load, and release suite tested in a real x86-64 Linux container | Tested on this recorded environment only |
| macOS | Not validated | No release wheel claim | Untested |

## Evidence model

- `KERNEL_VERIFIED`: checked by the Lean kernel.
- `KERNEL_VERIFIED_UNDER_ASSUMPTIONS`: kernel-checked with listed assumptions.
- `FORMALLY_DERIVED`: derived from versioned rules and evidence.
- `REFERENCE_CONTRACT`: backed by an upstream public reference.
- `EMPIRICALLY_VALIDATED` / `RUNTIME_EVIDENCE`: tests or a concrete run, not proof.
- `UNRESOLVED`: ambiguity, unsupported behavior, missing contract, or open obligation.

Exact equality, approximation, discretization, truncation, sampling, and
algorithmic realization are distinct relations. Read [proof levels](docs/proof-levels.md)
and the [trust boundary](docs/trust-boundary.md).

## Examples

- [Theory-free Python audit](examples/python_audit/weighted_sum.py)
- [Exact, non-exact, and unresolved operational audit](examples/operational_audit/README.md)
- [Rust-only consumer](examples/rust_native/README.md)
- [C-only consumer](examples/c_native/README.md)
- [C++ RAII consumer](examples/cpp_native/README.md)

## Non-goals and limitations

FormulaTracer does not prove compilers, CPUs, every external implementation, or
a researcher's scientific intent, and is not a general compiler, numerical
solver, CAS, Lean replacement, or arbitrary-software verifier. It does not
silently infer unknown semantics and does not replace scientific judgement. Complete Rust-source native audit
orchestration is not yet exposed by `formulatracer-native`. Performance is
secondary to semantic correctness and fail-closed behavior.

Runtime-only call targets, non-exhaustive dynamic keys, unknown backends,
impure/opaque callbacks, and unproved conditional theorems remain partial or
unresolved. “Currently unresolved” does not mean “fundamentally impossible”;
user contracts, runtime evidence, or provider evidence may close some cases,
but those evidence classes are never relabelled as static proof.

## Documentation and support

Start with the [class and function usage guide](docs/reference/api-usage-guide.md)
([日本語](docs/reference/api-usage-guide.ja.md)) or the
[documentation index](docs/index.md). Use
[GitHub Issues](https://github.com/3e456/FormulaTracer/issues) for bugs and
[GitHub Discussions](https://github.com/3e456/FormulaTracer/discussions) for
usage questions. Report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md). See [SUPPORT.md](SUPPORT.md) for the reporting and
support policy. External pull requests are not currently accepted; propose
changes through an Issue or Discussion.

## Citation, license, and contributing

Citation metadata is in [CITATION.cff](CITATION.cff). FormulaTracer is licensed
under [Apache-2.0](LICENSE); third-party categories and redistribution notes are
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Generated-code licensing
depends on user input, selected templates, and upstream provenance; generation
does not automatically impose the FormulaTracer project license on all output.

FormulaTracer's external participation model is documented in
[CONTRIBUTING.md](CONTRIBUTING.md). External pull requests are not currently
accepted.
