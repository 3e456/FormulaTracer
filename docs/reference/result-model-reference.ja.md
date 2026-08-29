# 構造化Result Model

FormulaTracer 0.1.0は構造化された`VerificationResult`/`NativeResult`を返します。
`to_tex()`、`to_json()`、`to_dict()`、`explain()`は派生表現であり、それ自体が
canonical resultではありません。

| Field | 意味 | 情報不足時の挙動 |
|---|---|---|
| `status` | exact/certified/empirical/failed/unresolvedの全体状態 | 数値的に近いだけでは昇格しない |
| `theory` | 存在する場合の独立登録理論 | `None`でもcode-first再構築は可能 |
| `implementation` | source/IRから再構築した数学 | 未知演算はopaqueのまま保持 |
| `relation` | 対象間のexactまたはnon-exact関係 | 不明なら`UNRESOLVED` |
| `assumptions` | 条件付きclaimが使う仮定 | 未解消仮定を表示し続ける |
| `proof_obligations` | 追加で必要な証拠 | 未解消なら強いcertificationを禁止 |
| `error`, `range` | certified/symbolic/empirical/unresolvedな境界 | runtime推定値はcertificateではない |
| `evidence` | claim authorityと来歴 | 証拠classを混同しない |
| `provenance`, `debugger` | source/IR/rewrite traceと局所化 | 曖昧なoriginを単一exact spanとしない |
| `reconstruction` | Formula→Code→Formulaの詳細結果 | `CORRECTLY_UNRESOLVED`は安全側の結果 |

`KERNEL_VERIFIED`はLean kernelが受理した証拠からのみ出力します。`USER_DECLARED`、
provider reference、structural witness、runtime observationは弱いauthorityのまま保持します。

