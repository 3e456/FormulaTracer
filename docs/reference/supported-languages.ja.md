# 対応言語とtoolchain

| 言語/tool | 役割 | version | 通常の利用者に必要? |
|---|---|---|---|
| Python | facade / CLI / Python frontend | >= 3.10 | Python distributionのみ |
| Rust | 単一semantic core / native CLI | >= 1.85, edition 2021 | wheel/native binaryでは不要 |
| C | stable ABI | ABI v1 | C consumer buildのみ |
| C++ | Clang frontend / RAII wrapper | 監査入力C++17/20、build C++20 | native C++利用時のみ |
| LLVM/Clang | C/C++ frontend | major 18 | optional frontend/開発者のみ |
| Lean/mathlib | 独立proof layer | 4.19.0 / 4.19.0 | proof開発者のみ |

FormulaTracerの実装言語、監査入力言語、生成対象言語は別です。生成対象は
Python/Rust/C++です。native CLIはsemantic document操作であり、Rust source監査全体の
native orchestrationは現時点で公開機能ではありません。
