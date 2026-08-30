# FormulaTracer

[English](README.md) | [日本語](README.ja.md)

**科学計算コードから監査可能な数学へ。**

FormulaTracerは、科学計算コードに実装された数学を復元し、仮定や近似を監査し、
実装と宣言されたTheoryを比較し、数式仕様から監査可能なコードを生成します。

見かけ上は数学的に似ているコードでも、離散化、浮動小数点挙動、ライブラリ固有の
意味、定義域、単位、仮定、実装詳細によって結果が異なり得る科学計算softwareを
対象としています。

根拠をもって意味を確定できない場合、推測で補完せず
`UNRESOLVED`として明示します。構造的類似はproof、数値的近さは
certified bound、provider retrievalはverificationと同じではありません。

```console
python -m pip install formulatracer
```

## FormulaTracerでできること

- 科学計算sourceから数式と数学的構造を復元します。
- exact equalityとapproximation、discretization、truncation、sampling、
  algorithmic realizationを区別します。
- 仮定、証明義務、数値誤差・range、provenanceを追跡します。
- コードから独立に復元した実装数学と、宣言されたTheoryを比較します。
- semantic mismatchをsource codeへ局所化します。
- opaqueまたはproprietaryな演算へuser-defined semanticsを与えられますが、
  declaration自体をverificationとして扱いません。
- 数式仕様から科学計算コードを生成し、その実装を独立に再監査します。
- 未解決の意味を推測で埋めず、`UNRESOLVED`として保持します。
- 利用可能な場合はLean kernelで確認されたproof evidenceを統合します。

## FormulaTracerの目的

科学計算コードは単なるsource syntaxではありません。Theoryと数学的に同じように
見える実装にも、次の差異が含まれる場合があります。

- 有限差分による離散化
- 浮動小数点reductionの順序
- 打切りや近似数値積分
- 暗黙のaxis、dtype、domain、unitに関する仮定
- ライブラリ固有のsemantics
- 未解決のcallback挙動

FormulaTracerはこれらを単一の「同値・非同値」へ潰さず、Rustが所有するsemantic
modelで明示します。結果は`VerificationResult`または`ReconstructionResult`として
返し、TeX、JSON、説明文はその派生表現です。

## 例: 微分と有限差分

Theory:

```text
dy/dx
```

Implementation:

```python
(f(x + h) - f(x)) / h
```

FormulaTracerは両者をexact equalityとは判定しません。実装を微分の有限差分による
realizationとして表し、discretization relationと必要な仮定を保持できます。

同様に、外部callbackについてsource、provider contract、user declaration、runtime
evidenceのいずれも得られない場合、数学的意味を捏造せず`UNRESOLVED`と報告します。

## インストール

Python 3.10から3.13に対応します。公開wheelはWindows x86-64とLinux x86-64
（manylinux）を対象とし、通常の利用者にRust、Cargo、CMakeを要求しません。

```console
python -m pip install formulatracer
```

現在のpackage versionは`0.1.1`です。macOS wheelは現在公開していません。
source開発にはRust 1.85以降、任意のC++ frontendにはLLVM/Clang major 18と
C++20 build toolchainが必要です。

## Quick Start: Theoryなしのコード監査

```console
python -m pip install -e .
formulatracer python-audit examples/python_audit/weighted_sum.py --function calculate_weighted_score --output weighted_score --mode REPORT_ONLY --report output/python-audit/report.md --json-output output/python-audit/audit.json --no-lean
```

レポートには、コードから独立に復元した実装式、numeric backward slice、仮定、
provider contract、provenance、未解決境界が含まれます。Theory annotationは不要です。

## 数式からコードへ

FormulaTracerは逆方向にも利用できます。数学仕様から実装候補を検索・選択して
sourceを生成し、その結果を通常の監査経路で独立に再解析します。

```python
from formulatracer import FormulaTracer

formula = FormulaTracer.from_tex(r"\sum_{i=0}^{N-1} x_i")
plan = formula.plan_generation(language="python", search="broad")
print(plan.explain(language="ja", limit=5))
generated = formula.generate(language="python", auto_select=True)
result = generated.verify()
print(result.status)
print(result.independent_audit)
```

similarityは調査開始の理由にすぎません。採用にはtyped unification、制約、
許可済み変形、独立再解析が必要です。

## Theory比較

Theoryの宣言は任意です。指定された場合も、コードから独立に復元した実装数学と
比較します。user declarationを実装抽出式の代わりに使用せず、宣言されたという
理由だけでverified evidenceへ昇格させません。

## 中心workflow

```text
科学計算source -> Implementation IR -> 数学的復元
  -> exact/relational解析 -> 仮定と証明義務
  -> error/rangeとprovider根拠 -> provenanceとsource localization
  -> structured result -> AuditBundle / TeX / JSON / explanation
```

## 対応言語

| 言語 | FormulaTracer内の役割 | 監査入力 | コード生成 | 利用者にPython必須? |
|---|---|---|---|---|
| Python | public facade / frontend | 対応 | 対応 | Python API/CLIでは必要 |
| Rust 2021 | semantic core / native CLI | 現行project frontend経由 | 対応 | native semantic-document APIでは不要 |
| C | stable ABI v1 | C/C++ frontend経由の限定経路 | 非対応 | 不要 |
| C++17/20 | Clang 18の監査対象 | 対応 | 対応 | C ABI/C++ wrapperでは不要 |
| Lean 4.19 | 独立proof layer | 非対応 | proof obligationのみ | 不要 |

FormulaTracer自身のC++ componentはC++20でbuildします。native CLIは現在、semantic documentの
`canonicalize`、`tex`、`compare`に対応し、Rust source全体の監査CLIではありません。

## Scientific library / Provider

provider contractは選択されたpublic APIを対象とし、upstream library全体の対応を意味しません。
多くは`REFERENCE_ONLY_VERSION_UNPINNED`であり、NumPy/SciPy/xarrayの広いversion範囲を
正式保証していません。axis、dtype、欠損値、named dimension、device、lazy evaluation、
mutation、default semanticsは個別のcontract条件です。

## Core auditにLLMは不要

FormulaTracerのcore semantic auditはLLMや生成AIを必要としません。未知の意味を
model-generated guessで補わず、未解決のまま保持します。

## User-defined semantics: 冗長な根拠経路

`@cpp_audit.theory(output=..., expression=...)`は、user declarationを自動復元と
同じMathematical IR / relation / evidence / provenance経路へ入力します。private callback、
将来のlibrary、hardware kernel、source非公開の関数にも使えますが、第二のsemantic evaluator
ではありません。declaration単独でimplementation/reference/Lean verifiedへ昇格しません。

実装由来の数学が取得できる場合、独立した両経路を`MATCH` / `MISMATCH` /
`NOT_EVALUABLE`として比較します。callbackのvalue semanticsとeffectは分離され、式を保持しても
purityは`UNKNOWN_EFFECT`のままにできます。詳細は
[user-defined semantics](docs/concepts/user-defined-semantics.ja.md)を参照してください。

## Physics foundation

versioned physics foundationは多変数・vector calculus、geometric integral relation、
dimension/frame、SO(3)/quaternion、Fourier/Laplace relation、numerical realization、
選択されたSciPy callback境界を扱います。各項目は`DEFINED`、`THEOREM_REGISTERED`、
`LEAN_KERNEL_VERIFIED`、`REALIZATION_AVAILABLE`、`CONDITIONAL`、`PARTIAL`を区別します。

FormulaTracerが監査するのは数学と実装のrelationであり、physical lawのempirical truthを
証明するものではありません。一般形Noether、Gauss/Stokes、SE(3)、finite-volume error、
ADは、明示された証明義務が閉じるまでconditionalです。
[Physics support boundary](docs/physics-foundation.ja.md)を参照してください。

## Platform状態

| Platform | source/test | native package | 状態 |
|---|---|---|---|
| Windows x86-64 | local検証済み | wheel build / clean install検証 | Tested |
| Linux x86-64 | Debian GNU/Linux 12 (bookworm)、Python 3.11.2 | 実x86-64 Linuxコンテナでwheel/sdist build、clean install、native load、release suiteを検証 | この記録環境だけでTested |
| macOS | 未検証 | release wheel claimなし | Untested |

## 根拠model

- `KERNEL_VERIFIED`: Lean kernelで確認されたclaim。
- `KERNEL_VERIFIED_UNDER_ASSUMPTIONS`: 表示された仮定の下でkernel確認。
- `FORMALLY_DERIVED`: versioned rule/evidenceから形式的に導出。
- `REFERENCE_CONTRACT`: upstream public referenceに基づくcontract。
- `EMPIRICALLY_VALIDATED` / `RUNTIME_EVIDENCE`: testまたは今回の実行による根拠。proofではありません。
- `UNRESOLVED`: 曖昧性、未対応、contract不足、未解決の義務。

## 例・制約

- [TheoryなしPython audit](examples/python_audit/weighted_sum.py)
- [exact / non-exact / unresolved operational audit](examples/operational_audit/README.md)
- [Rust-only consumer](examples/rust_native/README.md)
- [C-only consumer](examples/c_native/README.md)
- [C++ RAII consumer](examples/cpp_native/README.md)

FormulaTracerはcompiler、CPU、すべての外部library implementation、研究者の科学的意図を証明せず、
general compiler、numerical solver、CAS、Leanの置換、arbitrary software完全検証器でもありません。
未知の意味を推測せず、科学的判断の代替でもありません。性能よりsemantic correctnessと
fail-closed behaviorを優先します。

runtimeでしか分からないcall target、非exhaustive dynamic key、unknown backend、impure/opaque
callback、未証明のconditional theoremはpartialまたはunresolvedです。「現在未解決」と
「原理的に不可能」は区別し、user contract/runtime/provider evidenceで閉じられる場合も、
static proofへ誤昇格させません。

## Documentation / Support / Security

[クラス・関数の使い方](docs/reference/api-usage-guide.ja.md)
（[English](docs/reference/api-usage-guide.md)）または
[Documentation index](docs/index.ja.md)から始めてください。bugは
[GitHub Issues](https://github.com/3e456/FormulaTracer/issues)、利用方法の質問は
[GitHub Discussions](https://github.com/3e456/FormulaTracer/discussions)、脆弱性は
[SECURITY.md](SECURITY.md)に従いGitHub Private vulnerability reportingから報告してください。
報告・support方針は[SUPPORT.md](SUPPORT.md)を参照してください。外部からのPull Requestは
現在受け付けていないため、修正提案はIssueまたはDiscussionへ提出してください。

公開reference: [Python functions](docs/reference/public-functions.ja.md) ·
[Rust](docs/reference/rust-api-reference.ja.md) · [C ABI](docs/reference/c-api-reference.ja.md) ·
[C++](docs/reference/cpp-api-reference.ja.md) ·
[result/status/evidence](docs/reference/result-model-reference.ja.md) ·
[providers](docs/reference/provider-api.ja.md) · [physics](docs/reference/physics-api.ja.md) ·
[user-defined semantics](docs/reference/user-defined-api.ja.md)

## 引用・ライセンス・貢献

FormulaTracer v0.1.1の引用にはDOI
[10.5281/zenodo.22171670](https://doi.org/10.5281/zenodo.22171670)を使用してください。
引用情報は[CITATION.cff](CITATION.cff)にあります。FormulaTracerは[Apache-2.0](LICENSE)です。
第三者分類と再配布の注意点は[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)を参照してください。
生成コードのlicenseはuser input、template、upstream provenanceに依存します。

外部参加方針は[CONTRIBUTING.md](CONTRIBUTING.md)を参照してください。外部からのPull Requestは
現在受け付けていません。
