# Class and Function Usage Guide

[日本語](api-usage-guide.ja.md) | [API purpose and selection](api-purpose-guide.md) | [Complete generated inventory](public-functions.md) | [Runnable example](../../examples/api_reference_usage.py)

This guide documents the normal public API at the level expected from a class
and function reference: signatures, arguments, defaults, return values,
exceptions, ownership, and real code. The generated language references remain
the exhaustive symbol inventory.

## Common rules

- Text, JSON, Markdown, Unicode, and TeX are renderings of structured objects;
  they are not the canonical verification result.
- A completed call is not proof. Read `status`, `relation`, `assumptions`,
  `proof_obligations`, and `evidence`.
- Unsupported or ambiguous input fails closed as an exception or an explicit
  unresolved status.
- Owned native objects support `with` and `close()`.

## `FormulaTracer`

Primary code-first facade.

```python
FormulaTracer(
    entry_source: str | Path,
    *,
    project_root: str | Path | None = None,
    frontend: LanguageFrontend | None = None,
    resolver: DependencyResolver | None = None,
)
```

| Argument | Type / default | Meaning |
|---|---|---|
| `entry_source` | `str | Path` | Python, Rust, or C/C++ entry source. |
| `project_root` | `str | Path | None = None` | Dependency-discovery root; inferred when omitted. |
| `frontend` | `LanguageFrontend | None = None` | Explicit frontend override. |
| `resolver` | `DependencyResolver | None = None` | Explicit dependency resolver override. |

Returns a `FormulaTracer`; construction does not run an audit.

### Constructors

| Method | Arguments | Returns | Use |
|---|---|---|---|
| `from_source(source, **options)` | source path; constructor options | `FormulaTracer` | Explicit source-oriented constructor. |
| `from_tex(tex, **options)` | TeX plus assumptions/declarations/language | `MathematicalFormula` | Parse human mathematical notation. |
| `from_expression(expression, **options)` | canonical IR dictionary plus options | `MathematicalFormula` | Start from Mathematical IR. |

Ambiguous TeX raises `NotationResolutionError`; it is not guessed into a
verified interpretation.

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

| Argument | Meaning |
|---|---|
| `targets` | Output name, `OutputTarget`, or iterable; `None` discovers outputs. |
| `ranges` | Input range specification used by range analysis. |
| `output_ranges` | Mapping from output names to expected constraints. |
| `observed_results` | Runtime observations; these remain runtime evidence. |
| `error_specifications` | Declared error components; declarations are not certificates. |
| `model_error_scopes` | Mapping describing where model-error terms apply. |
| `input_artifacts` | Provenance-bearing input artifact records. |
| `configuration` | Configuration provenance records. |
| `audit_profile` | Acceptance profile; default `"RESEARCH"`. |

Returns `ProjectAuditResult`. Its principal fields are `status`, `roots`,
`outputs`, `diagnostics`, provenance, error/range claims, and debugger data.

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

`ProjectAnalyzer` accepts the same `entry_source`, `project_root`, `frontend`,
and `resolver` arguments and exposes
`analyze(targets=None) -> ProjectAuditResult`. Prefer `FormulaTracer` unless a
frontend integration needs direct analyzer access. `ProjectAuditResult` also
provides `get_output(name)`, `to_dict()`, `to_json(indent=2)`, and
`write_json(path) -> Path`.

Other methods:

| Method | Returns | Notes |
|---|---|---|
| `debug(targets=None, **analyze_options)` | debugger result | Runs the same audit and derives localization. |
| `analyze_incremental(previous, *, cache=None, **options)` | incremental result | `previous` must be a `ProjectAuditResult`. Cache validity fails closed. |
| `synthesize(*, theory, language, constraints=None, output_path=None, verify=True)` | synthesis result | `language` is `python`, `rust`, or `cpp`; generation and verification remain separate. |

## `MathematicalFormula`

Created through `FormulaTracer.from_tex()` or `from_expression()`.

```python
formula = FormulaTracer.from_tex(
    r"\frac{x}{a}+\frac{y}{a}",
    assumptions=["a != 0"],
    language="en",
)
print(formula.to_tex())
print(formula.inspect())
print(formula.explain(language="en"))
```

### Inspection and rendering

| Method | Arguments | Returns |
|---|---|---|
| `to_tex()` | none | Canonical TeX `str`. |
| `to_unicode()` | none | Unicode mathematical `str`. |
| `to_markdown()` | none | Markdown `str`. |
| `to_dsl()` | none | FormulaTracer DSL `str`. |
| `to_json()` | none | Canonical IR JSON `str`. |
| `inspect()` | none | `dict` containing expression, surface, assumptions, declarations, and features. |
| `explain(*, language=None)` | `"en"` or `"ja"` | Human-facing explanation `str`. |
| `debug(path=())` | semantic path iterable | Structured mathematical debug location. |

### Assumptions and domains

| Method | Arguments | Returns / effect |
|---|---|---|
| `assume(*assumptions)` | assumption strings | Same `MathematicalFormula`, with declarations appended. |
| `assume_tex(tex)` | TeX assumption | Same formula. |
| `domain(symbol, domain)` | symbol name; `Domain | str` | Same formula with a domain declaration. |
| `certified_range(symbol, lower, upper, *, evidence="DECLARED")` | symbol and bounds | Same formula; evidence remains explicitly classified. |

### Mathematical constructors

| Method | Arguments and defaults | Returns |
|---|---|---|
| `taylor(function, variable="x", order=5, center=0)` | function name, variable, finite order, center | Taylor `MathematicalFormula`. |
| `maclaurin(function, variable="x", order=5)` | function name, variable, finite order | Maclaurin formula. |
| `fourier(function="f")` | function name | Fourier-transform formula. |
| `inverse_fourier(function="F")` | transformed function name | Inverse-Fourier formula. |
| `laplace(function="f")` | function name | Laplace-transform formula. |
| `inverse_laplace(function="F")` | transformed function name | Inverse-Laplace formula. |
| `fourier_series(function="f", variable="x", period="2*pi")` | function, variable, period | Fourier-series formula. |
| `truncate(terms)` | positive term count | Truncated formula preserving the relation. |
| `truncate_symmetric(radius)` | nonnegative radius | Symmetrically truncated formula. |

These constructors do not prove convergence, a region of convergence, or an
inverse law merely by being called.

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

| Argument | Meaning |
|---|---|
| `expression` | Canonical Mathematical IR dictionary. |
| `search` | `"normal"` or high-recall `"broad"`. |
| `candidate_budget` | Retrieval limit if no `SearchBudget` is supplied. |
| `budget` | Detailed `SearchBudget` for retrieval/unification/verification. |
| `registry` | Optional iterable of `ProviderContract`; default registry otherwise. |
| `assumptions` | Facts available to typed matching. |
| `authorized_rewrites` | Exact rewrite IDs allowed during matching. |
| `language` | Restrict to `python`, `rust`, or `cpp`. |

`GenerationPlan` contains `status`, `candidates`, `budget`, `selected`, a
relation graph, and decision provenance.

```python
formula = FormulaTracer.from_tex("x + 2")
plan = formula.plan_generation(search="broad", language="python")
print(plan.explain(language="en", limit=5))

candidate = plan.select()
print(candidate.contract.provider_id)
print(candidate.verification_status)
print(candidate.remaining_obligations)
```

| Method | Returns | Failure |
|---|---|---|
| `plan.explain(*, language="en", limit=10)` | `str` | — |
| `plan.candidate(provider_id)` | `CandidateMatch` | `KeyError` if absent. |
| `plan.select(provider_id=None)` | rigorously eligible `CandidateMatch` | `ValueError` if no eligible candidate. |

Similarity and ranking are reasons to inspect candidates, never proof.

### Generate and independently re-audit

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

The initial status is `SOURCE_GENERATED_UNVERIFIED`. `verify=True` or
`generated.verify()` performs independent frontend re-analysis.

## `compare_ir()` and structured results

```python
compare_ir(theory: dict[str, Any], implementation: dict[str, Any]) -> NativeResultValue
```

`theory` and `implementation` must be independently obtained Mathematical IR.
The returned object exposes `status`, `theory`, `implementation`, `relation`,
`assumptions`, `diagnostics`, `evidence`, `error`, `range`, `provenance`,
`debugger`, and `reconstruction`.

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
print(result.explain("en"))
```

Read `result.evidence` separately. `EXACT_EQUALITY` does not by itself imply
that Lean kernel evidence is present.

`native_available() -> bool` probes whether the stable native library can be
loaded. `False` means native operations are unavailable; `True` is capability
information, not verification evidence.

## Native owned classes

### `NativeContext` and `NativeFormula`

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
                print(result.to_json())  # dict on NativeResult
                print(result.to_tex())
```

`NativeCallError` reports invalid/unsupported calls;
`NativeUnavailableError` reports a missing native library. Use `with` or
`close()` to release every owned wrapper.

### `NativeResult`

| Member | Returns |
|---|---|
| `value` | `NativeResultValue`, the ergonomic structured projection. |
| `to_json()` | `dict[str, Any]` on this owned wrapper. |
| `to_tex()` | certificate TeX `str`. |
| `to_audit_bundle(source_context=None, environment=None, artifact_lineage=None)` | integrity-protected AuditBundle `dict`. |
| `close()` | `None`; releases the native handle. |

### `NativeMathematicalFunction`

Create one with `result.theory.as_function()`, `from_ir(...)`, or
`from_schema(...)`.

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

| Method | Arguments | Returns |
|---|---|---|
| `from_ir(ir, *, assumptions=(), evidence=(), provenance=None)` | IR plus metadata | owned function. |
| `from_schema(schema)` | portable function schema | owned function. |
| `evaluate(**values)` / `__call__(**values)` | named scalar/array values | JSON-compatible value. |
| `substitute(**values)` | named replacements | new owned function. |
| `to_callable(backend="python")` | `python` or optional `numpy` | callable accepting keyword arguments. |
| `to_schema()` / `to_dict()` | none | portable `dict`. |
| `inspect()` | none | variables, parameters, assumptions, metadata. |
| `to_tex()` | none | function TeX `str`. |
| `close()` | none | releases handle/context. |

No Python `eval()` is used. Missing variables, unsupported operations, domain
violations, and shape mismatches raise `NativeCallError`. Certified functions
are exposed through `result.error.as_function()` and
`result.range.lower/upper.as_function()` only when evidence exists;
`BOUND_NOT_AVAILABLE` is not converted into an empirical bound.

## `reconstruct()`

```python
reconstruct(request: Mapping[str, Any]) -> ReconstructionResult
```

The versioned request describes independently reconstructed implementation
information. The result preserves exact/non-exact relations, assumptions,
proof obligations, diagnostics, and unresolved reasons.

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
print(reconstruction.explain("en"))
```

`ReconstructionResult.to_dict() -> dict[str, Any]` returns the portable
structured result. `explain(language="en") -> str` supports `"en"` and
`"ja"` without changing the canonical status.

`CORRECTLY_UNRESOLVED` is a safe semantic outcome, not a reason to invent an
exact relation.

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

Arguments are keyword-only strings `output` and `expression`. The return value
is a decorator that returns the original callable. It records a user
declaration but neither changes execution nor replaces the independently
reconstructed implementation formula.

## Rust, C++, and C

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
/* use json */
ft_string_free(json);
ft_result_free(result);
ft_formula_free(formula);
ft_context_free(context);
```

FormulaTracer-owned C strings use `ft_string_free`; every opaque handle uses
its matching `*_free`. Continue with the [C reference](c-api-reference.md),
[C++ reference](cpp-api-reference.md), and [Rust reference](rust-api-reference.md).
