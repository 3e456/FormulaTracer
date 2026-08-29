# クラス・関数の使い方

[English](api-usage-guide.md) | [APIの目的と使い分け](api-purpose-guide.ja.md) | [全公開シンボル一覧](public-functions.ja.md) | [実行可能な例](../../examples/api_reference_usage.py)

このガイドは、一般的なクラス／関数リファレンスと同様に、主要公開APIの
シグネチャ、引数、既定値、戻り値、例外、所有権、実コードを説明します。
全シンボルの網羅的な一覧は生成済み言語別リファレンスを参照してください。

## 共通ルール

- Text、JSON、Markdown、Unicode、TeXは構造化objectの派生表現であり、正規の
  検証結果ではありません。
- function callの完了はproofではありません。`status`、`relation`、`assumptions`、
  `proof_obligations`、`evidence`を確認します。
- 未対応または曖昧な入力は、例外または明示的なunresolved statusでfail-closedします。
- native owned objectは`with`と`close()`に対応します。

## `FormulaTracer`

Code-firstの主要facadeです。

```python
FormulaTracer(
    entry_source: str | Path,
    *,
    project_root: str | Path | None = None,
    frontend: LanguageFrontend | None = None,
    resolver: DependencyResolver | None = None,
)
```

| 引数 | 型／既定値 | 意味 |
|---|---|---|
| `entry_source` | `str | Path` | Python、Rust、C/C++のentry source。 |
| `project_root` | `str | Path | None = None` | dependency探索root。省略時は推定します。 |
| `frontend` | `LanguageFrontend | None = None` | 明示的なfrontend override。 |
| `resolver` | `DependencyResolver | None = None` | 明示的なdependency resolver override。 |

戻り値は`FormulaTracer`です。コンストラクタだけでは監査を実行しません。

### コンストラクタ

| method | 引数 | 戻り値 | 用途 |
|---|---|---|---|
| `from_source(source, **options)` | source pathとコンストラクタoption | `FormulaTracer` | source入力を明示。 |
| `from_tex(tex, **options)` | TeX、assumption、declaration、language | `MathematicalFormula` | 人間向け数式をparse。 |
| `from_expression(expression, **options)` | canonical IR dictionaryとoption | `MathematicalFormula` | Mathematical IRから開始。 |

曖昧なTeXは`NotationResolutionError`になります。推測でverified interpretationへ
変換しません。

### `analyze()`

```python
analyze(
    targets=None,
    *,
    ranges=None,
    output_ranges=None,
    observed_results=None,
    error_specifications=None,
    model_error_scopes=None,
    input_artifacts=(),
    configuration=(),
    audit_profile="RESEARCH",
) -> ProjectAuditResult
```

| 引数 | 意味 |
|---|---|
| `targets` | 出力名、`OutputTarget`、またはiterable。`None`なら出力を探索。 |
| `ranges` | range解析に使う入力範囲。 |
| `output_ranges` | 出力名から期待constraintへのmapping。 |
| `observed_results` | 実行時観測。実行時のevidenceとして保持。 |
| `error_specifications` | 宣言された誤差成分。宣言だけではcertificateになりません。 |
| `model_error_scopes` | model error termの適用範囲。 |
| `input_artifacts` | provenance付きinput artifact。 |
| `configuration` | configuration provenance。 |
| `audit_profile` | acceptance profile。既定値は`"RESEARCH"`。 |

戻り値は`ProjectAuditResult`です。主要fieldは`status`、`roots`、`outputs`、
`diagnostics`、provenance、error/range claim、debugger dataです。

```python
from formulatracer import FormulaTracer

tracer = FormulaTracer.from_source(
    "examples/python_audit/weighted_sum.py",
    project_root="examples/python_audit",
)
result = tracer.analyze(targets="weighted_score")
print(result.status)
for output in result.outputs:
    print(output.name, output.formula["op"], output.status)
```

`ProjectAnalyzer`は同じ`entry_source`、`project_root`、`frontend`、`resolver`を
受け取り、`analyze(targets=None) -> ProjectAuditResult`を提供します。frontend統合で
直接analyzerが必要な場合以外は`FormulaTracer`を推奨します。`ProjectAuditResult`には
`get_output(name)`、`to_dict()`、`to_json(indent=2)`、`write_json(path) -> Path`もあります。

その他のmethod:

| method | 戻り値 | 説明 |
|---|---|---|
| `debug(targets=None, **analyze_options)` | debugger result | 同じ監査からlocalizationを導出。 |
| `analyze_incremental(previous, *, cache=None, **options)` | incremental result | `previous`は`ProjectAuditResult`。cache validityはfail-closed。 |
| `synthesize(*, theory, language, constraints=None, output_path=None, verify=True)` | synthesis result | `language`は`python`、`rust`、`cpp`。生成と検証を分離。 |

## `MathematicalFormula`

`FormulaTracer.from_tex()`または`from_expression()`から作ります。

```python
formula = FormulaTracer.from_tex(
    r"\frac{x}{a}+\frac{y}{a}",
    assumptions=["a != 0"],
    language="ja",
)
print(formula.to_tex())
print(formula.inspect())
print(formula.explain(language="ja"))
```

### 確認と表示

| method | 引数 | 戻り値 |
|---|---|---|
| `to_tex()` | なし | canonical TeX `str`。 |
| `to_unicode()` | なし | Unicode数式`str`。 |
| `to_markdown()` | なし | Markdown `str`。 |
| `to_dsl()` | なし | FormulaTracer DSL `str`。 |
| `to_json()` | なし | canonical IRのJSON `str`。 |
| `inspect()` | なし | expression、surface、assumption、declaration、featureを含む`dict`。 |
| `explain(*, language=None)` | `"en"`または`"ja"` | 人間向け説明`str`。 |
| `debug(path=())` | semantic path iterable | 数学nodeのdebug location。 |

### assumptionとdomain

| method | 引数 | 戻り値／効果 |
|---|---|---|
| `assume(*assumptions)` | assumption文字列 | declarationを追加した同じ`MathematicalFormula`。 |
| `assume_tex(tex)` | TeX assumption | 同じformula。 |
| `domain(symbol, domain)` | symbol名、`Domain | str` | domain declarationを追加した同じformula。 |
| `certified_range(symbol, lower, upper, *, evidence="DECLARED")` | symbolと上下限 | evidence分類を保持した同じformula。 |

### 数学コンストラクタ

| method | 引数と既定値 | 戻り値 |
|---|---|---|
| `taylor(function, variable="x", order=5, center=0)` | 関数名、変数、有限order、center | Taylor `MathematicalFormula`。 |
| `maclaurin(function, variable="x", order=5)` | 関数名、変数、有限order | Maclaurin formula。 |
| `fourier(function="f")` | 関数名 | Fourier transform formula。 |
| `inverse_fourier(function="F")` | 変換後関数名 | inverse Fourier formula。 |
| `laplace(function="f")` | 関数名 | Laplace transform formula。 |
| `inverse_laplace(function="F")` | 変換後関数名 | inverse Laplace formula。 |
| `fourier_series(function="f", variable="x", period="2*pi")` | 関数、変数、周期 | Fourier series formula。 |
| `truncate(terms)` | 正のterm数 | relationを保持したtruncated formula。 |
| `truncate_symmetric(radius)` | 0以上のradius | symmetric truncated formula。 |

これらを呼んだだけではconvergence、ROC、inverse lawを証明しません。

## Generation planning

```python
MathematicalFormula.plan_generation(**options) -> GenerationPlan

plan_generation(
    expression,
    *,
    search="normal",
    candidate_budget=None,
    budget=None,
    registry=None,
    assumptions=(),
    authorized_rewrites=None,
    language=None,
) -> GenerationPlan
```

| 引数 | 意味 |
|---|---|
| `expression` | canonical Mathematical IR dictionary。 |
| `search` | `"normal"`またはhigh-recallの`"broad"`。 |
| `candidate_budget` | `SearchBudget`がない場合のretrieval上限。 |
| `budget` | retrieval/unification/verification用の詳細`SearchBudget`。 |
| `registry` | `ProviderContract` iterable。省略時はdefault registry。 |
| `assumptions` | typed matchingで利用できるfact。 |
| `authorized_rewrites` | matchingで許可するexact rewrite ID。 |
| `language` | `python`、`rust`、`cpp`へ限定。 |

`GenerationPlan`は`status`、`candidates`、`budget`、`selected`、relation graph、
decision provenanceを持ちます。

```python
formula = FormulaTracer.from_tex("x + 2")
plan = formula.plan_generation(search="broad", language="python")
print(plan.explain(language="ja", limit=5))

candidate = plan.select()
print(candidate.contract.provider_id)
print(candidate.verification_status)
print(candidate.remaining_obligations)
```

| method | 戻り値 | 失敗時 |
|---|---|---|
| `plan.explain(*, language="en", limit=10)` | `str` | — |
| `plan.candidate(provider_id)` | `CandidateMatch` | 存在しなければ`KeyError`。 |
| `plan.select(provider_id=None)` | 証拠要件を満たして採用可能な`CandidateMatch` | 候補がなければ`ValueError`。 |

similarityとrankingは候補を調べる理由でありproofではありません。

### 生成と独立再監査

```python
generate(
    *, provider=None, auto_select=False, verify=False,
    search="normal", language="python",
) -> GeneratedMathematicalImplementation
```

```python
generated = formula.generate(
    language="python",
    auto_select=True,
    verify=True,
)
print(generated.source)
print(generated.status)
```

初期statusは`SOURCE_GENERATED_UNVERIFIED`です。`verify=True`または
`generated.verify()`で独立frontend再解析を行います。

## `compare_ir()`とstructured result

```python
compare_ir(theory: dict[str, Any], implementation: dict[str, Any]) -> NativeResultValue
```

`theory`と`implementation`は独立に取得したMathematical IRでなければなりません。
戻り値は`status`、`theory`、`implementation`、`relation`、`assumptions`、
`diagnostics`、`evidence`、`error`、`range`、`provenance`、`debugger`、
`reconstruction`を持ちます。

```python
from formulatracer import compare_ir

expression = {
    "op": "Add",
    "args": [
        {"op": "Power", "args": [
            {"op": "FreeVariable", "name": "x"},
            {"op": "Constant", "value": 2},
        ]},
        {"op": "FreeVariable", "name": "a"},
    ],
}
result = compare_ir(expression, expression)
print(result.status)         # EXACT_EQUALITY
print(result.relation.kind)
print(result.to_dict())      # dict
print(result.to_json())      # JSON str
print(result.to_tex())       # certificate TeX
print(result.explain("ja"))
```

`result.evidence`は別に確認します。`EXACT_EQUALITY`だけではLean kernel evidenceが
存在するとは限りません。

`native_available() -> bool`はstable native libraryをloadできるか確認します。`False`は
native operationを利用できないという意味です。`True`はcapability情報であって
verification evidenceではありません。

## Native owned class

### `NativeContext`と`NativeFormula`

```python
NativeContext(library: NativeLibrary | None = None)
context.formula_from_json(value: dict | str) -> NativeFormula
context.formula_from_tex(tex: str) -> NativeFormula
NativeFormula.verify() -> NativeResult
NativeFormula.verify_against(implementation: NativeFormula) -> NativeResult
```

```python
from formulatracer import NativeContext

ir = {"op": "Constant", "value": 42}
with NativeContext() as context:
    with context.formula_from_json(ir) as theory:
        with context.formula_from_json(ir) as implementation:
            with theory.verify_against(implementation) as result:
                print(result.value.status)
                print(result.to_json())  # NativeResultではdict
                print(result.to_tex())
```

不正または未対応callは`NativeCallError`、native libraryがない場合は
`NativeUnavailableError`です。全owned wrapperを`with`または`close()`で解放します。

### `NativeResult`

| member | 戻り値 |
|---|---|
| `value` | ergonomicなstructured projectionである`NativeResultValue`。 |
| `to_json()` | このowned wrapperでは`dict[str, Any]`。 |
| `to_tex()` | certificate TeX `str`。 |
| `to_audit_bundle(source_context=None, environment=None, artifact_lineage=None)` | integrity-protected AuditBundle `dict`。 |
| `close()` | `None`。native handleを解放。 |

### `NativeMathematicalFunction`

`result.theory.as_function()`、`from_ir(...)`、`from_schema(...)`から作ります。

```python
function = result.theory.as_function()
try:
    assert function.evaluate(x=3, a=2) == 11.0
    assert function(x=3, a=2) == 11.0
    fixed = function.substitute(a=2)
    try:
        assert fixed(x=4) == 18.0
        print(fixed.to_tex())
        print(fixed.inspect()["variables"])  # ["x"]
    finally:
        fixed.close()
finally:
    function.close()
```

| method | 引数 | 戻り値 |
|---|---|---|
| `from_ir(ir, *, assumptions=(), evidence=(), provenance=None)` | IRとmetadata | owned function。 |
| `from_schema(schema)` | portable function schema | owned function。 |
| `evaluate(**values)` / `__call__(**values)` | 名前付きscalar/array | JSON-compatible value。 |
| `substitute(**values)` | 名前付き置換 | 新しいowned function。 |
| `to_callable(backend="python")` | `python`またはoptional `numpy` | keyword引数を取るcallable。 |
| `to_schema()` / `to_dict()` | なし | portable `dict`。 |
| `inspect()` | なし | variable、parameter、assumption、metadata。 |
| `to_tex()` | なし | function TeX `str`。 |
| `close()` | なし | handle/contextを解放。 |

Pythonの`eval()`は使いません。入力不足、未対応operation、domain違反、shape mismatchは
`NativeCallError`になります。`result.error.as_function()`と
`result.range.lower/upper.as_function()`はcertified evidenceがある場合だけ使えます。
`BOUND_NOT_AVAILABLE`を経験的なboundへ変換しません。

## `reconstruct()`

```python
reconstruct(request: Mapping[str, Any]) -> ReconstructionResult
```

versioned requestは独立復元したimplementation情報を記述します。戻り値は
exact/non-exact relation、assumption、proof obligation、diagnostic、unresolved reasonを
保持します。

```python
from formulatracer import reconstruct

ir = {"op": "Constant", "value": 2}
request = {
    "original_theory": ir, "reconstructed_theory": ir,
    "structural_facts": {}, "temporaries": [], "result_expression": None,
    "safety": {}, "algorithm_ir": None, "provider_projection": None,
    "relation_chain": [], "assumptions": [], "proof_obligations": [],
    "exact_egraph_verified": False, "error": None, "range": None,
    "provenance": None,
}
reconstruction = reconstruct(request)
print(reconstruction.status)
print(reconstruction.to_dict())
print(reconstruction.explain("ja"))
```

`ReconstructionResult.to_dict() -> dict[str, Any]`はportable structured resultを返します。
`explain(language="en") -> str`は`"en"`と`"ja"`に対応し、canonical statusを変更しません。

`CORRECTLY_UNRESOLVED`は安全なsemantic outcomeです。exact relationを捏造しません。

## Theory decorator

```python
from cpp_audit import theory

@theory(
    output="score",
    expression="score = sum(i=0..N-1, values[i] * weights[i])",
)
def calculate_score(values, weights):
    import numpy as np
    return np.sum(values * weights)
```

引数はkeyword-only文字列`output`と`expression`です。戻り値は元のcallableを返す
decoratorです。user declarationを記録しますが、実行を変更せず、コードから独立復元した
implementation formulaの代わりにも使いません。

## Rust、C++、C

Rust native API:

```rust
use formulatracer_core::Formula;

let theory = Formula::from_json(r#"{"op":"Constant","value":42}"#)?;
let implementation = Formula::from_json(r#"{"op":"Constant","value":42}"#)?;
let result = theory.verify_against(&implementation);
println!("{}", result.status);
println!("{}", result.to_json()?);
# Ok::<(), Box<dyn std::error::Error>>(())
```

C++ RAII wrapper:

```cpp
formulatracer::Context context;
auto theory = formulatracer::Formula::from_json(
    context, R"({"op":"Constant","value":42})");
auto implementation = formulatracer::Formula::from_json(
    context, R"({"op":"Constant","value":42})");
auto result = theory.verify_against(implementation);
std::cout << result.to_json() << '\n';
```

C ABI v1:

```c
FT_Context *context = ft_context_create();
FT_Formula *formula = ft_formula_from_json(
    context, "{\"op\":\"Constant\",\"value\":42}");
FT_Result *result = ft_verify(context, formula);
char *json = ft_result_to_json(result);
/* jsonを使用 */
ft_string_free(json);
ft_result_free(result);
ft_formula_free(formula);
ft_context_free(context);
```

FormulaTracerが所有するC文字列は`ft_string_free`、opaque handleは対応する`*_free`で
解放します。続きは[C reference](c-api-reference.ja.md)、
[C++ reference](cpp-api-reference.ja.md)、[Rust reference](rust-api-reference.ja.md)を
参照してください。
