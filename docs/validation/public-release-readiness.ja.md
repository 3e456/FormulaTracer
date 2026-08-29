# Public release readiness

revisionと実行根拠は`output/public_release_audit/final-public-release-assessment.json`にあります。
この文書は判定境界を説明するもので、実際の公開を宣言しません。

FormulaTracerは科学計算コードから数学を復元し、relation、仮定、証明義務、error/range、
provider contract、provenance、localizationを統合します。Theory比較は任意の後段です。

FormulaTracer 0.1.0のPython distributionはPython 3.10+、native開発はRust 1.85+ (edition 2021)、
C ABI v1、C++20 build、LLVM/Clang major 18、Lean/mathlib 4.19.0を使います。Rust/C/C++利用者は
native Rust APIまたはC ABI v1からPythonなしでcoreを使えます。native CLIは現在semantic document操作であり、
Rust source全体の監査orchestrationは公閃claimに含めません。

provider contractは選択APIのみを対象とします。external providerのversion範囲は、version別upstream照合が
完了するまで公閃上未固定です。記録済みのreference insufficient 4件は正しく未解決とし、
supportedへ昇格しません。

Apache-2.0を維持推奨とし、runtime、compiled Rust、build、proof、optional provider、validation-only、
reference-onlyを分離します。public exampleはsyntheticです。private research source/formula/dataset/path/credential/outputは
公閃artifactへ含めません。脆弱性はGitHub Private vulnerability reportingから報告します。

`PUBLIC_RELEASE_READY`は推測ではなく自動判定します。Python/Rust/C/C++/Lean全回帰、standalone example、
Windows/Linux clean wheel install、sdist、link/example、license artifact、privacy、semantic ownership gateが記録された場合のみtrueです。
