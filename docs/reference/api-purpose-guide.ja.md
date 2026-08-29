# APIの目的と使い分け

[English](api-purpose-guide.md) | [詳細な使い方](api-usage-guide.ja.md) | [公開シンボル完全一覧](public-functions.ja.md)

このページは、網羅的なAPI一覧とは別の問いに答えるためのガイドです。

> **FormulaTracerで何をしたいときに、どのAPIを使えばよいのか。なぜそのAPIが存在するのか。**

詳細な使い方ガイドではsignature、引数、戻り値、ownership、実行可能なコード例を説明します。このページでは、**目的、使う場面、通常は使わない場面、似たAPIとの使い分け**に重点を置きます。

## まずここから：やりたいことから選ぶ

| やりたいこと | 最初に使うAPI | 理由 |
|---|---|---|
| 科学計算のソースコードを監査したい | `FormulaTracer.from_source(...)` → `analyze()` | 通常の高水準code-first workflowです。 |
| PARTIAL / UNRESOLVEDの原因箇所を知りたい | `FormulaTracer.debug(...)` | 通常監査にsource/semantic localizationを追加します。 |
| 以前のproject監査を安全に再利用したい | `analyze_incremental(...)` | staleなcacheを無条件に信用せず、再利用可能な解析だけを使います。 |
| 数式そのものを入力したい | `FormulaTracer.from_tex(...)` または `from_expression(...)` | source由来と偽らずに`MathematicalFormula`を作ります。 |
| 独立に得た2つの数学構造を比較したい | `compare_ir(...)` | 2つのMathematical IRのsemantic correspondenceを調べます。 |
| 数式をどの実装で表現できるか調べたい | `plan_generation(...)` / `MathematicalFormula.plan_generation(...)` | provider/実装候補を順位付けします。順位はproofではありません。 |
| 数式からコードを生成したい | `MathematicalFormula.generate(...)` | realizationを生成し、必要なら生成sourceを独立再監査できます。 |
| Theoryと制約から実装を合成したい | `FormulaTracer.synthesize(...)` | generationをまとめた高水準workflowです。生成とverificationは別です。 |
| 自作関数の本来の数学的意味を宣言したい | `@theory` / user-defined semantics | user-declared evidenceを追加します。自動verificationではありません。 |
| 再構築した数式へ値を代入・評価したい | `NativeMathematicalFunction` | Pythonの`eval()`を使わず、対応するpure Mathematical IRを評価します。 |
| native coreを直接操作したい | `NativeContext`, `NativeFormula`, `NativeResult` | native integration向けの低水準owned-handle APIです。 |
| custom frontendを作りたい | `ProjectAnalyzer`, `reconstruct(...)` | 高度なintegration APIです。通常ユーザーは直接使いません。 |
| native libraryをロードできるかだけ確認したい | `native_available()` | 環境確認用です。semantic evidenceではありません。 |

## 全体像

FormulaTracerでは、主に3つの方向があります。

```text
source code
   ↓
FormulaTracer.analyze()
   ↓
ProjectAuditResult
   ↓
再構築された数学 + relation + evidence + unresolved理由
```

```text
mathematical formula
   ↓
MathematicalFormula
   ↓
plan_generation() / generate()
   ↓
実装候補または生成source
   ↓
独立再監査
```

```text
独立なtheory IR + implementation IR
   ↓
compare_ir()
   ↓
semantic comparison result
```

どの経路を使うか迷った場合は、native APIや`reconstruct()`ではなく、まず`FormulaTracer`から始めてください。

---

## `FormulaTracer`

### 目的

科学計算sourceを監査するときの標準的な公開入口です。高水準の数式workflowを開始するときにも使います。

### 使う場面

- Python、Rust、C、C++ sourceをFormulaTracerで監査したい。
- internal IRを手作業せず、project/dependency discoveryから任せたい。
- 標準result model、diagnostics、provenance、error/range、debugger dataを取得したい。

### 通常は代わりに使わないAPI

- custom frontendを組み込むのでなければ`ProjectAnalyzer`。
- 独立したimplementation descriptionをすでに持っているのでなければ`reconstruct()`。
- native layerを直接扱う必要がなければ`NativeContext`。

### 最小workflow

```python
tracer = FormulaTracer.from_source("model.py")
result = tracer.analyze()
```

通常ユーザーが最初に覚えるべきAPIです。

---

## `FormulaTracer.analyze()`

### 目的

source/projectのoutputを監査し、**コードが実際に実装している数学**を再構築します。その際、evidence、assumption、relation、数値的claim、provenance、unresolved条件を保持します。

### 使う場面

次の問いに答えたいときです。

> **「このコードは実際にはどんな数学を計算していて、その結論はどの程度の証拠で支えられているか。」**

### 誤解してはいけない点

関数が正常終了しただけではformal verificationを意味しません。返却された`status`、`relation`、`evidence`、assumption、proof obligation、error/range、diagnosticsを読んでください。

### 主な戻り値

`ProjectAuditResult`を返します。

---

## `ProjectAuditResult`

### 目的

`analyze()`後に読む、project全体の中心的な監査結果です。

### これで確認すること

- project監査がFULL、PARTIAL、UNRESOLVEDのどの状態か。
- どのoutputが再構築されたか。
- どのoutputがproject-level statusの原因になったか。
- diagnostics、provenance、error/range、debugger情報は何か。

### 重要な区別

project-level statusは複数outputの要約です。あるoutputがFULLでも、別outputがUNRESOLVEDなら全体はPARTIALになり得ます。top-level statusだけでなくper-output resultも確認してください。

### 次に使うもの

- 特定outputを見る：`get_output(name)`
- 構造化出力：`to_dict()` / `to_json()`
- audit artifact保存：`write_json(path)`
- 原因箇所を見る：`debug()`

---

## `FormulaTracer.debug()`

### 目的

UNRESOLVED、mismatch、その他重要な監査結果が、**source/semantic structureのどこから生じたか**を調べます。

### 使う場面

`analyze()`で「何が起きたか」は分かったが、「どこで、なぜ起きたか」を知りたいときです。

### 代表的な問い

- どのsource locationで未解決operationが入ったか。
- どの再構築expression/relationがmismatchの原因か。
- どこでevidenceが不足したか。

### 注意

別のverification engineではありません。通常監査と同じsemanticsからlocalizationを導出します。

---

## `analyze_incremental()`

### 目的

以前の`ProjectAuditResult`と互換なcache情報を再利用し、変更後projectを効率よく再監査します。

### 使う場面

大きなprojectを繰り返し監査し、不要な再計算を減らしたいときです。

### 安全性

cache reuseはvalidity条件付きです。stale/incompatible cacheをsemantic evidenceとして黙って採用してはいけません。

### 初回監査

`analyze()`を使ってください。

---

## `MathematicalFormula`

### 目的

数学そのものを直接表現し、inspect、explain、transform、generation planning、realizationに使う高水準objectです。

### 使う場面

出発点がsource codeではなく数学のときです。

例：

- 論文やノート中のTeX式。
- canonical Mathematical IR。
- 表示、制約付け、変換、実装化したい数式。

### 誤解してはいけない点

`MathematicalFormula`が存在するだけでは、その数式を特定のimplementationが実装していることを意味しません。implementation correspondenceには独立したimplementation evidenceまたは比較が必要です。

---

## `FormulaTracer.from_tex()`

### 目的

人間向けTeX notationをFormulaTracerのstructured mathematical representationへ変換します。

### 使う場面

入力がTeXで書かれた数式のときです。

### 証拠境界

式をparseしただけでは、convergence、domain、inverse law、programとの一致は証明されません。曖昧なnotationをverified interpretationとして推測しません。

---

## `FormulaTracer.from_expression()`

### 目的

すでにstructuredなMathematical IR expressionから直接開始します。

### 使う場面

別のtrusted componentがFormulaTracer-compatible Mathematical IRをすでに生成しており、TeX parseが不要なときです。

---

## `compare_ir()`

### 目的

**独立に得た**2つのMathematical IR documentをFormulaTracerのcanonical semantic machineryで比較します。

### 使う場面

例えば次を比較したいときです。

- declared theory と codeから再構築した数学。
- 独立に再構築された2つのimplementation。
- generated realization と independent frontend reconstruction。

### 使わない場面

同じinternal objectから作った2つのrenderingを入れて、それを独立verificationとして扱うこと。

### 重要な境界

semantic relationがEXACTでも、それだけでLean kernel evidenceがあるとは限りません。`evidence`を別に確認してください。

---

## `plan_generation()` / `MathematicalFormula.plan_generation()`

### 目的

数式に対して、実装/provider候補を検索・順位付けし、assumption、constraint、relation、proof obligationを保持します。

### 使う場面

数学が分かっていて、次を知りたいときです。

> **「この数式を実現できる既存implementation/provider contractは何か。」**

### rankingの意味

rankingはsearch resultでありproofではありません。高順位candidateでも条件やobligationが残ることがあります。

### 主な戻り値

`GenerationPlan`。

---

## `GenerationPlan`

### 目的

1つのgeneration requestについて、candidate、search budget、selection state、relation、decision provenanceをまとめます。

### 使い方

- candidateがなぜ見つかったか調べる。
- candidate同士を比較する。
- unmet obligationを見る。
- rigorously eligibleなcandidateだけをselectする。

### 通常の生成方法

直接constructorを呼ぶより`plan_generation()`から取得します。

---

## `CandidateMatch`

### 目的

`GenerationPlan`内の1つのprovider/implementation候補を表します。

### これで見るもの

- どのprovider contractが一致したか。
- verification/eligibility state。
- 残るobligation。
- select可能/不可能な理由。

### 注意

candidate match自体はimplementation proofではありません。

---

## `MathematicalFormula.generate()`

### 目的

選択した数学的realizationからsource codeを生成します。

### 使う場面

数式から対応target languageのimplementation candidateを作りたいときです。

### 最重要の区別

生成されたsourceは、生成されたという理由だけでverifiedではありません。`verify=True`または`generated.verify()`による独立frontend再解析が、生成sourceを通常監査経路へ戻す段階です。

---

## `GeneratedMathematicalImplementation`

### 目的

生成source、realization status、独立再監査状態をまとめて保持します。

### 使い方

- emitted codeを見る。
- independent verificationが行われたか確認する。
- generated artifactとindependently audited artifactを区別する。

### 通常の生成方法

`MathematicalFormula.generate()`から得ます。

---

## `FormulaTracer.synthesize()`

### 目的

declared theoryとlanguage/constraint情報からimplementationを作る、より高水準のworkflowです。

### 使う場面

planningとgenerationを個別に呼ぶより、end-to-end synthesis workflowを使いたいときです。

### `generate()`との違い

`generate()`は既存`MathematicalFormula`とgeneration contextから動きます。`synthesize()`はtheory + constraints + target languageをまとめた高水準facadeです。

### 注意

同じworkflow内でverificationを要求しても、synthesisとverificationは意味上別の段階です。

---

## `@theory`

### 目的

functionのexecutionを変更せず、「このfunctionは本来この数学を実装する」というuser declarationを付けます。

### 使う場面

> **「この関数は、この数学的relationを実装する意図で書いた。」**

と明示したいときです。

user-defined/domain-specific functionに対する冗長evidenceとして有用です。

### これだけでは意味しないもの

- implementationがdeclarationと一致すると証明された。
- reference-backedである。
- Lean kernel verifiedである。

FormulaTracerはuser declaration、implementation-derived semantics、reference evidence、formal evidenceを区別して保持する必要があります。

---

## User-defined semantics

### 目的

FormulaTracerが完全には自動推論できないfunctionへ、数学的意味、effect、domain等を明示的に与えます。

### 使う場面

- callbackがexternal/opaque。
- proprietary/native/hardware functionのsourceを取得できない。
- 数学的意味はユーザーが知っているがstatic analysisからは得られない。

### 自動coverageが増えても残す理由

future libraryや取得不能implementationに対する冗長なsemantic input pathだからです。

### evidence境界

user-declared semanticsは明示的provenanceを持つevidenceです。implementation verificationやkernel verificationへ自動昇格しません。

---

## `ProjectAnalyzer`

### 目的

frontend/integration用の、より低水準なproject analysis入口です。

### 使う場面

custom source frontendを実装・組込みしたい場合や、analyzerを直接制御する必要がある場合です。

### 通常ユーザー

`FormulaTracer`を使ってください。

---

## `reconstruct()`

### 目的

独立に作られたimplementation-description requestをreconstruction kernelへ渡し、数学的semanticsを再構築します。

### 使う場面

frontendや外部analysis pipelineから、すでに低水準implementation/algorithm情報を得ているときです。

### 通常のsource監査

reconstruction requestを手作業で組まず、`FormulaTracer.analyze()`を使ってください。

### このAPIが存在する理由

implementation extractionとFormulaTracer mathematical reconstruction semanticsのintegration boundaryだからです。

---

## `ReconstructionResult`

### 目的

reconstruction outcomeを、exact/non-exact relation、assumption、obligation、diagnostics、unresolved理由を失わずに保持します。

### 使う場面

`reconstruct()`を使う場合や、frontend/integration toolingを構築する場合です。

### 重要な境界

`CORRECTLY_UNRESOLVED`は正しいfail-closed resultです。coverageを増やすためだけに架空のexact relationへ変換してはいけません。

---

## `NativeContext`

### 目的

native formula/result/function handleを作るFormulaTracer native contextを所有します。

### 使う場面

Pythonからstable native boundaryを直接使う場合や、native layerをintegration/testする場合です。

### 通常のPythonユーザー

`FormulaTracer`と高水準result objectを優先してください。

### ownership

owned native objectはcontext managerまたは`close()`で解放します。

---

## `NativeFormula`

### 目的

native core内部の数学式を所有し、native verification/comparison operationを提供します。

### 使う場面

native API levelを意図的に直接扱う場合です。

### 通常の取得方法

`NativeContext.formula_from_json(...)`または`formula_from_tex(...)`。

---

## `NativeResult`

### 目的

native verification result handleを所有し、structured projectionやrenderingを提供します。rendering自体をcanonical resultとはしません。

### 使う場面

native verification APIを直接呼んだ場合です。

### 通常ユーザー

native ownership/controlが必要でなければ、通常workflowが返す高水準structured resultを使ってください。

---

## `NativeMathematicalFunction`

### 目的

native function evaluatorが対応するMathematical IRについて、evaluate、substitute、inspect、serializeを行います。

### 使う場面

再構築済み/canonical mathematicsに対して次を行いたいときです。

- named valueで評価する。
- parameterを部分代入する。
- 対応backend向けcallableを作る。
- function schemaをserializeする。

### これは何ではないか

general Python-expression evaluatorではありません。unsupported operation、missing variable、domain error、shape mismatchはfail-closedになります。

---

## `native_available()`

### 目的

現在環境でpackaged stable native libraryをloadできるか確認します。

### 使う場面

installation/native-loading問題を診断するときです。

### これだけでは意味しないもの

`True`でも、formula、program、provider、theoremがverifiedされたというevidenceにはなりません。

---

## Result/evidence API：最初に何を読むか

structured audit/comparison resultでは、概ね次の順序で読むと理解しやすくなります。

1. **`status`** — 全体のsemantic outcome。
2. **`relation`** — exact、approximation、discretization等の数学的関係。
3. **`evidence`** — 結論を実際に支える証拠。
4. **`assumptions` / `proof_obligations`** — まだ必要な条件。
5. **`error` / `range`** — 適切なevidenceがある場合だけ成立する数値claim。
6. **`provenance`** — input、contract、結論がどこから来たか。
7. **`diagnostics` / debugger情報** — PARTIAL/UNRESOLVEDの理由と発生箇所。

TeX、JSON、Markdown、説明文など、読みやすいrenderingからより強い保証を推測しないでください。

## 高水準APIと高度なAPI

### 多くのユーザーが最初に覚えるもの

- `FormulaTracer`
- `analyze()`
- `ProjectAuditResult`
- `debug()`
- `MathematicalFormula`
- `compare_ir()`
- generationが必要なら`plan_generation()` / `generate()`
- custom functionの意味を宣言するなら`@theory` / user-defined semantics

### 高度なintegration API

- `ProjectAnalyzer`
- `reconstruct()` / `ReconstructionResult`
- `NativeContext`
- `NativeFormula`
- `NativeResult`
- `NativeMathematicalFunction`

高度なAPIがpublicなのはintegration/native workflowに有用だからであり、全ユーザーが直接使う必要があるからではありません。

## 関連ドキュメント

- [クラス・関数の詳細な使い方](api-usage-guide.ja.md)
- [公開関数完全一覧](public-functions.ja.md)
- [Result model](result-types.ja.md)
- [User-defined semantics](../concepts/user-defined-semantics.ja.md)
- [C ABI](c-api.md)
- [Rust API](rust-api.md)
