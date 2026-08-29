# User-defined Semanticsリファレンス

Python監査frontendは互換decorator
`cpp_audit.theory(output=..., expression=...)`を公開します。これはtheory metadataを
付与するだけで関数実行を変えません。implementation式は引き続きPython ASTから独立再構築します。

```python
from cpp_audit import theory

@theory(output="y", expression="y = sum(i=0..n-1, x[i])")
def custom_sum(x):
    total = 0.0
    for value in x:
        total += value
    return total
```

native `USER_DECLARATION`比較は`MATCH`、`MISMATCH`、`NOT_EVALUABLE`を返します。
証拠は常に`USER_DECLARED`かつ`auto_verified=false`です。callbackのeffectが不明なら
`UNKNOWN_EFFECT`のままであり、値の式を宣言してもpurity、termination、units、frames、
shape、dtype、domainは証明されません。

宣言はcode-derived再構築の代替ではなく、冗長な意図・証拠pathとして使います。
不一致は監査findingです。

