# FormulaTracer documentation

[English](index.md) | [日本語](index.ja.md)

FormulaTracerは科学計算コードの復元、数学relation解析、数値的根拠、provenance、
source localizationを統合します。まずTheoryなしのコード監査から始め、必要な
場合だけ別に定義したTheoryと比較します。

## 入口

- [Python Quick Start](public-api/quickstart.md)
- [Python audit frontend](python-audit.md)
- [synthetic operational example](../examples/operational_audit/README.md)
- [Proof / evidence level](proof-levels.md)
- [Trust boundary](trust-boundary.md)

## Public API / support

- [クラス・関数の使い方](reference/api-usage-guide.ja.md) — signature、引数、戻り値、例外、実行可能な例
- [Python API](reference/python-api.ja.md)
- [Rust API / native CLI](reference/rust-api.md)
- [Stable C ABI v1](reference/c-api.md)
- [C++ RAII wrapper](reference/cpp-api.md)
- [Result type](reference/result-types.md)
- [Language / toolchain](reference/supported-languages.ja.md)
- [Scientific provider](reference/libraries-and-providers.ja.md)
- [Reference](reference/references.md)
- [License / redistribution](reference/licenses-and-third-party.md)

## Architecture / validation

- [User-defined semantics](concepts/user-defined-semantics.ja.md)
- [Physics foundation](physics-foundation.ja.md)
- [Single native semantic core](architecture/native-core.md)
- [Unsupported behavior](unsupported-behavior.md)
- [Public release readiness](validation/public-release-readiness.ja.md)
- [Repository sanitization](security/repository-sanitization-report.md)
