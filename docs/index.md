# FormulaTracer documentation

[English](index.md) | [日本語](index.ja.md)

FormulaTracer integrates scientific-code reconstruction, mathematical relation
analysis, numerical evidence, provenance, and source localization. Start with
the theory-free code-audit path; add a declared theory only when one exists.

## Start here

- [Python quick start](public-api/quickstart.md)
- [Python audit frontend](python-audit.md)
- [Operational synthetic example](../examples/operational_audit/README.md)
- [Proof and evidence levels](proof-levels.md)
- [Trust boundary](trust-boundary.md)

## Public API

- [Class and function usage guide](reference/api-usage-guide.md) — signatures, arguments, return values, failures, and runnable examples
- [Python API](reference/python-api.md)
- [Rust API and native CLI](reference/rust-api.md)
- [Stable C ABI v1](reference/c-api.md)
- [C++ RAII wrapper](reference/cpp-api.md)
- [Result types and statuses](reference/result-types.md)
- [Languages and toolchains](reference/supported-languages.md)
- [Scientific providers](reference/libraries-and-providers.md)
- [References](reference/references.md)
- [Licensing and redistribution](reference/licenses-and-third-party.md)

## Concepts and architecture

- [Design philosophy](concepts/design-philosophy.md)
- [Error and range](concepts/error-and-range.md)
- [User-defined semantics](concepts/user-defined-semantics.md)
- [Physics foundation](physics-foundation.md)
- [Provenance and debugger](concepts/provenance-and-debugger.md)
- [Single native semantic core](architecture/native-core.md)
- [Unsupported behavior](unsupported-behavior.md)

## Release evidence

- [Public-release readiness](validation/public-release-readiness.md)
- [Native-core completion](validation/native-core-completion.md)
- [Repository sanitization](security/repository-sanitization-report.md)
