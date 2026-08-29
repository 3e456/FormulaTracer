# Result型とstatusの読み方

[English](result-types.md) | [APIの目的と使い分け](api-purpose-guide.ja.md) | [クラス・関数の詳細な使い方](api-usage-guide.ja.md)

FormulaTracerのresultは、単一の`PASS/FAIL`ではなく、**何が再構築され、どの関係が成立し、何がその結論を支え、何がまだ未解決か**を分けて保持します。

## まず読むfield

| Field | 目的 |
|---|---|
| `status` | 監査・比較・再構築の全体的なsemantic outcomeを示します。 |
| `theory` | 比較対象となる理論側のstructured mathematicsです。 |
| `implementation` | source/Implementation IR側から得られたstructured mathematicsです。 |
| `relation` | theoryとimplementationの間がexact、approximation、discretization等のどの関係かを表します。 |
| `assumptions` | 結論が依存する前提条件です。 |
| `proof_obligations` | まだ満たす必要がある証明義務です。 |
| `diagnostics` | PARTIAL/UNRESOLVEDや不一致の理由を説明します。 |
| `error` | 数値error claimです。証拠がなければboundを捏造しません。 |
| `range` | 値域・上下界のclaimです。証拠の有無を別に確認します。 |
| `evidence` | 結論を実際に支える証拠の種類と強さです。 |
| `provenance` | source、provider contract、user declaration等の由来です。 |
| `debugger` | source/semantic locationを追跡するための情報です。 |
| `reconstruction` | Mathematical IR再構築の詳細、relation chain、未解決理由等です。 |

実際の型にfieldが存在する範囲は各API referenceを優先してください。

## `status`だけでverifiedと判断しない

`status`は重要ですが、それだけでは証拠の種類を表しません。

例えばsemantic equalityが成立していても、次は別々に確認する必要があります。

- implementation-derived evidenceがあるか。
- reference-backed evidenceがあるか。
- user declarationだけなのか。
- Lean kernel evidenceがあるか。
- runtime observationだけなのか。

したがって、通常は`status`と`evidence`をセットで読みます。

## project-level resultとoutput-level result

`ProjectAuditResult`ではproject全体のstatusと各outputのstatusを区別してください。

```text
ProjectAuditResult
├─ output A: FULLY_VERIFIED
├─ output B: FULLY_VERIFIED
└─ output C: UNRESOLVED

→ project全体はPROJECT_UNRESOLVEDになり得る
```

project-level statusだけを見て、すべてのoutputが同じ状態だと解釈しないでください。

## `relation`

`relation`は「2つの式が似ているか」ではなく、FormulaTracerが保持する数学的関係です。

代表的には次のような種類があります。

- exact equality
- approximation
- discretization
- truncation
- sampling
- algorithmic realization

non-exact relationをExact E-Graph equalityとして扱いません。

## `evidence`

`evidence`はclaim strengthを判断する中心fieldです。

概念的には次を区別します。

- implementationから再構築された証拠
- official/reference-backed evidence
- provider contract evidence
- runtime observation
- user declaration
- structural correspondence
- Lean kernel verified evidence
- unresolved / insufficient evidence

**`USER_DECLARED`は`LEAN_KERNEL_VERIFIED`ではありません。**

また、runtimeで値が一致したことだけを全入力での数学的一致とは扱いません。

## `assumptions`と`proof_obligations`

結論が条件付きの場合、その条件を捨てずに保持します。

例：

- 分母が0でない。
- domain条件を満たす。
- theorem適用に必要なregularityがある。
- provider realizationのpreconditionを満たす。

未解決obligationがある場合、無条件verifiedへ昇格させません。

## `error`と`range`

数値errorやrangeは、単なるannotationではなく、そのclaimを支えるevidenceと一緒に解釈してください。

FormulaTracerがcertificateを持たない場合、経験的な値や推測をcertified boundとして返さないことがfail-closed設計の一部です。

## `diagnostics`と`debugger`

PARTIAL / CORRECTLY_UNRESOLVEDが返った場合、次に見る場所です。

- `diagnostics`: 何が不足しているか。
- `debugger`: source/semantic structureのどこで不足が生じたか。

「対応していない」で終わらず、missing callback、unknown backend、dynamic dispatch、insufficient typing/effect information等の具体的な理由を確認するために使います。

## `CORRECTLY_UNRESOLVED`

これは主に`ReconstructionResult`で使われ、FormulaTracerの失敗を意味するとは限りません。project/output監査では対応するfail-closed statusとして`PROJECT_UNRESOLVED` / `UNRESOLVED`等が使われます。

現在利用可能なsource、provider、user contract、runtime evidence等からsoundに結論を出せないとき、推測せず未解決を保持した結果です。

```text
情報不足
  ↓
推測してEXACTにする     ×
CORRECTLY_UNRESOLVED     ○
```

## renderingはcanonical resultではない

TeX、JSON、Markdown、Unicode、human explanationはresultを表示・交換するための表現です。

読みやすいrenderingが生成されたこと自体をproofとして扱わないでください。canonical structured resultと`evidence`が判断基準です。

## 関連ドキュメント

- [APIの目的と使い分け](api-purpose-guide.ja.md)
- [クラス・関数の詳細な使い方](api-usage-guide.ja.md)
- [公開関数一覧](public-functions.ja.md)
- [User-defined semantics](../concepts/user-defined-semantics.ja.md)
